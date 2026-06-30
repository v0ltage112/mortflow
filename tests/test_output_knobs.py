# tests/test_output_knobs.py
"""Phase 6 / S4: the output.* knobs and the parsed-and-deferred payment holidays.

These tests pin two promises made in S4:

1. The ``output`` block is honoured. Each switch (write the workbook, write the
   CSVs, include the daily events) toggles its artefact, the currency knob picks
   the money symbol, and the defaults reproduce the pre-S4 behaviour exactly so
   an unchanged config writes an unchanged set of files.
2. ``bank.payment_holidays`` is parsed and validated but not applied. The
   records load and are checked for a sane window and a known mode; activation
   is deferred to a later phase so the golden master does not move.

The CLI-level test runs the real ``python -m src.engine`` so it exercises the
writer path end to end, mirroring how the golden-master test invokes the engine.

Phase 8 / S3 note: the CSVs now land under a ``csv/`` subfolder (the
``output.csv_subdir`` knob, default ``csv``), so the CLI gating test looks for
them there; only the workbook stays at the output root.
"""

from __future__ import annotations

import os
import subprocess
import sys
from datetime import date
from pathlib import Path

import pytest
import yaml

from src.engine.schema import load_inputs
from src.engine.report import money_number_format

# Repo root holds both tools/ and data_sample/; the tests live one level under it.
REPO_ROOT = Path(__file__).resolve().parents[1]


def _load_raw(inputs_path: Path) -> dict:
    """Read the property's YAML into a plain dict for editing in a test."""
    return yaml.safe_load(Path(inputs_path).read_text())


def _write_tmp_inputs(raw: dict, tmp_path: Path) -> Path:
    """Write an edited inputs dict to a temp file and return its path."""
    p = tmp_path / "inputs.yaml"
    p.write_text(yaml.safe_dump(raw, sort_keys=False))
    return p


def test_output_defaults_reproduce_today(inputs_path, tmp_path):
    """A config with no ``output`` block keeps every artefact on, euro, en_IE.

    Why we care: the S4 contract is that defaults reproduce the pre-S4 behaviour
    exactly. If a default ever flips, an unchanged config would silently stop
    writing a file or change its currency, which is the drift S4 must avoid.
    """
    raw = _load_raw(inputs_path)
    raw.pop("output", None)  # remove the block entirely to test the defaults
    tmp = _write_tmp_inputs(raw, tmp_path)

    out = load_inputs(tmp).output
    assert out.write_excel is True
    assert out.write_csv is True
    assert out.include_daily_events is True
    assert out.currency == "EUR"
    assert out.locale == "en_IE"


def test_output_block_is_honoured(inputs_path, tmp_path):
    """Explicit ``output`` values are read through to the parsed Inputs."""
    raw = _load_raw(inputs_path)
    raw["output"] = {
        "write_excel": False,
        "write_csv": False,
        "include_daily_events": False,
        "currency": "gbp",       # lower-case on purpose; should normalise to GBP
        "locale": "en_GB",
    }
    tmp = _write_tmp_inputs(raw, tmp_path)

    out = load_inputs(tmp).output
    assert out.write_excel is False
    assert out.write_csv is False
    assert out.include_daily_events is False
    assert out.currency == "GBP"
    assert out.locale == "en_GB"


def test_payment_holidays_parsed_and_validated(inputs_path, tmp_path):
    """The Gandon sample carries one holiday; it parses with the right fields.

    The block is read and validated but not applied to the schedule (S4 is
    parse-and-defer), so this only asserts the parse, not any change in figures.
    """
    raw = _load_raw(inputs_path)
    holidays = load_inputs(_write_tmp_inputs(raw, tmp_path)).payment_holidays
    assert len(holidays) == 1
    ph = holidays[0]
    assert ph.start == date(2024, 3, 26)
    assert ph.end == date(2024, 7, 31)
    assert ph.mode == "interest_only"
    assert ph.capitalise is True


def test_bad_payment_holiday_mode_raises(inputs_path, tmp_path):
    """An unrecognised holiday mode fails loudly at load time."""
    raw = _load_raw(inputs_path)
    bank = raw.setdefault("bank", {})
    bank["payment_holidays"] = [
        {"start": "2024-03-26", "end": "2024-07-31", "mode": "nonsense", "capitalise": True}
    ]
    tmp = _write_tmp_inputs(raw, tmp_path)
    with pytest.raises(ValueError):
        load_inputs(tmp)


def test_payment_holiday_reversed_window_raises(inputs_path, tmp_path):
    """A holiday whose end precedes its start is a config error."""
    raw = _load_raw(inputs_path)
    bank = raw.setdefault("bank", {})
    bank["payment_holidays"] = [
        {"start": "2024-07-31", "end": "2024-03-26", "mode": "interest_only", "capitalise": True}
    ]
    tmp = _write_tmp_inputs(raw, tmp_path)
    with pytest.raises(ValueError):
        load_inputs(tmp)


def test_money_number_format():
    """Currency maps to the right Excel money mask; EUR is unchanged from before."""
    assert money_number_format("EUR") == "€#,##0.00"
    assert money_number_format("eur") == "€#,##0.00"   # normalised
    assert money_number_format(None) == "€#,##0.00"    # default
    assert money_number_format("GBP") == "£#,##0.00"
    assert money_number_format("USD") == "$#,##0.00"
    # An unknown code stays labelled with its ISO code as a prefix.
    assert money_number_format("ZZZ") == '"ZZZ "#,##0.00'


def test_cli_gates_excel_and_events(inputs_path, actuals_path, tmp_path):
    """Running the engine with switches off suppresses exactly those artefacts.

    write_excel:false and include_daily_events:false should leave no workbook and
    no daily-events CSV, while the monthly and reconcile CSVs are still written.
    Tax is turned off here so the run does not need tenancy files in the temp dir;
    this test is about the output gating only.
    """
    raw = _load_raw(inputs_path)
    raw["output"] = {
        "write_excel": False,
        "write_csv": True,
        "include_daily_events": False,
        "currency": "EUR",
        "locale": "en_IE",
    }
    # Tax off so the CLI does not look for tenancy files beside the temp inputs.
    tax = raw.setdefault("tax", {})
    tax["enabled"] = False
    tmp_inputs = _write_tmp_inputs(raw, tmp_path)

    out_dir = tmp_path / "out"
    env = dict(os.environ)
    # Force UTF-8 stdio so the child's status prints encode on every platform,
    # mirroring the golden-master subprocess setup.
    env["PYTHONUTF8"] = "1"
    env["PYTHONIOENCODING"] = "utf-8"
    subprocess.run(
        [
            sys.executable, "-m", "src.engine",
            "--inputs", str(tmp_inputs),
            "--actuals", str(actuals_path),
            "--out", str(out_dir),
        ],
        cwd=str(REPO_ROOT),  # repo root must be importable under -m
        env=env,
        check=True,
    )

    # Phase 8 / S3: CSVs now land under the csv/ subfolder (output.csv_subdir,
    # default "csv"); only the workbook would sit at the property root.
    csv_dir = out_dir / "csv"
    # Workbook suppressed: write_excel is off, so no .xlsx is written at the
    # property root at all (glob is robust to the S2 <slug>_model.xlsx rename).
    assert not list(out_dir.glob("*.xlsx"))
    # Daily-events CSV suppressed: absent from the csv/ folder.
    assert not (csv_dir / "events_daily.csv").exists()
    # The other CSVs are still written, now inside csv/.
    assert (csv_dir / "schedule_monthly.csv").exists()
    assert (csv_dir / "reconcile.csv").exists()