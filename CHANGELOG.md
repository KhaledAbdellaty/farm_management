# Changelog — Farm Management System

All notable changes to this project are documented here.
Format follows [Keep a Changelog](https://keepachangelog.com/en/1.0.0/).

---

## [Unreleased] — 2026-05-09

### Bug Fix

- **Analytic entry not created for Labor/Service lines after posting vendor bill**
  Guard 1 in `_sync_analytic_line()` was unconditionally skipping cost-analysis
  analytic line creation whenever the linked invoice was posted — even when the
  bill had no `analytic_distribution` set and therefore produced no analytic
  lines of its own. Bills posted without an analytic distribution (common for
  PO-backed service bills) now fall through and keep the cost-analysis analytic
  line as the sole entry for that cost.
  *(models/cost_analysis.py)*

- **DR `actual_cost` diverging from analytic entry amount after stock validation**
  `DailyReportLine._compute_actual_cost()` was falling back to
  `product.standard_price × quantity` for consumable/storable products when
  `product_price_value_unit` was unavailable. Because Odoo's AVCO engine updates
  `standard_price` during `button_validate()` — after the SVL is written but
  potentially before the DR line recomputes — `actual_cost` could reflect the
  *new* AVCO price while the analytic entry correctly used the frozen SVL value,
  causing a permanent mismatch between `report.actual_cost` and the analytic
  account balance.
  *(models/daily_report.py — `DailyReportLine._compute_actual_cost`)*

- **`action_repair_invoice_analytic_duplicates` incorrectly cleaning records
  where bill has no analytic lines**
  The repair action was removing cost-analysis analytic lines for any
  posted-invoice cost, regardless of whether the invoice had generated its own
  analytic lines. It now filters to only remove ghost lines when the bill has a
  confirmed analytic line for the project account.
  *(models/cost_analysis.py — `action_repair_invoice_analytic_duplicates`)*

### Improvement

- **Unified cost source: SVL (Stock Valuation Layer) as single source of truth**
  `DailyReportLine._compute_actual_cost()` for storable/consumable products now
  reads cost exclusively from `stock.valuation.layer` records linked to the
  validated stock moves. SVL values are frozen at picking validation time and are
  immune to subsequent AVCO/FIFO `standard_price` recalculations, making
  `actual_cost`, `report.actual_cost`, and the analytic entry amount all
  consistent with each other.
  Falls back to `standard_price` only before any stock moves are validated
  (pre-confirmation state).
  *(models/daily_report.py — `DailyReportLine._compute_actual_cost`)*

- **Simplified `_create_analytic_entries()` cost resolution**
  Replaced ~80 lines of multi-approach cost cascade (accounting entries →
  SVL → `product_price_value_unit` → `price_unit` → `standard_price` →
  minimum 1.0/unit) with a single call to `line.actual_cost`. Since
  `_compute_actual_cost()` now correctly reads from SVL, this removes a large
  block of fragile, hard-to-debug fallback code and ensures both the analytic
  entry and the DR cost field always show the same number.
  *(models/daily_report.py — `_create_analytic_entries`)*

### Feature

- **Repair action: "Repair Invoice-Backed Analytic Duplicates"**
  New server action accessible from Farm Management → Configuration → Tools.
  Finds and removes ghost `account.analytic.line` records on cost-analysis
  entries whose linked vendor bill is posted *and* has its own authoritative
  analytic line. Safe to run multiple times; already-clean databases are
  unaffected.
  *(models/cost_analysis.py — `action_repair_invoice_analytic_duplicates`,
  data/server_actions.xml, views/farm_menu.xml)*

- **`AccountMove.action_post()` cleanup hook**
  When a vendor bill is confirmed, any linked `farm.cost.analysis` records
  immediately run `_sync_analytic_line()`. This ensures Guard 1 fires at post
  time to remove the cost-analysis ghost line the moment the bill creates its
  own authoritative analytic line — no manual repair needed for new data.
  *(models/account_move.py)*

- **`CostAnalysis.credit_account_id` and `journal_entry_id` fields**
  Standalone cost records (no invoice or payment) can now generate a proper
  double-entry journal entry. The accountant selects the credit account
  (e.g. Accrued Expenses, Accounts Payable); a draft journal entry is created
  automatically and can be posted via the "Post to Ledger" smart button.
  *(models/cost_analysis.py — `_create_journal_entry`, `action_post_journal_entry`)*

### Translation

- **Regenerated `.pot` template from `Live-Database`** — 556 source strings
  captured including all new harvest batch, cost analysis, and repair action
  strings.
  *(i18n/farm_management.pot)*

- **Arabic (`ar.po`) fully updated — 117 new strings translated**
  New coverage includes:
  - Harvest Batch workflow: labels, confirmation dialogs, validation messages,
    inline HTML info blocks, error messages
  - Cost Analysis: `Credit Account`, `Financial Account`, `Journal Entry`,
    `Product / Service`, `Vendor / Partner` field labels and help text
  - Analytic repair actions: tool names and result notifications
  - Security roles: `Farm Accountant (Read-Only)` group description
  - Daily Report: `Default Vendor` field label and help text
  - Financial summary labels: `Total Revenue`, `Total Profit`, `Total Value`
  - Configuration menu: `Tools` submenu label
  *(i18n/ar.po)*

---

## [1.1.2] — 2025-10 (previous release)

### Feature
- Cost Analysis journal entry integration
- Project accounting enhancements
- Initial analytic duplication guards for PO-backed labor/machinery DR lines
- Gross Margin "None" grouping fix (two-step analytic line create/write for
  `project_id` to bypass `hr_timesheet.create()` ValidationError)

### Bug Fix
- Bill posting error "This analytic item was created by a journal item" — caused
  by `AccountMoveLine._prepare_analytic_distribution_line()` override injecting
  `employee_id`; removed the override entirely
- Zero-amount analytic entries for stock products after `project_id` write —
  `hr_timesheet._timesheet_postprocess()` was overwriting the SVL amount with
  `standard_price × unit_amount`; fixed by restoring correct amount after
  `project_id` write in both `_create_analytic_entries()` and
  `_sync_analytic_line()`
