# Task 5 — Audit Reference Field
**Status:** ✅ Implemented
**Gaps closed:** F5 (ref field, user_id explicit)
**Depends on:** nothing (independent, 2-line change)

---

## Problem

Farm-created analytic lines have no `ref` field. An auditor cannot trace a line in the Gross Margin report back to its source document.

Example:
- Analytic line: `amount = -3,500 EGP`, `name = "Fertilizers: DAP"`
- Auditor asks: *"Where is the source? Which report, which cost entry, which date?"*
- Today: no answer. The line is a dead end.

Additionally, `user_id` is left to implicit default (whoever runs the ORM call) instead of being explicitly set.

---

## Solution

Set `ref` to the source document reference number on every farm-created analytic line.

| Source | `ref` value |
|--------|-------------|
| `farm.cost.analysis` | `cost.name` (e.g. `COST/2026/00042`) |
| `farm.daily.report` | `report.name` (e.g. `RPT/2026/00017`) |

Set `user_id` explicitly to the user who triggered the action.

---

## Files to Modify

| File | Action |
|------|--------|
| `models/cost_analysis.py` | **Edit** — add `'ref'` and `'user_id'` in `_sync_analytic_line()` |
| `models/daily_report.py` | **Edit** — add `'ref'` and `'user_id'` in `_create_analytic_entries()` |

---

## Exact Changes

### `cost_analysis._sync_analytic_line()`
```python
vals = {
    ...existing fields...,
    'category': 'vendor_bill',
    'ref': cost.name,            # ← ADD
    'user_id': self.env.uid,     # ← ADD
}
```

### `daily_report._create_analytic_entries()`
```python
entry_vals = {
    ...existing fields...,
    'category': 'vendor_bill',
    'ref': report.name,          # ← ADD
    'user_id': self.env.uid,     # ← ADD
}
```

---

## What This Enables

After this change, in the Gross Margin report an accountant can:
1. See a cost line with `ref = COST/2026/00042`
2. Go to Financial → Cost Analysis → search `COST/2026/00042`
3. Open the record and see all details (date, type, amount, vendor, invoice)

Or for a daily report line:
1. See `ref = RPT/2026/00017`
2. Go to Cultivation → Daily Reports → search `RPT/2026/00017`
3. Open and see the full field operation log

---

## Acceptance Criteria

- [ ] New cost analysis entry → analytic line `ref = cost.name`
- [ ] New daily report done → analytic lines `ref = report.name`
- [ ] `user_id` on analytic line shows the actual user who created the cost/report
- [ ] `ref` is visible as a column in the Analytic Lines list view (Odoo's standard — already there)
- [ ] Auditor can search analytic lines by `ref` to find source document

---

## Questions for Review

1. Should the `ref` include more context? E.g. `"RPT/2026/00017 — Project WHEAT-001"`?
2. Should we update existing analytic lines' `ref` for historical data?
