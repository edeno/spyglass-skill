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
- **`database.password`**: Omit this line on shared machines (DataJoint will prompt interactively)
- **`filepath_checksum_size_limit`**: Max file size (bytes) for checksum verification of externally stored files. Default is 1 GB

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
| `HD5_USE_FILE_LOCKING` | `FALSE` | HDF5 file locking |
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
