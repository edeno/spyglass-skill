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

Pure pip is not a substitute for `environment.yml`. Several Spyglass
deps (`mountainsort4`, `ghostipy`, `pyfftw`) require binary components
supplied by conda-forge, and `pip install spyglass-neuro` outside a
conda env will typically fail when building `isosplit5` wheels or at
runtime when `pyfftw` can't find its FFTW library. Use the
automated installer or `mamba env create -f environments/environment.yml`
+ `pip install -e .` unless you have a specific reason to avoid conda.

### conda (from environment file)

Spyglass provides environment files in the `environments/` directory. Per the repo's `notebooks/py_scripts/00_Setup.py:229-239`, the minimal file is the recommended starting point — `environment.yml` is the full, heavier install.

```bash
# Minimal environment (recommended default — faster install)
conda env create -f environments/environment_min.yml

# Full environment (includes optional deps — larger install)
conda env create -f environments/environment.yml

# With DeepLabCut support — creates a different env name (spyglass-dlc),
# and the MoSeq files use spyglass-moseq-cpu / spyglass-moseq-gpu.
# Check `name:` at the top of the file before activating.
conda env create -f environments/environment_dlc.yml
```

After creating the environment, install Spyglass itself. The env name is `spyglass` for `environment.yml` / `environment_min.yml`, but `spyglass-dlc` / `spyglass-moseq-cpu` / `spyglass-moseq-gpu` for the specialty variants:

```bash
conda activate spyglass          # or: spyglass-dlc, spyglass-moseq-cpu, etc.
pip install -e .
```

### From Source (development)

```bash
git clone https://github.com/LorenFrankLab/spyglass.git
cd spyglass
pip install -e .
```

The `-e` flag installs in editable mode so changes to the source are reflected immediately.

### Env drift and upstream breakages

`pip install <onepkg>` into an existing Spyglass env silently upgrades
transitive deps (especially `numpy`, `setuptools`, `pydot`, `networkx`)
and breaks otherwise-working installs. Symptoms include:

- `AttributeError` deep in `cv2.gapi` on import
- `"ndx-franklab-novela is not a namespace"`
- `dj.Diagram(...)._repr_svg_` → "Node names and attributes should not contain ':'"
- `pkg_resources` errors after `setuptools>=82`
- `RuntimeError: Undefined plan with nthreads` from `pyfftw 0.13.0`

**Fix.** Recreate the env from the current `environment.yml`:

```bash
mamba env update --file environment.yml --prune
# OR for a clean rebuild:
mamba env remove -n spyglass && mamba env create -f environment.yml
```

Do NOT `pip install <pkg>` piecemeal into a working env — the next `pip
install` will almost certainly overwrite a pinned version Spyglass
relies on. When you must, run `pip install --dry-run <pkg>` first and
check which transitive deps pip wants to move.

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
- **Self-hosted MySQL 8 only** — vanilla MySQL 8 caps InnoDB composite-PK
  index size at 3072 bytes, and some Spyglass tables exceed this with
  default `utf8mb4` widths. Use the `datajoint/mysql:8.0` Docker image
  (or ensure your MySQL 8 server uses `ROW_FORMAT=DYNAMIC`, which is
  the MySQL 8 default). Note: `innodb_large_prefix` was deprecated in
  MySQL 5.7 and removed in 8.0 (it's effectively always-on), so don't
  set it in `my.cnf` — depending on minor version it'll error or be
  silently ignored. A production lab DB that has been running Spyglass
  for a while is usually pre-tuned by its admin; you will generally
  only hit this on a fresh self-host.
- **`ndx-optogenetics` pin** — Spyglass's `pyproject.toml` currently
  pins `ndx-optogenetics==0.3.0`. Earlier Spyglass releases pinned
  0.2.0, so mixed-version installs (old Spyglass + new extension, or
  the reverse) can raise `ImportError: cannot import name
  'OpticalFiberLocationsTable' from 'ndx_optogenetics'` on
  `from spyglass.common import ...`. Check both versions with
  `pip show ndx-optogenetics spyglass-neuro`; `pip install -e .` on a
  current Spyglass checkout pulls the matching pin.

## Environment Setup Scenarios

### Local Development with Docker Database

Best for trying out Spyglass or solo development:

```bash
python scripts/install.py --docker
```

This starts a MySQL container on localhost:3306. The default credentials are `root` with a tutorial password. Config is saved to `~/.datajoint_config.json`.

**Pin the Docker image tag.** `datajoint/mysql:latest` currently points
at a MySQL 5 image whose SSL ciphers don't handshake with modern
`pymysql` / OpenSSL defaults; `dj.conn()` raises
`SSLError: SSLV3_ALERT_HANDSHAKE_FAILURE`. Use
`datajoint/mysql:8.0` explicitly, or for local dev disable TLS:
`dj.config['database.use_tls'] = False`.

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

### Obtaining tutorial NWB files

The example files referenced in `02_Insert_Data.ipynb` /
`0_intro.ipynb` are periodically re-homed. The current canonical
locations are linked from the tutorial notebooks themselves — if a
Dropbox link 404s, open the notebook on master to get the current
UCSF Box URL, or use the `minirec` / `mediumnwb` files hosted by the
Frank Lab.

### Common first-install pitfalls

- After editing env vars in `~/.bashrc`, run `source ~/.bashrc` OR
  open a new shell — the existing kernel sees the old environment.
- Renaming the conda env: edit the `name:` field at the top of
  `environments/environment.yml` before running `mamba env create`;
  the default name is `spyglass`.
- If you use `numba`-backed code (e.g. ripple detection, some
  decoding paths) on numpy >= 1.24, pin `numpy<1.24` until the
  relevant numba version catches up. `environment.yml` handles this;
  piecemeal pip installs don't.
- Validate after install: `python scripts/validate.py`.

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
