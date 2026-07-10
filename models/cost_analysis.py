from odoo import fields, models, api, Command, _
from odoo.exceptions import ValidationError
import logging

_logger = logging.getLogger(__name__)


class CostAnalysis(models.Model):
    _name = 'farm.cost.analysis'
    _description = 'Farm Cost Analysis'
    _inherit = ['mail.thread', 'mail.activity.mixin']
    _order = 'date desc, id desc'
    _check_company_auto = True

    name = fields.Char(string='Reference', required=True, copy=False, readonly=True,
                     default=lambda self: _('New'))
    date = fields.Date(string='Date', required=True, default=fields.Date.today, tracking=True)

    # Project and location information
    project_id = fields.Many2one('farm.cultivation.project', string='Cultivation Project',
                              required=True, tracking=True, ondelete='cascade', check_company=True)
    farm_id = fields.Many2one('farm.farm', related='project_id.farm_id',
                           string='Farm', store=True, readonly=True)
    field_id = fields.Many2one('farm.field', related='project_id.field_id',
                            string='Field', store=True, readonly=True)
    crop_id = fields.Many2one('farm.crop', related='project_id.crop_id',
                           string='Crop', store=True, readonly=True)

    def _get_cost_types(self):
        """Return selection options for cost types with proper translations"""
        return [
            ('seeds', _('Seeds/Seedlings')),
            ('fertilizer', _('Fertilizers')),
            ('pesticide', _('Pesticides')),
            ('herbicide', _('Herbicides')),
            ('water', _('Irrigation Water')),
            ('labor', _('Labor/Workforce')),
            ('machinery', _('Machinery/Equipment')),
            ('rent', _('Land Rent')),
            ('fuel', _('Fuel')),
            ('maintenance', _('Maintenance')),
            ('services', _('Services')),
            ('transportation', _('Transportation')),
            ('storage', _('Storage')),
            ('certification', _('Certification')),
            ('testing', _('Laboratory Testing')),
            ('other', _('Other')),
        ]

    # Cost categorization
    cost_type = fields.Selection(
        selection='_get_cost_types',
        string='Cost Type',
        required=True,
        tracking=True
    )

    # Product / service this cost relates to — optional but improves analytic detail.
    # Selecting a product auto-fills cost_name and uom_id.
    product_id = fields.Many2one(
        'product.product',
        string='Product / Service',
        tracking=True,
        check_company=True,
        help='Optional. Product or service this cost relates to. '
             'Auto-fills description and unit of measure when selected.',
    )

    # Cost details
    cost_name = fields.Char(string='Cost Description', required=True, tracking=True)
    cost_amount = fields.Monetary(string='Cost Amount', required=True, tracking=True,
                               currency_field='currency_id')
    cost_unit_amount = fields.Float(string='Unit Cost', compute='_compute_unit_cost', store=True)
    currency_id = fields.Many2one('res.currency', related='company_id.currency_id',
                               readonly=True)
    company_id = fields.Many2one('res.company', related='project_id.company_id',
                              readonly=True, store=True)

    # Quantity information if applicable
    quantity = fields.Float(string='Quantity', tracking=True)
    uom_id = fields.Many2one('uom.uom', string='Unit of Measure', tracking=True)

    # Financial data
    invoice_id = fields.Many2one('account.move', string='Invoice', tracking=True,
                               check_company=True)
    payment_id = fields.Many2one('account.payment', string='Payment', tracking=True,
                               check_company=True)

    # Analytical accounting — display reference only (analytic line is managed via analytic_line_id)
    analytic_account_id = fields.Many2one('account.analytic.account',
                                        string='Analytic Account',
                                        related='project_id.analytic_account_id',
                                        store=True, readonly=True)

    # Tracks the analytic line posted to the analytic account for this cost entry
    analytic_line_id = fields.Many2one(
        'account.analytic.line', string='Analytic Line',
        readonly=True, copy=False, ondelete='set null',
        help='Analytic line automatically created in the project analytic account for this cost entry'
    )

    # Vendor / customer linked to this cost — auto-filled from invoice or payment,
    # or set manually for cash / undocumented expenses.
    partner_id = fields.Many2one(
        'res.partner',
        string='Vendor / Partner',
        tracking=True,
        help='Supplier or partner for this cost. Auto-filled from the linked invoice or payment.',
    )

    # GL account — links this cost to the chart of accounts so the analytic
    # line is fully reconcilable.  Auto-filled from the linked invoice or
    # payment; the accountant can also select it manually when no document exists.
    general_account_id = fields.Many2one(
        'account.account',
        string='Financial Account',
        domain="[('deprecated', '=', False)]",
        tracking=True,
        check_company=True,
        help='GL expense account for this cost. Auto-filled from the linked invoice '
             'or payment. Select manually when no invoice or payment is linked.',
    )

    # Credit side of the journal entry when no invoice/payment exists.
    # The debit is always general_account_id (expense). The accountant selects
    # the appropriate payable or accrual account here.
    credit_account_id = fields.Many2one(
        'account.account',
        string='Credit Account',
        domain="[('deprecated', '=', False)]",
        tracking=True,
        groups='account.group_account_user',
        check_company=True,
        help='Credit account for the generated journal entry '
             '(e.g. Accrued Expenses, Accounts Payable). '
             'Used only when no invoice or payment is linked.',
    )

    # Journal entry generated from this cost record (standalone costs only).
    journal_entry_id = fields.Many2one(
        'account.move',
        string='Journal Entry',
        readonly=True,
        copy=False,
        ondelete='set null',
        check_company=True,
        help='Journal entry automatically generated for this cost '
             'when no invoice or payment is linked.',
    )

    notes = fields.Html(string='Notes', translate=True)

    # Cost per area calculations
    cost_per_area = fields.Monetary(string='Cost per Area', compute='_compute_cost_per_area',
                                 store=True, currency_field='currency_id')
    field_area = fields.Float(related='field_id.area', string='Field Area',
                           readonly=True, store=True)
    field_area_unit = fields.Selection(related='field_id.area_unit',
                                    string='Area Unit', readonly=True, store=True)

    # For budgeting and variance analysis
    is_budgeted = fields.Boolean(string='Budgeted Cost', default=False, tracking=True)

    def _get_source_types(self):
        """Return selection options for source types with proper translations"""
        return [
            ('daily_report', _('Daily Report')),
            ('bom', _('Bill of Materials')),
            ('manual', _('Manual Entry')),
        ]

    # Source tracking for automatic cost entries
    source_type = fields.Selection(
        selection='_get_source_types',
        string='Source Type',
        default='manual',
        tracking=True
    )
    source_id = fields.Integer(string='Source Record ID', tracking=True)
    budget_variance = fields.Float(string='Budget Variance %', compute='_compute_budget_variance',
                               store=True)

    def _get_cost_effectiveness(self):
        """Return selection options for cost effectiveness with proper translations"""
        return [
            ('excellent', _('Excellent')),
            ('good', _('Good')),
            ('average', _('Average')),
            ('poor', _('Poor')),
        ]

    # Cost effectiveness
    cost_effectiveness = fields.Selection(
        selection='_get_cost_effectiveness',
        string='Cost Effectiveness',
        tracking=True
    )

    # ── Product auto-fill ────────────────────────────────────────────────────

    @api.onchange('product_id')
    def _onchange_product_id(self):
        """Auto-fill cost_name and uom_id when a product is selected."""
        if not self.product_id:
            return
        if not self.cost_name:
            self.cost_name = self.product_id.name
        if not self.uom_id:
            self.uom_id = self.product_id.uom_id

    # ── GL account auto-fill ──────────────────────────────────────────────────

    @api.onchange('invoice_id')
    def _onchange_invoice_id(self):
        """Sync cost_amount, partner_id, and general_account_id from the linked vendor bill."""
        if not self.invoice_id:
            return
        self.cost_amount = self.invoice_id.amount_total
        self.partner_id = self.invoice_id.partner_id
        # Prefer an expense-type line; fall back to the first line so the
        # field always updates when the invoice changes.
        expense_line = self.invoice_id.invoice_line_ids.filtered(
            lambda l: l.account_id and l.account_id.account_type in (
                'expense', 'expense_depreciation', 'expense_direct_cost'
            )
        )[:1]
        self.general_account_id = (
            expense_line.account_id
            if expense_line
            else self.invoice_id.invoice_line_ids[:1].account_id
        )

    @api.onchange('payment_id')
    def _onchange_payment_id(self):
        """Sync cost_amount, partner_id, and general_account_id from the linked payment (no invoice)."""
        if not self.payment_id or self.invoice_id:
            return
        self.cost_amount = self.payment_id.amount
        self.partner_id = self.payment_id.partner_id
        # Always reassign so switching payments updates the field
        self.general_account_id = self.payment_id.destination_account_id or False

    # ── Analytic line synchronisation ─────────────────────────────────────────

    def _sync_analytic_line(self):
        """
        Create or update the matching account.analytic.line for this cost entry.
        Costs are posted as negative amounts (Odoo analytic convention).

        project_id is always set when the cultivation project has a linked
        project.project record. Because hr_timesheet.create() raises a
        ValidationError when project_id is included in create vals without a
        matching employee, new lines are created without project_id and then
        project_id is patched via write() — hr_timesheet.write() has no such
        restriction, so this is always safe regardless of whether the current
        user has an hr.employee record.
        """
        for cost in self:
            account = cost.project_id.analytic_account_id
            if not account:
                continue

            # ── Duplication guards ────────────────────────────────────────────
            # Guard 1: Invoice-backed cost.
            # A posted vendor bill creates its own authoritative analytic line
            # (move_line_id set) via analytic_distribution.  Defer to the
            # bill's line ONLY when it actually has one for this project account.
            # If the bill was posted without analytic_distribution (e.g. a PO
            # bill where the distribution was never set), fall through and keep
            # the cost-analysis analytic line so no entry goes missing.
            if cost.invoice_id and cost.invoice_id.state == 'posted':
                bill_analytic = cost.invoice_id.line_ids.analytic_line_ids.filtered(
                    lambda l: l.account_id == account
                )
                if bill_analytic:
                    # Bill has authoritative analytic line — remove ghost and defer.
                    if cost.analytic_line_id and not cost.analytic_line_id.move_line_id:
                        cost.analytic_line_id.unlink()
                        cost.with_context(skip_analytic_sync=True).write(
                            {'analytic_line_id': False}
                        )
                    continue
                # Bill is posted but has no analytic lines for this project account.
                # Fall through to create / maintain the cost-analysis analytic line.

            # Guard 2: Daily-report-sourced cost.
            # When a cost analysis record is generated from a done Daily Report
            # (source_type='daily_report'), _create_analytic_entries() has
            # already posted an analytic line for that report.  Creating a
            # second line here would double the cost in the analytic account.
            if cost.source_type == 'daily_report' and cost.source_id:
                dr = self.env['farm.daily.report'].browse(cost.source_id)
                if dr.exists() and dr.analytic_line_ids:
                    if cost.analytic_line_id and not cost.analytic_line_id.move_line_id:
                        cost.analytic_line_id.unlink()
                        cost.with_context(skip_analytic_sync=True).write(
                            {'analytic_line_id': False}
                        )
                    continue
            # ─────────────────────────────────────────────────────────────────

            label = _("%(type)s: %(name)s") % {
                'type': cost.get_cost_type_label(),
                'name': cost.cost_name,
            }
            vals = {
                'name': label,
                'date': cost.date,
                'account_id': account.id,
                'amount': -cost.cost_amount,        # negative = expense in analytic
                'unit_amount': cost.quantity or 0.0,
                'product_uom_id': cost.uom_id.id if cost.uom_id else False,
                'company_id': cost.company_id.id,
                'category': 'vendor_bill',
                'ref': cost.name,
            }
            if cost.product_id:
                vals['product_id'] = cost.product_id.id
            if cost.general_account_id:
                vals['general_account_id'] = cost.general_account_id.id
            if cost.partner_id:
                vals['partner_id'] = cost.partner_id.id

            project_id = cost.project_id.project_id.id if cost.project_id.project_id else False

            if cost.analytic_line_id:
                # write() does not enforce the hr_timesheet employee+project
                # requirement, so we can include project_id directly.
                if project_id:
                    vals['project_id'] = project_id
                cost.analytic_line_id.write(vals)
                _logger.debug(
                    "Updated analytic line %s for cost entry %s",
                    cost.analytic_line_id.id, cost.name,
                )
            else:
                # Create WITHOUT project_id to avoid hr_timesheet.create()
                # ValidationError ("Timesheets must be created with an active
                # employee"), then patch project_id via write() immediately after.
                line = self.env['account.analytic.line'].create(vals)
                if project_id:
                    line.write({'project_id': project_id})
                    # hr_timesheet._timesheet_preprocess_get_accounts() injects
                    # account_id into the write vals, triggering _timesheet_postprocess()
                    # to recompute amount as standard_price × unit_amount.
                    # Restore the correct cost amount to prevent it being zeroed out.
                    line.with_context(check_move_validity=False).write(
                        {'amount': vals['amount']}
                    )
                cost.with_context(skip_analytic_sync=True).write(
                    {'analytic_line_id': line.id}
                )
                _logger.debug(
                    "Created analytic line %s for cost entry %s",
                    line.id, cost.name,
                )

    # ── One-time data repair ──────────────────────────────────────────────────

    @api.model
    def action_repair_invoice_analytic_duplicates(self):
        """
        Remove cost-analysis analytic lines that duplicate a posted invoice's
        analytic line (Guard 1 in _sync_analytic_line).

        Before the fix was in place, every farm.cost.analysis record with a
        linked posted vendor bill had TWO analytic lines in the project account:
          • one from _sync_analytic_line()  (no move_line_id)  ← ghost
          • one from the posted bill         (move_line_id set) ← authoritative

        This action finds and removes all remaining ghost lines.
        Safe to run multiple times — already-cleaned databases are unaffected.
        """
        to_clean = self.search([
            ('invoice_id.state', '=', 'posted'),
            ('analytic_line_id', '!=', False),
        ]).filtered(
            lambda c: (
                not c.analytic_line_id.move_line_id
                # Only remove when the bill actually has its own analytic line
                # for this project account; otherwise the cost-analysis line is
                # the only entry and must be kept.
                and c.invoice_id.line_ids.analytic_line_ids.filtered(
                    lambda l: l.account_id == c.project_id.analytic_account_id
                )
            )
        )

        count = len(to_clean)
        for cost in to_clean:
            cost.analytic_line_id.unlink()
            cost.with_context(skip_analytic_sync=True).write(
                {'analytic_line_id': False}
            )

        _logger.info(
            "Repair invoice analytic duplicates: removed %d ghost entries.", count
        )
        return {
            'type': 'ir.actions.client',
            'tag': 'display_notification',
            'params': {
                'title': _('Duplicates Removed'),
                'message': _(
                    '%(count)d ghost analytic entries removed. '
                    'Gross Margin now matches Actual Cost.',
                    count=count,
                ) if count else _('No duplicates found. Database is already clean.'),
                'type': 'success' if count else 'info',
                'sticky': False,
            },
        }

    # ── Journal entry generation ──────────────────────────────────────────────

    def _create_journal_entry(self):
        """
        Create or update a draft journal entry for standalone cost records.

        Skipped when invoice_id or payment_id is set — those documents carry
        their own GL entries and creating another would double-count the cost.

        Entry structure:
          Dr  general_account_id   cost_amount   (expense)
          Cr  credit_account_id    cost_amount   (payable / accrual)

        The analytic distribution is included on the debit line so the expense
        is also reflected in the analytic reporting layer.

        A previously posted entry is left unchanged; only draft entries are
        updated to reflect edits to the cost record.
        """
        for cost in self:
            if cost.invoice_id or cost.payment_id:
                continue
            if not cost.general_account_id or not cost.credit_account_id:
                continue
            if not cost.cost_amount:
                continue

            journal = self.env['account.journal'].search(
                [('type', '=', 'general'), ('company_id', '=', cost.company_id.id)],
                limit=1,
            )
            if not journal:
                _logger.warning(
                    "No general journal found for company %s — cannot generate journal entry for %s",
                    cost.company_id.name, cost.name,
                )
                continue

            analytic_distribution = {}
            if cost.project_id.analytic_account_id:
                analytic_distribution = {
                    str(cost.project_id.analytic_account_id.id): 100.0
                }

            line_vals = [
                Command.create({
                    'name': cost.cost_name,
                    'account_id': cost.general_account_id.id,
                    'debit': cost.cost_amount,
                    'credit': 0.0,
                    'partner_id': cost.partner_id.id if cost.partner_id else False,
                    'analytic_distribution': analytic_distribution or False,
                }),
                Command.create({
                    'name': cost.cost_name,
                    'account_id': cost.credit_account_id.id,
                    'debit': 0.0,
                    'credit': cost.cost_amount,
                    'partner_id': cost.partner_id.id if cost.partner_id else False,
                }),
            ]

            if cost.journal_entry_id:
                if cost.journal_entry_id.state == 'draft':
                    cost.journal_entry_id.write({
                        'date': cost.date,
                        'ref': cost.name,
                        'line_ids': [Command.clear()] + line_vals,
                    })
                # Posted entries are intentionally left untouched.
            else:
                move = self.env['account.move'].create({
                    'move_type': 'entry',
                    'journal_id': journal.id,
                    'date': cost.date,
                    'ref': cost.name,
                    'company_id': cost.company_id.id,
                    'line_ids': line_vals,
                })
                cost.with_context(skip_analytic_sync=True).write(
                    {'journal_entry_id': move.id}
                )
                _logger.debug(
                    "Created journal entry %s for cost entry %s",
                    move.name, cost.name,
                )

    def action_post_journal_entry(self):
        """Create (if missing) and post the draft journal entry."""
        self._create_journal_entry()
        for cost in self:
            if cost.journal_entry_id and cost.journal_entry_id.state == 'draft':
                cost.journal_entry_id.action_post()

    # ── CRUD overrides ────────────────────────────────────────────────────────

    @api.model_create_multi
    def create(self, vals_list):
        """Generate reference number, sync analytic line, and draft journal entry."""
        for vals in vals_list:
            if vals.get('name', _('New')) == _('New'):
                vals['name'] = (
                    self.env['ir.sequence'].next_by_code('farm.cost.analysis') or _('New')
                )
        records = super().create(vals_list)
        records._sync_analytic_line()
        records._create_journal_entry()
        return records

    def write(self, vals):
        """Update analytic line and journal entry when cost-affecting fields change."""
        result = super().write(vals)
        if not self.env.context.get('skip_analytic_sync'):
            analytic_triggers = {
                'cost_amount', 'date', 'cost_name', 'cost_type',
                'quantity', 'uom_id', 'product_id', 'general_account_id',
                'partner_id', 'invoice_id', 'payment_id',
            }
            je_triggers = {
                'cost_amount', 'date', 'cost_name', 'general_account_id',
                'credit_account_id', 'partner_id', 'invoice_id', 'payment_id',
            }
            changed = set(vals)
            if analytic_triggers & changed:
                self._sync_analytic_line()
            if je_triggers & changed:
                self._create_journal_entry()
        return result

    def unlink(self):
        """Remove linked analytic line and draft journal entry before deleting."""
        analytic_lines = self.mapped('analytic_line_id').filtered(bool)
        draft_entries = self.mapped('journal_entry_id').filtered(
            lambda m: m.state == 'draft'
        )
        result = super().unlink()
        if analytic_lines:
            analytic_lines.unlink()
        if draft_entries:
            draft_entries.unlink()
        return result

    # ── Computed fields ───────────────────────────────────────────────────────

    def name_get(self):
        """Returns the display name of the record with translations applied at runtime"""
        result = []
        for record in self:
            cost_type_label = record.get_cost_type_label() if record.cost_type else ''
            name = f"{record.name} - {cost_type_label}"
            result.append((record.id, name))
        return result

    @api.depends('cost_amount', 'quantity')
    def _compute_unit_cost(self):
        """Calculate unit cost based on quantity"""
        for cost in self:
            cost.cost_unit_amount = cost.quantity and cost.cost_amount / cost.quantity or 0.0

    @api.depends('cost_amount', 'field_area')
    def _compute_cost_per_area(self):
        """Calculate cost per area unit"""
        for cost in self:
            cost.cost_per_area = cost.field_area and cost.cost_amount / cost.field_area or 0.0

    @api.depends('cost_amount', 'is_budgeted', 'project_id.budget')
    def _compute_budget_variance(self):
        """Calculate budget variance percentage"""
        for cost in self:
            if cost.is_budgeted and cost.project_id.budget:
                cost.budget_variance = (cost.cost_amount / cost.project_id.budget) * 100
            else:
                cost.budget_variance = 0.0

    @api.constrains('date', 'project_id')
    def _check_date(self):
        """Ensure cost date is within project dates"""
        for record in self:
            if record.date and record.project_id:
                if record.date < record.project_id.start_date:
                    raise ValidationError(_(
                        "Cost date cannot be before the project start date."
                    ))
                if (record.project_id.actual_end_date and
                        record.date > record.project_id.actual_end_date):
                    raise ValidationError(_(
                        "Cost date cannot be after the project end date."
                    ))

    # ── Label helpers (runtime translation for AR/EN) ─────────────────────────

    def get_cost_type_label(self):
        """Get translated label for cost type at runtime"""
        cost_type_labels = {
            'seeds':          _('Seeds/Seedlings'),
            'fertilizer':     _('Fertilizers'),
            'pesticide':      _('Pesticides'),
            'herbicide':      _('Herbicides'),
            'water':          _('Irrigation Water'),
            'labor':          _('Labor/Workforce'),
            'machinery':      _('Machinery/Equipment'),
            'rent':           _('Land Rent'),
            'fuel':           _('Fuel'),
            'maintenance':    _('Maintenance'),
            'services':       _('Services'),
            'transportation': _('Transportation'),
            'storage':        _('Storage'),
            'certification':  _('Certification'),
            'testing':        _('Laboratory Testing'),
            'other':          _('Other'),
        }
        return cost_type_labels.get(self.cost_type, self.cost_type)

    def get_source_type_label(self):
        """Get translated label for source type at runtime"""
        source_type_labels = {
            'daily_report': _('Daily Report'),
            'bom':          _('Bill of Materials'),
            'manual':       _('Manual Entry'),
        }
        return source_type_labels.get(self.source_type, self.source_type)

    def get_cost_effectiveness_label(self):
        """Get translated label for cost effectiveness at runtime"""
        cost_effectiveness_labels = {
            'excellent': _('Excellent'),
            'good':      _('Good'),
            'average':   _('Average'),
            'poor':      _('Poor'),
        }
        return cost_effectiveness_labels.get(self.cost_effectiveness, self.cost_effectiveness)
