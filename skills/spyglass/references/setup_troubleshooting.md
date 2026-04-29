# Spyglass Setup Troubleshooting

Common errors during installation and first-run. For installation steps, see [setup_install.md](setup_install.md). For configuration, see [setup_config.md](setup_config.md).

## First-response diagnostic

This file covers **install, import, config, connection, and base-dir** failures only — symptoms that surface before the user can run a normal Spyglass query at all. `populate` / `make` / `fetch1` failures, NumPy / pandas errors inside `make()`, and join-multiplicity issues belong to runtime debugging — see [runtime_debugging.md](runtime_debugging.md) and [common_mistakes.md](common_mistakes.md).

When a user reports something is "not working" at install / import / connection time — a base-dir warning, a `dj.conn()` timeout, a missing-symbol `ImportError` after `git pull` — run `python skills/spyglass/scripts/verify_spyglass_env.py` first. It's a single command that checks DataJoint config, base-dir resolution and writability, subdir layout, DB connection (with a 10-second timeout so it doesn't hang), and version-pin drift. The output tells you which of those seven surfaces is actually broken before you start reading tracebacks. Pass `--json` if you want machine-parseable output; pass `--check <name>` to run one specific check.

## Contents

- [First-response diagnostic](#first-response-diagnostic)
- ["Could not find SPYGLASS_BASE_DIR"](#could-not-find-spyglass_base_dir)
- [Database Connection Fails](#database-connection-fails)
- ["Cannot import spyglass"](#cannot-import-spyglass)
- [Stores Mismatch Warning](#stores-mismatch-warning)
- [`AccessError` / `PermissionError` on a shared installation](#accesserror--permissionerror-on-a-shared-installation)
- [Environment Creation Fails](#environment-creation-fails)
- [Reinstalling or Resetting](#reinstalling-or-resetting)
- [Import-time failures (`from spyglass.settings ...`)](#import-time-failures-from-spyglasssettings-)
- [`ImportError` / symbol-moved errors after `git pull` — editable-install drift](#importerror--symbol-moved-errors-after-git-pull--editable-install-drift)
- [`KeyError: '<column>' is not in the table heading` after `git pull`](#keyerror-column-is-not-in-the-table-heading-after-git-pull)
- [Setting a DataJoint password on first connect](#setting-a-datajoint-password-on-first-connect)
- [`Access denied for CREATE command` on shared-prefix schemas](#access-denied-for-create-command-on-shared-prefix-schemas)
- [`HDF5_USE_FILE_LOCKING` on shared / NFS filesystems](#hdf5_use_file_locking-on-shared--nfs-filesystems)

## "Could not find SPYGLASS_BASE_DIR"

Run `python skills/spyglass/scripts/verify_spyglass_env.py --check base_dir_resolved` first — it reports which resolution path (dj.config vs env var) the base dir did or didn't come from, before you start patching either one.

The base directory is not set. Fix by setting the environment variable or adding it to your DataJoint config:

```bash
export SPYGLASS_BASE_DIR=~/spyglass_data
```

Or in a DataJoint config file (`~/.datajoint_config.json` if you want it global, or `dj_local_conf.json` next to your code for a per-project override — both are honored, the local form takes precedence):
```json
{
  "custom": {
    "spyglass_dirs": {
      "base": "/path/to/data"
    }
  }
}
```

## Database Connection Fails

1. If using Docker: ensure Docker Desktop is running
2. Verify non-secret config fields: **never `Read`/`cat` `dj_local_conf.json` or `~/.datajoint_config.json` directly** — these files may contain a plaintext `database.password`, and any tool output enters the model context. Run the bundled scrub script (masks password, S3 / kachery creds, tokens):

    ```bash
    python skills/spyglass/scripts/scrub_dj_config.py
    ```

    If the script isn't available in your checkout, the inline fallback — note this only strips `database.password` and still leaks any S3 store or kachery credentials:

    ```bash
    jq 'del(.["database.password"])' dj_local_conf.json
    python3 -c 'import json; d=json.load(open("dj_local_conf.json")); d.pop("database.password", None); print(json.dumps(d, indent=2))'
    ```

    Check `database.host`, `database.user`, `database.port`, and `database.use_tls` in the scrubbed output. If the password itself is the suspected problem, have the user verify it locally — don't read it through the tool surface. Full pattern: [setup_config.md](setup_config.md) "Reading the config file safely".
3. For remote databases: confirm TLS settings (`database.use_tls`) match server requirements
4. Test connection with a timeout: `python skills/spyglass/scripts/verify_spyglass_env.py --check dj_connection --timeout 10` (the bare `python -c "import datajoint as dj; dj.conn()"` hangs indefinitely on an unreachable server, which is itself a useful signal — the script gives you that answer in 10 seconds).

## "Cannot import spyglass"

- Ensure you are in the correct conda environment: `conda activate spyglass`
- If installed from source, verify editable install: `pip install -e .` from the repo root
- Check for import errors: `python -c "import spyglass"` -- the error message will point to the issue

## Stores Mismatch Warning

If `SpyglassConfig` logs a stores mismatch warning, the `raw` or `analysis` paths in `dj.config['stores']` differ from the resolved directory paths. This is auto-corrected **in memory** at startup (the on-disk config file is *not* rewritten). To fix permanently, update your config file so `stores.raw.location` matches `custom.spyglass_dirs.raw`.

## `AccessError` / `PermissionError` on a shared installation

This file owns the *setup-adjacent* permission failures: MySQL grants on a new install / new schema, the one-time `LabMember.LabMemberInfo` onboarding insert, and shared-filesystem write bits. The runtime-debugging questions that *use* the team check — `super_delete()` bypass decisions, `force_permission=True`, debugging which experimenter blocked your delete — belong in [destructive_operations.md](destructive_operations.md); generic populate/fetch error triage is in [runtime_debugging.md § Failure signatures](runtime_debugging.md#failure-signatures).

**1. MySQL grants (for `INSERT` / `UPDATE` / `DELETE` / `CREATE`).**

```python
dj.conn().query('SHOW GRANTS FOR CURRENT_USER();').fetchall()
```

Grants are per-schema-prefix on shared installations. A brand-new schema (e.g. `ripple_v1`, `spikesorting_recording`, or a user-custom prefix) may not be covered by your grants. If `SHOW GRANTS` has no entry for the schema named in the error, ask the DB admin for an explicit `GRANT` on that prefix, or name your custom schemas with a prefix you already have grants for.

**2. Filesystem permissions (for analysis / recording / kachery directories).**

```bash
ls -ld /path/to/failing/dir
python -c "import os; print(os.access('/path/to/failing/dir', os.W_OK))"
```

Directories under `${SPYGLASS_BASE_DIR}/analysis/<session>/` and `${SPYGLASS_BASE_DIR}/recording/` are created by whichever user first populated them, so later writers hit `EACCES` unless the directory is group-writable. The data owner runs `chmod -R g+w <dir>` (or the admin chmods to `2775` / `2777` depending on lab policy); avoid piecemeal chmods that drift. Many labs running Spyglass on a shared filesystem operate a cron or admin-run script that periodically re-asserts group-write on the whole tree — if yours does, flag to the admin instead of chmod-ing piecemeal.

**3. `LabMember.LabMemberInfo` onboarding (one-time per DataJoint user).** This is a setup-time task even though the failure surfaces at runtime: `cautious_delete` won't run for a DataJoint user that isn't registered. The error you'll see (and the cross-links from `runtime_debugging.md` and `destructive_operations.md` that route here):

```
ValueError: Could not find exactly 1 datajoint user <name> in
common.LabMember.LabMemberInfo. Please add one: []
```

Insert the master and part rows in one shot — do this once per new lab member, then never again:

```python
import spyglass.common as sgc
import datajoint as dj

sgc.LabMember.insert1({
    'lab_member_name': 'Jane Doe',
    'first_name': 'Jane',
    'last_name': 'Doe',
}, skip_duplicates=True)

sgc.LabMember.LabMemberInfo.insert1({
    'lab_member_name': 'Jane Doe',
    'google_user_name': 'jane@lab.org',
    'datajoint_user_name': dj.config['database.user'],
    'admin': 0,
}, skip_duplicates=True)
```

`admin=1` reserves a member as a lab admin; team-permission semantics, `super_delete()` decisions, and the `force_permission=True` bypass live in [destructive_operations.md](destructive_operations.md) — don't reach for those to "fix" a missing-LabMember error. The fix is the insert above.

**On shared lab filesystems.** Analysis, recording, export, and kachery directories drift out of group-writable as new subdirs are created by different users. If `ls -ld` shows the failing dir isn't group-writable, fix it through your lab's shared-permission process (cron, admin-run script, or `chown -R`) rather than chmod-ing per session. `Nwbfile().cleanup()` removes orphan NWB files from disk but does NOT fix permission bits on existing directories — filesystem-permission fixes must happen at the filesystem level, not via Spyglass helpers.

## Environment Creation Fails

```bash
# Remove and retry
conda env remove -n spyglass
python scripts/install.py

# Or clear conda cache first
conda clean --all
```

## Reinstalling or Resetting

To start fresh without losing data:

```bash
conda env remove -n spyglass
python scripts/install.py
```

Data directories are preserved -- only the conda environment and config are recreated.

## Import-time failures (`from spyglass.settings ...`)

Two symptoms fail `import spyglass.*` / `from spyglass.settings ...`
BEFORE you get to call `save_dj_config` or `populate()`. Diagnose by
error class:

**1. `OperationalError (2003)` — MySQL connect during import.**

Symptom: `OperationalError: (2003, "Can't connect to MySQL server...")`
from `from spyglass.settings import SpyglassConfig` or `from
spyglass.utils ...`, even though you haven't touched a table.

Spyglass's settings/utils modules historically triggered a DataJoint
connection at import time (`ExportErrorLog` in `dj_helper_fn` pulled in
a handshake). If `dj.config` wasn't valid yet — bad host, no password,
wrong TLS — the import failed.

**Current Spyglass:** `ExportErrorLog` lives in
`spyglass/common/common_usage.py` (verify with `code_graph.py describe
ExportErrorLog`); `dj_helper_fn.py` imports it lazily inside the
function body, so importing `spyglass.utils` no longer triggers a
DataJoint handshake. If `code_graph.py describe ExportErrorLog`
shows it defined under `spyglass/utils/dj_helper_fn.py` (or imported
at module top of `dj_helper_fn`), the install predates this fix —
upgrade (`git pull && pip install -e .`).

Workaround for older installs — populate `dj.config` BEFORE the first
`from spyglass...`:

```python
import datajoint as dj
dj.config.load('dj_local_conf.json')   # or dj.config['database.host'] = ...
dj.conn()                              # prove it connects
# only now:
from spyglass.settings import SpyglassConfig
```

**2. `PermissionError` — `SpyglassConfig.load_config` tries to mkdir
an unwritable path.**

Symptom: `PermissionError: [Errno 13] Permission denied:
'/nimbus/deeplabcut'` (or similar) during `from spyglass.settings ...`
— you can't even call `save_dj_config` to fix it because the error
happens during import.

Cause: `SpyglassConfig.load_config` runs
`Path(self._dlc_base).mkdir(exist_ok=True)` unconditionally. `_dlc_base`
resolves from stored `dj.config['custom']['dlc_dirs']`, then
`DLC_BASE_DIR` / `DLC_PROJECT_PATH`, then a fallback under
`${SPYGLASS_BASE_DIR}/deeplabcut`. If any of those resolves to a path
you can't write, import fails.

Fix without importing Spyglass — edit the DataJoint config directly:

```bash
python3 -c '
import json, datajoint as dj
dj.config.load()                   # ~/.datajoint_config.json / local
dj.config["custom"].setdefault("dlc_dirs", {})["base"] = "/your/writable/path"
dj.config.save_global()
'
```

or in a shell:

```bash
unset DLC_BASE_DIR DLC_PROJECT_PATH
```

then re-import.

Both modes are import-time, so neither can be fixed from a live
Spyglass session — the fix goes through the raw DataJoint config, or
through upgrading to a Spyglass that defines `ExportErrorLog` in
`common_usage` and imports it lazily inside `dj_helper_fn` (verify
with `code_graph.py describe ExportErrorLog`).

## `ImportError` / symbol-moved errors after `git pull` — editable-install drift

Symptom: stack trace shows `AttributeError: module 'spyglass...' has
no attribute ...` or `ImportError: cannot import name '...'`, and the
traceback paths point at `.../site-packages/spyglass/...` rather than
your checkout (e.g. `~/spyglass/src/spyglass/...`).

This means `python` is loading a pip-installed Spyglass from the env's
`site-packages`, ignoring your pulled source.

**Confirm.**

```python
import spyglass
print(spyglass.__file__)   # should be the source checkout, not site-packages
```

```bash
(cd <your spyglass source>; git log -1 --oneline)
```

**Fix (editable install recipe).**

```bash
conda activate spyglass
cd <your spyglass source>
git pull
pip install -e .
# then RESTART the Jupyter kernel / Python process so the old import cache clears
```

If you installed Spyglass via `pip install spyglass-neuro` originally,
uninstall that first: `pip uninstall spyglass-neuro` before `pip install -e .`
on the source tree.

## `KeyError: '<column>' is not in the table heading` after `git pull`

Between Spyglass releases, some table definitions change and the
database needs `Table().alter()` calls run by an admin to catch
up to the package. Recent releases (≥0.5.5) document each required
alter call in the version's `CHANGELOG.md` section, including the
import scope each alter needs. Older releases sometimes shipped
schema changes without an explicit alter list, so `CHANGELOG.md`
isn't a complete history — but for current versions it's the
authoritative checklist. Symptoms include:

- `KeyError: 'accessed'` on `AnalysisNwbfileLog.increment_access`
- `KeyError: 'pipeline'` on `SpikeSortingRecording.populate`
- `KeyError: 'target_sampling_rate'` on `LFPV1.populate`
- `DataError (1406): Data too long for column ...`

**Confirm drift.**

```python
Table().describe()                                              # Python-side
dj.conn().query(f'SHOW CREATE TABLE `<schema>`.`<table>`').fetchall()  # DB-side
```

Columns that only appear on one side are the drift.

**Fix.** Read the `CHANGELOG.md` section for the version you just
pulled to. The release notes list every `Table().alter()` an admin
needs to run (with the right import-scope so foreign-key references
resolve). On shared databases, the alter calls require ALTER
privilege the average user does not have — coordinate with an admin
rather than running them yourself. The canonical alter shape is:

```python
from spyglass.common import *   # pull every FK-referenced class into scope;
                                # otherwise `.alter()` raises
                                # "Foreign key reference Session could not be resolved"
SomeTable().alter()
```

For tables where `.alter()` doesn't detect the drift (rare), drop
and recreate — only when the table is empty. Track these cases with
an admin before acting.

**DataJoint version drift after `git pull`.** Spyglass sometimes
starts using a new DataJoint feature (`dj.Top`, `force_parts`,
tripart `make`) without bumping the hard datajoint requirement. If
imports fail referencing a missing DataJoint symbol:

```bash
pip install -U datajoint       # target >= 0.14.6 as of late 2025
```

## Setting a DataJoint password on first connect

Use `dj.set_password()`. Spyglass's installer (`scripts/install.py:2609`) and the upstream `Management.md:73` both call this directly:

```python
import datajoint as dj
dj.conn()
dj.set_password()                                  # prompts for old/new
# or, non-interactively:
# dj.set_password(new_password=..., update_config=True)
```

(`dj.admin.set_password()` still exists for legacy notebooks but is no longer the recommended entry point.)

If the MySQL server is >= 8.0 and the call raises
`QuerySyntaxError ... near 'PASSWORD('...')'`, you're on a DataJoint
version from before <https://github.com/datajoint/datajoint-python/pull/1106>.
Upgrade datajoint: `pip install -U datajoint`. One-off workaround (substitute a placeholder; **do not paste a real password into a chat, log, terminal history, or notebook output** — read it from a prompt or env var so it never lands in transcripts):

```python
import getpass
new_pw = getpass.getpass("New MySQL password: ")
dj.conn().query("ALTER USER user() IDENTIFIED BY %s", (new_pw,))
del new_pw
```

## `Access denied for CREATE command` on shared-prefix schemas

Labs that revoked CREATE on shared prefixes after site incidents will
refuse users declaring new tables under e.g. `common_*` or
`spikesorting_v1_*`. Declare your tables under a user- or
project-specific prefix instead: set
`dj.config['custom']['database.prefix'] = '<yourname>_'` before
importing your custom schema modules, and ask an admin to GRANT
CREATE on that prefix.

## `HDF5_USE_FILE_LOCKING` on shared / NFS filesystems

Symptom: HDF5 file-locking errors during `fetch_nwb()` / `populate()`
on an NFS or other shared filesystem, even though Spyglass's
`settings.py` appears to set the relevant env var.

The `env_defaults` block in `src/spyglass/settings.py` historically
had a typo (`HD5_USE_FILE_LOCKING` instead of `HDF5_USE_FILE_LOCKING`),
so Spyglass did not actually export the variable that HDF5 reads.
Current Spyglass uses the correct spelling
(`src/spyglass/settings.py:120`). If you installed Spyglass before
that rename reached you, set the variable explicitly in the shell
that launches Python:

```bash
export HDF5_USE_FILE_LOCKING=FALSE
```

Or from Python BEFORE importing `pynwb` / `h5py`:

```python
import os
os.environ['HDF5_USE_FILE_LOCKING'] = 'FALSE'
import pynwb   # and whatever else uses HDF5
```

The separate "`pynwb` version too old" failure in the same area —
`AttributeError` on `TimeSeries.get_timestamps` — needs the floor
specified in `pyproject.toml` (currently `pynwb>=3.1.3` at line 65;
verify on your install). Upgrade your env (`pip install -U pynwb`)
if you're below the floor.

For more troubleshooting guidance, see `docs/src/GettingStarted/TROUBLESHOOTING.md` and `docs/src/GettingStarted/DATABASE.md` in the repository.
