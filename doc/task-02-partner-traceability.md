# Task 2 — Partner Traceability
**Status:** ✅ Implemented
**Gaps closed:** F3 (partner_id on analytic lines), S2 (partner field on cost analysis)
**Depends on:** nothing (independent)

---

## Problem

Every analytic line created by invoices/vendor bills carries `partner_id` (the vendor or customer).
Every analytic line created by the farm module has `partner_id = False`.

Result:
- Cannot group Gross Margin by vendor
- Cannot answer "what is our total exposure to Supplier X?"
- Cannot answer "which customer generates the most margin?"

The data **exists** but is never used:
- `cost_analysis.invoice_id.partner_id` ← available, not transferred
- `cost_analysis.payment_id.partner_id` ← available, not transferred
- `daily_report` PO-backed lines → already handled via vendor bill (Odoo fills partner) ✅
- `daily_report` non-PO lines → no partner source currently

---

## Solution

### Priority resolution for `cost_analysis`:
```
1. cost.invoice_id.partner_id     → linked vendor bill partner
2. cost.payment_id.partner_id     → linked payment partner
3. cost.partner_id                → new manual field (optional)
4. None                           → leave empty
```

### For `daily_report` non-PO lines:
Add optional `partner_id` field on the daily report itself (a "default vendor for this operation day").

---

## Files to Modify

| File | Action |
|------|--------|
| `models/cost_analysis.py` | **Edit** — add `partner_id` field + `_sync_analytic_line()` |
| `views/cultivation_project_views.xml` | **Edit** — add partner column (optional) to inline cost list |
| `views/cost_analysis_views.xml` | **Edit** — add `partner_id` to form + list view |
| `models/daily_report.py` | **Edit** — add `partner_id` field + pass to analytic entries |
| `views/daily_report_views.xml` | **Edit** — add `partner_id` to daily report form |

---

## Model Change — `farm.cost.analysis`

```python
partner_id = fields.Many2one(
    'res.partner',
    string='Vendor / Partner',
    help='Supplier or customer associated with this cost. '
         'Auto-filled from linked invoice or payment if available.',
    tracking=True,
)
```

Add computed auto-fill logic in `_sync_analytic_line()`:
```python
partner = (
    cost.invoice_id.partner_id
    or cost.payment_id.partner_id
    or cost.partner_id
)
if partner:
    vals['partner_id'] = partner.id
```

---

## Model Change — `farm.daily.report`

```python
partner_id = fields.Many2one(
    'res.partner',
    string='Default Vendor',
    domain="[('supplier_rank', '>', 0)]",
    help='Vendor associated with this day\'s operations (for non-PO lines).',
)
```

In `_create_analytic_entries()`:
```python
if report.partner_id:
    entry_vals['partner_id'] = report.partner_id.id
```

---

## View Changes

### Financial tab — inline cost list (optional column)
```xml
<field name="partner_id" optional="hide"/>
```

### Cost analysis form view
```xml
<field name="partner_id" options="{'no_create': True}"/>
```

### Daily report form view
```xml
<field name="partner_id" options="{'no_create': True}"/>
```

---

## Acceptance Criteria

- [ ] Cost analysis linked to invoice → analytic line `partner_id` = invoice vendor
- [ ] Cost analysis with manual partner → analytic line `partner_id` = that partner
- [ ] Gross Margin report → group by partner → vendor rows appear
- [ ] Daily report with `partner_id` → non-PO analytic lines carry that partner
- [ ] PO-backed daily report lines → partner comes from vendor bill (no change needed) ✅
- [ ] Empty partner is acceptable — no required constraint
- [ ] `partner_id` shows in the optional column of the Financial tab cost list

---

## Questions for Review

1. Should the `partner_id` on cost analysis be **auto-filled** from invoice (computed) or **manually set** (stored)? Recommend stored with auto-fill `@api.onchange('invoice_id')`.
2. Should the daily report `partner_id` propagate down to individual product lines, or just the report level?
3. Should there be a chatter warning when cost > threshold and no partner set?
