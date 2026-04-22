# Implementation plan — outside-collaborator data-sharing coverage

**Date:** 2026-04-22
**Status:** Draft — ready to execute
**Scope:** close the gap where the skill has scattered mentions of Kachery, roles, and exports but no unified walkthrough of "I'm a lab admin onboarding an outside collaborator" or "I'm an outside collaborator receiving data from a lab I don't belong to."

## Goals and non-goals

**Goals.**

- Ship a single reference file that walks both personas (lab admin, outside collaborator) through the full onboarding workflow end to end.
- Route the SKILL.md table at the right points so vague questions ("how do I share this with X?" / "how do I get access to X's data?") land on the new reference instead of the fragmented current coverage.
- Surface Spyglass's existing provisioning API (`DatabaseSettings.add_guest / add_collab / add_user / add_admin`) that the skill currently ignores.
- Optionally bundle a thin provisioning script so admins don't have to run the API by hand with all the right flags.

**Non-goals.**

- Building a new permission model. Spyglass's existing `dj_guest` / `dj_collab` / `dj_user` / `dj_admin` roles + `LabMember` / `LabTeam` are the vocabulary; the plan is to *teach* them, not replace them.
- Row-level security in DataJoint. The granularity is schema-prefix + role, not per-row. If row-level scoping ever lands upstream, revisit.
- Automating the kachery-gateway admin-page step. That's a web UI outside Spyglass; script can't drive it.
- DANDI upload flow beyond what `export.md` + `dandi_preflight.py` (planned) already cover.

## Audit — what the skill has today

| Piece | Where | Persona | Gap |
| --- | --- | --- | --- |
| Role table (`dj_guest` / `dj_collab` / `dj_user` / `dj_admin`) | [custom_pipeline_authoring.md § Schema Naming and Your Write Surface](../../skills/spyglass/references/custom_pipeline_authoring.md#schema-naming-and-your-write-surface) | new lab member | explains what roles *mean*, never how to *grant* one |
| Kachery env vars + zone authorization | [setup_config.md § Data Sharing Tables (Kachery)](../../skills/spyglass/references/setup_config.md) | new user whose admin already onboarded them | one paragraph, consumer-angle only; no admin-side instructions |
| Permission triage (`SHOW GRANTS`, LabMember check) | [setup_troubleshooting.md § AccessError / PermissionError on a shared installation](../../skills/spyglass/references/setup_troubleshooting.md) + eval 46 | existing user hitting errors | diagnostic, not provisioning |
| Export bundle (paper snapshot) | [export.md](../../skills/spyglass/references/export.md) | paper author | doesn't address how the bundle reaches / is consumed by the outside reviewer |
| `DatabaseSettings.add_guest()` / `add_collab()` / `add_user()` / `add_admin()` | upstream at `spyglass/utils/database_settings.py:155-170` | lab admin | **unmentioned by the skill** — admins run raw `CREATE USER` + `GRANT` SQL today because the skill doesn't name these helpers |
| `LabMember.insert1 + LabMember.LabMemberInfo.insert1` | upstream; mentioned in eval 46's layer 3 | lab admin | admin side of the cautious_delete / export-permission setup |
| `LabTeam` + `LabTeamMember` | upstream `common_lab.py:160-170` | lab admin | team creation for shared-access cohorts |
| SKILL.md routing | single row: "Syncing / sharing with collaborators (Kachery) → setup_config.md" | any | under-weighted — routes only the Kachery fragment |

**Synthesis:** the pieces of a complete onboarding workflow exist in the skill, but a lab admin reading through sequentially never gets a clear "Step 1, Step 2, …" path. An outside collaborator trying to consume data has no reference aimed at them at all.

## Three personas the new reference must serve

1. **Lab admin onboarding an outside collaborator** (primary — this is the user's stated pain). Needs: decide role, provision DB user, wire LabMember, grant Kachery zone access, prepare initial config for them.
2. **Outside collaborator receiving access from someone else's lab** (secondary). Needs: set up their `dj_local_conf.json` against the foreign lab's DB, confirm what they can and can't access, know how to fetch analysis files.
3. **Consumer of an export bundle** (tertiary). Needs: install Spyglass, import the bundle into a fresh local DB, reproduce the original fetches.

## Proposed changes

### 1. New reference: `data_sharing.md`

Net-new file under `skills/spyglass/references/data_sharing.md`. Size budget: aim ≤ 400 lines so there's headroom before the 500-line soft cap.

#### Outline

```
# Data Sharing — Onboarding Outside Collaborators

## Contents

- [Three personas](#three-personas)
- [Deciding the access level](#deciding-the-access-level)
- [Persona A — Lab admin: onboarding an outside collaborator](#persona-a--lab-admin-onboarding-an-outside-collaborator)
  - [Step 1: pick the role](#step-1-pick-the-role)
  - [Step 2: provision the DB user](#step-2-provision-the-db-user)
  - [Step 3: wire LabMember + LabMemberInfo](#step-3-wire-labmember--labmemberinfo)
  - [Step 4: grant Kachery zone access](#step-4-grant-kachery-zone-access)
  - [Step 5: hand over a starter config](#step-5-hand-over-a-starter-config)
- [Persona B — Outside collaborator: connecting to a foreign lab](#persona-b--outside-collaborator-connecting-to-a-foreign-lab)
- [Persona C — Consuming an export bundle standalone](#persona-c--consuming-an-export-bundle-standalone)
- [When access isn't enough: giving them files directly](#when-access-isnt-enough-giving-them-files-directly)
- [Revoking access](#revoking-access)
- [Cross-references](#cross-references)
```

#### Key content decisions

- **Role-choice decision tree.** Which role to assign depends on what the collaborator needs: SELECT on everything → `dj_guest`. SELECT + own `<name>_*` schemas (run their own custom tables) → `dj_collab`. Can extend shared pipelines (rare; usually a co-author joining as a full member) → `dj_user`. Never hand out `dj_admin`.
- **Named Spyglass API: `DatabaseSettings`.** Admins run it from inside a Spyglass-configured Python session. Canonical example:

  ```python
  from spyglass.utils.database_settings import DatabaseSettings

  # DatabaseSettings reads dj.config for host + executing-admin credentials.
  # Username here is the MySQL user the collaborator will use (not GitHub).
  ds = DatabaseSettings(user_name="collab_doe")
  ds.add_collab()   # creates user, grants dj_collab role, grants own prefix
  ```

  The `debug=True` flag pretty-prints the SQL instead of running it — recommended for first-time onboardings so admins can review before executing.

- **LabMember wiring** as a concrete pair of inserts (not just a pointer to eval 46):

  ```python
  from spyglass.common.common_lab import LabMember

  LabMember.insert1({"lab_member_name": "Jane Doe"}, skip_duplicates=True)
  LabMember.LabMemberInfo.insert1({
      "lab_member_name": "Jane Doe",
      "datajoint_user_name": "collab_doe",
      "google_user_name": "jane.doe@university.edu",
      "admin": 0,
  }, skip_duplicates=True)
  ```

- **Kachery zone step.** Acknowledge the kachery-gateway admin page is a web UI (can't script); give admins the exact zone name to enter. Name the failure mode ("Client not registered") and route to the existing `setup_config.md` diagnostic.

- **Starter config for the collaborator.** Include a ready-to-copy `dj_local_conf.json` template with placeholders for host, user, password. Recommend `dj.config['safemode'] = True` on first connect for read-only collaborators.

- **Persona B and C sections** are deliberately shorter — most of their work is just Persona A from the other side. Reuse Persona A's pointers rather than restating.

- **Revoke-access section.** Critical for lifecycle: `DatabaseSettings` does not ship a `remove_user` method (verify at implementation time); if it doesn't, document the raw `DROP USER 'collab_doe'@'%';` + `LabMember` row removal in a single paragraph.

#### Validator-gated citations

Every upstream API cited (`DatabaseSettings`, `LabMember`, `LabMemberInfo`, `LabTeam`, `KacheryZone`, `AnalysisNwbfileKachery`) must be in `KNOWN_CLASSES` in `validate_skill.py` — or added. Method names are checked via the method-existence gate.

### 2. SKILL.md routing update

The current single row collapses two distinct questions:

- **Existing row** (keep, retarget):
  `| Syncing / sharing with collaborators (Kachery) | [setup_config.md](references/setup_config.md) — "Data Sharing Tables (Kachery)" | 03_Data_Sync.ipynb |`
- **New row**:
  `| Onboarding an outside collaborator (DB user + Kachery + LabMember) | [data_sharing.md](references/data_sharing.md) | — |`

Two rows — the first remains the "Kachery plumbing" answer for existing users; the second is the "I need to grant access to someone new" answer. Watch the 1200-word SKILL.md cap when the row lands; trim elsewhere if needed.

### 3. New eval — `setup-onboard-outside-collab`

Add to `evals.json` (bumping from 47 to 48 or next available ID). Prompt shape:

> A PI at another university asked me (the lab admin) to give one of their PhD students read access to our shared Spyglass install so they can replicate an analysis from our recent paper. What do I need to do?

`expected_output` cites `data_sharing.md` Persona A, walks through role choice (`dj_collab` for "they might run their own analyses" or `dj_guest` for "pure read"), names `DatabaseSettings.add_collab(user_name="...")`, includes the `LabMember` + `LabMemberInfo` inserts, mentions Kachery zone step.

`behavioral_checks`: leads with role decision (not provisioning); names `DatabaseSettings` (not raw SQL); completes all three required steps (DB user, LabMember, Kachery).

`forbidden_substrings`: `GRANT ALL PRIVILEGES ON *.*` (too permissive); `dj_admin` (should never hand this out); `chmod -R 777`.

### 4. Optional script — `provision_collaborator.py`

Speculative; ship only if the reference file alone isn't enough. Would wrap `DatabaseSettings.add_collab()` with:

- Prompts for role, lab member name, email, Kachery-gateway instructions.
- Writes LabMember / LabMemberInfo inserts as a preview before execution.
- Emits the starter `dj_local_conf.json` for handoff (masking the temporary password via `scrub_dj_config.py`).

Hold off in v1. See how the reference alone performs in evals. If an agent still reconstructs the same five-step provisioning by hand, graduate to a script.

## Tests

### Reference validation

- Standard validator rules already apply. `data_sharing.md` gets parsed like every other reference — link checks, method-existence, line-citation resolution.
- Add two regression fixtures:
  - `fixture_data_sharing_routes_from_skill_md_onboarding` — asserts SKILL.md's new row points at `data_sharing.md`.
  - `fixture_database_settings_methods_resolve` — asserts `DatabaseSettings.add_guest` / `add_collab` / `add_user` / `add_admin` all resolve in Spyglass source. Catches upstream rename.

### Eval coverage

- The new eval `setup-onboard-outside-collab` (above). Must be green before PR closes.
- Augment the existing eval 46 (`config-permission-triage`) with one behavioral check: "When the LabMember layer is the broken one, recommends [data_sharing.md Persona A Step 3](../../skills/spyglass/references/data_sharing.md) as the canonical wiring reference." Keeps 46 focused on triage while pointing at the new ref for the fix.

## Validator integration

No new validator checks beyond the two regression fixtures above. The existing method-existence gate handles the named APIs (`DatabaseSettings.add_collab` etc.) once the classes are added to `KNOWN_CLASSES`.

## Skill integration (cross-references)

`data_sharing.md` is a landing page; other references should cross-link to it, not duplicate its content.

- [custom_pipeline_authoring.md § Schema Naming and Your Write Surface](../../skills/spyglass/references/custom_pipeline_authoring.md#schema-naming-and-your-write-surface) — one-line pointer at the end of the role table: "To *grant* one of these roles, see [data_sharing.md](data_sharing.md)."
- [setup_config.md § Data Sharing Tables (Kachery)](../../skills/spyglass/references/setup_config.md) — top-of-section pointer: "If you're onboarding an outside collaborator (not configuring your own install), start at [data_sharing.md](data_sharing.md); this section is for users whose admin already granted Kachery access."
- [setup_troubleshooting.md § AccessError / PermissionError on a shared installation](../../skills/spyglass/references/setup_troubleshooting.md) — one-line pointer in the LabMember layer: "To set up a NEW user's LabMember row (not debug an existing one), see [data_sharing.md § Step 3](data_sharing.md)."
- [export.md § Overview](../../skills/spyglass/references/export.md) — one-line pointer in the "who consumes the bundle" case: "Sharing the bundle with someone outside the lab: see [data_sharing.md Persona C](data_sharing.md)."

Four cross-reference additions. Each is one line; none approach their file's size cap.

## Size budgets (affected references)

| File | Before (lines) | After (est.) | Cap |
| --- | --- | --- | --- |
| SKILL.md | at word-cap | at word-cap (1 row added, 1 elsewhere trimmed to stay within 1200 words) | 1200 (hard) |
| data_sharing.md | new | 350-400 | 500 soft / 700 hard |
| custom_pipeline_authoring.md | 312 | 313 | 500 |
| setup_config.md | 322 | 324 | 500 |
| setup_troubleshooting.md | ~330 | 331 | 500 |
| export.md | 148 | 149 | 500 |

## Phased rollout

Two atomic PRs; reference lands before the SKILL.md routing + eval updates so the link target exists.

### PR A — new reference + cross-references (~1 day)

1. Write `skills/spyglass/references/data_sharing.md` covering Persona A in full detail + shorter Persona B / C sections.
2. Add cross-reference pointers in the four existing references named above.
3. Add `DatabaseSettings`, `LabMember`, `LabMemberInfo`, `LabTeam`, `LabTeamMember` to `validate_skill.py:KNOWN_CLASSES` with their correct source paths (where not already present).
4. Run validator; ruff; pre-commit.
5. Commit: `references: add data_sharing for outside-collaborator onboarding`.

### PR B — SKILL.md routing + eval (~half day)

1. Add the new SKILL.md routing row; trim another entry to stay under the 1200-word cap if needed.
2. Add the new eval `setup-onboard-outside-collab` to `evals.json`.
3. Augment eval 46 with the one-line behavioral check tying LabMember fixes to `data_sharing.md`.
4. Run validator; ruff.
5. Commit: `SKILL.md + evals: route outside-collaborator onboarding to data_sharing`.

## Review workflow (applies to every PR above)

Before each commit, dispatch both reviewers in parallel (single message with two `Agent` tool calls) and address findings:

1. **`pr-review-toolkit:code-reviewer`** — even though this plan is documentation-heavy, the reviewer still checks: does every cited Spyglass API actually exist at the named path / method name; are code blocks in the reference runnable against the named classes; are fixture additions to `test_validator_regressions.py` correct.
2. **`general-purpose` agent with skill-design framing** — reviews the reference's discoverability (does SKILL.md route correctly? do the four cross-referenced files point at the right anchors?), persona coverage (does Persona A actually walk through all five steps without jumping ahead?), eval alignment (does the new eval's expected output match the reference?). The `skill-creator` Skill is NOT available as a subagent — `general-purpose` with a skill-design-focused brief serves the role.

Both reviewers must sign off before the PR's commits land. Documentation work looks low-risk but ships broken routing / outdated API cites more often than code does — the review catch rate is real.

## Acceptance criteria

- [ ] `data_sharing.md` exists; 350-400 lines; validator clean.
- [ ] Persona A covers all five steps (role, DB user, LabMember, Kachery, starter config) with concrete Spyglass API calls, not raw SQL.
- [ ] Four cross-references land and point at the right anchors in `data_sharing.md`.
- [ ] SKILL.md routing has a dedicated row for outside-collaborator onboarding, distinct from the existing Kachery sync row.
- [ ] New eval green; eval 46 augmentation doesn't break its existing pass.
- [ ] Two regression fixtures added to `tests/test_validator_regressions.py`.
- [ ] `DatabaseSettings` + `LabMember` + `LabMemberInfo` + `LabTeam` + `LabTeamMember` pinned in `KNOWN_CLASSES` with source paths.
- [ ] Validator + ruff clean; no regressions in the currently-passing tests.

## Upstream migration readiness

The reference is documentation, not code — nothing to migrate.

If the `provision_collaborator.py` script lands later, its upstream home is `spyglass.utils.database_settings` (the existing provisioning module). The optional script would slot alongside `add_guest()`, `add_collab()` etc. as a more-guardrailed wrapper.

## Risks and mitigations

- **Stale admin-page URL for Kachery gateway** (`kachery-gateway.figurl.org/admin`). Validator link-check doesn't reach external URLs today; add a soft reminder in `data_sharing.md` that this URL may move and the admin page is the source of truth. Re-check annually when other refs are updated.
- **`DatabaseSettings` API churn.** Regression fixture `fixture_database_settings_methods_resolve` catches method renames before they silently break the reference's code blocks.
- **Persona overlap.** A user might be both an external collaborator AND a new lab member; the reference handles this by making Persona B explicitly "reuse Persona A's pointers from the receiving side" rather than re-documenting.
- **LabMember insertion semantics.** `LabMemberInfo` has team-permission implications beyond cautious_delete; the reference must not oversimplify (a read-only collaborator doesn't need write access via team membership). Explicit warning in Step 3.
- **SKILL.md word cap.** Adding one row will push over 1200 words; plan identifies which entry to trim but doesn't specify — handle at implementation time by picking the lowest-value existing row (likely an overly verbose pipeline row).

## Next step

Start PR A. Write `data_sharing.md` following the outline. Audit which of the named classes are already in `KNOWN_CLASSES` (via `grep "class_name:" validate_skill.py`) and add the missing ones before citing their methods in the new reference.
