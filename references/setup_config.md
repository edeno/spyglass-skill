# Spyglass Configuration

Configuring an already-installed Spyglass — database connection, directory layout, env vars, and Kachery sharing tables. For installation, see [setup_install.md](setup_install.md). For common errors, see [setup_troubleshooting.md](setup_troubleshooting.md).

## Contents

- [Database Configuration](#database-configuration)
- [Directory Configuration](#directory-configuration)

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
- **`database.use_tls`**: TLS encryption for the connection. Automatically enabled for remote hosts by the installer; typically `false` for localhost
- **`database.password`**: **Strongly prefer to omit this field.** Storing a plaintext password in a config file means every `cat`, `Read`, or screen-share exposes it — and since `dj_local_conf.json` is the first thing people inspect to debug connection errors, the exposure surface is large. Move the password to the `DJ_PASS` env var, a `~/.my.cnf` MySQL defaults file, or let DataJoint prompt interactively. If you must keep it in the file, restrict perms (`chmod 600 dj_local_conf.json`).
- **`filepath_checksum_size_limit`**: Max file size (bytes) for checksum verification of externally stored files. Default is 1 GB

### Reading the config file safely

**Never `Read` or `cat` `dj_local_conf.json` or `~/.datajoint_config.json` directly** — they may contain a plaintext password. Once the password enters a tool result, it is in the model's context and can be echoed back inadvertently. Use a scrubbed read that strips `database.password` before it reaches you:

```bash
# jq (preferred — works on any key path, including nested)
jq 'del(.["database.password"])' dj_local_conf.json

# Python fallback if jq isn't installed
python3 -c 'import json; d=json.load(open("dj_local_conf.json")); d.pop("database.password", None); print(json.dumps(d, indent=2))'
```

Use these forms from the `Bash` tool (not the `Read` tool). Apply the same pattern for `~/.datajoint_config.json`. If you need to inspect `dj.config` at runtime from Python, print `{k: v for k, v in dj.config.items() if k != "database.password"}` — never bare `dict(dj.config)`.

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

## Directory Configuration

Spyglass organizes data into a tree of directories under a base path. The directory structure is defined in `src/spyglass/directory_schema.json` (the single source of truth).

### Setting the Base Directory

The base directory can be set via (in order of precedence):

1. **`SpyglassConfig(base_dir="...")`** -- passed directly to the constructor
2. **`dj.config['custom']['spyglass_dirs']['base']`** -- in the DataJoint config file
3. **`SPYGLASS_BASE_DIR` environment variable**
4. No default — errors if unset. The installer prompts with `~/spyglass_data/` as a suggestion, but this is not a runtime fallback

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
```

All directories are created automatically on first config load if they do not exist.

### Additional Environment Variables

`SpyglassConfig` sets several environment variables with defaults (see `env_defaults` in `settings.py`):

| Variable | Default | Purpose |
| ---------- | --------- | --------- |
| `FIGURL_CHANNEL` | `franklab2` | figurl visualization channel |
| `DJ_SUPPORT_FILEPATH_MANAGEMENT` | `TRUE` | Enable DataJoint filepath management |
| `KACHERY_CLOUD_EPHEMERAL` | `TRUE` | Kachery cloud mode |
| `HDF5_USE_FILE_LOCKING` | `FALSE` | HDF5 file locking |
| `KACHERY_ZONE` | `franklab.default` | Kachery zone for data sharing |

### Data Sharing Tables (Kachery)

Two tables configure kachery-cloud sharing alongside the env vars above:

```python
from spyglass.sharing import AnalysisNwbfileKachery, KacheryZone
```

**KacheryZone** (Manual)

- Key: `kachery_zone_name`
- Registers the kachery zone(s) this install can publish to.

**AnalysisNwbfileKachery** (Computed)

- Part table: `AnalysisNwbfileKachery.LinkedFile`
- Links analysis files to kachery-cloud for sharing.

Use `KACHERY_ZONE` / `KACHERY_CLOUD_EPHEMERAL` env vars above to pick the zone and mode.

**Common kachery failure modes + diagnostics.**

**`KACHERY_CLOUD_DIR` mismatch.** Spyglass sets `KACHERY_CLOUD_DIR` to
`${SPYGLASS_BASE_DIR}/.kachery_cloud` on import. `kachery-cloud-init`
by default writes a `client_id` to `~/.kachery-cloud`. If the two
don't agree, the Spyglass process can't find the client and Kachery
calls fail with "Client not registered" or silent 500s.

**Zone authorization.** `KACHERY_ZONE` must be set BEFORE importing
Spyglass, and the DB admin must have added your github user to that
zone. Ask your DB admin for the correct zone name; Kachery admins
manage access via the kachery-gateway admin page at
<https://kachery-gateway.figurl.org/admin>.

**Diagnostic recipe.**

```python
import os
from spyglass.settings import config
print('KACHERY_ZONE      =', os.environ.get('KACHERY_ZONE'))
print('KACHERY_CLOUD_DIR =', os.environ.get('KACHERY_CLOUD_DIR'))
print('spyglass config   =', config.get('kachery_cloud_dir'))
```

If the three don't agree, align them (set both env vars to the spyglass
config value, OR put `kachery_dirs` in `dj.config['custom']` so a single
source of truth covers every user), then re-run `kachery-cloud-init`.

VSCode-over-SSH frequently drops env vars from `~/.bashrc`; prefer
`dj.config['custom']['kachery_dirs']` + `dj.config.save_global()` over
bashrc so all shells/kernels pick it up.
