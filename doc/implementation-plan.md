# Analytic Accounting — Implementation Plan
**Module:** farm_management
**Date:** 2026-05-04
**Reference:** analytic-gap-analysis.md

---

## Overview

Six sequential tasks that build on each other.
Each task is self-contained and reviewable before moving to the next.

```
Task 1 → Task 2 → Task 3 → Task 4 → Task 5 → Task 6
  GL       Partner  Category  Product   Ref    Crop Plan
 Account   & Audit  Fix       on Cost   Field  Dimension
 on Cost
```

---

## Task 1 — GL Account on Cost Analysis

**Gaps closed:** F1
**Files:** `models/cost_analysis.py`, `views/cost_analysis_views.xml`, `views/cultivation_project_views.xml`

### What it does
Adds a `general_account_id` field directly to `farm.cost.analysis` — auto-filled from the linked invoice or payment, or selected manually by the accountant when no document exists. No new model needed.

### Resolution priority
1. `cost.invoice_id` set → auto-fill from the invoice's expense line account
2. `cost.payment_id` set (no invoice) → auto-fill from `payment.destination_account_id`
3. Neither → accountant selects manually on the form

### Logic changes
- Add `general_account_id` Many2one field on `farm.cost.analysis`
- Add `@api.onchange('invoice_id')` and `@api.onchange('payment_id')` to auto-fill
- In `_sync_analytic_line()`: pass `general_account_id` to the analytic line vals

### Acceptance Criteria
- [ ] Invoice linked → `general_account_id` auto-filled on change
- [ ] Payment linked (no invoice) → `general_account_id` from destination account
- [ ] Neither → accountant selects manually, no constraint blocking save
- [ ] Analytic line `general_account_id` matches the cost entry's value
- [ ] Field visible to accounting group users only

---

## Task 2 — Partner Traceability

**Gaps closed:** F3, S2
**Files:** `models/cost_analysis.py`, `views/cultivation_project_views.xml` (Financial tab cost list)

### What it does
Resolves and stores `partner_id` on every analytic line so vendor/customer traceability is complete.

### Resolution logic (priority order)

**For cost_analysis:**
1. `cost.invoice_id.partner_id` — if cost is linked to a vendor bill
2. `cost.payment_id.partner_id` — if cost is linked to a payment
3. `cost.partner_id` — new optional field on cost analysis model (manual entry)
4. None — leave empty, no error

**For daily_report non-PO lines:**
1. `report.partner_id` — new optional field on the daily report
2. None

**For daily_report PO-backed lines:**
- Already skipped by the duplication fix (analytic line comes from vendor bill)
- Vendor bill path sets `partner_id` via Odoo standard ✅

### Model changes
Add to `farm.cost.analysis`:
```python
partner_id = fields.Many2one(
    'res.partner', string='Vendor / Partner',
    help='Supplier or partner associated with this cost. Auto-filled from linked invoice or payment.'
)
```

### View changes
Add `partner_id` column (optional) in the inline cost list on the Financial tab.
Add `partner_id` field on `farm.cost.analysis` form view.

### Acceptance Criteria
- [ ] Cost analysis line with linked invoice → analytic line `partner_id` = invoice partner
- [ ] Cost analysis line with manual partner → analytic line `partner_id` = manual partner
- [ ] Gross Margin report can be grouped by partner
- [ ] Empty partner is acceptable (no constraint); warning in chatter if cost > 1000 EGP and no partner

---

## Task 3 — Category Fix

**Gaps closed:** F2
**Files:** `models/cost_analysis.py`, `models/daily_report.py`

### What it does
Sets `category` correctly on all farm-created analytic lines so Odoo's Gross Margin separates revenue from cost automatically.

### Rules
| Source | Category |
|--------|----------|
| `cost_analysis` (any cost type) | `'vendor_bill'` |
| `daily_report` product lines | `'vendor_bill'` |
| Revenue from sale order invoices | Already `'invoice'` via Odoo standard ✅ |

### Logic changes

**`cost_analysis._sync_analytic_line()`:**
```python
vals['category'] = 'vendor_bill'
```

**`daily_report._create_analytic_entries()`:**
```python
entry_vals['category'] = 'vendor_bill'
```

That's it. One line each. Small change, large impact.

### Acceptance Criteria
- [ ] Open Analytic Account → Gross Margin: costs now appear in `vendor_bill` group
- [ ] Revenue lines appear in `invoice` group (already working)
- [ ] The balance (gross margin) is computed correctly by Odoo's report engine
- [ ] No `'other'` category lines remain for farm-originated entries

---

## Task 4 — Product on Cost Analysis

**Gaps closed:** F4
**Files:** `models/cost_analysis.py`, `views/cultivation_project_views.xml`, `views/cost_analysis_views.xml`

### What it does
Adds an optional `product_id` field to `farm.cost.analysis` so manual cost entries can reference the exact product/service, and that product is carried to the analytic line — making farm cost entries consistent with daily report entries.

### Model changes
Add to `farm.cost.analysis`:
```python
product_id = fields.Many2one(
    'product.product', string='Product / Service',
    help='Optional. The product or service this cost relates to. Used for analytic reporting.'
)
```

### Logic changes
In `_sync_analytic_line()`:
```python
if cost.product_id:
    vals['product_id'] = cost.product_id.id
    # Also derive general_account_id from product if no mapping found
```

Auto-fill `cost_name` from product name if cost_name is empty when product is selected (`@api.onchange('product_id')`).
Auto-fill `uom_id` from product's UoM.

### View changes
Add `product_id` field in cost analysis form view (before cost_name).
Add `product_id` as optional column in inline cost list on Financial tab.

### Acceptance Criteria
- [ ] Selecting a product on a cost entry auto-fills name and UoM
- [ ] Analytic line `product_id` matches the cost entry's product
- [ ] Product-level analytic reporting works (group by product in analytic lines)
- [ ] Field is optional — existing entries without product continue to work

---

## Task 5 — Audit Reference Field

**Gaps closed:** F5
**Files:** `models/cost_analysis.py`, `models/daily_report.py`

### What it does
Sets `ref` on every farm-created analytic line to the source document's reference number, giving auditors a direct link back to the originating record.

### Rules
| Source | `ref` value |
|--------|-------------|
| `farm.cost.analysis` | `cost.name` (the auto-generated reference, e.g. `COST/2026/00042`) |
| `farm.daily.report` | `report.name` (e.g. `RPT/2026/00017`) |

### Logic changes

**`cost_analysis._sync_analytic_line()`:**
```python
vals['ref'] = cost.name
```

**`daily_report._create_analytic_entries()`:**
```python
entry_vals['ref'] = report.name
```

**`cost_analysis.write()` — also update `user_id` explicitly:**
```python
vals['user_id'] = self.env.uid
```

### Acceptance Criteria
- [ ] Analytic line `ref` field shows the cost/report document number
- [ ] In Gross Margin report, auditor can read the ref and find the source record
- [ ] `user_id` shows who created the cost, not just a default

---

## Task 6 — Crop Analytic Plan Dimension *(Advanced)*

**Gaps closed:** S4, Story 7
**Files:** `models/cultivation_project.py`, `data/analytic_plan_data.xml`, `models/cost_analysis.py`, `models/daily_report.py`

### What it does
Introduces a second Odoo 18 analytic plan — **Crop Plan** — so every analytic entry carries two dimensions:
1. **Farm Project** (existing) — tracks per-project costs
2. **Crop** (new) — tracks costs aggregated across all projects for the same crop

This enables: *"What is our total cost and margin for wheat across all farms and seasons?"*

### Approach
1. Create an `account.analytic.plan` record: `"Farm Crop Plan"` in `data/analytic_plan_data.xml`
2. On `farm.crop`, add `analytic_account_id` (auto-created when crop is saved, similar to project)
3. On all analytic line creation, set `analytic_distribution` to include **both** accounts:
   ```python
   {
       str(project_analytic_account.id): 100.0,  # existing farm project plan
       str(crop_analytic_account.id): 100.0,      # new crop plan
   }
   ```
4. On sale order lines, extend `_apply_cultivation_analytic_distribution()` to include crop account

### Acceptance Criteria
- [ ] Each crop has its own analytic account (auto-created)
- [ ] All analytic lines (cost + revenue) carry both project and crop dimensions
- [ ] Gross Margin can be viewed grouped by crop across all projects
- [ ] Multi-company: wheat in Farm A + wheat in Farm B both roll up to crop "Wheat"

---

## Review Checkpoints

After each task, verify in Odoo:

| Task | Quick Verification |
|------|--------------------|
| 1 | Cost entry analytic line → `general_account_id` filled |
| 2 | Analytic line → `partner_id` matches invoice/manual vendor |
| 3 | Gross Margin report → no `'other'` rows for farm costs |
| 4 | Group analytic lines by product → cost analysis entries appear |
| 5 | Analytic line `ref` → click through to source document |
| 6 | Analytic report → group by crop → multi-project aggregation |

---

## Dependency Map

```
Task 1 (GL Mapping)
    └── prerequisite for meaningful Task 3, 4, 5 verification

Task 2 (Partner)
    └── independent, can run in parallel with Task 1

Task 3 (Category)
    └── independent, 2-line change, can run any time

Task 4 (Product)
    └── best after Task 1 (product can also derive GL account)

Task 5 (Ref)
    └── independent, 2-line change, can run any time

Task 6 (Crop Plan)
    └── requires Task 1-5 complete (analytic lines must be clean first)
```

Recommended order: **3 → 5 → 1 → 2 → 4 → 6**
(quick wins first, then foundation, then advanced)
