# Contract data model (Phase 10 build brief)

> Section A (this file), authored in P9/S4: the Contract object and the loan / contract data model. Section B (lender profile, universal rules, cascade map, migration) is authored in S5; Section C (anonymisation mapping, data, Phase 10 plan) in S6.
>
> All figures below are illustrative placeholders, not real contract values. Real amounts, dates, and account numbers stay off-repo. This file carries structure and reasoning only, never verbatim legal wording.

## A0. Purpose and scope

This document is the Phase 10 build brief for the contract data model. It replaces the month-number rate model with a date-based `contracts:` array, separates loan-level facts from contract-level facts, and defines the Contract object a fresh agent implements in Phase 10 (`v2.0.0`). Section A locks the object shape and the loan / contract split. The universal rules layer, the cascade map, and the migration plan are Section B (S5); the anonymisation mapping, the data files, and the Phase 10 session breakdown are Section C (S6).

## A1. Two levels: Loan and Contract

Design principle: money advanced is a loan fact; the rate agreement over time is a sequence of contracts. A property has exactly one loan (one drawdown of new money) and one or more contracts over that loan's life. A refix advances no new money, so it is a new Contract on the same loan, not a new drawdown. The only genuine second loan-level money event would be a further advance or top-up, which no property has today.

### Loan (one per property)

| Field | Type | Default | Notes |
| --- | --- | --- | --- |
| `property_id` | str | required | Stable id for the property. |
| `lender` | str | required | Profile key (for example `boi`). Resolves the universal rules; see Section B. |
| `drawdown_amount` | decimal | required | New money advanced, once per loan. |
| `drawdown_date` | date | required | Date the money was advanced. |
| `total_term_months` | int | required | Full amortisation term. |
| `maturity_date` | date or null | null | Derived from drawdown plus term if null. |
| `property_value` | decimal | required | For LTV and valuation. |
| `valuation_blocks` | list | empty list | Unchanged from today. |
| `repayment_day` | int or month_end | required | Per-account (illustrative: day-5 or month-end). Governs projected dates only. |
| `property_growth_pa` | decimal | required | Unchanged from today. |
| `tax` / `tenancy` | object | as today | Unchanged from today. |
| `contracts` | list of Contract | required | Ordered by `start_date`. |

### Contract (one or more per loan)

| Field | Type | Default | Notes |
| --- | --- | --- | --- |
| `id` | str | required | Stable id, for example A1, B2, B3. |
| `start_date` | date | required | Contract start (drawdown date for the first; day after the prior contract's end for a refix). |
| `end_date` | date or null | null | Fixed-period end; null = open-ended (rolled to variable with no agreed end). |
| `rate` | decimal | required | Annual fixed rate for this contract's period (for example 0.0350). |
| `rate_type` | fixed / variable / tracker | fixed | Rate character during this contract. |
| `instalment` | decimal or null | null | Contractual monthly repayment. Null = engine derives via PMT. A bank-stated figure that differs from a naive PMT because of a payment break or capitalisation overrides the derivation. |
| `follow_on` | object or null | null | Directional roll-to rate; see A2. |
| `standing_overpayment` | object or null | null | Recurring voluntary overpayment window; see A3. |
| `payment_events` | list | empty list | Contract-scoped events; see A4. |
| `overpayment_cap_override` | object or null | null | Null = inherit the profile rule effective at this contract's dates (Section B). |
| `breakage_override` | object or null | null | Null = inherit the profile. |

## A2. Rate model: fixed period plus a directional follow-on

A contract is a fixed period plus a directional rate for what happens after it, which is rarely exercised because a new contract is usually negotiated before the fixed period ends.

    follow_on:
      rate: 0.0450          # decimal or null
      rate_type: variable   # fixed | variable | tracker
      basis: "lender variable, LTV-banded"
      indicative: true      # non-binding, provisional
      note: "roll-to rate if not refixed; expected to be renegotiated first"

Rules: `follow_on` is non-binding. Projections past `end_date` use it only as a clearly flagged provisional assumption. Adding a refix Contract supersedes it. This preserves S3 decision (a): there is no confirmed mid-period rate split, and a refix stays provisional until a statement spans it.

## A3. Standing overpayment (date-based)

Replaces the month-number `overpay_rules`. For a recurring voluntary overpayment attached to a contract:

    standing_overpayment:
      amount: 120.00
      start_date: 2025-08-01
      end_date: 2026-06-30   # null = open-ended
      note: "voluntary overpay window; within allowance; ends at refix"

The cap check uses the profile allowance for this contract (Section B), applied to the contract `instalment`.

## A4. Payment events (date-based, contract-scoped)

Replaces `payment_holidays` plus `contractual_ladder`. Each event:

    payment_events:
      - type: payment_holiday        # payment_holiday | part_capital_increase | ...
        start_date: 2024-04-01
        end_date: 2024-08-01         # null = open-ended
        treatment: capitalise        # interest_only | capitalise | instalment_increase
        amount: null                 # decimal or null
        note: "3-month break; interest accrues daily and capitalises"

Covers a payment break (interest-only plus capitalise) and a formalised part-capital instalment increase (contractual, not an overpayment).

## A5. How `contracts:` subsumes the legacy constructs

| Legacy (today) | Replaced by |
| --- | --- |
| `rate_blocks` (month-number) | `Contract.start_date` / `end_date` / `rate`; month numbers become dates, engine derives month offsets from `drawdown_date` |
| `known_first_payment` | first `Contract.instalment` |
| `contractual_ladder` (Phase 7 steps) | per-Contract `instalment` across contracts plus `payment_events` for mid-contract formalised changes |
| `overpayment_cap_pct` (scalar) | retired; derived from the profile rule times `instalment` (Section B) |
| `overpay_rules` (start_month windows) | `Contract.standing_overpayment` (date windows) |
| `strategy_at_refix` | `follow_on` plus the presence or absence of a subsequent Contract |
| `payment_holidays` | `payment_events` with type payment_holiday |

## A6. Loan-level vs contract-level (quick reference)

- Loan-level (one per property): `property_id`, `lender`, `drawdown_amount`, `drawdown_date`, `total_term_months`, `maturity_date`, `property_value`, `repayment_day`, `property_growth_pa`, tax / tenancy.
- Contract-level (one per contract): `id`, `start_date`, `end_date`, `rate`, `rate_type`, `instalment`, `follow_on`, `standing_overpayment`, `payment_events`, overrides.

## A7. Illustrative examples (placeholder figures)

Single-contract loan with a payment break:

    loan:
      property_id: sample_a
      lender: boi
      drawdown_amount: 400000.00
      drawdown_date: 2024-04-01
      total_term_months: 420
      repayment_day: 5
      contracts:
        - id: A1
          start_date: 2024-04-01
          end_date: 2028-04-01
          rate: 0.0350
          rate_type: fixed
          instalment: 1900.00        # post-break recalculated figure; overrides naive PMT
          follow_on:
            rate: 0.0450
            rate_type: variable
            basis: "lender variable, LTV-banded"
            indicative: true
            note: "roll-to rate if not refixed; expected to be renegotiated first"
          payment_events:
            - type: payment_holiday
              start_date: 2024-04-01
              end_date: 2024-08-01
              treatment: capitalise
              note: "3-month break; interest accrues daily and capitalises"
            - type: part_capital_increase
              start_date: 2025-08-01
              end_date: null
              treatment: instalment_increase
              amount: 200.00
              note: "formalised part-capital increase; contractual, not an overpayment"

Two-contract loan across a refix with a standing overpayment:

    loan:
      property_id: sample_b
      lender: boi
      drawdown_amount: 350000.00
      drawdown_date: 2022-07-01
      total_term_months: 420
      repayment_day: month_end
      contracts:
        - id: B2
          start_date: 2022-07-01
          end_date: 2026-07-01
          rate: 0.0190
          rate_type: fixed
          instalment: 1200.00
          standing_overpayment:
            amount: 120.00
            start_date: 2025-08-01
            end_date: 2026-06-30
            note: "voluntary overpay window; within allowance; ends at refix"
          follow_on:
            rate: 0.0310
            rate_type: variable
            indicative: true
        - id: B3
          start_date: 2026-07-01
          end_date: 2030-07-01
          rate: 0.0310
          rate_type: fixed
          instalment: 1500.00
          # no standing overpayment on B3

## A8. Defaults summary

| Field | Default |
| --- | --- |
| `end_date` | null (open-ended) |
| `rate_type` | fixed |
| `instalment` | null (derive via PMT unless stated) |
| `follow_on` | null |
| `standing_overpayment` | null |
| `payment_events` | empty list |
| `overpayment_cap_override` | null (inherit profile) |
| `breakage_override` | null (inherit profile) |

## A9. Carried forward (locked from S1 to S3)

- Overpayment cap is a per-payment allowance of max(10% of the monthly repayment, EUR 65), not a calendar-year balance reset. Derived from the profile times the contract `instalment`.
- Breakage type `principal_x_rate_differential_x_remaining_years`, C = A x (R% - R1%) x D / 365, with R% / R1% external nullable BOI money-market rates; emit "not computable" when absent; a computed C of zero or less means no charge.
- Payment date is Modified Following (forward to the next working day; back to the last working day of the month if forward crosses into the next month). Payment day is per-account. Governs projected dates only, never an actual posted date.
- Mid-month rate change stays PROVISIONAL / UNCONFIRMED.
- Drawdown is a loan-level fact (one per property). A refix is a new Contract sharing the loan (no new money).

## A10. Deferred to S5 / S6

- S5: lender profile schema (effective-dated `rule_versions` plus rationale plus money-market rates), the rule-resolution anchor, cap-basis variants, the breakage formula catalog, the full cascade / ripple map, and the migration plus golden re-baseline (refactor before re-data).
- S6: anonymisation mapping (real to sample), the committed sample files, the private real-data blocks, and the confirmed Phase 10 session breakdown.
- Open decision for S5: which date anchors each rule lookup. Proposed default: the overpayment cap and the payment-date convention resolve on the event or contract-period date; breakage rates resolve on the breakage-quote date.