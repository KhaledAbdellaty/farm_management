# Task 3 — Analytic Category Fix
**Status:** ✅ Implemented
**Gaps closed:** F2 (category field)
**Depends on:** nothing (independent, 2-line change)

---

## Problem

Odoo's `account.analytic.line` has a `category` field that distinguishes:
- `'invoice'` — revenue from customer invoice
- `'vendor_bill'` — cost from vendor bill
- `'other'` — everything else (default)

The Gross Margin report engine uses this to separate revenue rows from cost rows and compute the margin.

Every analytic line created by the farm module (cost_analysis + daily_report) defaults to `'other'` because we never set `category`. This means:
- Report cannot auto-compute gross margin on farm costs
- Costs appear in an undifferentiated "Other" bucket
- Revenue (from invoices) is in `'invoice'` bucket; costs are not in `'vendor_bill'` bucket
- The balance Odoo computes is **wrong** from an accounting perspective

---

## Solution

One line added in each model's analytic line creation:

### `cost_analysis._sync_analytic_line()`
```python
vals['category'] = 'vendor_bill'
```

### `daily_report._create_analytic_entries()`
```python
entry_vals['category'] = 'vendor_bill'
```

That's it. The revenue side is already correct (customer invoice path → Odoo sets `'invoice'`).

---

## Files to Modify

| File | Action |
|------|--------|
| `models/cost_analysis.py` | **Edit** — add `'category': 'vendor_bill'` in `_sync_analytic_line()` |
| `models/daily_report.py` | **Edit** — add `'category': 'vendor_bill'` in `_create_analytic_entries()` |

---

## Exact Edit Locations

### cost_analysis.py — `_sync_analytic_line()`
In the `vals` dict that is built before create/write:
```python
vals = {
    'name': label,
    'date': cost.date,
    'account_id': account.id,
    'amount': -cost.cost_amount,
    'unit_amount': cost.quantity or 0.0,
    'product_uom_id': cost.uom_id.id if cost.uom_id else False,
    'company_id': cost.company_id.id,
    'category': 'vendor_bill',   # ← ADD THIS LINE
}
```

### daily_report.py — `_create_analytic_entries()`
In the `entry_vals` dict:
```python
entry_vals = {
    'name': f"...",
    'date': report.date,
    'account_id': analytic_account.id,
    'amount': analytic_amount,
    'unit_amount': line.quantity,
    'product_id': line.product_id.id,
    'product_uom_id': line.uom_id.id,
    'daily_report_id': report.id,
    'category': 'vendor_bill',   # ← ADD THIS LINE
}
```

---

## Impact on Existing Data

Existing analytic lines already in the database will still have `category = 'other'`.
To fix historical data, run once in a shell:
```python
env['account.analytic.line'].search([
    ('daily_report_id', '!=', False)
]).write({'category': 'vendor_bill'})
# For cost_analysis-created lines (identifiable by no move_line_id + negative amount):
env['account.analytic.line'].search([
    ('move_line_id', '=', False),
    ('amount', '<', 0),
    # add account filter for farm analytic accounts
]).write({'category': 'vendor_bill'})
```
> ⚠️ Run with caution — filter carefully to only target farm analytic lines.

---

## Acceptance Criteria

- [ ] New cost analysis entry → analytic line `category = 'vendor_bill'`
- [ ] New daily report done → analytic lines `category = 'vendor_bill'`
- [ ] Customer invoice → analytic line `category = 'invoice'` (unchanged, Odoo handles this ✅)
- [ ] Gross Margin report: vendor_bill rows sum to negative (costs), invoice rows sum to positive (revenue), balance = gross margin
- [ ] No `'other'` category rows in Gross Margin for farm-originated entries

---

## Questions for Review

1. Should we also update existing analytic lines (one-time data migration)?
2. Any cost entries that should be `'other'` (e.g., internal reallocation, depreciation)?
