# Task 1 — GL Account on Cost Analysis
**Status:** ✅ Implemented
**Gaps closed:** F1 (general_account_id on analytic lines)
**Depends on:** nothing (foundation task)

---

## Problem

Farm-created analytic lines have no `general_account_id` — no link to the chart of accounts.
An accountant cannot reconcile analytic costs to the GL or verify accounting treatment.

The data to resolve this is **already available** on the cost analysis record:
- If an invoice is linked → the expense account is on the invoice line
- If a payment is linked → the account is on the linked invoice or payment journal
- If neither → the accountant should be able to select it manually

No new model needed. One field on `farm.cost.analysis` is enough.

---

## Solution

Add a single `general_account_id` field to `farm.cost.analysis` with this resolution logic:

```
1. cost.invoice_id set?
   → auto-fill from the first expense line of that invoice
2. cost.payment_id set (no invoice)?
   → auto-fill from payment.destination_account_id
3. Neither set?
   → accountant selects manually on the form
4. Always: pass the value to the analytic line via _sync_analytic_line()
```

---

## Files to Modify

| File | Action |
|------|--------|
| `models/cost_analysis.py` | **Edit** — add `general_account_id` field + auto-fill onchange + `_sync_analytic_line()` |
| `views/cost_analysis_views.xml` | **Edit** — add `general_account_id` to form view |
| `views/cultivation_project_views.xml` | **Edit** — add `general_account_id` optional column to inline cost list |

---

## Model Change

```python
general_account_id = fields.Many2one(
    'account.account',
    string='Financial Account',
    domain="[('deprecated', '=', False)]",
    help='GL expense account for this cost. Auto-filled from linked invoice or payment. '
         'Set manually if no invoice or payment is linked.',
    tracking=True,
)

@api.onchange('invoice_id')
def _onchange_invoice_id(self):
    if self.invoice_id:
        # Take the account from the first expense line of the invoice
        expense_line = self.invoice_id.invoice_line_ids.filtered(
            lambda l: l.account_id and l.account_id.account_type in (
                'expense', 'expense_depreciation', 'expense_direct_cost'
            )
        )[:1]
        if expense_line:
            self.general_account_id = expense_line.account_id

@api.onchange('payment_id')
def _onchange_payment_id(self):
    if self.payment_id and not self.invoice_id:
        if self.payment_id.destination_account_id:
            self.general_account_id = self.payment_id.destination_account_id
```

---

## Change to `_sync_analytic_line()`

```python
if cost.general_account_id:
    vals['general_account_id'] = cost.general_account_id.id
```

Also resolve `partner_id` from the same sources (Task 2 overlap — can be done here together):
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

## View Changes

### `cost_analysis_views.xml` form — Financial Details tab
```xml
<field name="general_account_id"
       groups="account.group_account_user"
       options="{'no_create': True}"/>
```

### Financial tab inline cost list (optional column)
```xml
<field name="general_account_id" optional="hide"
       groups="account.group_account_user"/>
```

---

## What the Accountant Sees

**With invoice linked:**
- Invoice auto-fills `general_account_id` → analytic line is complete → reconciliation works

**Without invoice (e.g. cash payment for seeds):**
- Accountant opens the cost entry, selects the expense account manually (e.g. 5101 - Seeds)
- Saves → analytic line gets `general_account_id`

**Result:** Every analytic line has a GL account. Gross Margin is fully reconcilable.

---

## Acceptance Criteria

- [ ] Cost linked to invoice → `general_account_id` auto-filled on `invoice_id` change
- [ ] Cost linked to payment (no invoice) → `general_account_id` from `destination_account_id`
- [ ] Cost with neither → accountant can select manually
- [ ] Analytic line `general_account_id` = cost entry's `general_account_id`
- [ ] Field is optional (no required constraint — don't block save)
- [ ] Field visible to accounting group users only in the Financial Details tab
- [ ] Module upgrade clean

---

## Why Not a Mapping Table?

The mapping table approach (cost_type → account) requires:
- A new model, new views, new security rows, new menu item
- The accountant to configure it before it works
- Guessing the GL account from a generic category (seeds → 5101) which may be wrong for this specific purchase

The direct approach (from invoice/payment) is:
- Zero new models
- Already has the exact account used for this specific transaction
- Falls back to manual selection when no document exists
- Simpler to understand, test, and maintain
