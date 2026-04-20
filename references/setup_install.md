# Spyglass Installation

Installing Spyglass via the installer, pip, conda, or from source. For configuration of an existing install, see [setup_config.md](setup_config.md). For common errors, see [setup_troubleshooting.md](setup_troubleshooting.md).

## Contents

- [Installation Methods](#installation-methods)
- [Environment Setup Scenarios](#environment-setup-scenarios)
- [Installer and Validator Scripts](#installer-and-validator-scripts)

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

Spyglass provides environment files in the `environments/` directory. Per the repo's `notebooks/py_scripts/00_Setup.py:229-239`, the minimal file is the recommended starting point — `environment.yml` is the full, heavier install.

```bash
# Minimal environment (recommended default — faster install)
conda env create -f environments/environment_min.yml

# Full environment (includes optional deps — larger install)
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

- Python 3.10 – 3.12 (check `pyproject.toml` `requires-python` for the
  current range). Common version-pin symptoms:

  | Python version | Error you'll see |
  |---|---|
  | 3.9 | `ImportError: cannot import name 'TypeAlias' from 'typing'` |
  | 3.10+ against an old MySQL server | `OperationalError (2003) [SSL: SSLV3_ALERT_HANDSHAKE_FAILURE]` — either upgrade the server's TLS or set `database.use_tls: false` for local dev |

- On macOS, `pyfftw` has no PyPI wheels; use conda-forge:
  `conda install -c conda-forge pyfftw pybind11` before `pip install -e .`.
- If you see `Cargo, the Rust package manager, is not installed` during
  a jupyter-lab dependency build, install Rust via rustup — or
  preferably install via `environment.yml` which pulls prebuilt wheels.
- conda or mamba package manager (miniforge recommended)
- ~10 GB disk space for minimal install, ~25 GB for full
- macOS or Linux (Windows is experimental)

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
| ------ | ------------- |
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
| ------- | ----------- | ------------------ |
| Python version | Yes | Meets minimum from `pyproject.toml` |
| Conda/Mamba | Yes | Package manager available |
| Spyglass import | Yes | `import spyglass` works, version available |
| SpyglassConfig | No | Config loads, base directory set |
| Database connection | No | Can connect to MySQL via DataJoint |

Exit code 0 means all critical checks passed (warnings are non-fatal). Exit code 1 means a critical check failed.
