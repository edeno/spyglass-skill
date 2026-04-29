# Spyglass Configuration

Configuring an already-installed Spyglass — database connection, directory layout, env vars, and Kachery sharing tables. For installation, see [setup_install.md](setup_install.md). For common errors, see [setup_troubleshooting.md](setup_troubleshooting.md).

## Contents

- [Database Configuration](#database-configuration)
  - [Config File Location](#config-file-location)
  - [Config File Structure](#config-file-structure)
  - [Reading the config file safely](#reading-the-config-file-safely)
  - [Generating Config Programmatically](#generating-config-programmatically)
  - [Stores Configuration](#stores-configuration)
- [Directory Configuration](#directory-configuration)
  - [Setting the Base Directory](#setting-the-base-directory)
  - [Directory Tree](#directory-tree)
  - [Per-Directory Overrides](#per-directory-overrides)
  - [Accessing Directories at Runtime](#accessing-directories-at-runtime)
  - [Additional Environment Variables](#additional-environment-variables)
  - [Data Sharing Tables (Kachery)](#data-sharing-tables-kachery)

## Database Configuration

Spyglass uses DataJoint, which requires a MySQL-compatible database. Configuration is stored in a `dj_local_conf.json` file (DataJoint's standard config) or in a global DataJoint config file.

### Config File Location

DataJoint searches for config in this order:

1. `dj_local_conf.json` in the current working directory
2. `.datajoint_config.json` in the user's home directory (global config)
3. Environment variables and programmatic `dj.config` settings

### Config File Structure

See `dj_local_conf_example.json` in the repo root for a complete template. The key database fields:

```json
{
  "database.host": "localhost",
  "database.user": "your_username",
  "database.password": "your_password",
  "database.port": 3306,
  "database.use_tls": true,
  "database.reconnect": true,
  "enable_python_native_blobs": true,
  "filepath_checksum_size_limit": 1073741824
}
```

- **`database.host`**: MySQL server hostname. Use `localhost` for Docker, or your lab's database server address for remote
- **`database.port`**: Default 3306
- **`database.use_tls`**: TLS encryption for the connection. The installer auto-detects (enabled for remote hosts, disabled for localhost). The programmatic path differs: `SpyglassConfig.save_dj_config()` forwards `**kwargs` to `_generate_dj_config`, which defaults `database_use_tls=True` (`spyglass/settings.py:346`). So when calling `save_dj_config()` for a localhost setup, pass `database_use_tls=False` explicitly.
- **`database.password`**: **Strongly prefer to omit this field.** Storing a plaintext password in a config file means every `cat`, `Read`, or screen-share exposes it — and since `dj_local_conf.json` is the first thing people inspect to debug connection errors, the exposure surface is large. Move the password to the `DJ_PASS` env var, a `~/.my.cnf` MySQL defaults file, or let DataJoint prompt interactively. If you must keep it in the file, restrict perms (`chmod 600 dj_local_conf.json`).
- **`filepath_checksum_size_limit`**: Max file size (bytes) for checksum verification of externally stored files. Default is 1 GB

### Reading the config file safely

**Never `Read` or `cat` `dj_local_conf.json` or `~/.datajoint_config.json` directly** — they may contain a plaintext password. Once the password enters a tool result, it is in the model's context and can be echoed back inadvertently. Use the bundled scrub script:

```bash
python skills/spyglass/scripts/scrub_dj_config.py
# Or, with an explicit path:
python skills/spyglass/scripts/scrub_dj_config.py path/to/dj_local_conf.json
```

The script masks `password`, `access_key`, `secret_key`, `token`, `credential`, `api_key`, and `auth` leaves (anywhere in the tree, including nested `stores.*` and `custom.kachery_cloud.*` sections) while preserving host / user / port / dir paths so the rest of the config is still inspectable. Header goes to stderr, scrubbed body to stdout — pipe the body into `jq` or similar without contamination.

If the script isn't available in the current checkout, the equivalent inline patterns — **these only strip `database.password`**. They miss S3 store credentials (`stores.*.access_key` / `stores.*.secret_key`) and Kachery tokens (`custom.kachery_cloud.*`); if your config has either, run the script rather than the fallback:

```bash
jq 'del(.["database.password"])' dj_local_conf.json
python3 -c 'import json; d=json.load(open("dj_local_conf.json")); d.pop("database.password", None); print(json.dumps(d, indent=2))'
```

Use these forms from the `Bash` tool (not the `Read` tool). Apply the same pattern for `~/.datajoint_config.json`. If you need to inspect `dj.config` at runtime from Python, print `{k: v for k, v in dj.config.items() if k != "database.password"}` — never bare `dict(dj.config)`.

**For *validating* config resolution rather than *reading* config values**, use the skill-side triage script: `python skills/spyglass/scripts/verify_spyglass_env.py --check dj_config --check base_dir_resolved`. It confirms the resolved values without echoing secrets — the right tool when the goal is "does Spyglass see the config it should?" rather than "what's in the file?"

### Generating Config Programmatically

`SpyglassConfig` can generate and save DataJoint config files:

```python
from spyglass.settings import SpyglassConfig

config = SpyglassConfig()
config.save_dj_config(
    save_method="global",          # "global", "local", or "custom"
    output_filename="~/my_config.json",  # for custom
    base_dir="/path/to/data",
    database_user="myuser",
    database_host="db.lab.edu",
    database_port=3306,
)
```

Save methods:

- **`global`**: Saves to `~/.datajoint_config.json`
- **`local`**: Saves to `./dj_local_conf.json` in the current directory
- **`custom`**: Saves to the path specified by `output_filename`

### Stores Configuration

DataJoint "stores" tell the database where externally stored files (raw data, analysis results) live on disk. These are set automatically by `SpyglassConfig` based on the directory configuration:

```json
{
  "stores": {
    "raw": {
      "protocol": "file",
      "location": "/path/to/base/raw",
      "stage": "/path/to/base/raw"
    },
    "analysis": {
      "protocol": "file",
      "location": "/path/to/base/analysis",
      "stage": "/path/to/base/analysis"
    }
  }
}
```

**Cross-machine mount drift.** The resolved `dj.config['stores']` is
machine-local — it carries absolute filesystem paths (`location`)
that point at where the data is mounted on *this* machine. When
`SpyglassConfig.load_config()` runs, `_set_dj_config_stores()`
(`src/spyglass/settings.py:268, 316`) refreshes the **in-memory**
`dj.config['stores']` from the resolved dirs, applying this
precedence (`settings.py:133`):

1. explicit `SpyglassConfig(base_dir=...)`
2. `dj.config['custom']['spyglass_dirs']`
3. env vars (`SPYGLASS_*_DIR`)
4. resolved `<base>/<X>`

But the *persisted* config file does NOT auto-regenerate when env
vars change. If the persisted stores block was written for one
machine's mount point and you connect from another machine where
the same shared drive is mounted at a different path
(`/data/shared/...` vs `/mnt/shared/...`), and `SpyglassConfig`
hasn't been imported / loaded on the new machine to refresh
`dj.config['stores']` from local env vars, fetches fail with
`FileNotFoundError: Inaccessible local directory ...`. Two configs
are persisted by default: `~/.datajoint_config.json` (global —
`dj.config.save_global()` and `SpyglassConfig.save_dj_config()`'s
default) and `dj_local_conf.json` in the cwd (local — only with
`save_method='local'` or `dj.config.save_local()`).

Fix: confirm the resolved `dj.config['stores']['raw']['location']`
matches `SPYGLASS_BASE_DIR` on the current machine, then save the
per-machine config — `SpyglassConfig().save_dj_config(...)` (writes
global by default) or `dj.config.save_local()` if you want a
project-scoped override. A useful check at session start:

```python
import datajoint as dj, os
assert 'stores' in dj.config, 'dj.config has no stores block'
raw_loc = dj.config['stores']['raw']['location']
assert raw_loc.startswith(os.environ['SPYGLASS_BASE_DIR']), (
    f'stores.raw.location={raw_loc} does not share prefix with '
    f'SPYGLASS_BASE_DIR={os.environ["SPYGLASS_BASE_DIR"]}'
)
```

## Directory Configuration

Spyglass organizes data into a tree of directories under a base path. The directory structure is defined in `src/spyglass/directory_schema.json` (the single source of truth).

### Setting the Base Directory

The base directory can be set via (in order of precedence):

1. **`SpyglassConfig(base_dir="...")`** -- passed directly to the constructor
2. **`dj.config['custom']['spyglass_dirs']['base']`** -- in the DataJoint config file
3. **`SPYGLASS_BASE_DIR` environment variable**
4. No default — errors if unset. The installer prompts with `~/spyglass_data/` as a suggestion, but this is not a runtime fallback

Which of the tiers actually resolved the base dir on a given machine is often what you want to know when debugging "my SPYGLASS_BASE_DIR isn't what I expected." `python skills/spyglass/scripts/verify_spyglass_env.py --check base_dir_resolved` walks this exact priority order and reports the winning source.

```bash
# Environment variable approach
export SPYGLASS_BASE_DIR=/data/spyglass
```

### Directory Tree

All subdirectories are relative to the base directory. The schema is loaded from `directory_schema.json` at runtime. The standard layout (check the JSON file for current values):

```text
$SPYGLASS_BASE_DIR/
  raw/              # Raw NWB files
  analysis/         # Analysis NWB output files
  recording/        # Extracted recordings for spike sorting
  spikesorting/     # Spike sorting output
  waveforms/        # Waveform data
  tmp/              # Temporary files
  video/            # Video files
  export/           # Exported data
  .kachery-cloud/   # Kachery cloud cache
  kachery_storage/  # Kachery persistent storage
  deeplabcut/       # DLC base directory
    projects/       # DLC project files
    video/          # DLC video files
    output/         # DLC output files
  moseq/            # MoSeq base directory
    projects/       # MoSeq project files
    video/          # MoSeq video files
```

### Per-Directory Overrides

Individual directories can be overridden independently via `dj.config` or environment variables:

```python
# In dj_local_conf.json under "custom":
{
  "custom": {
    "spyglass_dirs": {
      "base": "/data/spyglass",
      "raw": "/fast_disk/raw",
      "analysis": "/fast_disk/analysis"
    }
  }
}
```

```bash
# Or via environment variables
export SPYGLASS_RAW_DIR=/fast_disk/raw
export SPYGLASS_ANALYSIS_DIR=/fast_disk/analysis
```

The environment variable naming pattern is `{PREFIX}_{KEY}_DIR` where prefix is `SPYGLASS`, `KACHERY`, `DLC`, or `MOSEQ`. See `SpyglassConfig.dir_to_var()` in `settings.py`.

### Accessing Directories at Runtime

```python
from spyglass.settings import SpyglassConfig

config = SpyglassConfig()
config.base_dir        # Base directory
config.raw_dir         # Raw data directory
config.analysis_dir    # Analysis output directory
config.recording_dir   # Recording directory
config.sorting_dir     # Spike sorting directory
config.waveforms_dir   # Waveforms directory
config.temp_dir        # Temporary files
config.video_dir       # Video directory
config.export_dir      # Export directory
config.dlc_project_dir # DLC projects
config.dlc_video_dir   # DLC video
config.dlc_output_dir  # DLC output
config.moseq_project_dir  # MoSeq projects (`settings.py:628`)
config.moseq_video_dir    # MoSeq video
```

All directories are created automatically on first config load if they do not exist.

### Additional Environment Variables

`SpyglassConfig` sets several environment variables on load. Most defaults live in `env_defaults` (`settings.py`); `KACHERY_ZONE` is handled separately via a `kachery_zone_dict` that reads `os.environ["KACHERY_ZONE"]` first, then falls back to `dj.config['custom']['kachery_zone']`, then to the `franklab.default` zone (`settings.py:245-264`):

| Variable | Default | Source | Purpose |
| ---------- | --------- | --------- | --------- |
| `FIGURL_CHANNEL` | `franklab2` | `env_defaults` | figurl visualization channel |
| `DJ_SUPPORT_FILEPATH_MANAGEMENT` | `TRUE` | `env_defaults` | Enable DataJoint filepath management |
| `KACHERY_CLOUD_EPHEMERAL` | `TRUE` | `env_defaults` | Kachery cloud mode |
| `HDF5_USE_FILE_LOCKING` | `FALSE` | `env_defaults` | HDF5 file locking |
| `KACHERY_ZONE` | `franklab.default` | `kachery_zone_dict` (env → dj.config → default) | Kachery zone for data sharing |

> **Note:** `FIGURL_CHANNEL` and `KACHERY_ZONE` defaults are hardcoded
> to Frank Lab values in `settings.py` (historical). Labs running their
> own figurl/kachery infrastructure should override these in the shell
> or via `dj.config['custom']` before importing `spyglass.settings` —
> the defaults will not match your zone.

**Fresh-workstation setup — the one piece of state that doesn't travel with the source.** `dj.config['stores']` is machine-local (filesystem paths), so `git pull` or a fresh `pip install` leaves it unset on a new machine. Populate it via either of:

```bash
python scripts/install.py --config-only --base-dir /path/to/spyglass_data
```

```python
from spyglass.settings import SpyglassConfig
SpyglassConfig(base_dir="/path/to/spyglass_data").save_dj_config(
    save_method="global", base_dir="/path/to/spyglass_data",
    database_user="<your-db-user>",
)
```

`save_method="global"` writes `~/.datajoint_config.json` (no extra `dj.config.save_global()` needed). Avoid the legacy `config/dj_config.py` helper in the Spyglass repo — it passes `filename=` to `SpyglassConfig.save_dj_config` (now `output_filename=`, `src/spyglass/settings.py:388`), and crashes with no args by assigning `None` to `SPYGLASS_BASE_DIR` (`config/dj_config.py:8`).

Sanity check at session start:

```python
import datajoint as dj
from spyglass.settings import SpyglassConfig  # ensures env_defaults applied
assert 'stores' in dj.config
assert 'raw' in dj.config['stores'] and 'analysis' in dj.config['stores']
```

> **On `DataJointError: The filepath data type is disabled…`.**
> `DJ_SUPPORT_FILEPATH_MANAGEMENT=TRUE` IS set automatically by
> `SpyglassConfig` on import (see the env-var defaults table above).
> If you still hit the error, it's almost always an import-order
> problem: DataJoint was imported / called before anything under
> `spyglass.*` pulled `SpyglassConfig` in. Fix by importing
> `spyglass.settings` (or any `spyglass.*` module) BEFORE your first
> `fetch1_dataframe()`. Exporting the env var in your shell rc is a
> last-resort workaround; the correct fix is ensuring Spyglass's
> settings module runs first.

## Data Sharing Tables (Kachery)

Three tables configure kachery-cloud sharing alongside the env vars above. The chain is `KacheryZone` (manual registry of available zones) → `AnalysisNwbfileKacherySelection` (manual selection pairing a zone with an analysis-NWB row) → `AnalysisNwbfileKachery` (computed; FKs to the selection at `sharing/sharing_kachery.py:113`). Skip the selection in your mental model and the populate path doesn't make sense.

```python
from spyglass.sharing import (
    KacheryZone,
    AnalysisNwbfileKacherySelection,
    AnalysisNwbfileKachery,
)
```

**KacheryZone** (Manual)

- Key: `kachery_zone_name`
- Registers the kachery zone(s) this install can publish to.

**AnalysisNwbfileKacherySelection** (Manual)

- Pairs a `KacheryZone` row with an `AnalysisNwbfile` row — the manual selection step that says "publish *this* analysis file under *that* zone."
- `AnalysisNwbfileKachery.populate(...)` reads its rows; an unselected pair will not appear in the output.

**AnalysisNwbfileKachery** (Computed)

- Part table: `AnalysisNwbfileKachery.LinkedFile`
- Links analysis files to kachery-cloud for sharing.

Use `KACHERY_ZONE` / `KACHERY_CLOUD_EPHEMERAL` env vars above to pick the zone and mode.

**Common kachery failure modes + diagnostics.**

**`KACHERY_CLOUD_DIR` mismatch.** By default, Spyglass sets `KACHERY_CLOUD_DIR` to `${SPYGLASS_BASE_DIR}/.kachery-cloud` on import (note the hyphen — see `directory_schema.json` `kachery.cloud: ".kachery-cloud"`). The default can be overridden by `dj.config['custom']['kachery_dirs']` or, if no custom config value is set, by exporting `KACHERY_CLOUD_DIR` before import — `dj.config['custom']['kachery_dirs']` takes precedence over the env var.
`kachery-cloud-init` by default writes a `client_id` to
`~/.kachery-cloud`. If the two don't agree, the Spyglass process can't
find the client and Kachery calls fail with "Client not registered" or
silent 500s.

**Zone authorization.** `KACHERY_ZONE` must be set BEFORE importing
Spyglass, and the DB admin must have added your github user to that
zone. Ask your DB admin for the correct zone name; Kachery admins
manage access via the kachery-gateway admin page at
<https://kachery-gateway.figurl.org/admin>.

**Diagnostic recipe.**

```python
import os
from spyglass.settings import config
# SpyglassConfig.load_config() stores env-var-style keys, so the
# spyglass-side lookup uses the SAME name as the env var:
print('KACHERY_ZONE (env)        =', os.environ.get('KACHERY_ZONE'))
print('KACHERY_CLOUD_DIR (env)   =', os.environ.get('KACHERY_CLOUD_DIR'))
print('KACHERY_CLOUD_DIR (config)=', config.get('KACHERY_CLOUD_DIR'))
print('KACHERY_ZONE (config)     =', config.get('KACHERY_ZONE'))
```

`KACHERY_CLOUD_DIR` (a path) and `KACHERY_ZONE` (a zone name) are
distinct concepts — check each independently. If the directory env
var and the spyglass-config value of `KACHERY_CLOUD_DIR` don't agree,
align them (set the env var to the spyglass config value, OR put
`kachery_dirs` in `dj.config['custom']` so a single source of truth
covers every user), then re-run `kachery-cloud-init`. Do the same
zone-vs-zone check for `KACHERY_ZONE`.

VSCode-over-SSH frequently drops env vars from `~/.bashrc`; prefer
`dj.config['custom']['kachery_dirs']` + `dj.config.save_global()` over
bashrc so all shells/kernels pick it up.
