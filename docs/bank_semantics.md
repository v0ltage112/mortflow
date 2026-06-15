# Bank Semantics Specification

This document defines the "reference behaviour" for the mortgage engine. The engine code must strictly implement these rules. If a bank behaves differently, we adapt via configuration flags (e.g. `posting_order`) rather than ad-hoc logic changes.

## 1. Interest Accrual

*   **Basis**: `ACT/365` (compatible with `ACT/360`, `30/360` via configuration).
*   **Timing**: Interest accrues on the *opening balance* of the day.
*   **Formula**: `Daily Interest = Opening Balance * (Annual Rate / Divisor)`
*   **Precision**: Calculated as a full float standard (double precision). **Never** rounded during the daily summation, only at the moment of "posting" (capitalisation) to the principal.

## 2. Event Order (Intra-day)

On any given day, events occur in a strict sequence. This sequence matters because it determines the closing balance for the next day's accrual.

### Default Order (Debit-First)
Most common for daily-interest accounts where you pay down principal *before* end-of-day operations.

1.  **Opening Balance** (used for today's accrual).
2.  **Debits**: Payments, Extras, Lump Sums reduce the principal.
3.  **Credits**: Interest Posting (if today is a posting day) increases the principal.
4.  **Closing Balance** = Opening - Debits + Credits.

### Alternative Order (Post-First)
Some banks post interest *before* applying the daily debit (or treat the debit as affecting the *next* day). This is configurable via `posting_order: post_then_debit`.

1.  Opening Balance.
2.  **Credits**: Interest Posting.
3.  **Debits**: Payments, Extras, Lump Sums.
4.  Closing Balance.

## 3. Rounding Policy

To eliminate fractional cent drift over decades:

1.  **Accrual Accumulator**: Kept as high-precision float (e.g., `123.456789...`).
2.  **Interest Posting**: When interest is capitalised (monthly or other), the accumulated amount is **rounded to 2 decimal places** (standard arithmetic rounding: 0.005 -> 0.01).
    *   *Example*: Accrued `45.678` -> Posted `45.68`. `45.674` -> Posted `45.67`.
    *   The accumulator resets to `0.0` exactly after posting.
3.  **Debits**: All external inputs (Payment, Extra, Lump) are rounded to 2 decimal places upon ingestion.
4.  **Balances**: The principal balance is always the sum of 2-decimal values, so it naturally stays at 2 decimals.

## 4. Merge Logic (Actual vs Scheduled)

Distinguishing "Bank Statement Lines" from "Modelled Components".

### Actual Months (Bank Data Present)
*   **Source**: `actuals.csv`.
*   **Rule**: The bank is always right. If the bank says `-2000.00`, the model debits `2000.00`.
*   **Unhiding Extras**: If you have a standing overpayment of €500 inside that €2000:
    *   `merge_extra_mode: "auto"` or `"true"` -> Model creates one "Payment" event of €2000.
    *   `merge_extra_mode: "false"` -> Model creates "Payment" €1500 + "Extra" €500. (Sum is still €2000).

### Scheduled Months (Future/Missing Data)
*   **Source**: Calculated PMT + `inputs.yaml` Extras.
*   **Rule**: We construct the events.
    *   `merge_extra_mode: "true"` -> Create one "Payment" event (PMT + Extra).
    *   `merge_extra_mode: "false"` (default/safe) -> Create "Payment" (PMT) event and separate "Extra" event.

## 5. Final Payment Trim
*   **Rule**: Principal cannot go negative.
*   **Action**: If a debit exceeds the balance, we reduce the debit amount so the Balance becomes `0.00`.
*   **Interest Suppression**: On the day the loan clears, no interest is posted (or it is posted *before* the clearing debit if `post_then_debit` is active, but usually clearing happens on the debit).

## 6. Tenancy & Tax (Section 97(2J))
*   **Deductibility**: Interest is deductible only for days the property is "let or available for letting".
*   **Availability**: Gaps between tenancies count as "available" (deductible) unless `policy.gaps_count_as_available` is false or the gap is owner-occupied.
