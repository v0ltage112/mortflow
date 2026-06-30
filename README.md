# 🏠 mortflow

> **Disclosure:** This project was built for personal use with the assistance of AI tools (Claude / Notion AI). It has been reviewed, tested, and validated by the author, but it originates from an AI-assisted workflow. Use it as a starting point, not as financial or legal advice.

Daily ACT/365 cashflow engine for Irish residential mortgages. The project takes a property's bank transactions and modelling assumptions, produces auditable CSV + Excel outputs, and optionally builds Form 11 schedules. Portfolio and baseline tools sit on top so you can batch multiple properties or capture strict "contract only" benchmarks.

The code is decoupled from where its data and outputs live. Clone the repo anywhere, point it at your data, and run. A fresh clone runs on the bundled sample data with no configuration at all.

---

## ✨ Highlights

- **Daily engine** – realistic payment timing, rate blocks, overpayments, and one-off lump sums are simulated from `inputs.yaml` + `actuals.csv`.
- **Multi-property toggles** – each property declares a *kind* (investment, primary residence, owned-outright) and mortgage / tax / valuation switch independently; an owned-outright property runs a no-mortgage valuation-only path.
- **Bank reconciliation** – running balance comparison, portal snapshots, and tolerances are tracked so the model stays aligned with the bank feed.
- **Tax reporting** – tenancy metadata and occupancy windows drive the Form 11 `TaxYear`, `TaxAudit`, and `TenancyLog` sheets when tax is enabled.
- **Valuation & LTV analytics** – valuation blocks and HPI-style growth factors feed portfolio KPIs such as `property_value_asof` and `ltv_asof`.
- **Portfolio + baseline tooling** – batch run every enabled property, produce a formatted summary workbook, and pre-compute "strict" contractual baselines for reconciliations.
- **Portable paths** – data and output locations are resolved from config (CLI flag, environment variable, or `paths.local.yaml`), so the code and your private data can live in separate places on any machine.

---

## 📦 Repository layout

```text
mortflow/
├── data_sample/                # Anonymised sample data (committed — zero-config demo runs)
│   ├── portfolio.yaml          # Declares the sample properties to batch (kind + enable toggles)
│   ├── property_a/             # Sample investment property: mortgage + tax + valuation
│   │   ├── actuals.sample.csv
│   │   ├── inputs.sample.yaml
│   │   └── tenancy.sample.yaml # Anonymised tenancy schema example
│   ├── property_b/             # Sample residence (primary): mortgage on, tax off (disabled by default)
│   │   ├── actuals.sample.csv
│   │   └── inputs.sample.yaml
│   └── property_c/             # Sample owned-outright property: valuation-only, no mortgage (disabled by default)
│       └── inputs.sample.yaml
├── data/                       # Your real data (gitignored — never committed)
├── src/
│   ├── engine/                 # Core daily ACT/365 engine package
│   │   ├── __init__.py         # Re-export facade: the public API (run_engine, loaders, dataclasses)
│   │   ├── __main__.py         # CLI entry point (python -m src.engine); branches on property kind
│   │   ├── helpers.py          # Generic date + numeric helpers (incl. growth_to_decimal)
│   │   ├── schema.py           # Input dataclasses + YAML/CSV loaders; property kind + module toggles
│   │   ├── valuation.py        # Property value + LTV helpers
│   │   ├── valuation_only.py   # No-mortgage valuation-only path (value over time, no loan)
│   │   ├── monthly.py          # Rate lookup, month scaffolding, monthly schedule
│   │   ├── reconcile.py        # Model-vs-bank reconcile + tolerance labels
│   │   ├── report.py           # Output writer: CSV + Excel, honours the output.* knobs
│   │   └── simulate.py         # Daily simulation loop + run_engine orchestrator
│   ├── metrics.py              # Portfolio KPI helpers
│   ├── paths.py                # Data/output path resolver (config layer)
│   └── tax.py                  # Tenancy loader + Form 11 logic
├── tools/
│   ├── baseline.py             # Strict baseline builder (portfolio or single)
│   └── portfolio.py            # Portfolio runner + summary formatter
├── tests/                      # Pytest coverage for engine, tax, metrics, paths
├── paths.sample.yaml           # Tracked template: copy to paths.local.yaml
├── paths.local.yaml            # Your machine's data/out paths (gitignored)
├── requirements.txt            # Minimal runtime dependencies
├── run.bat                     # Windows helper: venv + baseline + portfolio (real data)
├── run_sample.bat              # Windows helper: runs against data_sample/ (no setup needed)
└── README.md
```

The `data_sample/` folder lets a fresh clone run immediately. Your real, private data does not need to live in the repository.

Generated artefacts land in the configured output directory (the bundled default is `out/`, ignored by Git).

---

## 🗂️ Data & output locations

The engine and tools resolve their data and output directories from the first source that is set, highest priority first:

1. **CLI flag** – an explicit path passed on the command line (for example `--out`).
2. **Environment variable** – `MORTGAGE_DATA_DIR` / `MORTGAGE_OUT_DIR`.
3. **`paths.local.yaml`** – a gitignored file at the repo root, with `data_dir` and `out_dir` keys.
4. **Defaults** – the in-repo `./data_sample` and `./out` folders.

Because the defaults point at the bundled sample data, a fresh clone runs with zero configuration. To use your own data, set one of the higher-priority sources.

### Recommended split: code vs data

Keep the cloned repository off any cloud-synced folder, and keep your private data and outputs somewhere separate and backed up:

```text
# Code: versioned, disposable, clone anywhere off cloud sync
C:\Code\mortflow

# Data + outputs: private, backed up (placeholder paths)
D:\path\to\mortgage_model\data
D:\path\to\mortgage_model\out
```

The repository never needs to hold your real data. The link between the two is config, set one of two ways.

### Option A: environment variables (recommended)

Set two persistent user environment variables to your data and output folders, then open a new terminal so they take effect:

```powershell
setx MORTGAGE_DATA_DIR "D:\path\to\mortgage_model\data"
setx MORTGAGE_OUT_DIR  "D:\path\to\mortgage_model\out"
```

### Option B: paths.local.yaml

Copy the tracked template and edit it. `paths.local.yaml` is gitignored, so your real paths are never committed:

```powershell
cp paths.sample.yaml paths.local.yaml
```

```yaml
# paths.local.yaml
data_dir: "D:/path/to/mortgage_model/data"
out_dir:  "D:/path/to/mortgage_model/out"
```

Use forward slashes even on Windows to avoid backslash-escaping issues. Paths referenced inside the data tree resolve relative to their own folder, so the whole data tree can be moved as one unit.

---

## 🚀 Getting started

```bash
git clone https://github.com/v0ltage112/mortflow.git
cd mortflow
python -m venv .venv

# macOS / Linux
source .venv/bin/activate

# Windows PowerShell
.\.venv\Scripts\Activate.ps1

pip install -r requirements.txt
```

On Windows, clone to a folder that is not inside a cloud-synced directory (for example `C:\Code\mortflow`) so Git never fights the sync client.

Straight after cloning, run `run_sample.bat` (Windows) to execute a full run against the bundled sample data with no further setup. Point the tools at your own data via the mechanisms in Data & output locations above.

`run.bat` provides a one-click path on Windows for real-data runs: it creates the virtual environment (if needed), installs dependencies, builds strict baselines for the portfolio, and runs the regular portfolio batch. It reads the configured data and output folders, so it writes wherever `MORTGAGE_DATA_DIR` / `MORTGAGE_OUT_DIR` (or `paths.local.yaml`) point.

---

## 🏃 Running the engine

### Single property

```bash
python -m src.engine \
  --inputs data/property_a/inputs.yaml \
  --actuals data/property_a/actuals.csv \
  --out out/property_a
```

The command writes `mortgage_outputs.xlsx` alongside CSV exports:

| File | Contents |
| --- | --- |
| `schedule_monthly.csv` | Modelled monthly schedule with payments, extras, lumps, and balances |
| `reconcile.csv` | Bank vs model comparison with tolerance metrics |
| `events_daily.csv` | Daily event log including accrual and postings |
| `tax_year.csv` | Calendar-year Form 11 summary when tax is enabled |
| `tax_audit.csv` | Month-level deductible audit trail |

The Excel workbook mirrors those tables and, when tax is on, also includes `TenancyLog` and `TaxAudit` sheets with light formatting for review.

### Portfolio batch

Run every enabled property declared in the configured `portfolio.yaml` and build a portfolio summary workbook + CSV listing KPIs such as payoff date, next payment details, and LTV as-of values:

```bash
python -m tools.portfolio --portfolio data/portfolio.yaml --out out/portfolio
```

Use `--only "Property Name"` to run a single entry from the portfolio file.

### Baseline builder

Baselines strip user overlays (recurring overpays, lump sums, merge-extra behaviour) so you can reconcile pure contractual schedules with bank data:

```bash
python -m tools.baseline --portfolio data/portfolio.yaml --out out/baseline --strict-baseline
```

For ad-hoc runs you can also call `tools.baseline` with `--inputs`/`--actuals`. The baseline folder contains `baseline_monthly.csv`, `baseline_reconcile.csv`, `baseline_events_daily.csv`, and `baseline_kpis.xlsx` per property, plus a portfolio KPI workbook when you run in batch mode.

---

## 🛠️ Configuration & data

- **`inputs.yaml`** – drawdown details, rate blocks, bank settings, valuation assumptions, and modelling windows. Tax settings live under the `tax:` block.
- **`actuals.csv`** – chronological bank transactions: drawdown, scheduled repayments, extras, and posted interest.
- **`tenancy.local.yaml`** – private tenancy metadata (rent, occupancy, RTB registration). Keep the file beside each property; it is gitignored and never committed.
- **`portfolio.yaml`** – list of properties with pointers to inputs and actuals. Toggle `enabled: true/false` to control portfolio inclusion, or add metadata (e.g. `property_kind`, `tax_enabled`) for reporting.
- **`paths.local.yaml`** – gitignored per-machine override of the data and output directories (`data_dir`, `out_dir`). Copy from `paths.sample.yaml`.

See `data_sample/` for the expected format and schema of each file type.

---

## 📊 Tests

The pytest suite covers reconciliation tolerances, interest accrual, valuation blocks, tax schedules, KPI calculations, path resolution, and regression guards around merge-extra behaviour.

```bash
pytest -q
```

Expected: **64 passed, 2 skipped, 0 failed**.

Run the tests after dependency updates or when you change the engine/tax logic to ensure both the financial maths and tax outputs stay within contract tolerances.

---

## ❓ FAQ

**Where does the engine read data and write outputs?**
From the first configured source: a CLI flag, then `MORTGAGE_DATA_DIR` / `MORTGAGE_OUT_DIR`, then `paths.local.yaml`, then the bundled `./data_sample` and `./out`. See Data & output locations.

**Can I skip the tax outputs?**
Set `tax.enabled: false` in `inputs.yaml`. The engine will still generate the mortgage schedules while omitting tax sheets.

**Where does the occupancy ratio come from?**
Occupancy is derived from `tenancy.local.yaml` (days let vs available) and is combined with the tax configuration to compute deductible percentages.

**How are RPZ limits handled?**
Include an `rpz:` block per tenancy with historical rent and HICP data. The module stores the details today and will feed future rent projections.

**What about owner-occupied periods?**
Remove those months from the tenancy file or configure `deductible_window` ranges in `inputs.yaml` so tax only applies when the property was let or available for letting under section 97(2J) TCA 1997.

---

 ## 🪜 Version history

| Version | Date | Highlights |
| --- | --- | --- |
| v1.4.0 | 2026-06-15 | Initial public release. Daily ACT/365 engine, anonymised sample data, PolyForm Noncommercial licence. |
| v1.5.0 | 2026-06-16 | Verification & behaviour lock: golden-master snapshot test, pinned dependencies. |
| v1.6.0 | 2026-06-17 | engine.py refactored into a src/engine/ package behind a re-export facade; run_engine decomposed into simulate / monthly / reconcile / valuation; helper dedupe and dead-import cleanup. No behaviour change. |
| v1.7.0 | 2026-06-19 | Multi-property scaffolding & toggles: a property kind drives independent mortgage / tax / valuation modules, including a no-mortgage valuation-only path; ignored YAML knobs (output.*) now honoured and payment_holidays parse-and-defer; three-property sample data (Gandon investment, Somerton primary, Paragon owned-outright) with portfolio enable / kind toggles. Gandon golden master unchanged. |
| v1.8.0 | 2026-06-29 | Overpayment attribution. Each monthly payment now splits into contractual, overpayment, lump, and an explicit Difference residual, driven by agreed terms rather than the merge flag. Conserved quantities (total paid, interest, principal, balance, payoff) byte-identical to v1.7.0; only the attribution columns are new, renamed, or reordered. Legacy payment_amount and extra_amount columns retired; portfolio KPIs report total_contractual / total_overpayment / total_difference and the next-payment figure reports the contractual instalment. Golden master re-baselined to the new column set. |


---

## 📄 Licence

PolyForm Noncommercial License 1.0.0. Free for personal and non-commercial use.
Commercial use requires a separate written agreement with the author.
See `LICENSE` for full terms or contact: a.a.madras@gmail.com
