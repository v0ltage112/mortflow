# START_AGENT.md — Stable Operating Model

> **Read this first, every session.** It is stable guidance for any agent
> (human or AI) picking up `mortflow`. It changes only when the general
> operating model changes — not for every feature.

---

## 1. What this project is

`mortflow` is a daily ACT/365 cashflow engine for Irish residential mortgages.
It takes a property's bank transactions and modelling assumptions, produces
auditable CSV + Excel outputs, and optionally builds Form 11 schedules.
Portfolio and baseline tools sit on top so multiple properties can be batched
or strict "contract only" benchmarks captured.

- **Public repo:** `github.com/v0ltage112/mortflow`
- **Local clone:** `C:\Code\mortflow` (kept off any cloud-synced folder)
- **Real data + outputs:** private, outside the repo, linked by config
  (`MORTGAGE_DATA_DIR` / `MORTGAGE_OUT_DIR` or `paths.local.yaml`). The real
  location is recorded only in the git-ignored `paths.local.yaml`, never in a
  tracked file.
- **Old private repo:** `github.com/v0ltage112/mortgage-model` (archived)

---

## 2. Where things live

| Asset | Location |
| --- | --- |
| Product code | `src/` (`src/engine/` package, `src/paths.py`, `src/tax.py`, `src/metrics.py`) |
| Developer tools | `tools/` (`baseline.py`, `portfolio.py`, `verify_calendar.py`) |
| Tests | `tests/` (pytest; golden master in `tests/fixtures/golden/`) |
| Bundled demo data | `data_sample/` (tracked — zero-config demo runs) |
| Real data | `data/` (git-ignored) |
| Technical docs | `docs/` |
| Agent handoff | `docs/agent_handoff/` (this folder) |
| Product direction | `docs/PRODUCT_VISION.md`, `docs/PRODUCT_DELIVERY_PLAN.md`, `docs/PRODUCT_BACKLOG.md` |

---

## 3. Read order for a new session

1. **This file** (`START_AGENT.md`) — the operating model.
2. **`AGENT_STATUS.md`** — the current operational truth (active phase, branch,
   last verified commit, exact next action).
3. **The active work package** in `work_packages/` — the bounded feature detail.
4. **`DECISIONS_AND_LEARNINGS.md`** — durable facts and approved decisions.
5. **`PRODUCT_DELIVERY_PLAN.md`** — the authorised phase sequence.
6. **`PRODUCT_BACKLOG.md`** — possible future work (NOT authorised).

Then inspect the repository itself: branch, status, relevant files, tests.

---

## 4. How to determine the active assignment

- The active phase is named in `AGENT_STATUS.md` (`Active phase`).
- The active work package is named in `AGENT_STATUS.md` (`Active work package`).
- **One phase is active at a time.** Do not start a second work package for the
  same feature.
- If `AGENT_STATUS.md` and the repository disagree, **the repository wins** —
  then correct `AGENT_STATUS.md`.

---

## 5. Git and branch model

- Default branch: **`main`**. `main` must always be runnable and tested.
- Significant or user-facing work uses a feature branch:
  `phase<N>/<short-name>` (e.g. `phase13/scenario-engine`).
- Completed feature branches are merged into `main` before the next feature
  starts. Prefer `git merge --no-ff` for phase merges (the project's established
  convention), then tag.
- Completed branches are retained locally as rollback references.
- **Never** use `git add .` in a controlled commit. Stage explicit paths only.
- Run `git diff --cached --check` before committing.
- Tags are annotated and semantic: `v2.2.0`, `v2.3.0`, …

### Standard session Git flow

```powershell
git checkout main
git pull
git checkout -b phase<N>/<short-name>   # first session of a phase only
# ... author, apply, test, inspect ...
git add -- <explicit paths>
git diff --cached --check
git commit -m "<scoped message>"
git push -u origin phase<N>/<short-name>
```

---

## 6. Protected areas

These must not change without an explicit, validated, re-baselined decision:

- **The golden master** (`tests/fixtures/golden/`) — the behaviour lock. Any
  change to a locked figure is a deliberate re-baseline, never an accident.
- **Conserved quantities** — total paid, interest, principal, balance, payoff.
  Refactors must keep these byte-identical unless the phase explicitly changes
  behaviour.
- **`data_sample/`** — the tracked demo data that the golden master runs against.
- **`src/paths.py` resolution precedence** — CLI > env > `paths.local.yaml` >
  repo defaults.
- **The frozen `Inputs` dataclass** — scenario work clones, never mutates.

---

## 7. Permanent delivery rules

- Deliver complete, working code - no stubs, no placeholders.
- Every function gets a docstring; every non-obvious line gets a comment.
- Validate inputs at the boundary; fail fast with actionable messages.
- Use `pathlib.Path` and explicit UTF-8 for text files.
- Keep business logic deterministic and testable; prefer pure functions.
- Apply changes first, test second, inspect outputs third, commit separately.
- Do not stage or commit during first implementation.
- Preserve unrelated user changes; never silently reset or discard work.
- Run the full suite before and after a controlled commit.
- Record evidence (counts, hashes, fingerprints) rather than assumptions.
- **House style:** direct, restrained, no em-dashes anywhere (code comments,
  docstrings, docs). No moralising, no permission-seeking phrasing.
- **Delivery mechanism:** pick one per output and state it - paste (new file or
  full rewrite), concatenation (too long for one block), or patch (surgical,
  multi-file). Never paste and patch the same file in the same session.
- **Privacy:** treat every tracked file as public. Tracked templates, samples,
  docs and comments use generic placeholder paths only. Real machine-specific
  paths live only in git-ignored files (`paths.local.yaml`, `*.local.yaml`).

---

## 8. Backlog discipline

- `PRODUCT_BACKLOG.md` is the **single authoritative home** for possible future
  work outside the active delivery pipeline.
- **Recording a backlog item does not authorise its implementation.**
- Do not implement a backlog item unless repository evidence shows it was
  explicitly **promoted** into the delivery plan.
- Before creating a backlog item, check for an existing or overlapping one.
- When an item is promoted from the backlog into the delivery plan, mark it
  `PROMOTED` and reference the phase.

---

## 9. Relationship to Notion

The `mortgage_model` Notion workspace (under *Projects*) remains the **master**
record; this repository is the **day-to-day working copy**. Keep both in sync
manually at phase close. The repo docs must always be sufficient for a successor
agent to continue **without** Notion or chat history.

Key Notion pages (master record):

- Master Handoff - cross-phase status, decisions, active pointer, backlog.
- Operating Contract - conventions and rules of the road.
- Project Plan, Phases & Git Workflow - the phase spine and Definition of Done.
- Active Phase Handoff Log - per-phase and per-session detail.
- Latest Code - Consolidated Reference - the code mirror (Notion-side only).
- Implementation Guide - the codebase mental model.

**Note:** the Notion-side workflow assumes GitHub is unreachable from the agent
and reads code from the Notion mirror. In this repository the live code **is**
the source of truth; the Notion code mirror is not migrated here.

---

## 10. Quick reference

```powershell
# Tests
.\.venv\Scripts\python.exe -m pytest -q

# Sample run (bundled data, no config)
run_sample.bat

# Real-data run
run.bat

# Single property
python -m src.engine --inputs <inputs.yaml> --actuals <actuals.csv> --out <dir>

# Portfolio batch
python -m tools.portfolio --portfolio <portfolio.yaml> --out <dir>

# Strict baseline
python -m tools.baseline --portfolio <portfolio.yaml> --out <dir> --strict-baseline
```
