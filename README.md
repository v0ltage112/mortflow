# README.md — v1 Authored Output (P2/S3)

<aside>
📄

**Paste into:** repo root as `README.md` (full replacement). Rendered natively for readability; copy the page content to reconstruct the file. All paths here are generic placeholders per Operating Contract section 10.

</aside>

# 🏠 Mortgage Model

Daily ACT/365 cashflow engine for Irish residential mortgages. The project takes a property's bank transactions and modelling assumptions, produces auditable CSV + Excel outputs, and optionally builds Form 11 schedules. Portfolio and baseline tools sit on top so you can batch multiple properties or capture strict "contract only" benchmarks.

The code is decoupled from where its data and outputs live. Clone the repo anywhere, point it at your data, and run. A fresh clone runs on the bundled sample data with no configuration at all.

---

## ✨ Highlights

- **Daily engine** – realistic payment timing, rate blocks, overpayments, and one-off lump sums are simulated from `inputs.yaml` + `actuals.csv`.
- **Bank reconciliation** – running balance comparison, portal snapshots, and tolerances are tracked so the model stays aligned with the bank feed.
- **Tax reporting** – tenancy metadata and occupancy windows drive the Form 11 `TaxYear`, `TaxAudit`, and `TenancyLog` sheets when tax is enabled.
- **Valuation & LTV analytics** – valuation blocks and HPI-style growth factors feed portfolio KPIs such as `property_value_asof` and `ltv_asof`.
- **Portfolio + baseline tooling** – batch run every enabled property, produce a formatted summary workbook, and pre-compute "strict" contractual baselines for reconciliations.
- **Portable paths** – data and output locations are resolved from config (CLI flag, environment variable, or `paths.local.yaml`), so the code and your private data can live in separate places on any machine.

---

## 📦 Repository layout

```
mortgage-model/
├── data/                       # Bundled sample data (zero-config demo runs)
│   ├── gandon/                 # Sample investment property (full tax data)
│   │   ├── actuals.csv
│   │   ├── inputs.yaml
│   │   ├── tenancy.local.yaml  # Private tenancy details (git-ignored template)
│   │   └── tenancy.sample.yaml # Public schema example
│   ├── somerton/               # Sample owner-occupied profile (disabled)
│   │   ├── actuals.somerton.csv
│   │   └── inputs.somerton.yaml
│   └── portfolio.yaml          # Declares the properties to batch
├── src/
│   ├── engine.py               # Core daily engine + CLI
│   ├── metrics.py              # Portfolio KPI helpers
│   ├── paths.py                # Data/output path resolver (config layer)
│   └── tax.py                  # Tenancy loader + Form 11 logic
├── tools/
│   ├── baseline.py             # Strict baseline builder (portfolio or single)
│   └── portfolio.py            # Portfolio runner + summary formatter
├── tests/                      # Pytest coverage for engine, tax, metrics, paths
├── paths.sample.yaml           # Tracked template: copy to paths.local.yaml
├── paths.local.yaml            # Your machine's data/out paths (git-ignored)
├── requirements.txt            # Minimal runtime dependencies
├── run.bat                     # Windows helper: venv + baseline + portfolio
└── README.md
```

The bundled `data/` folder lets a fresh clone run immediately. Your real, private data does not need to live in the repository.

Generated artefacts land in the configured output directory (the bundled default is `out/`, ignored by Git).

---

## 🗂️ Data & output locations

The engine and tools resolve their data and output directories from the first source that is set, highest priority first:

1. **CLI flag** – an explicit path passed on the command line (for example `--out`).
2. **Environment variable** – `MORTGAGE_DATA_DIR` / `MORTGAGE_OUT_DIR`.
3. **`paths.local.yaml`** – a git-ignored file at the repo root, with `data_dir` and `out_dir` keys.
4. **Defaults** – the in-repo `./data` and `./out` folders.

Because the defaults point at the bundled sample data, a fresh clone runs with zero configuration. To use your own data, set one of the higher-priority sources.

### Recommended split: code vs data

Keep the cloned repository off any cloud-synced folder, and keep your private data and outputs somewhere separate and backed up:

```
# Code: versioned, disposable, clone anywhere off cloud sync
C:\Code\mortgage-model

# Data + outputs: private, backed up (placeholder paths)
D:\path\to\mortgage_model\data
D:\path\to\mortgage_model\out
```

The repository never needs to hold your real data. The link between the two is config, set one of two ways.

### Option A: environment variables (recommended)

Set two persistent user environment variables to your data and output folders, then open a new terminal so they take effect:

```bash
setx MORTGAGE_DATA_DIR "D:\path\to\mortgage_model\data"
setx MORTGAGE_OUT_DIR  "D:\path\to\mortgage_model\out"
```

### Option B: paths.local.yaml

Copy the tracked template and edit it. `paths.local.yaml` is git-ignored, so your real paths are never committed:

```bash
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
git clone https://github.com/v0ltage112/mortgage-model.git
cd mortgage-model
python -m venv .venv
# macOS / Linux
source .venv/bin/activate
# Windows PowerShell
.\.venv\Scripts\Activate.ps1
pip install -r requirements.txt
```

On Windows, clone to a folder that is not inside a cloud-synced directory (for example `C:\Code\mortgage-model`) so Git never fights the sync client.

Straight after cloning, `python -m tools.portfolio` runs against the bundled sample data with no further setup. Point the tools at your own data via the mechanisms in Data & output locations above.

`run.bat` provides a one-click path on Windows that creates the virtual environment (if needed), installs dependencies, builds strict baselines for the portfolio, and runs the regular portfolio batch. It reads the configured data and output folders, so it writes wherever `MORTGAGE_DATA_DIR` / `MORTGAGE_OUT_DIR` (or `paths.local.yaml`) point.

---

## 🏃‍♀️ Running the engine

### Single property

```bash
python -m src.engine \
  --inputs data/gandon/inputs.yaml \
  --actuals data/gandon/actuals.csv \
  --out out/gandon
```

The command writes `mortgage_outputs.xlsx` alongside CSV exports:

| **File** | **Contents** |
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

### Baseline builder (Phase S0)

Baselines strip user overlays (recurring overpays, lump sums, merge-extra behaviour) so you can reconcile pure contractual schedules with bank data:

```bash
python -m tools.baseline --portfolio data/portfolio.yaml --out out/baseline --strict-baseline
```

For ad-hoc runs you can also call `tools.baseline` with `--inputs`/`--actuals`. The baseline folder contains `baseline_monthly.csv`, `baseline_reconcile.csv`, `baseline_events_daily.csv`, and `baseline_kpis.xlsx` per property, plus a portfolio KPI workbook when you run in batch mode.

---

## 🛠️ Configuration & data

- **`inputs.yaml`** – drawdown details, rate blocks, bank settings, valuation assumptions, and modelling windows. Tax settings live under the `tax:` block.
- **`actuals.csv`** – chronological bank transactions: drawdown, scheduled repayments, extras, and posted interest.
- **`tenancy.local.yaml`** – private tenancy metadata (rent, occupancy, RTB registration). Keep the file beside each property and add it to `.gitignore` if you store real data.
- **`portfolio.yaml`** – list of properties with pointers to inputs and actuals. Toggle `enabled: true/false` to control portfolio inclusion, or add metadata (e.g. `property_kind`, `tax_enabled`) for reporting.
- **`paths.local.yaml`** – git-ignored per-machine override of the data and output directories (`data_dir`, `out_dir`). Copy from `paths.sample.yaml`.

---

## 📊 Tests

The pytest suite covers reconciliation tolerances, interest accrual, valuation blocks, tax schedules, KPI calculations, path resolution, and regression guards around merge-extra behaviour.

```bash
pytest -q
```

Run the tests after dependency updates or when you change the engine/tax logic to ensure both the financial maths and tax outputs stay within contract tolerances.

---

## ❓ FAQ

**Where does the engine read data and write outputs?**

From the first configured source: a CLI flag, then `MORTGAGE_DATA_DIR` / `MORTGAGE_OUT_DIR`, then `paths.local.yaml`, then the bundled `./data` and `./out`. See Data & output locations.

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

| **Version** | **Date** | **Highlights** |
| --- | --- | --- |
| v0.1–0.2 | 2023 | Initial daily engine and reconcile outputs |
| v0.3 | 2023 | Baseline smoke + reconcile tests |
| v0.4–0.5 | 2024 | Merge-extra guard, YAML schema improvements |
| v0.6.0 | 2024 | Form 11 schedules, tenancy log, tax audit |
| v0.7.0 | 2024 | Portfolio runner, KPI metrics module, strict baseline tooling |
| v1.2.0 | 2026 | Consolidated monolithic engine baseline (rollback point) |
| v1.3.0 | 2026 | Remove OneDrive dependency: config-driven data and output paths |