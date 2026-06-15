# tests/test_paths.py
"""Tests for the Phase 2 path resolver (src/paths.py).

These tests pin the resolver contract introduced in P2/S1:

* precedence is CLI > environment > paths.local.yaml > repo defaults, and
* resolve_relative anchors relative paths on the base file's parent while
  leaving absolute paths untouched.

The tests are deterministic on any machine: they set and clear their own
environment variables via monkeypatch, and they skip the bare-default case when
a local paths.local.yaml is present (which would legitimately override the
repo defaults).
"""
import pytest
from pathlib import Path

from src.paths import resolve_data_dir, resolve_out_dir, resolve_relative

# Repo root mirrors src/paths.py's own _repo_root() (parents[1] of this file,
# since tests/ sits directly under the repo root).
REPO_ROOT = Path(__file__).resolve().parents[1]


def test_cli_value_wins_for_data_dir(tmp_path):
    """An explicit CLI value is returned verbatim (resolved)."""
    # The CLI argument is the highest-priority source, so the result is tmp_path.
    assert resolve_data_dir(str(tmp_path)).resolve() == tmp_path.resolve()


def test_cli_value_wins_for_out_dir(tmp_path):
    """An explicit CLI value is returned verbatim (resolved) for the out dir."""
    assert resolve_out_dir(str(tmp_path)).resolve() == tmp_path.resolve()


def test_env_used_when_no_cli_data_dir(tmp_path, monkeypatch):
    """With no CLI value, MORTGAGE_DATA_DIR drives the result."""
    # Set the env var; monkeypatch restores the previous value at teardown.
    monkeypatch.setenv("MORTGAGE_DATA_DIR", str(tmp_path))
    assert resolve_data_dir().resolve() == tmp_path.resolve()


def test_env_used_when_no_cli_out_dir(tmp_path, monkeypatch):
    """With no CLI value, MORTGAGE_OUT_DIR drives the result."""
    monkeypatch.setenv("MORTGAGE_OUT_DIR", str(tmp_path))
    assert resolve_out_dir().resolve() == tmp_path.resolve()


def test_cli_overrides_env_data_dir(tmp_path, monkeypatch):
    """A CLI value takes priority over the environment variable."""
    env_dir = tmp_path / "from_env"
    cli_dir = tmp_path / "from_cli"
    monkeypatch.setenv("MORTGAGE_DATA_DIR", str(env_dir))
    # CLI wins, so the env value is ignored.
    assert resolve_data_dir(str(cli_dir)).resolve() == cli_dir.resolve()


def test_cli_overrides_env_out_dir(tmp_path, monkeypatch):
    """A CLI value takes priority over the environment variable for the out dir."""
    env_dir = tmp_path / "from_env"
    cli_dir = tmp_path / "from_cli"
    monkeypatch.setenv("MORTGAGE_OUT_DIR", str(env_dir))
    assert resolve_out_dir(str(cli_dir)).resolve() == cli_dir.resolve()


def test_default_data_dir_is_repo_data(monkeypatch):
    """With no CLI and no env, the data dir defaults to <repo>/data."""
    # A local paths.local.yaml legitimately overrides the default; skip if present.
    if (REPO_ROOT / "paths.local.yaml").exists():
        pytest.skip("paths.local.yaml present; default would be overridden")
    # Ensure the environment does not interfere with the default lookup.
    monkeypatch.delenv("MORTGAGE_DATA_DIR", raising=False)
    assert resolve_data_dir().resolve() == (REPO_ROOT / "data").resolve()


def test_default_out_dir_is_repo_out(monkeypatch):
    """With no CLI and no env, the out dir defaults to <repo>/out."""
    if (REPO_ROOT / "paths.local.yaml").exists():
        pytest.skip("paths.local.yaml present; default would be overridden")
    monkeypatch.delenv("MORTGAGE_OUT_DIR", raising=False)
    assert resolve_out_dir().resolve() == (REPO_ROOT / "out").resolve()


def test_resolve_relative_leaves_absolute_unchanged(tmp_path):
    """An absolute path is returned unchanged regardless of the base file."""
    base = tmp_path / "inputs.yaml"
    absolute = tmp_path / "elsewhere" / "tenancy.local.yaml"
    # Absolute inputs must pass through (resolved) without being re-anchored.
    assert resolve_relative(base, str(absolute)).resolve() == absolute.resolve()


def test_resolve_relative_anchors_on_base_parent(tmp_path):
    """A relative path is anchored on the base file's parent directory."""
    base = tmp_path / "inputs.yaml"
    # "tenancy.local.yaml" should resolve beside inputs.yaml, i.e. in tmp_path.
    got = resolve_relative(base, "tenancy.local.yaml")
    assert got.resolve() == (tmp_path / "tenancy.local.yaml").resolve()


def test_resolve_relative_accepts_path_and_str(tmp_path):
    """Both str and Path inputs are accepted and produce the same result."""
    base = tmp_path / "inputs.yaml"
    as_str = resolve_relative(str(base), "tenancy.sample.yaml")
    as_path = resolve_relative(base, Path("tenancy.sample.yaml"))
    expected = (tmp_path / "tenancy.sample.yaml").resolve()
    assert as_str.resolve() == expected
    assert as_path.resolve() == expected