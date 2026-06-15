"""Make sure optional metadata blocks in YAML inputs stay truly optional."""

from pathlib import Path

import yaml

from src.engine import load_inputs


def test_meta_block_is_ignored_by_engine(inputs_path, tmp_path):
    """Persist a synthetic ``meta`` block and ensure loading still works.

    Why we care
    -----------
    Modellers often include extra notes in the YAML under a ``meta`` key.  The
    engine should ignore that block entirely.  This test injects such a block,
    round-trips the file through :func:`load_inputs`, and asserts that no
    validation error is raised.  If the loader ever tightens validation too
    aggressively this check will fail and remind us to keep metadata flexible.
    """

    raw = yaml.safe_load(Path(inputs_path).read_text())
    raw["meta"] = {"note": "harmless testing block"}
    tmp_inputs = tmp_path / "inputs.yaml"
    tmp_inputs.write_text(yaml.safe_dump(raw))

    # Should load without error; any exception indicates we started parsing the
    # meta block for real, which is a backwards-incompatible change.
    _ = load_inputs(tmp_inputs)
