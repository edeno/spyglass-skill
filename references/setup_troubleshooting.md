# Spyglass Setup Troubleshooting

Common errors during installation and first-run. For installation steps, see [setup_install.md](setup_install.md). For configuration, see [setup_config.md](setup_config.md).

## Contents

- ["Could not find SPYGLASS_BASE_DIR"](#could-not-find-spyglass_base_dir)
- [Database Connection Fails](#database-connection-fails)
- ["Cannot import spyglass"](#cannot-import-spyglass)
- [Stores Mismatch Warning](#stores-mismatch-warning)
- [Environment Creation Fails](#environment-creation-fails)
- [Reinstalling or Resetting](#reinstalling-or-resetting)

## "Could not find SPYGLASS_BASE_DIR"

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

## Database Connection Fails

1. If using Docker: ensure Docker Desktop is running
2. Verify credentials: check `database.host`, `database.user`, `database.password` in your config
3. For remote databases: confirm TLS settings (`database.use_tls`) match server requirements
4. Test connection directly: `python -c "import datajoint as dj; dj.conn()"`

## "Cannot import spyglass"

- Ensure you are in the correct conda environment: `conda activate spyglass`
- If installed from source, verify editable install: `pip install -e .` from the repo root
- Check for import errors: `python -c "import spyglass"` -- the error message will point to the issue

## Stores Mismatch Warning

If `SpyglassConfig` logs a stores mismatch warning, the `raw` or `analysis` paths in `dj.config['stores']` differ from the resolved directory paths. This is auto-corrected at startup. To fix permanently, update your config file so `stores.raw.location` matches `custom.spyglass_dirs.raw`.

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

For more troubleshooting guidance, see `docs/src/GettingStarted/TROUBLESHOOTING.md` and `docs/src/GettingStarted/DATABASE.md` in the repository.
