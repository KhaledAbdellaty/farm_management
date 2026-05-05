# Task 4 — Product Field on Cost Analysis
**Status:** ✅ Implemented
**Gaps closed:** F4 (product_id consistency)
**Depends on:** Task 1 (product can also be used to derive GL account in fallback)

---

## Problem

`farm.cost.analysis` analytic lines have no `product_id`. This means:
- Cannot group Gross Margin by product/service
- Cannot reconcile cost analysis entries with inventory costing
- Inconsistency: daily report analytic lines DO have `product_id`; cost analysis ones don't
- Reporting tools need special-case logic to handle the two models differently

---

## Solution

Add an **optional** `product_id` field to `farm.cost.analysis`.
When set, it:
1. Auto-fills `cost_name` (if empty)
2. Auto-fills `uom_id`
3. Is passed to the analytic line as `product_id`
4. Provides fallback `general_account_id` (Task 1 fallback path)

---

## Files to Modify

| File | Action |
|------|--------|
| `models/cost_analysis.py` | **Edit** — add `product_id`, `@api.onchange`, update `_sync_analytic_line()` |
| `views/cost_analysis_views.xml` | **Edit** — add `product_id` to form view |
| `views/cultivation_project_views.xml` | **Edit** — add `product_id` optional column to inline cost list |

---

## Model Change

```python
product_id = fields.Many2one(
    'product.product',
    string='Product / Service',
    help='Optional. The product or service this cost relates to.',
    tracking=True,
)

@api.onchange('product_id')
def _onchange_product_id(self):
    if self.product_id:
        if not self.cost_name:
            self.cost_name = self.product_id.name
        if self.product_id.uom_id:
            self.uom_id = self.product_id.uom_id
```

---

## Change to `_sync_analytic_line()`

```python
if cost.product_id:
    vals['product_id'] = cost.product_id.id
```

And in the GL account fallback (if no mapping found — Task 1):
```python
if not gl_account and cost.product_id and cost.product_id.categ_id:
    acc = cost.product_id.categ_id.property_account_expense_categ_id
    if acc:
        gl_account = acc.id
```

---

## View Changes

### `cost_analysis_views.xml` form view
Add between date and cost_name:
```xml
<field name="product_id" options="{'no_create': True}"/>
```

### Financial tab inline cost list
```xml
<field name="product_id" optional="hide"/>
```

---

## Acceptance Criteria

- [ ] Selecting a product on a cost entry auto-fills `cost_name` and `uom_id` (if empty)
- [ ] Analytic line `product_id` = cost entry's product
- [ ] Product is optional — existing entries without product continue to work unchanged
- [ ] In Gross Margin: analytic lines can be grouped by product, including cost analysis entries
- [ ] If no GL mapping (Task 1) but product has expense category account → that account is used

---

## Questions for Review

1. Should `product_id` domain be restricted to `purchase_ok = True` (only purchasable products)?
2. Should auto-fill of `cost_name` also suggest the `cost_type` from product's internal category?
3. Should `cost_amount` auto-fill from product's `standard_price * quantity`?
