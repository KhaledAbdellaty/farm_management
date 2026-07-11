# Review Fixes (Critical/Warnings/Suggestions) Implementation Plan

> **For Claude:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development to implement this plan task-by-task, in this worktree, on branch `review-fixes-2026-07-10`.

**Goal:** Fix the 1 critical, 4 warning, and 4 suggestion findings from the 2026-07-10 `/odoo-review` re-review of `farm_management` (Odoo 18.0).

**Architecture:** Nine independent, small tasks against a single Odoo module. Each task touches 1-2 files (a security rule, a model field, a view, or a manifest/import cleanup) and is verified via the existing `tests/` suite (15 tests) run against a fresh throwaway Odoo database — never against `farm-test`/`Live-Database` directly during implementation. Mandatory for every task per this project's Odoo workflow: invoke the `odoo-development:odoo-context-gatherer` agent before touching any Odoo code, ground the fix in the actual current file content (don't trust this plan's line numbers blindly — files may have shifted), then implement, then run the test suite.

**Tech Stack:** Odoo 18.0, Python 3.12, PostgreSQL 16. Venv at `/media/portable/ECF0050EF004E126/odoo-venv`. Odoo core at `/media/portable/ECF0050EF004E126/odoo18`.

---

## How to run the test suite (every task uses this)

The module must be discoverable under an `addons_path` entry as a folder literally named `farm_management` — this worktree's checkout is at a path whose leaf directory is `review-fixes`, not `farm_management`, so a symlink already exists to work around this:

```bash
ls -la /media/portable/ECF0050EF004E126/odoo18/custom-addons/farm_management/.worktrees/addons_root/farm_management
# -> symlinks to .worktrees/review-fixes
```

Run tests like this (creates a disposable DB, runs the 15 existing tests + any new ones, drops the DB):

```bash
source /media/portable/ECF0050EF004E126/odoo-venv/bin/activate
cd /media/portable/ECF0050EF004E126/odoo18
ADDONS_ROOT=/media/portable/ECF0050EF004E126/odoo18/custom-addons/farm_management/.worktrees/addons_root
PGPASSWORD=odoo dropdb -h localhost -U odoo --if-exists farm-mgmt-testsuite
PGPASSWORD=odoo createdb -h localhost -U odoo farm-mgmt-testsuite
python3 odoo-bin -c odoo-server.conf -d farm-mgmt-testsuite \
  --addons-path="/media/portable/ECF0050EF004E126/odoo18/addons,$ADDONS_ROOT" \
  -i farm_management --test-enable --test-tags /farm_management --stop-after-init --log-level=test --http-port=8189
# Expect: "N failed, 0 error(s) of 15 tests" (or more, if a task added tests) with N=0
PGPASSWORD=odoo dropdb -h localhost -U odoo farm-mgmt-testsuite
```

Also run `python3 -m py_compile <changed .py files>` and, for XML changes, `python3 -c "import xml.dom.minidom as m; m.parse('<file>')"` before running the full suite — cheaper to catch syntax errors early.

**Never** run `-u farm_management` or any command against `farm-test` or `Live-Database` from within a task — those are real environments the human handles separately after this plan's work is reviewed and merged.

---

### Task 1: [CRITICAL] `group_farm_accountant` not covered by `account_move_farm_rule`

**Files:**
- Modify: `security/farm_security.xml` (the `account_move_farm_rule` record, currently ~line 122)
- Test: `tests/test_security_rules.py`

**Problem:** `group_farm_accountant` is documented as "Read-only financial view of farm operations" (see the `group_farm_accountant` record's `comment` field near the top of `farm_security.xml`) and has a read-only ACL on `account.move` (`access_account_move_farm_accountant` in `security/ir.model.access.csv`). But `account_move_farm_rule`'s `groups` only lists `group_farm_user`. A user assigned ONLY `group_farm_accountant` (not Farm User/Manager) can currently read every journal entry/vendor bill in the company, not just farm-linked ones.

**Step 1: Invoke odoo-context-gatherer**

Confirm the exact current line numbers/content of `account_move_farm_rule` and `group_farm_accountant` in `security/farm_security.xml`, and confirm `group_farm_accountant` does NOT already imply `group_farm_user` (it shouldn't — the file's own comment says "Farm Accountant is in a separate category and should NOT be combined with User/Manager").

**Step 2: Write the failing test**

Add to `tests/test_security_rules.py` (reuse `cls.partner`/`cls.project` from `setUpClass`):

```python
def test_farm_accountant_only_sees_journal_entries_linked_to_farm_sale_orders(self):
    farm_accountant = self.env['res.users'].create({
        'name': 'Farm Accountant Test',
        'login': 'farm_accountant_security_test',
        'groups_id': [(6, 0, [self.env.ref('farm_management.group_farm_accountant').id])],
    })
    product = self.env['product.product'].create({
        'name': 'Sec Test Accountant Crop', 'type': 'consu', 'is_storable': True,
    })
    order = self.env['sale.order'].create({
        'partner_id': self.partner.id,
        'cultivation_project_id': self.project.id,
    })
    order_line = self.env['sale.order.line'].create({
        'order_id': order.id, 'product_id': product.id, 'product_uom_qty': 1.0,
    })
    unrelated_invoice = self.env['account.move'].create({
        'move_type': 'out_invoice', 'partner_id': self.partner.id,
    })
    farm_invoice = self.env['account.move'].create({
        'move_type': 'out_invoice',
        'partner_id': self.partner.id,
        'invoice_line_ids': [(0, 0, {
            'product_id': product.id, 'quantity': 1.0, 'price_unit': 10.0,
            'sale_line_ids': [(6, 0, [order_line.id])],
        })],
    })

    visible = self.env['account.move'].with_user(farm_accountant).search([
        ('id', 'in', (unrelated_invoice | farm_invoice).ids),
    ])
    self.assertEqual(visible, farm_invoice)
```

**Step 3: Run the test suite to verify the new test fails**

Use the command block above. Expect the new test to fail (accountant currently sees both invoices, or the search itself might raise/behave unexpectedly — either way, `assertEqual` should fail because `visible` includes `unrelated_invoice`).

**Step 4: Implement the fix**

In `security/farm_security.xml`, change:
```xml
<field name="groups" eval="[(4, ref('group_farm_user'))]"/>
```
on `account_move_farm_rule` to:
```xml
<field name="groups" eval="[(4, ref('group_farm_user')), (4, ref('group_farm_accountant'))]"/>
```

**Step 5: Run the test suite to verify it passes**

Expect "0 failed, 0 error(s) of 16 tests" (15 existing + 1 new).

**Step 6: Commit**

```bash
git add security/farm_security.xml tests/test_security_rules.py
git commit -m "fix: scope account_move_farm_rule to group_farm_accountant too"
```

---

### Task 2: [WARNING] `farm.crop` missing `_check_company_auto`/`check_company`

**Files:**
- Modify: `models/crop.py` (class `Crop`, and the `product_id` field, currently ~lines 9-34)
- Test: `tests/test_farm_field_bootstrap.py` or a new small test in that file

**Problem:** Every other model touched in this session's check_company pass (`farm.py`, `cultivation_project.py`, `daily_report.py`, `cost_analysis.py`, `crop_bom.py`, `harvest_batch.py`) has `_check_company_auto = True`. `farm.crop` has its own `company_id` field but was missed — its `product_id` Many2one has no `check_company=True`, so a crop could be linked to a product from a different company with no validation.

**Step 1: Invoke odoo-context-gatherer**

Confirm `farm.crop`'s exact current field list and that `product_id`/`company_id` haven't changed shape since the last review. Confirm no legitimate reason exists for `product_id` to cross companies (it shouldn't — a crop's product should always belong to the crop's own company).

**Step 2: Write the failing test**

In `tests/test_farm_field_bootstrap.py`, add (uses a second company, mirroring the pattern in `test_security_rules.py`'s `test_crop_bom_line_multi_company_rule`):

```python
def test_crop_rejects_product_from_different_company(self):
    from odoo.exceptions import UserError
    company2 = self.env['res.company'].create({'name': 'Bootstrap Test Other Co'})
    other_product = self.env['product.product'].create({
        'name': 'Other Co Product', 'type': 'consu', 'is_storable': True,
        'company_id': company2.id,
    })
    with self.assertRaises(UserError):
        self.env['farm.crop'].create({
            'name': 'Cross Company Crop Test',
            'product_id': other_product.id,
        })
```

**Step 3: Run the test suite to verify it fails**

Expect failure: without `check_company=True`, no `UserError` is raised, so `assertRaises` fails.

**Step 4: Implement the fix**

In `models/crop.py`:
```python
class Crop(models.Model):
    _name = 'farm.crop'
    _description = 'Crop'
    _inherit = ['mail.thread', 'mail.activity.mixin']
    _order = 'name'
    _check_company_auto = True
```
and on the `product_id` field, add `check_company=True`:
```python
    product_id = fields.Many2one(
        'product.product',
        string='Product',
        required=False,
        tracking=True,
        readonly=False,
        check_company=True,
        help="The product associated with this crop for inventory and sales - auto-created on save"
    )
```

**Step 5: Run the test suite to verify it passes**

Expect "0 failed, 0 error(s) of 16 tests" (from Task 1's baseline + this task's new test — if run standalone before Task 1 merges, expect 15+1=16 either way, adjust count based on execution order).

**Step 6: Commit**

```bash
git add models/crop.py tests/test_farm_field_bootstrap.py
git commit -m "fix: add check_company to farm.crop.product_id"
```

---

### Task 3: [WARNING] Dead search filters + broken `search_default_*` in `farm_stock_views.xml`

**Files:**
- Modify: `views/farm_stock_views.xml`

**Problem:** Two custom search views (`farm_product_stock_search_view`, `farm_stock_move_line_search`) are commented out, but the two window actions that need them (`farm_action_product_stock`, `farm_action_move_line_history`) still set `search_default_agricultural`, `search_default_farm_supplies`, `search_default_by_daily_report`, `search_default_farm_operations` in their context — filters that don't exist anywhere the actions actually look. Both custom "Farm Inventory" and "Stock Move History" menus silently show unfiltered data.

Additionally, **both commented-out views have stale xpath anchors that would fail even if uncommented as-is**:
- `farm_product_stock_search_view`'s `inherit_id` targets `stock.product_search_form_view` (xpath anchor `//filter[@name='consumable']`), but the action's `search_view_id` is `stock.product_search_form_view_stock_report` — a different view with no `consumable` filter anywhere in its inheritance chain (confirmed by reading `addons/stock/views/product_views.xml` and `addons/product/views/product_views.xml`).
- `farm_stock_move_line_search`'s xpath anchor `//filter[@name='by_product']` doesn't exist in `stock.stock_move_line_view_search` — the real filter name is `groupby_product_id` (confirmed by reading `addons/stock/views/stock_move_line_views.xml`).

**Step 1: Invoke odoo-context-gatherer**

Re-confirm both base views' actual current filter names in this exact Odoo checkout (`addons/stock/views/product_views.xml` around `product_search_form_view_stock_report`, `addons/stock/views/stock_move_line_views.xml` around `stock_move_line_view_search`) — core Odoo view content can differ across point releases, don't trust this plan's citations blindly.

**Step 2: Implement the fix** (no automated test — this is a pure-XML view wiring fix with no model-level behavior to assert; verify manually per Step 3)

Replace the commented block (currently lines 20-31) with:
```xml
<record id="farm_product_stock_search_view" model="ir.ui.view">
    <field name="name">product.product.stock.search.farm</field>
    <field name="model">product.product</field>
    <field name="inherit_id" ref="stock.product_search_form_view_stock_report"/>
    <field name="arch" type="xml">
        <xpath expr="//filter[@name='real_stock_negative']" position="after">
            <separator/>
            <filter string="Agricultural Products" name="agricultural" domain="[('categ_id.name', '=', 'Agricultural')]"/>
            <filter string="Farm Supplies" name="farm_supplies" domain="[('categ_id.name', 'in', ['Fertilizer', 'Pesticide', 'Seed', 'Labor Services', 'Machinery'])]"/>
        </xpath>
    </field>
</record>
```

Replace the second commented block (currently lines 45-61) with:
```xml
<record id="farm_stock_move_line_search" model="ir.ui.view">
    <field name="name">stock.move.line.search.farm</field>
    <field name="model">stock.move.line</field>
    <field name="inherit_id" ref="stock.stock_move_line_view_search"/>
    <field name="arch" type="xml">
        <xpath expr="//field[@name='product_id']" position="after">
            <field name="daily_report_id"/>
        </xpath>
        <xpath expr="//filter[@name='groupby_product_id']" position="after">
            <filter name="by_daily_report" string="Farm Operation" context="{'group_by':'daily_report_id'}" invisible="not context.get('daily_report_id')"/>
        </xpath>
        <xpath expr="//filter[@name='done']" position="after">
            <filter string="Farm Operations" name="farm_operations" domain="[('daily_report_id', '!=', False)]"/>
        </xpath>
    </field>
</record>
```

Then update `farm_action_product_stock`'s `search_view_id` to point at the new custom view instead of the raw core one:
```xml
<field name="search_view_id" ref="farm_product_stock_search_view"/>
```
(`farm_action_move_line_history`'s `search_view_id` already correctly references `stock.stock_move_line_view_search` — no change needed there, since the new `farm_stock_move_line_search` inherits it and Odoo resolves the full inheritance chain regardless of which specific view id an action names, as long as one view in the chain is registered.)

**Step 3: Manual verification** (since this is view-only, confirm via `-i farm_management` install log, not a Python test)

```bash
source /media/portable/ECF0050EF004E126/odoo-venv/bin/activate
cd /media/portable/ECF0050EF004E126/odoo18
ADDONS_ROOT=/media/portable/ECF0050EF004E126/odoo18/custom-addons/farm_management/.worktrees/addons_root
PGPASSWORD=odoo dropdb -h localhost -U odoo --if-exists farm-mgmt-testsuite
PGPASSWORD=odoo createdb -h localhost -U odoo farm-mgmt-testsuite
python3 odoo-bin -c odoo-server.conf -d farm-mgmt-testsuite \
  --addons-path="/media/portable/ECF0050EF004E126/odoo18/addons,$ADDONS_ROOT" \
  -i farm_management --stop-after-init --log-level=info 2>&1 | grep -iE "error|traceback|ParseError"
# Expect: no output (no errors), confirming both views parsed and validated cleanly
PGPASSWORD=odoo dropdb -h localhost -U odoo farm-mgmt-testsuite
```

Then run the full test suite (per the header's command block) to confirm nothing else broke — expect the same pass count as before this task (view-only change, no new tests).

**Step 4: Commit**

```bash
git add views/farm_stock_views.xml
git commit -m "fix: wire up farm inventory/stock-move-history search filters correctly"
```

---

### Task 4: [WARNING] N+1 in `ProductProduct._compute_farm_usage`

**Files:**
- Modify: `models/stock.py` (`ProductProduct._compute_farm_usage`, currently ~lines 19-30)

**Problem:** Loops `for product in self:` and does one `stock.move` search per product instead of one batched query. Shows up in `farm_product_stock_tree_view` (a list view), so this is a real N+1 for any list of many products.

**Step 1: Invoke odoo-context-gatherer**

Confirm the exact current method body and the `is_used_in_farm`/`last_farm_usage_date` field definitions haven't changed shape.

**Step 2: Implement the fix**

Replace:
```python
    @api.depends('stock_move_ids.daily_report_id')
    def _compute_farm_usage(self):
        """Compute if product is used in farm operations and the last usage date"""
        for product in self:
            farm_moves = self.env['stock.move'].search([
                ('product_id', '=', product.id),
                ('daily_report_id', '!=', False),
                ('state', '=', 'done')
            ], order='date desc', limit=1)

            product.is_used_in_farm = bool(farm_moves)
            product.last_farm_usage_date = farm_moves.date.date() if farm_moves else False
```
with a single batched query using `_read_group` (matches the pattern already used in `cultivation_project.py::_compute_total_irrigation_hours`):
```python
    @api.depends('stock_move_ids.daily_report_id')
    def _compute_farm_usage(self):
        """Compute if product is used in farm operations and the last usage date"""
        groups = self.env['stock.move']._read_group(
            [
                ('product_id', 'in', self.ids),
                ('daily_report_id', '!=', False),
                ('state', '=', 'done'),
            ],
            groupby=['product_id'],
            aggregates=['date:max'],
        )
        last_usage_by_product = {product.id: last_date for product, last_date in groups}
        for product in self:
            last_date = last_usage_by_product.get(product.id)
            product.is_used_in_farm = bool(last_date)
            product.last_farm_usage_date = last_date.date() if last_date else False
```

**Step 3: Run the test suite**

No dedicated test exists for this compute method (out of scope to add one here — it's a pure performance fix with identical output, not new behavior). Run the full suite per the header's command block and confirm the pass count is unchanged (15 or 16, depending on execution order relative to Tasks 1/2) — this confirms the refactor didn't break anything the other tests happen to touch (e.g. any test that creates a `stock.move` with `daily_report_id` set will indirectly exercise this compute).

**Step 4: Commit**

```bash
git add models/stock.py
git commit -m "perf: batch ProductProduct._compute_farm_usage instead of per-product search"
```

---

### Task 5: [WARNING] Unused imports

**Files:**
- Modify: `models/cultivation_project.py` (line 3: `from odoo.osv import expression`)
- Modify: `models/crop.py` (line 1: `tools` in `from odoo import fields, models, api, _, tools`)

**Step 1: Invoke odoo-context-gatherer**

Grep both files for actual usage of `expression.` and `tools.` to confirm they're genuinely unused (not just imported at the top but referenced somewhere deep in the file):
```bash
grep -n "expression\." models/cultivation_project.py
grep -n "\btools\." models/crop.py
```
Both should return no matches (already confirmed once during the review, but re-verify since files may have changed).

**Step 2: Implement the fix**

In `cultivation_project.py`, remove the line:
```python
from odoo.osv import expression
```

In `crop.py`, change:
```python
from odoo import fields, models, api, _, tools
```
to:
```python
from odoo import fields, models, api, _
```

**Step 3: Compile-check and run the test suite**

```bash
python3 -m py_compile models/cultivation_project.py models/crop.py
```
Then run the full suite per the header's command block — expect the same pass count as before this task (pure dead-code removal, zero behavior change).

**Step 4: Commit**

```bash
git add models/cultivation_project.py models/crop.py
git commit -m "chore: remove unused imports (expression, tools)"
```

---

### Task 6: [SUGGESTION] Dead manifest hook keys

**Files:**
- Modify: `__manifest__.py` (currently ~lines 73-75)

**Step 1: Invoke odoo-context-gatherer**

Confirm no other file in the module references `post_init_hook`/`pre_init_hook`/`post_load` as actual Python function names (they'd need to be, since these manifest keys point to callables) — a quick grep confirms:
```bash
grep -rn "post_init_hook\|pre_init_hook\|post_load" models/ *.py 2>/dev/null
```
Should return nothing outside `__manifest__.py` itself, confirming these are genuinely unused empty-string placeholders.

**Step 2: Implement the fix**

Remove these three lines from `__manifest__.py`:
```python
    'post_init_hook': '',
    'pre_init_hook': '',
    'post_load': '',
```

**Step 3: Compile-check and run the test suite**

```bash
python3 -m py_compile __manifest__.py
```
Then run the full suite per the header's command block — expect the same pass count (manifest metadata cleanup, zero behavior change).

**Step 4: Commit**

```bash
git add __manifest__.py
git commit -m "chore: remove unused empty manifest hook keys"
```

---

### Task 7: [SUGGESTION] Dead assets block and unused vendored `chart.min.js`

**Files:**
- Modify: `__manifest__.py` (the `assets` block, currently ~lines 56-71)
- Delete: `static/vendor/chart.min.js`

**Step 1: Invoke odoo-context-gatherer**

Confirm no other file references `chart.min.js` or any of the commented-out dashboard file paths (`farm_dashboard.scss`/`.js`/`.xml`, `dashboard_loader.js`, `farm_management.scss`):
```bash
grep -rn "chart.min.js\|farm_dashboard\|dashboard_loader\|farm_management.scss" . --include="*.py" --include="*.xml" 2>/dev/null | grep -v "__manifest__.py"
```
Should return nothing, confirming these are genuinely dead. Also confirm none of the referenced static files under `static/src/components/dashboard/` actually exist on disk (if they DO exist, this is a "someone started building this and paused" situation, not dead code — investigate further and report back rather than deleting working-in-progress files).

**Step 2: Implement the fix**

If the investigation in Step 1 confirms nothing exists under `static/src/components/dashboard/` and `chart.min.js` truly has zero references: remove the entire `assets` key from `__manifest__.py` (it's just an empty commented-out shell) and delete `static/vendor/chart.min.js`.

If the dashboard component files DO exist and look like genuine in-progress work: stop, don't delete anything, and report back — this task becomes "ask the user whether this dashboard feature is abandoned or paused" rather than a mechanical cleanup.

**Step 3: Compile-check and run the test suite**

```bash
python3 -m py_compile __manifest__.py
```
Then run the full suite — expect the same pass count (asset/static cleanup, zero Python behavior change).

**Step 4: Commit**

```bash
git add __manifest__.py
git rm static/vendor/chart.min.js  # only if actually deleted in Step 2
git commit -m "chore: remove dead assets block and unused vendored chart.min.js"
```

---

### Task 8: [SUGGESTION] Hoist repeated per-line query in `_compute_available_products`

**Files:**
- Modify: `models/daily_report.py` (`DailyReportLine._compute_available_products`, currently ~lines 1615-1624)

**Problem:** `_compute_available_products` loops `for line in self:` and calls `self._get_products_with_po_lines()` inside the loop for every `labor_machinery` line — but `_get_products_with_po_lines()` is `@api.model` and returns the exact same company-wide result regardless of which line calls it. It's recomputing the identical query once per line instead of once per batch.

**Step 1: Invoke odoo-context-gatherer**

Confirm the exact current body of both `_compute_available_products` and `_get_products_with_po_lines`, and confirm `_get_products_with_po_lines()`'s result genuinely doesn't depend on anything about the calling `line` (it shouldn't — re-read its domain, which only filters on PO state/partner/category, nothing line-specific).

**Step 2: Implement the fix**

Replace:
```python
    @api.depends('line_type')
    def _compute_available_products(self):
        """Compute available products based on line type"""
        for line in self:
            if line.line_type == 'labor_machinery':
                # Get products with available PO lines
                product_ids = self._get_products_with_po_lines()
                line.available_product_ids = [(6, 0, product_ids)]
            else:
                line.available_product_ids = [(5, 0, 0)]  # Clear the field
```
with:
```python
    @api.depends('line_type')
    def _compute_available_products(self):
        """Compute available products based on line type"""
        # ponytail: _get_products_with_po_lines() is company-wide and doesn't
        # vary per line, so compute it once per batch instead of once per line.
        labor_machinery_lines = self.filtered(lambda l: l.line_type == 'labor_machinery')
        if labor_machinery_lines:
            product_ids = labor_machinery_lines._get_products_with_po_lines()
            labor_machinery_lines.available_product_ids = [(6, 0, product_ids)]
        (self - labor_machinery_lines).available_product_ids = [(5, 0, 0)]
```

Note: `_get_products_with_po_lines` is declared `@api.model`, meaning it ignores `self` and works the same whether called on an empty recordset, one record, or many — calling it as `labor_machinery_lines._get_products_with_po_lines()` is safe and behaves identically to the old per-line calls, just once instead of N times.

**Step 3: Run the test suite**

No dedicated test exists for this compute (out of scope to add one — pure performance fix with identical output). Run the full suite per the header's command block and confirm the pass count is unchanged.

**Step 4: Commit**

```bash
git add models/daily_report.py
git commit -m "perf: compute available_product_ids once per batch, not once per line"
```

---

## After all 8 tasks

Dispatch a final code-reviewer subagent over the whole diff (`git diff dev...review-fixes-2026-07-10` from the worktree), covering all 8 tasks together — confirm nothing conflicts, the full test suite still passes end to end, and no task accidentally touched a file another task also owns.

Then use **superpowers:finishing-a-development-branch** to decide how to integrate: merge to `dev` locally (this repo has a GitHub remote `origin` — do NOT push without the user's explicit go-ahead), open a PR, or leave the branch for the user to review manually. The remote URL contains an embedded access token (visible via `git remote -v`) — do not repeat it in any commit message, PR description, or chat output.

Once merged to `dev` (or whatever the user decides), the human handles applying these changes to `farm-test`/`Live-Database` via `-u farm_management` separately — that is explicitly out of scope for this plan's execution (see the "Never" rule in the test-running section above).
