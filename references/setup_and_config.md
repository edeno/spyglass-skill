# Setup and Configuration Reference


## Contents

- [Installation Methods](#installation-methods)
- [Database Configuration](#database-configuration)
- [Directory Configuration](#directory-configuration)
- [Environment Setup Scenarios](#environment-setup-scenarios)
- [Installer and Validator Scripts](#installer-and-validator-scripts)
- [Common Setup Troubleshooting](#common-setup-troubleshooting)

This reference covers installing Spyglass, configuring the database connection, setting up data directories, and troubleshooting setup issues. For authoritative details, always consult the source files: `src/spyglass/settings.py` (runtime config), `scripts/install.py` (installer), and `scripts/validate.py` (validator).


## Installation Methods

### Automated Installer (Recommended)

The fastest path from zero to working environment:

```bash
git clone https://github.com/LorenFrankLab/spyglass.git
cd spyglass
python scripts/install.py
conda activate spyglass
```

The installer handles conda environment creation, database setup, directory creation, and validation. See [Installer and Validator Scripts](#installer-and-validator-scripts) for all CLI options.

### pip (into an existing environment)

```bash
pip install spyglass-neuro
```

This installs Spyglass and its core Python dependencies but does not create a conda environment or configure the database. You must set up `dj_local_conf.json` or environment variables manually.

### conda (from environment file)

Spyglass provides environment files in the `environments/` directory:

```bash
# Core environment
conda env create -f environments/environment.yml

# With DeepLabCut support
conda env create -f environments/environment_dlc.yml
```

After creating the environment, install Spyglass itself:

```bash
conda activate spyglass
pip install -e .
```

### From Source (development)

```bash
git clone https://github.com/LorenFrankLab/spyglass.git
cd spyglass
pip install -e .
```

The `-e` flag installs in editable mode so changes to the source are reflected immediately.

### Prerequisites

- Python 3.10+ (check `pyproject.toml` `requires-python` for the current range)
- conda or mamba package manager (miniforge recommended)
- ~10 GB disk space for minimal install, ~25 GB for full
- macOS or Linux (Windows is experimental)


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

```
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
|----------|---------|---------|
| `FIGURL_CHANNEL` | `franklab2` | figurl visualization channel |
| `DJ_SUPPORT_FILEPATH_MANAGEMENT` | `TRUE` | Enable DataJoint filepath management |
| `KACHERY_CLOUD_EPHEMERAL` | `TRUE` | Kachery cloud mode |
| `HD5_USE_FILE_LOCKING` | `FALSE` | HDF5 file locking |
| `KACHERY_ZONE` | `franklab.default` | Kachery zone for data sharing |


## Environment Setup Scenarios

### Local Development with Docker Database

Best for trying out Spyglass or solo development:

```bash
python scripts/install.py --docker
```

This starts a MySQL container on localhost:3306. The default credentials are `root` with a tutorial password. Config is saved to `~/.datajoint_config.json`.

### Joining an Existing Lab (Remote Database)

For connecting to a lab's shared database:

```bash
python scripts/install.py --remote --db-host db.lab.edu --db-user myuser
```

You will be prompted for your password. The installer enables TLS automatically for remote hosts.

### Non-Interactive / CI Setup

For automated environments, set variables and use CLI flags:

```bash
export SPYGLASS_BASE_DIR=/data/spyglass
export SPYGLASS_DB_PASSWORD=secret
python scripts/install.py --minimal --remote --db-host db.lab.edu --db-user ci_user
```

### Config-Only Mode (No Environment Creation)

To generate just the DataJoint config file without creating a conda environment:

```bash
python scripts/install.py --config-only --remote --db-host db.lab.edu --db-user alice --base-dir ~/data
```

### Lab Administrator Setup

Lab admins can pre-configure shared settings so new members only need to provide credentials. Two approaches:

1. **Environment variables** in a shared profile (e.g., `/etc/profile.d/spyglass.sh`):
   ```bash
   export SPYGLASS_BASE_DIR="/lab/shared/data"
   ```

2. **Lab-specific setup script** -- see `scripts/setup_franklab.sh` for an example wrapper.


## Installer and Validator Scripts

### `scripts/install.py`

Automated installer that handles environment creation, database setup, and validation.

**Key CLI flags:**

| Flag | Description |
|------|-------------|
| `--minimal` | Core dependencies only (~5 min) |
| `--full` | All optional dependencies (~15 min) |
| `--docker` | Set up local MySQL via Docker |
| `--remote` | Connect to remote database |
| `--db-host HOST` | Database hostname (with `--remote`) |
| `--db-port PORT` | Database port (default: 3306) |
| `--db-user USER` | Database username (default: root) |
| `--db-password PASS` | Database password (or use `SPYGLASS_DB_PASSWORD` env var) |
| `--env-name NAME` | Conda environment name (default: spyglass) |
| `--base-dir PATH` | Data directory (overrides `SPYGLASS_BASE_DIR`) |
| `--config-only` | Generate config file only, skip environment setup |
| `--skip-validation` | Skip post-install validation |
| `--dry-run` | Show plan without making changes |
| `--force` | Overwrite existing environment without prompting |

**What it does:**
1. Checks prerequisites (Python version, conda/mamba, disk space)
2. Creates conda environment from the appropriate environment file
3. Installs Spyglass in editable mode (`pip install -e .`)
4. Prompts for or configures database connection
5. Sets up data directories
6. Saves DataJoint config
7. Runs validation

### `scripts/validate.py`

Post-install validation script. Run it to check your Spyglass installation:

```bash
python scripts/validate.py
```

**Checks performed:**

| Check | Critical? | What it verifies |
|-------|-----------|------------------|
| Python version | Yes | Meets minimum from `pyproject.toml` |
| Conda/Mamba | Yes | Package manager available |
| Spyglass import | Yes | `import spyglass` works, version available |
| SpyglassConfig | No | Config loads, base directory set |
| Database connection | No | Can connect to MySQL via DataJoint |

Exit code 0 means all critical checks passed (warnings are non-fatal). Exit code 1 means a critical check failed.


## Common Setup Troubleshooting

### "Could not find SPYGLASS_BASE_DIR"

The base directory is not set. Fix by setting the environment variable or adding it to your DataJoint config:

```bash
export SPYGLASS_BASE_DIR=~/spyglass_data
```

Or in `dj_local_conf.json`:
```json
{
  "custom": {
    "spyglass_dirs": {
      "base": "/path/to/data"
    }
  }
}
```

### Database Connection Fails

1. If using Docker: ensure Docker Desktop is running
2. Verify credentials: check `database.host`, `database.user`, `database.password` in your config
3. For remote databases: confirm TLS settings (`database.use_tls`) match server requirements
4. Test connection directly: `python -c "import datajoint as dj; dj.conn()"`

### "Cannot import spyglass"

- Ensure you are in the correct conda environment: `conda activate spyglass`
- If installed from source, verify editable install: `pip install -e .` from the repo root
- Check for import errors: `python -c "import spyglass"` -- the error message will point to the issue

### Stores Mismatch Warning

If `SpyglassConfig` logs a stores mismatch warning, the `raw` or `analysis` paths in `dj.config['stores']` differ from the resolved directory paths. This is auto-corrected at startup. To fix permanently, update your config file so `stores.raw.location` matches `custom.spyglass_dirs.raw`.

### Environment Creation Fails

```bash
# Remove and retry
conda env remove -n spyglass
python scripts/install.py

# Or clear conda cache first
conda clean --all
```

### Reinstalling / Resetting

To start fresh without losing data:

```bash
conda env remove -n spyglass
python scripts/install.py
```

Data directories are preserved -- only the conda environment and config are recreated.

For more troubleshooting guidance, see `docs/src/GettingStarted/TROUBLESHOOTING.md` and `docs/src/GettingStarted/DATABASE.md` in the repository.
