# DECISIONS_AND_LEARNINGS.md — Durable Evidence and Decisions

> Durable findings that affect future work. Keep the categories separate.
> Do not convert an observed pattern into an approved business decision.

**Last updated:** 2026-09-26

---

## Confirmed facts

Facts verified against the repository or an authoritative source.

- **F1.** The engine is a daily ACT/365 cashflow model for Irish residential
  mortgages. Public repo `github.com/v0ltage112/mortflow`.
- **F2.** `main` is at `218f8ce`, tagged `v2.2.0`. The working tree is clean.
- **F3.** The test suite currently reports **1 failed, 170 passed, 4 skipped**.
  The failure is `test_golden_master.py::test_root_csv_locked[portfolio_summary.csv]`.
- **F4.** The golden master compares CSVs to two decimal places and the
  effective-inputs YAML byte-for-byte.
- **F5.** `Inputs` is a frozen dataclass with `.copy()` / `.clone()`.
- **F6.** Path resolution precedence is CLI > env (`MORTGAGE_DATA_DIR` /
  `MORTGAGE_OUT_DIR`) > `paths.local.yaml` > repo defaults (`data_sample`, `out`).
- **F7.** Property `kind` maps to module toggles as data
  (`KIND_DEFAULT_TOGGLES` in `src/engine/schema.py`).
- **F8.** Lender rules are effective-dated YAML resolved by `src/engine/profile.py`.
- **F9.** The active phase is Phase 13 (scenario / what-if analysis), target tag
  `v2.3.0`, rollback `v2.2.0`. The active session is Phase 13 / S1.
- **F10.** `tests/test_overpayment_cap_headroom.py` is tracked and 0 bytes.
- **F11.** Phase 12 shipped `v2.2.0` at `main` `218f8ce` with 171 passed / 4
  skipped / 0 failed.
- **F12.** Local code path is `C:\Code\mortflow`; data and outputs live outside
  the repo (private, backed up), linked via git-ignored `paths.local.yaml`. The
  real location is deliberately not recorded in tracked files.
- **F13.** The old private repo `github.com/v0ltage112/mortgage-model` is archived.
- **F14.** Phase 13 is additive: a new `scenarios` module and a new scenarios
  output, with no breaking `inputs.yaml` change.
- **F15.** The Phase 13 always-generated scenario set is locked (see
  `AGENT_STATUS.md`).
- **F16.** Phase 14 is the multi-property dashboard; Phase 15 is RPZ projection.
- **F17.** The CI pipeline was dropped from the active spine to the backlog on
  2026-07-16 (solo dev runs `pytest` before every push).

---

## Approved decisions

Decisions explicitly agreed with the project owner.

- **D1.** The repository is structured to align with the
  `python-engineer-companion-coach` skill's Companion Project infrastructure.
  *(2026-09-26)*
- **D2.** The Notion `mortgage_model` workspace remains the **master** record;
  the repository is the **day-to-day working copy**. Both are kept in sync
  manually at phase close. *(2026-09-26)*
- **D3.** The first structuring step covers the scaffold plus migration of the
  **active phase and backlog**; historical phases are summarised, not migrated in
  full. *(2026-09-26)*
- **D4.** Phase merges use `git merge --no-ff` (the project's established
  convention), followed by an annotated tag. *(established practice)*
- **D5.** Phase 13 ships `v2.3.0` (minor bump: additive `scenarios` module and a
  new scenarios output, no breaking `inputs.yaml` change), rollback `v2.2.0`.
  *(Notion Phase 13 Design Decision 1)*
- **D6.** Scenarios are declared in `scenarios.yaml` beside `inputs.yaml`; each
  scenario is a named list of perturbations applied to a cloned baseline
  `Inputs`. The baseline is never mutated. *(Notion Phase 13 Design Decision 2)*
- **D7.** The scenario runner is a pipeline; each layer (rental, tax) is a
  transform on the results object, not embedded in the runner. Inert hooks are
  built this phase and left empty. *(Notion Phase 13 Design Decision 10)*
- **D8.** Test strategy for Phase 13 is analytical (closed-form) tests, not
  golden masters, because golden masters do not fit dynamic scenario outputs.
  *(Notion Phase 13 Design Decision 9)*
- **D9.** Gandon (rental) interest-saved is reported gross only this phase; the
  net-of-tax figure needs the tax layer. It must be flagged, never presented as
  net. *(Notion Phase 13 scope guardrail)*
- **D10.** Tracked files must not contain real machine-specific paths or cloud
  folder structures. Use generic placeholders (e.g. `D:/path/to/mortgage_model/data`).
  The real location lives only in git-ignored `paths.local.yaml`. *(Operating
  Contract section 10; reaffirmed 2026-09-26 after a real Drive path was briefly
  added to the new handoff docs and then removed.)*
- **D11.** The property nicknames (Gandon / Somerton / Paragon) are retained in
  tracked code comments, tests and docs as readable labels. They are not
  addresses and have been public since Phase 3. Owner confirmed 2026-09-26 that
  they are acceptable; `BACKLOG-008` is closed as REJECTED. *(2026-09-26)*

---

## Working assumptions

Believed true but not yet fully verified. Re-check before relying on them.

- **A1.** ~~The migrated Phase 13 session list (S0-S9) is complete and accurate.~~
  **VERIFIED 2026-09-26** against the pasted Notion Master Handoff and Phase 13
  Handoff Log.
- **A2.** ~~The backlog items listed in `PRODUCT_BACKLOG.md` are the full set.~~
  **VERIFIED 2026-09-26** against the pasted Notion Master Handoff Backlog table.
- **A3.** ~~Phase 14 is the dashboard and Phase 15 is RPZ.~~ **VERIFIED
  2026-09-26** against the pasted Notion Roadmap and Project Plan.
- **A4.** The golden-master failure is caused solely by the `date.today()` call
  in `_valuation_summary_row`; no other figure has drifted.

---

## Unresolved questions

- What is the exact BOI breakage wording and the R% / R1% money-market rate
  source for the breakage fee (Phase 13 / S5)?
- Do actuals-based scenarios ship in `v2.3.0` or defer? (Hypothetical scenarios
  are built fully either way.) Confirm at S1.
- What default alternative return rate feeds the opportunity-cost metric? Confirm
  at S4.
- Output placement: dedicated `scenarios.xlsx` per property plus a comparison
  summary, or a Scenarios sheet on each property workbook? Confirm at S1/S8.
- Where do scenario metrics live? The backlog layered-metrics refactor suggests
  splitting `metrics.py` before the rental/tax layers land. Decide at S4.
- Should the golden master be made deterministic by deriving `as_of` from the
  schedule, or by accepting an explicit `--as-of` override?

---

## Rejected options

- **Migrating the Notion "Latest Code dashboard" / code mirror into the repo.**
  Rejected: the live code is the source of truth; a mirror would drift and
  duplicate. *(2026-09-26)*
- **Making Notion the sole source of truth.** Rejected in favour of D2, so a
  successor agent can work without Notion access. *(2026-09-26)*

---

## Reusable engineering lessons

- **L1.** A regression lock that depends on `date.today()` is not a regression
  lock — it fails on the calendar. Deterministic fixtures must pin every date.
- **L2.** An empty committed test file implies coverage that does not exist;
  delete or fill it.
- **L3.** Duplicated constants (kind sets, slugify, date helpers) drift silently;
  keep one canonical definition and import it.
- **L4.** `assert` is stripped under `python -O`; use explicit exceptions for
  input validation.
- **L5.** On Windows, `Path.read_text()` without `encoding="utf-8"` uses the
  locale code page and can mis-read UTF-8 content.
