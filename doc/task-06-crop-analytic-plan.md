# Task 6 — Crop Analytic Plan Dimension
**Status:** 📋 Planned
**Gaps closed:** S4 (second analytic dimension), Story 7 (multi-project crop aggregation)
**Depends on:** Tasks 1–5 complete (analytic lines must be clean before adding a dimension)

---

## Problem

Today, analytic accounting has one dimension: the **Farm Project** (per cultivation project).

This means you can ask: *"What is the cost and margin for project WHEAT-2026-FARM-A?"*

But you cannot ask: *"What is the total cost and margin for ALL wheat projects across all farms and seasons?"*

An ERP specialist needs crop-level aggregation for:
- Crop profitability across seasons
- Input cost benchmarking per crop type
- Multi-farm consolidated reporting to investors

---

## Solution

Use Odoo 18's native **multi-plan analytic distribution** to add a second dimension: **Crop**.

Every analytic line carries both:
1. `Farm Project Account` — the existing per-project analytic account
2. `Crop Account` — a new analytic account per crop (e.g. "Wheat", "Clover", "Corn")

This is done via `analytic_distribution` dict with 100% on each plan simultaneously:
```python
{
    str(project_analytic_id): 100.0,   # Farm Management Plan
    str(crop_analytic_id):    100.0,   # Farm Crop Plan (new)
}
```

Both plans operate independently — costs appear in both reports without double-counting.

---

## Files to Create / Modify

| File | Action |
|------|--------|
| `data/analytic_plan_data.xml` | **Create** — define "Farm Crop Plan" analytic plan |
| `models/crop.py` (or wherever farm.crop is defined) | **Edit** — add `analytic_account_id` field + auto-create on save |
| `models/cost_analysis.py` | **Edit** — extend `_sync_analytic_line()` with crop account |
| `models/daily_report.py` | **Edit** — extend `_create_analytic_entries()` with crop account |
| `models/sale.py` | **Edit** — extend `_apply_cultivation_analytic_distribution()` with crop account |
| `views/crop_views.xml` | **Edit** — show `analytic_account_id` field (readonly, groups analytic) |
| `__manifest__.py` | **Edit** — add `data/analytic_plan_data.xml` |

---

## Analytic Plan Data

```xml
<!-- data/analytic_plan_data.xml -->
<record id="analytic_plan_farm_crop" model="account.analytic.plan">
    <field name="name">Farm Crop</field>
    <field name="default_applicability">optional</field>
</record>
```

---

## Crop Model Change

```python
# In farm.crop model:
analytic_account_id = fields.Many2one(
    'account.analytic.account',
    string='Analytic Account',
    readonly=True,
    copy=False,
    help='Auto-created analytic account for crop-level cost aggregation.',
)

def _get_or_create_crop_analytic_account(self):
    """Ensure the crop has an analytic account. Create if missing."""
    self.ensure_one()
    if not self.analytic_account_id:
        plan = self.env.ref('farm_management.analytic_plan_farm_crop')
        account = self.env['account.analytic.account'].create({
            'name': self.name,
            'plan_id': plan.id,
            'company_id': self.env.company.id,
        })
        self.write({'analytic_account_id': account.id})
    return self.analytic_account_id

@api.model_create_multi
def create(self, vals_list):
    crops = super().create(vals_list)
    crops._get_or_create_crop_analytic_account()
    return crops
```

---

## Extension to `_sync_analytic_line()`

```python
# Build analytic_distribution for multi-plan
distribution = {str(account.id): 100.0}  # existing project plan

crop = cost.project_id.crop_id
if crop and crop.analytic_account_id:
    distribution[str(crop.analytic_account_id.id)] = 100.0

vals['analytic_distribution'] = distribution
# Note: account_id (single plan field) still set for backwards compat
vals['account_id'] = account.id
```

---

## Extension to Sale Order Distribution

```python
# In _apply_cultivation_analytic_distribution():
distribution = {str(project.analytic_account_id.id): 100.0}

crop = project.crop_id
if crop and crop.analytic_account_id:
    distribution[str(crop.analytic_account_id.id)] = 100.0

order_line.analytic_distribution = distribution
```

---

## What This Enables

After this task:

**Report A — Farm Project Gross Margin (unchanged)**
- Filter by Farm Management Plan
- Group by project → same as today

**Report B — Crop Gross Margin (new)**
- Filter by Farm Crop Plan
- Group by analytic account (= crop)
- Shows: all wheat costs across Farm A + Farm B + Season 2025 + Season 2026
- Revenue from all wheat sales in one row

**Report C — Crop × Farm Matrix**
- Cross-filter both plans
- Shows: wheat costs broken down by farm

---

## Migration Note

Existing analytic lines do NOT automatically get the crop dimension — they only have the project plan. This is acceptable because historical data is clean as-is. Only new lines (after module upgrade) get both dimensions.

If historical backfill is needed, a one-time script can be run post-deployment.

---

## Acceptance Criteria

- [ ] `account.analytic.plan` "Farm Crop" exists after upgrade
- [ ] Each `farm.crop` record has an `analytic_account_id` (auto-created on first save)
- [ ] New cost analysis entries → analytic line `analytic_distribution` contains both project and crop accounts
- [ ] New daily report done → analytic lines carry both dimensions
- [ ] Sale order invoices → both dimensions in `analytic_distribution`
- [ ] Analytic report filtered by "Farm Crop" plan → shows aggregated crop margin
- [ ] No duplication in amounts (Odoo handles multi-plan correctly — each plan gets 100% of the amount independently)

---

## Questions for Review

1. Should the Crop Plan be mandatory (every entry must have crop) or optional (graceful fallback)?
2. Should crop analytic accounts be company-specific or shared across companies?
3. Should existing crops get analytic accounts auto-created during module upgrade (post_init_hook)?
4. Does the farm.crop model already exist in a separate file? Need to confirm location before editing.
