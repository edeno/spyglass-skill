# Runtime Debugging for Spyglass Pipelines

Diagnosing failures that surface *after* Spyglass is installed and configured: `populate()` / `make()` errors, `fetch1()` cardinality mistakes, join multiplicity, and scientific-object bugs (NumPy/pandas) inside `make()`. If your error is install- or connection-related (cannot import spyglass, connection refused, SPYGLASS_BASE_DIR not set, Docker not running, TLS), go to [setup_troubleshooting.md](setup_troubleshooting.md) instead — that file owns the setup surface and this one does not duplicate it.

Spyglass **does not** wrap DataJoint errors: `SpyglassMixin` and `PopulateMixin` pass exceptions through unchanged (`src/spyglass/utils/mixins/populate.py:118`). The only Spyglass-specific exception class is a bare `PopulateException` in `src/spyglass/common/errors.py`. So the traceback you see *is* the DataJoint traceback, and the root cause is almost never the final line.

## Contents

- [When to use this file](#when-to-use-this-file)
- [Required inputs](#required-inputs)
- [Core philosophy](#core-philosophy)
- [Procedure](#procedure)
- [Failure signatures](#failure-signatures)
  - [A. fetch1() cardinality](#a-fetch1-cardinality)
  - [B. Ambiguous truth value of an array](#b-ambiguous-truth-value-of-an-array)
  - [C. Silent row multiplication from joins](#c-silent-row-multiplication-from-joins)
  - [D. Special-case key failures](#d-special-case-key-failures)
  - [E. Transaction / reservation confusion](#e-transaction-reservation-confusion)
  - [F. Interval / epoch mismatch across pipelines](#f-interval-epoch-mismatch-across-pipelines)
- [Automatic heuristics](#automatic-heuristics)
- [Sub-modes](#sub-modes)
- [Output shape](#output-shape)
- [Cross-references](#cross-references)

## When to use this file

Route here when any of the following hold:

- `populate()` raises, but you cannot tell which key failed
- `make()` succeeds on most keys and fails on one
- A restriction returns too many or too few rows and `fetch1()` explodes
- A join unexpectedly duplicates or drops rows
- DataJoint internals dominate the traceback but the real cause is unclear
- The table populates successfully but the stored result looks wrong
- A comparison involving a NumPy array, pandas Series, or DataFrame breaks inside `make()` (typically `The truth value of an array with more than one element is ambiguous`)
- A parallel populate hides which worker / key caused the crash

If the user's problem is **install, config, Docker, MySQL, imports, Apple Silicon, or disk space**, route to [setup_troubleshooting.md](setup_troubleshooting.md) — do not handle it here.

## Required inputs

Before proposing anything, ask for or infer:

- Full traceback (not just the final line)
- The table name that failed
- The exact `.populate(...)` or `.make(...)` call, including any restriction
- The table definition (primary key + dependencies)
- The relevant portion of `make()` when it's user code
- The failing key, if known
- A one-sentence statement of what the code was supposed to do

Also helpful when available:

- `key_source` for the failing table (what drives `populate()` iteration)
- Upstream table definitions referenced inside `make()`
- One key that succeeds and one that fails — the comparison is usually decisive
- Shape / dtype / type printouts of important intermediate variables

If the user pastes only the final traceback line, ask for the full traceback before guessing. The real cause is typically several frames above the line they pasted.

## Core philosophy

Always assume:

1. **The final traceback line may not be the true cause.** DataJoint internals routinely surface at the bottom of the stack when the bug is in user code several frames up.
2. **One bad key is more informative than the whole populate call.** Reproduce on a single key before rewriting anything.
3. **Relational assumptions break as often as Python code does.** Many "DataJoint bugs" are really cardinality bugs — the restriction or join returned a different row count than the code assumed.
4. **Scientific Python objects are frequent hidden causes.** Array equality, pandas truthiness, dtype surprises, and shape mismatches often masquerade as DataJoint errors.
5. **The smallest useful diagnostic beats a speculative rewrite.** Prefer a 2-line print over a 50-line refactor until the root cause is confirmed.

## Procedure

Work in this order. Don't skip to step 6.

### Step 1 — Classify the failure layer

Decide which of these four layers is actually failing:

- **Layer A — DataJoint orchestration**: `populate()` reservation, `use_transaction`, parallel workers. Symptoms: worker died silently, job reserved but not running, transaction rolled back.
- **Layer B — Relational logic**: keys, restrictions, joins, merge-table resolution, cardinality. Symptoms: `fetch1()` raises on 0 or >1 rows, joins duplicate results, `merge_get_part()` returns the wrong partition.
- **Layer C — User code in make()**: the Python/NumPy/pandas work inside the table's `make()`. Symptoms: `ValueError`, `KeyError`, shape mismatches, `ambiguous truth value`.
- **Layer D — Spyglass wrapper behavior**: merge-table classmethod dispatch, interval helpers, `_Merge` mechanics. Symptoms: classmethod calls silently dropping restrictions, merge resolution returning unexpected part tables. See [merge_and_mixin_methods.md](merge_and_mixin_methods.md).

State which layer is most likely before proposing anything.

### Step 2 — Identify the failing key

This is the single highest-leverage step. Spyglass ships no `debug_populate` or `populate_one` helper, so the pattern is manual:

```python
# Enumerate the keys the failing table would process
keys = (MyTable.key_source & restriction).fetch("KEY")
print(f"{len(keys)} keys to process")

# Run them one at a time so tracebacks name the failing key
for k in keys:
    try:
        MyTable().populate(k, reserve_jobs=False)
    except Exception as e:
        print(f"FAILED on key: {k}")
        print(f"  {type(e).__name__}: {e}")
        break   # or continue, if you want to see all failures
```

Ask:

- Does the error happen on every key, or only one?
- Can the failing key be reproduced with `MyTable().make(failing_key)` directly (bypassing `populate()`)?
- How does the failing key differ from one that succeeds? Different interval, subject, session length, sampling rate, electrode count?

Once you have a specific failing key, the rest of the procedure becomes concrete.

### Step 3 — Check relational assumptions

For each fetch / join / restriction touched by the failing code:

- What primary-key fields uniquely identify a row in this relation?
- Should the restriction return exactly 0, 1, or many rows? What does it actually return?
- After a join, did the row count change? Was that expected?
- Is `fetch1()` logically valid here — i.e., does the code *know* there's exactly one row?
- Are there hidden duplicates upstream (e.g., multiple parameter sets, multiple pipeline versions for the same session)?
- Is a merge table introducing multiplicity via its parts? (If you restrict a merge table with a friendly key like `{"nwb_file_name": ...}`, you typically get every part-table entry for that session.)

The single question that catches the most bugs:

> Does this relation have the cardinality the next line of code assumes?

See [datajoint_api.md](datajoint_api.md#restriction-) for restriction/join semantics and the too-loose-restriction footgun.

### Step 4 — Check object and type assumptions in make()

Many "DataJoint errors" during `make()` are scientific-code errors. Look for:

- `arr1 == arr2` used in a boolean context (`if`, `and`, `or`) where one side is an array
- `if series:` or `if df:` on a pandas object
- `object` dtype arrays — almost always a sign of ragged data sneaking in
- Shape mismatches between keys (one session has 4 LEDs, another has 2)
- Empty intervals, empty spike trains, or NaN-only epochs
- Assumptions that a fetched array has fixed length across keys

Print `type(obj)`, `obj.shape`, and `obj.dtype` before the failing line. Ninety percent of the time the type is not what you expected.

### Step 5 — Propose 2–5 narrow confirmation checks

Do **not** jump to a rewrite. Propose the smallest diagnostics that would confirm or refute your hypothesis. Good ones:

```python
# Cardinality check before fetch1
rel = (UpstreamTable & key)
print(f"rel has {len(rel)} rows; primary key fields = {rel.primary_key}")

# Type/shape check before the failing line
print(f"type={type(x).__name__}, shape={getattr(x, 'shape', None)}, dtype={getattr(x, 'dtype', None)}")

# Compare failing and succeeding keys
for k in [succeeding_key, failing_key]:
    r = (UpstreamTable & k).fetch()
    print(k, "->", len(r), r.dtype.names)
```

Each check should be 1–3 lines and run in under a second.

### Step 6 — Minimal fix

Give the narrowest repair that addresses the confirmed cause. Examples:

- Replace `arr1 == arr2` with `np.array_equal(arr1, arr2)` in a boolean context
- Replace `fetch1()` with `fetch()` plus an explicit row-count assertion
- Tighten a restriction so it returns exactly one row
- Coerce a pandas object to a NumPy array before comparison
- Guard against empty relations with an early return
- Handle the one special-case key explicitly

Do not bundle a refactor with the fix. Keep them separate.

### Step 7 — Robust fix

Only after the minimal fix lands, describe the more durable solution:

- Add a shape/type assertion at the top of `make()` so the next mismatch fails loudly
- Check `len(relation) == 1` before every `fetch1()` and raise with a descriptive message
- Validate key cardinality before joining upstream relations
- Standardize object types at the table boundary (always NumPy, always float64, etc.)
- Split long `make()` bodies into helpers with explicit pre/post invariants
- Add debug logging around the failing key category

The minimal fix unsticks the user. The robust fix stops the same class of bug from returning.

## Failure signatures

Each signature follows the same shape so the triage output is consistent.

### A. fetch1() cardinality

**Symptom.** `DataJointError: fetch1 should only be called on relations with exactly one tuple` (or `no tuples`). Sometimes surfaces as `ValueError` from wrappers like `merge_get_part()` or `fetch1_dataframe()`. The decoding-specific `DecodingOutput.fetch_results()` wraps `fetch1()` under the hood and raises the same error shape — but that method only exists on `DecodingOutput`, not on other merge tables.

**Most likely root cause.** The restriction in front of `fetch1()` is either too loose (matches multiple rows — every interval, every parameter set, every pipeline version) or too tight (matches zero rows because a field was wrong).

**Why that explanation fits.** `fetch1()` is defined to raise on anything other than exactly one row, and Spyglass's universal wrappers `merge_get_part` and `fetch1_dataframe` call it internally (as does the decoding-only `DecodingOutput.fetch_results`).

**Fastest confirmation checks.**

```python
rel = (SomeTable & key)
print(len(rel))              # should be exactly 1
rel.fetch(as_dict=True)      # shows every matching row and its full primary key
```

**Minimal fix.** Add the missing primary-key fields to the restriction so it uniquely identifies one row:

```python
# Before (under-specified)
key = {"nwb_file_name": nwb_file}
(SomeTable & key).fetch1()

# After (fully specified)
key = {"nwb_file_name": nwb_file,
       "interval_list_name": "02_r1",
       "trodes_pos_params_name": "default"}
(SomeTable & key).fetch1()
```

**Robust fix.** Wrap `fetch1()` patterns in a small helper that validates `len(rel) == 1` with a message naming the fields the caller passed, so the next too-loose restriction fails with a pinpoint error.

**Watch-outs.** `fetch_nwb()` does **not** raise on multiple rows — it silently returns a list across every match. If your code does `(Table & key).fetch_nwb()[0]` on an under-specified restriction, you get a plausibly-shaped result from an arbitrary row. See [datajoint_api.md](datajoint_api.md#fetch-fetch-fetch1) for the detailed footgun.

### B. Ambiguous truth value of an array

**Symptom.** `ValueError: The truth value of an array with more than one element is ambiguous. Use a.any() or a.all()` — typically inside `make()`, during an `if`, `and`, `or`, or comparison.

**Most likely root cause.** A NumPy array or pandas Series ended up somewhere the code expects a scalar boolean.

**Why that explanation fits.** NumPy deliberately raises on `bool(array)` when the array has more than one element; pandas does the same on Series/DataFrame in most contexts.

**Fastest confirmation checks.**

```python
print(type(x).__name__, getattr(x, "shape", None), getattr(x, "dtype", None))
# If x is an ndarray or Series, any `if x:` or `x == y` inside `if` will trip this.
```

**Minimal fix.** Pick the operator that matches the intent:

- Element-wise equality with a scalar boolean result → `np.array_equal(a, b)`
- "Is any element true" → `arr.any()`
- "Are all elements true" → `arr.all()`
- pandas object equality → `a.equals(b)`

**Robust fix.** At the boundary of `make()`, coerce inputs to a known type (`np.asarray(x, dtype=float)`) so downstream comparisons are always array-vs-array with documented shape, not "some scalar / some array depending on the key."

**Watch-outs.** Same family includes `KeyError` inside a DataFrame boolean indexer, and `IndexError` when a scalar index was expected but an array arrived. Print `type(...)` before indexing.

### C. Silent row multiplication from joins

**Symptom.** Results have more rows than expected, `fetch1()` starts raising on a restriction that used to work, or a populated table contains more entries than the number of source sessions.

**Most likely root cause.** A relation you assumed was one-to-one is actually one-to-many. Common culprits: merge tables (one `nwb_file_name` → many parts), parameter tables (one session → many parameter sets), interval lists (one session → many intervals).

**Why that explanation fits.** DataJoint joins are natural joins over shared primary-key fields; any field that looks like a foreign key but is actually repeated across the upstream table multiplies rows.

**Fastest confirmation checks.**

```python
# Count before and after the join
print(len(UpstreamA & key))                # e.g., 1
print(len(UpstreamB & key))                # e.g., 7
print(len((UpstreamA * UpstreamB) & key))  # if 7, the join multiplied as expected
# Inspect the join keys
set(UpstreamA.heading.names) & set(UpstreamB.heading.names)
```

**Minimal fix.** Tighten the restriction so the join side that multiplies is reduced to one row first:

```python
one_param = (TrodesPosParams & {"trodes_pos_params_name": "default"}).fetch1("KEY")
(UpstreamA & key) * (UpstreamB & one_param)
```

Or aggregate before joining with `.aggr()` if you truly want a many-to-one rollup.

**Robust fix.** In `make()`, assert cardinality before fetching: `assert len(rel) == 1, f"{rel.primary_key} matched {len(rel)} rows for key={key}"`. This catches multiplicity at the earliest possible point rather than at a confusing `fetch1()` further down.

**Watch-outs.** Restricting a merge table with a friendly key (e.g., `{"nwb_file_name": ...}`) almost always multiplies — use `merge_get_part()` or `merge_restrict()` instead. See [merge_and_mixin_methods.md](merge_and_mixin_methods.md).

### D. Special-case key failures

**Symptom.** `populate()` runs fine for most sessions and crashes on one. Error is often a shape mismatch, `KeyError`, or an `AttributeError` on a field that is `None` only for the failing session.

**Most likely root cause.** `make()` assumes all keys have the same data shape (same number of LEDs, non-empty position array, non-NaN intervals, a specific epoch label) but one session violates the assumption.

**Why that explanation fits.** Science data is messy. Different recording rigs, different animals, different experimenter conventions → one session per batch that breaks the invariants.

**Fastest confirmation checks.** Compare a succeeding key to the failing key side-by-side:

```python
for k in [good_key, bad_key]:
    upstream = (UpstreamTable & k).fetch1()
    print(k["nwb_file_name"],
          "shape=", upstream["data"].shape,
          "dtype=", upstream["data"].dtype,
          "nan_frac=", np.isnan(upstream["data"]).mean())
```

Pay attention to the first field that differs — that's almost always the cause.

**Minimal fix.** Add an explicit guard in `make()` for the special case (skip, pad, raise with a descriptive message), or upstream-validate the bad session out of `key_source`.

**Robust fix.** Move the invariant check to the top of `make()` with a clear error that names the offending field; if the pattern recurs across pipelines, factor the validator into a helper. Consider tightening the upstream `SelectionTable` so the bad session never reaches `populate()`.

**Watch-outs.** "Works on my machine" often means "the failing key isn't in your local test subset." Before declaring the fix done, run the single failing key through `make()` directly.

### E. Transaction / reservation confusion

**Symptom.** `populate()` fails repeatedly without naming the failing key; subsequent runs say the job is reserved; parallel populate hides which worker crashed.

**Most likely root cause.** DataJoint's orchestration (reservation, transactions, parallel workers) is masking the underlying error from steps 2–4. Spyglass doesn't customize this — `PopulateMixin` delegates to DataJoint's `populate()` (`src/spyglass/utils/mixins/populate.py:98`), and a single worker failure in `NonDaemonPool` kills the entire pool.

**Why that explanation fits.** With `reserve_jobs=True`, failed keys are written to the `~jobs` table and skipped on the next call; with `use_transaction=True` (Spyglass default), the failing row is rolled back so post-mortem inspection shows no partial state; with parallel workers, only the first exception propagates.

**Fastest confirmation checks.** Drop orchestration and reproduce serially:

```python
# Single key, no reservation, no parallelism
MyTable().populate(
    failing_key,
    reserve_jobs=False,
    processes=1,
)
# Or bypass populate entirely
MyTable().make(failing_key)
```

Inspect the jobs table to see reserved/errored keys:

```python
import datajoint as dj
jobs = dj.schema("spyglass_common").jobs   # or whichever schema owns MyTable
jobs.fetch(as_dict=True)
jobs.delete_quick()   # only after confirming you want to re-run those keys
```

**Minimal fix.** Debug with orchestration off. Once the true cause is fixed, re-enable reservation/parallelism for the full run.

**Robust fix.** For pipelines that routinely hit this, document the "debug single key" idiom in the pipeline's README and wrap common diagnostic calls in a small helper. If `use_transaction=False` is required (for long-running populates with external file writes), know that Spyglass adds an upstream-hash check around it (`src/spyglass/utils/mixins/populate.py:88-108`) that will raise if an upstream table changes mid-populate.

**Watch-outs.** A reserved job from a previous crashed run will silently skip in subsequent populates and look like "nothing is happening." Always check `jobs` before concluding that `populate()` is broken.

### F. Interval / epoch mismatch across pipelines

**Symptom.** Upstream tables look populated, restrictions look sensible, but the downstream output is empty, suspiciously small, or the populate silently does nothing. Joining two upstream tables returns zero rows even though each has rows for the session.

**Most likely root cause.** Different pipelines take different interval-name fields as input, and a selection was made against one interval while a downstream step expected another. Spyglass does **not** use a single universal `target_interval_list_name` — pipelines name their interval selection differently, and some pipelines take *two* intervals that can differ from each other.

Field names vary across the codebase. A non-exhaustive map:

| Pipeline / table | Interval field in its selection |
|---|---|
| `IntervalList` (the source) | `interval_list_name` (primary key, `common_interval.py:28`) |
| `LFPSelection` / `LFPV1` | `target_interval_list_name` (`lfp/v1/lfp.py`) |
| `LFPArtifactRemovedIntervalList` | `artifact_removed_interval_list_name` (`lfp/v1/lfp_artifact.py:162`) |
| `LFPBandSelection` | `target_interval_list_name` (`lfp/analysis/v1/lfp_band.py:28`) |
| `SpikeSortingRecordingSelection` (v0) | `sort_interval_name` — inherited via `-> SortInterval` (`spikesorting_recording.py:324-332`; field defined in `SortInterval` at `:241`) |
| `SpikeSortingArtifactDetectionSelection` | `artifact_removed_interval_list_name` (`spikesorting/v0/spikesorting_artifact.py:88`) |
| `RippleLFPSelection` (feeds `RippleTimesV1`) | `target_interval_list_name` — **inherited two hops** via `-> LFPBandV1 -> LFPBandSelection`. `RippleLFPSelection` (`ripple/v1/ripple.py:33-37`) has no interval field of its own; the inherited name only shows up in the transitive primary key, so check `RippleLFPSelection.heading.primary_key` to see it. |
| `MuaEventsV1` | `detection_interval` (projected from `IntervalList.interval_list_name` at `mua/v1/mua.py:68`) |
| Decoding V1 selections | `encoding_interval` AND `decoding_interval` (both projected from `IntervalList.interval_list_name`, `decoding/v1/clusterless.py:88-89`) |
| `TrodesPosSelection` | `interval_list_name` (unaliased — inherited via `-> RawPosition -> IntervalList`) |
| DLC position selections | Interval is not set at the user-facing selection level; it flows in through the pose-estimation chain. Inspect the specific selection's primary key to confirm. |

Two intervals can overlap in time but live under different names (e.g., one session's raw epoch vs. a trimmed "valid_times" version; a position-computed interval vs. the raw recording interval). A restriction that works on the LFP selection table may match zero rows on the decoding selection table because the field name, the interval name, or both differ.

**Why that explanation fits.** DataJoint silently ignores restriction fields that aren't present on the table (the field is treated as a no-op), and silently produces empty joins when key fields match on name but not on value. Both shapes look "correct" to the user but return nothing.

**Fastest confirmation checks.**

```python
# List all intervals actually defined for this session
(IntervalList & {"nwb_file_name": f}).fetch("interval_list_name")

# Inspect the selection table's interval field(s) directly
print(UpstreamSelection.heading.primary_key)  # shows the exact field names
(UpstreamSelection & {"nwb_file_name": f}).fetch(as_dict=True, limit=5)

# If a downstream populate is empty, check key_source:
print(len(DownstreamTable.key_source & key))  # 0 = no upstream rows match

# For two-interval pipelines (decoding), check BOTH explicitly:
# encoding_interval and decoding_interval may differ — and they often should,
# but not by accident.
```

**Minimal fix.** Align the interval name(s) with what the downstream table's selection expects. Either (a) re-insert the downstream selection using the correct interval-name value, or (b) if the intervals really are different epochs and need intersection, compute the intersection explicitly using `IntervalList.fetch1("valid_times")` and build a new `IntervalList` row for the intersected span.

**Robust fix.** In custom pipelines, project the upstream interval field onto the downstream selection so the name travels with the data instead of being re-specified (`-> IntervalList.proj(my_interval='interval_list_name')`, matching the decoding V1 pattern). When the name is a projection you can't accidentally typo it on the downstream side.

**Watch-outs.**

- **Empty populate ≠ error.** DataJoint's `populate()` silently does nothing when `key_source & key` is empty. See the pre-populate feedback loop in [feedback_loops.md](feedback_loops.md) — a `len(key_source & key) > 0` assertion before populate catches this immediately.
- **Name equality ≠ time equality.** `"02_r1"` in one table and `"02_r1"` in another probably refer to the same IntervalList row (same PK), but `"02_r1_valid"` is a different row even if its `valid_times` overlap. Check by joining on the `IntervalList` PK when in doubt.
- **Decoding specifically.** `encoding_interval` and `decoding_interval` are intentional separate inputs. They CAN be the same; they often SHOULDN'T be (train on encoding, evaluate on decoding). Verify by design intent, not by assuming they're equal.

## Automatic heuristics

Apply these before asking the user:

1. **Traceback ends in DataJoint internals → suspect `make()` first.** The last frame is the framework; the bug is usually in user code several frames up.
2. **Only some keys fail → compare a succeeding key to a failing key before editing code.** This narrows the cause faster than reading `make()` line by line.
3. **`fetch1()` is involved → verify relation cardinality explicitly** with `len(rel)` before proposing a fix.
4. **NumPy or pandas objects near the failure → print `type`, `shape`, `dtype`** before hypothesizing.
5. **Spyglass interval logic is involved → verify the restriction returns the intended epoch/interval rows** with `(IntervalList & restriction).fetch("interval_list_name")`.

## Sub-modes

Same reference, three entry points depending on what the user brought:

- **Traceback-first.** Input is an error log. Start at step 1 (classify layer), then skip to the matching [failure signature](#failure-signatures).
- **Relational-logic-first.** Code runs but returns wrong rows. Skip to step 3 (cardinality) and signatures A and C.
- **Failing-key comparison.** One key fails, another succeeds. Skip to step 2 then step 4, and signature D.

## Output shape

When responding to a runtime-debug question, structure the reply as:

1. **Symptom** — one line restating what failed.
2. **Most likely root cause** — your current best explanation, stated as a claim you're prepared to verify.
3. **Why that explanation fits** — what in the evidence points here rather than to alternatives.
4. **Fastest confirmation checks** — 2–5 narrow diagnostics, each 1–3 lines of code.
5. **Minimal fix** — narrowest repair that addresses the confirmed cause.
6. **Robust fix** — the durable change that prevents the class of bug from returning.
7. **Watch-outs** — adjacent failure modes the user should still keep in mind.

Keep steps 4–7 terse. The confirmation checks are the part that matters; the fixes follow once the checks land.

## Cross-references

- [datajoint_api.md](datajoint_api.md) — restriction/join semantics, `fetch1()` cardinality footgun, too-loose-restriction pattern
- [merge_and_mixin_methods.md](merge_and_mixin_methods.md) — merge-table classmethod dispatch gotcha, `<<`/`>>` upstream/downstream restriction
- [custom_pipeline_authoring.md](custom_pipeline_authoring.md) — `make()` conventions, `AnalysisNwbfile.build()` state errors
- [setup_troubleshooting.md](setup_troubleshooting.md) — install, config, Docker/MySQL, imports, base directory (this file does not duplicate those)
- [workflows.md](workflows.md) — cross-table exploration patterns useful for comparing succeeding vs. failing keys
