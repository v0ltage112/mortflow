"""Path resolution for mortgage_model.

This module decouples the code from where its input data and outputs live, so
the repository can be cloned to any machine and pointed at data that sits
elsewhere (for example a synced cloud folder) without editing any source.

Resolution precedence, highest priority first:
    1. An explicit value passed by the caller (the ``cli`` argument).
    2. An environment variable (MORTGAGE_DATA_DIR / MORTGAGE_OUT_DIR).
    3. A git-ignored ``paths.local.yaml`` at the repository root.
    4. The in-repo defaults ``<repo_root>/data_sample`` and ``<repo_root>/out``.

The defaults mean a fresh clone runs on the bundled sample data with zero
configuration; a real machine overrides via ``paths.local.yaml`` or an env var.
"""

from __future__ import annotations

import os
from pathlib import Path

import yaml


# Environment variables checked before falling back to config or defaults.
_DATA_DIR_ENV = "MORTGAGE_DATA_DIR"
_OUT_DIR_ENV = "MORTGAGE_OUT_DIR"

# Name of the git-ignored local override file, read from the repo root.
_LOCAL_PATHS_FILENAME = "paths.local.yaml"


def _repo_root() -> Path:
    """Return the repository root as an absolute path.

    This file lives at ``<repo_root>/src/paths.py``, so the root is the parent
    of the ``src`` directory that contains this module.
    """
    # parents[0] is the src/ directory; parents[1] is the repo root.
    return Path(__file__).resolve().parents[1]


def _load_local_paths() -> dict:
    """Load ``paths.local.yaml`` from the repo root if it exists.

    Returns the parsed mapping, or an empty dict when the file is absent or
    empty. A missing file is a normal case (a fresh clone has none), so this
    never raises for that.
    """
    local_file = _repo_root() / _LOCAL_PATHS_FILENAME
    if not local_file.exists():
        # No local override present: callers fall back to env vars or defaults.
        return {}
    # utf-8-sig tolerates a Windows-authored file that carries a BOM.
    with local_file.open("r", encoding="utf-8-sig") as handle:
        loaded = yaml.safe_load(handle)
    # An empty YAML document parses to None; normalise to an empty dict.
    return loaded or {}


def _first_set(*candidates: str | None) -> str | None:
    """Return the first candidate that is neither None nor blank."""
    for candidate in candidates:
        # Treat empty or whitespace-only strings as "not set".
        if candidate is not None and str(candidate).strip() != "":
            return candidate
    return None


def _resolve_path(cli: str | None, env_value: str | None, local_value: str | None, default: Path) -> Path:
    """Resolve a path while tolerating stale environment overrides.

    Explicit CLI values always win. Environment settings are only used when they
    point to an existing location; otherwise the loader falls back to the
    machine-local YAML override and, finally, the built-in default. This keeps a
    stale one-off env var from blocking a valid local config.
    """
    if cli is not None and str(cli).strip() != "":
        return Path(cli).expanduser().resolve()

    for candidate in (env_value, local_value):
        if candidate is None or str(candidate).strip() == "":
            continue
        path = Path(candidate).expanduser()
        if path.exists():
            return path.resolve()

    return default.resolve()


def resolve_data_dir(cli: str | None = None) -> Path:
    """Resolve the input-data directory as an absolute path.

    Precedence: cli > existing MORTGAGE_DATA_DIR > existing paths.local.yaml
    'data_dir' > <repo_root>/data_sample. A stale env override that points to a
    missing location is ignored so a valid local YAML path still works.
    """
    local = _load_local_paths()
    return _resolve_path(
        cli,
        os.environ.get(_DATA_DIR_ENV),
        local.get("data_dir"),
        _repo_root() / "data_sample",
    )


def resolve_out_dir(cli: str | None = None) -> Path:
    """Resolve the output directory as an absolute path.

    Precedence: cli > existing MORTGAGE_OUT_DIR > existing paths.local.yaml
    'out_dir' > <repo_root>/out. A stale env override that points to a missing
    location is ignored so a valid local YAML path still works.
    """
    local = _load_local_paths()
    return _resolve_path(
        cli,
        os.environ.get(_OUT_DIR_ENV),
        local.get("out_dir"),
        _repo_root() / "out",
    )


def resolve_relative(base_file: str | Path, path: str | Path) -> Path:
    """Resolve ``path`` relative to the folder containing ``base_file``.

    If ``path`` is already absolute it is returned unchanged (resolved). This
    lets a data tree reference its own children by relative path, so the whole
    folder can be moved as one unit to any machine.
    """
    candidate = Path(path)
    if candidate.is_absolute():
        # Absolute paths are honoured as-is.
        return candidate.resolve()
    # Anchor the relative path on the directory of the referring file.
    return (Path(base_file).resolve().parent / candidate).resolve()