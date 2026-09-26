# PRODUCT_VISION.md — mortflow

> Enduring direction and boundaries. Changes rarely. For authorised, sequenced
> work see `PRODUCT_DELIVERY_PLAN.md`; for possible future work see
> `PRODUCT_BACKLOG.md`.

---

## User problem

Managing Irish residential mortgage cashflows across multiple properties is
opaque. Bank statements, rate changes, overpayments, and tax rules interact in
ways that are hard to reason about by hand, and hard to audit after the fact.
The user needs a model that reproduces the bank's own arithmetic, reconciles
against real transactions, and produces defensible outputs for tax and
investment decisions.

## Intended users

- The project owner (primary): a property investor managing a small Irish
  residential portfolio, preparing Form 11 returns and evaluating refinancing
  and overpayment decisions.
- Future: any non-technical user consuming a release package (no Git, Python or
  virtual-environment knowledge required).

## Value proposition

- **Auditable** — every figure traces to an agreed input or a bank transaction.
- **Deterministic** — the same inputs always produce the same outputs, locked by
  a golden master.
- **Config-driven** — adding a property, changing a rate, or toggling a module
  is a configuration change, not a code change.
- **Portable** — code and private data live in separate places on any machine.

## Product boundaries

- Irish residential mortgages, daily ACT/365 day count.
- Irish rental tax (Form 11, section 97(2J)).
- Multi-property portfolios with per-property currency.
- CSV + Excel outputs; no database, no web service.

## Non-goals

- Not financial or legal advice.
- Not a general-purpose accounting system.
- Not a commercial product (PolyForm Noncommercial licence).
- Not a real-time or bank-connected system.

## Long-term architecture

```text
identify -> adapt -> compile -> summarise -> publish
```

- **Engine** (`src/engine/`) — deterministic daily simulation and reporting.
- **Config layer** (`src/paths.py`) — decouples code from data locations.
- **Tools** (`tools/`) — portfolio batch, strict baseline, calendar verification.
- **Layered extensions** — rental, tax, and investment-decision layers compose
  on top of the mortgage engine without changing its maths.

## Operating principles

1. Deterministic behaviour is the default for finance and audit workflows.
2. Business logic is pure and testable; edges are thin.
3. Configuration drives behaviour; no magic numbers or embedded mappings.
4. The golden master is the behaviour lock; changes to it are deliberate.
5. Git repositories are for developers; release packages are for users.
6. Preserve evidence and traceability; separate facts from assumptions.
