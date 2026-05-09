# Analytic Accounting Gap Analysis
**Module:** farm_management
**Date:** 2026-05-04
**Scope:** Gross Margin integrity, audit traceability, ERP scalability

---

## 1. Current State — What Works

| Cost Source | Analytic Line Quality |
|-------------|----------------------|
| Customer invoice posted (sale order revenue) | **Complete** — Odoo standard path sets all fields |
| Vendor bill posted (PO-backed labor/machinery) | **Complete** — Odoo path + `_prepare_analytic_distribution_line()` injects `project_id` |
| Daily report product lines (non-PO) | **Partial** — sets `product_id` + `general_account_id` conditionally, missing `partner_id`, `category` |
| Manual cost analysis entries | **Minimal** — only `name`, `date`, `amount`, `account_id`. Missing product, partner, category, GL account |

---

## 2. Field Population Comparison

| Field | Invoice-Created | Cost Analysis | Daily Report |
|-------|-----------------|---------------|--------------|
| `name` | ✅ | ✅ | ✅ |
| `date` | ✅ | ✅ | ✅ |
| `account_id` | ✅ | ✅ | ✅ |
| `amount` | ✅ | ✅ | ✅ |
| `unit_amount` | ✅ | ✅ | ✅ |
| `product_uom_id` | ✅ | ✅ | ✅ |
| `company_id` | ✅ | ✅ | ✅ |
| `project_id` | ✅ (via override) | ✅ conditional | ✅ conditional |
| `employee_id` | ✅ (via override) | ✅ conditional | ✅ conditional |
| `product_id` | ✅ | ❌ never set | ✅ |
| `partner_id` | ✅ | ❌ never set | ❌ never set |
| `general_account_id` | ✅ | ❌ never set | ⚠️ conditional |
| `category` | ✅ intelligent | ❌ defaults `'other'` | ❌ defaults `'other'` |
| `move_line_id` | ✅ | ❌ | ❌ |
| `ref` | ✅ | ❌ | ❌ |
| `user_id` | ✅ explicit | ❌ implicit | ❌ implicit |

---

## 3. Critical Gaps

### Gap 1 — `general_account_id` missing from manual cost entries
Every analytic line should trace back to a GL (chart of accounts) expense account.
Manual cost analysis entries have **no GL link** — they are disconnected from the financial ledger.
Daily report entries set it only when `product.categ_id.property_account_expense_categ_id` exists.

### Gap 2 — `category` never set on farm-created lines
Odoo's Gross Margin report separates revenue from cost via:
- Invoice path → `'invoice'`
- Vendor bill path → `'vendor_bill'`
- Manual farm entries → `'other'` (meaningless default)

The report cannot automatically compute gross margin on farm-created costs.

### Gap 3 — `partner_id` never set on any manually-created line
No vendor traceability. Cannot answer: which vendor costs the most? Which supplier prices are rising?
Data is **available** (via PO link on daily report lines, via invoice link on cost analysis) but never transferred.

### Gap 4 — `product_id` missing from cost analysis entries
Daily report lines correctly set `product_id`. Manual cost analysis entries do not.
Inconsistency breaks product-level cost reporting and inventory costing reconciliation.

### Gap 5 — No audit reference (`ref`)
Farm-created analytic lines have no reference number. Auditors cannot trace a line back to its source document.

---

## 4. User Stories

### Story 1: Monthly Close Reconciliation
> "Every month-end I verify that every debit in the analytic matches a GL journal entry. Half the lines have no `general_account_id` so I can't reconcile them."

**Requirement:** `general_account_id` on every analytic line from a configurable cost-type → GL account mapping.

### Story 2: Vendor Cost Analysis
> "I need total spend per vendor across all projects. Today farm cost entries have no partner — impossible."

**Requirement:** `partner_id` resolved from invoice, payment, or PO line.

### Story 3: Audit Trail
> "Revenue lines all trace to invoices. 60% of cost lines are orphaned — no journal entry link, no vendor, no GL account. I can't hand this to an auditor."

**Requirement:** `ref` set to source document number; `move_line_id` where applicable.

### Story 4: Budget vs. Actual by GL Account
> "Budgeted seeds: 50,000 EGP. Actual: 73,000 EGP. Variance mapped to account 5100. Impossible without GL links."

**Requirement:** Configurable cost-type → account mapping table applied at analytic line creation.

### Story 5: Cash Flow vs. Accrual Tracking
> "Labor cost accrued March 15 in daily report. Vendor bill arrives April 3. I need to see WHEN it was accrued vs. WHEN paid."

**Requirement:** Accrual flag / payment state on analytic lines.

### Story 6: Irrigation Cost per Hectare
> "Water costs by product and UoM — today lines have `unit_amount` but inconsistent product/UoM context."

**Requirement:** Consistent `product_id` + `product_uom_id` + `unit_amount` on ALL analytic lines.

### Story 7: Multi-Company Consolidation
> "3 farms under different companies. I want consolidated gross margin for wheat across all farms."

**Requirement:** Crop-level analytic plan dimension using Odoo 18 multi-plan `analytic_distribution`.

---

## 5. Enhancement Backlog

### 🔴 Must Fix — Accounting Integrity

| # | Fix | Location |
|---|-----|----------|
| F1 | Add `general_account_id` field to cost analysis — auto-filled from linked invoice/payment, manually selectable otherwise | `cost_analysis` model + `_sync_analytic_line()` |
| F2 | Set `category = 'vendor_bill'` on costs, `'invoice'` on revenues | Both models |
| F3 | Set `partner_id` from invoice / payment / PO when available | `cost_analysis._sync_analytic_line()` |
| F4 | Set `product_id` on cost analysis analytic lines | `cost_analysis` model + view + `_sync_analytic_line()` |
| F5 | Set `ref` to source document reference for audit trail | Both models |

### 🟡 High Value — Scalability

| # | Enhancement | Benefit |
|---|-------------|---------|
| S1 | `partner_id` field on cost analysis form | Full vendor traceability for manual entries |
| S3 | Accrual vs. paid flag on analytic lines | Cash flow accuracy |
| S4 | Second analytic plan for crop dimension | Cross-project crop cost comparison |

### 🟢 Nice to Have — ERP Maturity

| # | Enhancement | Benefit |
|---|-------------|---------|
| N1 | Gross Margin dashboard widget per project | At-a-glance project health |
| N2 | Cost forecasting from BOM remaining quantities | Prevent budget overrun |
| N3 | Analytic closing journal entry when project = done | Clean GL treatment |
| N4 | PDF financial report per project | Shareholder / investor reporting |

---

## 6. Implementation Order Rationale

The Must Fix group (F1–F5) is the foundation. Without it:
- S1 has no effect (mapping table but no mechanism to apply it)
- N1 dashboard shows unreliable numbers
- Auditor review fails

Tasks 3 and 5 are 2-line fixes — implement them first for immediate visible impact.
