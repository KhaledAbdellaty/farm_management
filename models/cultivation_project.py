from odoo import fields, models, api, _
from odoo.exceptions import ValidationError
from odoo.osv import expression
from datetime import timedelta
import logging

_logger = logging.getLogger(__name__)


class CultivationProject(models.Model):
    _name = 'farm.cultivation.project'
    _description = 'Cultivation Project'
    _inherit = ['mail.thread', 'mail.activity.mixin']
    _order = 'start_date desc, name'

    # Link to project.project instead of inheriting from it
    project_id = fields.Many2one('project.project', string='Related Project', tracking=True)

    name = fields.Char(string='Project Name', required=True, tracking=True, translate=True)
    code = fields.Char(string='Project Code', required=True, tracking=True, readonly=True, default=lambda self: _('New'))
    active = fields.Boolean(default=True, tracking=True)

    # Project timeframe
    start_date = fields.Date(string='Start Date', required=True, tracking=True)
    planned_end_date = fields.Date(string='Planned End Date', required=True, tracking=True)
    actual_end_date = fields.Date(string='Actual End Date', tracking=True)

    # Farm and field information
    farm_id = fields.Many2one('farm.farm', string='Farm', required=True,
                            tracking=True, ondelete='restrict')
    field_id = fields.Many2one('farm.field', string='Field', required=True,
                             tracking=True, ondelete='restrict',
                             domain="[('farm_id', '=', farm_id), "
                                   "('state', 'in', ['available', 'fallow'])]")
    field_area = fields.Float(related='field_id.area', string='Field Area',
                            readonly=True, store=True)
    field_area_unit = fields.Selection(related='field_id.area_unit',
                                    string='Area Unit', readonly=True, store=True)

    # Crop information
    crop_id = fields.Many2one('farm.crop', string='Crop', required=True,
                            tracking=True, ondelete='restrict')

    # BOM for crop inputs
    crop_bom_id = fields.Many2one('farm.crop.bom', string='Crop BOM', tracking=True,
                                domain="[('crop_id', '=', crop_id)]")

    # Project stages
    state = fields.Selection([
        ('draft', 'Planning'),
        ('preparation', 'Field Preparation'),
        ('sowing', 'Planting/Sowing'),
        ('growing', 'Growing'),
        ('maintenance', 'Maintenance'),
        ('harvest', 'Harvest'),
        ('sales', 'Sales'),
        ('done', 'Done'),
        ('cancel', 'Cancelled'),
    ], string='Stage', default='draft', required=True, tracking=True)

    color = fields.Integer(compute='_compute_color', store=True)

    @api.depends('state')
    def _compute_color(self):
        _COLOR = {
            'draft':       0,
            'preparation': 7,
            'sowing':      4,
            'growing':     10,
            'maintenance': 6,
            'harvest':     3,
            'sales':       8,
            'done':        5,
            'cancel':      1,
        }
        for rec in self:
            rec.color = _COLOR.get(rec.state, 0)

    # ── Harvest batches ────────────────────────────────────────────────────────
    harvest_batch_ids = fields.One2many(
        'farm.harvest.batch', 'project_id', string='Harvest Batches'
    )
    harvest_batch_count = fields.Integer(
        compute='_compute_harvest_batch_count', string='Harvest Batches'
    )

    # Yield UoM — still a project-level setting, inherited by each batch
    yield_uom_id = fields.Many2one('uom.uom', string='Yield UoM', tracking=True)

    # Harvest totals — computed from validated batches
    planned_yield = fields.Float('Planned Yield', tracking=True)
    actual_yield = fields.Float(
        'Actual Yield',
        compute='_compute_actual_yield', store=True,
        help="Sum of all validated harvest batch quantities."
    )
    harvest_price = fields.Monetary(
        'Harvest Price (Weighted Avg)',
        compute='_compute_harvest_price', store=True,
        currency_field='currency_id',
        help="Weighted average price across all validated harvest batches."
    )
    yield_quality = fields.Selection([
        ('excellent', 'Excellent'),
        ('good', 'Good'),
        ('average', 'Average'),
        ('poor', 'Poor'),
    ], string='Yield Quality', tracking=True)

    # ── Financial information ──────────────────────────────────────────────────
    budget = fields.Monetary('Budget', compute='_compute_bom_budget', store=True,
                         currency_field='currency_id', tracking=True, readonly=True,
                         help="Budget based on the total cost of the selected BOM")
    bom_total_cost = fields.Monetary(related='crop_bom_id.total_cost',
                                string='BOM Total Cost', readonly=True,
                                currency_field='currency_id',
                                help="Total cost from the selected BOM")
    actual_cost = fields.Monetary('Actual Cost', compute='_compute_actual_cost',
                               store=True, currency_field='currency_id')
    revenue = fields.Monetary('Revenue', compute='_compute_revenue', store=True,
                             currency_field='currency_id', tracking=True)
    profit = fields.Monetary('Profit', compute='_compute_profit', store=True,
                          currency_field='currency_id')
    currency_id = fields.Many2one('res.currency', related='company_id.currency_id')
    company_id = fields.Many2one('res.company', related='farm_id.company_id',
                                store=True)

    # Daily operations and reporting
    daily_report_ids = fields.One2many('farm.daily.report', 'project_id',
                                      string='Daily Reports')
    daily_report_count = fields.Integer(compute='_compute_daily_report_count',
                                     string='Daily Reports Count')

    # Cost analysis
    cost_line_ids = fields.One2many('farm.cost.analysis', 'project_id',
                                   string='Cost Lines')

    # Analytic account
    analytic_account_id = fields.Many2one('account.analytic.account',
                                        string='Analytic Account',
                                        tracking=True)

    # Related tasks (from project.project inheritance)
    task_count = fields.Integer(compute='_compute_task_count')

    # Sales information
    sale_order_ids = fields.One2many('sale.order', 'cultivation_project_id', string='Sales Orders')
    sale_order_count = fields.Integer(compute='_compute_sale_order_count', string='Sales Orders Count')

    # Irrigation statistics
    total_irrigation_hours = fields.Float(string='Total Irrigation Hours',
                                        compute='_compute_total_irrigation_hours',
                                        help='Total hours spent on irrigation for this project',
                                        store=True)

    notes = fields.Html('Notes', translate=True)


    _sql_constraints = [
        ('code_unique', 'UNIQUE(code)', 'Project code must be unique!'),
    ]

    @api.model_create_multi
    def create(self, vals_list):
        """Create analytic account and project record, update field status"""
        for vals in vals_list:
            project_name = vals.get('name', _('New Project'))
            if vals.get('code', 'New') == 'New':
                vals['code'] = self.env['ir.sequence'].next_by_code('farm.cultivation.project') or _('New')
            farm = vals.get('farm_id') and self.env['farm.farm'].browse(vals.get('farm_id'))
            company_id = farm and farm.company_id.id or self.env.company.id

            # Create a dedicated analytic account for the cultivation project
            if not vals.get('analytic_account_id'):
                farm_name = farm and farm.name or _('Unknown Farm')

                default_plan = self.env['account.analytic.plan'].search([], limit=1)
                if not default_plan:
                    default_plan = self.env['account.analytic.plan'].create({
                        'name': _('Farm Management'),
                        'default_applicability': 'optional'
                    })

                analytic_account = self.env['account.analytic.account'].create({
                    'name': f"{_('Farm Project')}: {farm_name} - {project_name}",
                    'code': vals.get('code', ''),
                    'company_id': company_id,
                    'partner_id': farm and farm.owner_id and farm.owner_id.id or False,
                    'plan_id': default_plan.id,
                })
                vals['analytic_account_id'] = analytic_account.id
                _logger.info(f"Created analytic account '{analytic_account.name}' for cultivation project")

            # Create project.project record
            if not vals.get('project_id'):
                project_values = {
                    'name': project_name,
                    'company_id': company_id,
                    'user_id': self.env.user.id,
                    'date_start': vals.get('start_date'),
                    'date': vals.get('planned_end_date'),
                    'allow_timesheets': True,
                    'account_id': vals.get('analytic_account_id'),
                }
                _logger.info(f"Creating project with values: {project_values}")
                project = self.env['project.project'].create(project_values)
                vals['project_id'] = project.id
                _logger.info(f"Linked analytic account to project {project.name}")

            # Update field status
            if vals.get('field_id'):
                field = self.env['farm.field'].browse(vals['field_id'])
                field.write({'state': 'preparation'})

        return super().create(vals_list)

    def write(self, vals):
        """Update field status based on project state and sync with project.project"""
        # Update related project.project when relevant fields change
        for project in self:
            project_vals = {}

            if 'name' in vals:
                project_vals['name'] = vals['name']
                if project.analytic_account_id:
                    farm_name = project.farm_id.name
                    farm_project_label = _('Farm Project')
                    project.analytic_account_id.write({
                        'name': f"{farm_project_label}: {farm_name} - {vals['name']}"
                    })

            if 'analytic_account_id' in vals and project.project_id:
                project_vals['account_id'] = vals['analytic_account_id']

            if 'start_date' in vals:
                project_vals['date_start'] = vals['start_date']
            if 'planned_end_date' in vals:
                project_vals['date'] = vals['planned_end_date']

            if project_vals and project.project_id:
                project.project_id.write(project_vals)

        result = super().write(vals)

        if 'state' in vals:
            for project in self:
                if vals['state'] == 'sowing':
                    project.field_id.write({
                        'state': 'cultivated',
                        'current_crop_id': project.crop_id.id,
                    })
                elif vals['state'] == 'harvest':
                    project.field_id.write({'state': 'harvested'})
                elif vals['state'] == 'sales':
                    # Update product price when moving to sales; stock is managed by batches
                    project._update_product_price()
                elif vals['state'] == 'done':
                    project.field_id.write({
                        'state': 'fallow',
                        'current_crop_id': False,
                    })
                    project._update_product_price()
                elif vals['state'] == 'cancel' and project.field_id.state != 'available':
                    project.field_id.write({
                        'state': 'available',
                        'current_crop_id': False,
                    })
        return result


    @api.onchange('crop_id')
    def _onchange_crop_id(self):
        """When crop changes, suggest appropriate BOM and update yield UoM"""
        self.crop_bom_id = False
        if self.crop_id:
            default_bom = self.env['farm.crop.bom'].search([
                ('crop_id', '=', self.crop_id.id),
                ('is_default', '=', True)
            ], limit=1)
            if default_bom:
                self.crop_bom_id = default_bom.id

            if self.crop_id.product_id and self.crop_id.product_id.uom_id:
                self.yield_uom_id = self.crop_id.product_id.uom_id

    @api.onchange('start_date', 'crop_id')
    def _onchange_dates(self):
        """Calculate end date based on crop growing cycle"""
        if self.start_date and self.crop_id and self.crop_id.growing_cycle:
            self.planned_end_date = self.start_date + timedelta(days=self.crop_id.growing_cycle)

    @api.onchange('farm_id')
    def _onchange_farm_id(self):
        """Clear field_id when farm changes to ensure proper domain filtering"""
        self.field_id = False

    @api.onchange('crop_bom_id')
    def _onchange_crop_bom_id(self):
        """Update budget based on the BOM total cost when BOM is selected/changed"""
        if self.crop_bom_id:
            self.budget = self.crop_bom_id.total_cost
        else:
            self.budget = 0.0

    # ── Harvest batch computed totals ──────────────────────────────────────────

    @api.depends('harvest_batch_ids.quantity', 'harvest_batch_ids.state')
    def _compute_actual_yield(self):
        """Sum quantities of all validated harvest batches."""
        for project in self:
            validated = project.harvest_batch_ids.filtered(lambda b: b.state == 'validated')
            project.actual_yield = sum(validated.mapped('quantity'))

    @api.depends('harvest_batch_ids.quantity', 'harvest_batch_ids.price_unit', 'harvest_batch_ids.state')
    def _compute_harvest_price(self):
        """Weighted average price across all validated harvest batches."""
        for project in self:
            validated = project.harvest_batch_ids.filtered(lambda b: b.state == 'validated')
            total_qty = sum(validated.mapped('quantity'))
            if total_qty:
                weighted_sum = sum(b.quantity * b.price_unit for b in validated)
                project.harvest_price = weighted_sum / total_qty
            else:
                project.harvest_price = 0.0

    def _compute_harvest_batch_count(self):
        for project in self:
            project.harvest_batch_count = len(project.harvest_batch_ids)

    # ── Financial computes ─────────────────────────────────────────────────────

    @api.depends('cost_line_ids.cost_amount', 'daily_report_ids.actual_cost')
    def _compute_actual_cost(self):
        """Compute actual costs from cost analysis lines and daily reports"""
        for project in self:
            cost_line_total = sum(project.cost_line_ids.mapped('cost_amount'))

            daily_report_total = 0
            for report in project.daily_report_ids.filtered(lambda r: r.state == 'done'):
                existing_cost_line = project.cost_line_ids.filtered(lambda l:
                    l.source_type == 'daily_report' and l.source_id == report.id)
                if not existing_cost_line:
                    daily_report_total += report.actual_cost

            project.actual_cost = cost_line_total + daily_report_total

    @api.depends('actual_cost', 'revenue')
    def _compute_profit(self):
        """Compute profit as revenue minus actual cost"""
        for project in self:
            project.profit = project.revenue - project.actual_cost

    def _compute_daily_report_count(self):
        for project in self:
            project.daily_report_count = len(project.daily_report_ids)

    def _compute_task_count(self):
        for record in self:
            if record.project_id:
                record.task_count = self.env['project.task'].search_count([
                    ('project_id', '=', record.project_id.id)
                ])
            else:
                record.task_count = 0

    def _compute_sale_order_count(self):
        for project in self:
            project.sale_order_count = len(project.sale_order_ids)

    @api.depends('sale_order_ids.state', 'sale_order_ids.amount_total')
    def _compute_revenue(self):
        """Compute revenue from confirmed/done sales orders"""
        for project in self:
            valid_states = ['sale', 'done']
            valid_orders = project.sale_order_ids.filtered(lambda o: o.state in valid_states)
            project.revenue = sum(valid_orders.mapped('amount_total'))

    @api.depends('crop_bom_id', 'crop_bom_id.total_cost')
    def _compute_bom_budget(self):
        """Compute budget based on the selected BOM's total cost"""
        for project in self:
            if project.crop_bom_id:
                project.budget = project.crop_bom_id.total_cost
            elif not project.budget:
                project.budget = 0.0

    # ── Smart-button actions ───────────────────────────────────────────────────

    def action_view_daily_reports(self):
        self.ensure_one()
        return {
            'name': _('Daily Reports'),
            'view_mode': 'list,form',
            'res_model': 'farm.daily.report',
            'domain': [('project_id', '=', self.id)],
            'type': 'ir.actions.act_window',
            'context': {'default_project_id': self.id}
        }

    def action_view_tasks(self):
        self.ensure_one()
        return {
            'name': _('Tasks'),
            'view_mode': 'list,form',
            'res_model': 'project.task',
            'domain': [('project_id', '=', self.project_id.id)],
            'type': 'ir.actions.act_window',
            'context': {'default_project_id': self.project_id.id}
        }

    def action_view_sale_orders(self):
        self.ensure_one()
        return {
            'name': _('Sales Orders'),
            'view_mode': 'list,form',
            'res_model': 'sale.order',
            'domain': [('cultivation_project_id', '=', self.id)],
            'type': 'ir.actions.act_window',
            'context': {
                'default_cultivation_project_id': self.id,
                'default_partner_id': self.farm_id.owner_id.id if self.farm_id.owner_id else False,
                'default_product_id': self.crop_id.product_id.id if self.crop_id.product_id else False,
            }
        }

    def action_view_harvest_batches(self):
        """Smart button — open harvest batches list for this project."""
        self.ensure_one()
        return {
            'name': _('Harvest Batches'),
            'view_mode': 'list,form',
            'res_model': 'farm.harvest.batch',
            'domain': [('project_id', '=', self.id)],
            'type': 'ir.actions.act_window',
            'context': {
                'default_project_id': self.id,
                'default_uom_id': self.yield_uom_id.id if self.yield_uom_id else False,
            },
        }

    # ── State transition actions ───────────────────────────────────────────────

    def action_draft(self):
        return self.write({'state': 'draft'})

    def action_preparation(self):
        return self.write({'state': 'preparation'})

    def action_sowing(self):
        return self.write({'state': 'sowing'})

    def action_growing(self):
        return self.write({'state': 'growing'})

    def action_harvest(self):
        """Set to harvest state and pre-fill yield UoM from the crop product."""
        for project in self:
            if project.crop_id and project.crop_id.product_id:
                product = project.crop_id.product_id
                if not project.yield_uom_id and product.uom_id:
                    project.yield_uom_id = product.uom_id
            return project.write({'state': 'harvest'})

    def action_sales(self):
        """
        Move project to Sales state.
        Requires at least one validated harvest batch — stock has already been
        received per batch.  No new stock picking is created here.
        """
        for project in self:
            validated_batches = project.harvest_batch_ids.filtered(
                lambda b: b.state == 'validated'
            )
            if not validated_batches:
                raise ValidationError(_(
                    "Please create and validate at least one harvest batch before "
                    "moving to the Sales stage. Use the Harvest Batches tab to record "
                    "each harvest event and validate its stock receipt."
                ))

            if not project.yield_uom_id:
                raise ValidationError(_(
                    "Please set the Yield Unit of Measure on the project before proceeding."
                ))

            project.write({'state': 'sales'})
            project._update_product_price()

        return True

    def action_done(self):
        return self.write({
            'state': 'done',
            'actual_end_date': fields.Date.today()
        })

    def action_cancel(self):
        return self.write({'state': 'cancel'})

    # ── Sales order creation ───────────────────────────────────────────────────

    def action_create_sale_order(self):
        """Create a sales order for the harvest using computed totals."""
        self.ensure_one()

        if not self.crop_id or not self.crop_id.product_id:
            raise ValidationError(_(
                "Please specify a crop with an associated product before creating a sales order."
            ))

        if not self.yield_uom_id:
            raise ValidationError(_(
                "Please set the Yield Unit of Measure before creating a sales order."
            ))

        validated_batches = self.harvest_batch_ids.filtered(lambda b: b.state == 'validated')
        if not validated_batches:
            raise ValidationError(_(
                "No validated harvest batches found. Please validate at least one harvest batch "
                "receipt before creating a sales order."
            ))

        if self.actual_yield <= 0:
            raise ValidationError(_("Total validated yield is zero. Nothing to sell."))

        if self.harvest_price <= 0:
            raise ValidationError(_("Weighted average harvest price is zero. Check your batch prices."))

        partner_id = self.farm_id.owner_id.id if self.farm_id.owner_id else self.env.company.partner_id.id
        self._update_product_price()

        sale_order = self.env['sale.order'].create({
            'partner_id': partner_id,
            'cultivation_project_id': self.id,
            'date_order': fields.Datetime.now(),
            'company_id': self.company_id.id,
            'origin': f"Project {self.code} - {self.name}",
            'client_order_ref': f"Harvest {self.code}",
        })

        product = self.crop_id.product_id
        self.env['sale.order.line'].create({
            'order_id': sale_order.id,
            'product_id': product.id,
            'name': f"{product.name} - {self.name}",
            'product_uom_qty': self.actual_yield,
            'product_uom': self.yield_uom_id.id,
            'price_unit': self.harvest_price,
        })

        if self.state == 'harvest':
            self.write({'state': 'sales'})

        return {
            'name': _('Sales Order'),
            'view_mode': 'form',
            'res_model': 'sale.order',
            'res_id': sale_order.id,
            'type': 'ir.actions.act_window',
        }

    # ── Constraints ────────────────────────────────────────────────────────────

    @api.constrains('start_date', 'planned_end_date')
    def _check_dates(self):
        for record in self:
            if record.planned_end_date and record.start_date and \
                    record.planned_end_date < record.start_date:
                raise ValidationError(_("End date must be after start date."))

    @api.model
    def _expand_states(self, states, domain, order=None, context=None):
        """Required method for kanban grouping by state."""
        return [state[0] for state in self._fields['state'].selection]

    # ── Product price update ───────────────────────────────────────────────────

    def _update_product_price(self):
        """Update product's list price and optionally standard price from harvest data."""
        for project in self:
            if not (project.actual_yield > 0 and
                    project.harvest_price > 0 and
                    project.crop_id and
                    project.crop_id.product_id):
                continue

            product = project.crop_id.product_id
            product.list_price = project.harvest_price

            if project.actual_cost > 0:
                unit_cost = project.actual_cost / project.actual_yield
                if product.cost_method == 'standard':
                    product.standard_price = unit_cost

            _logger.info(
                f"Updated product {product.name}: "
                f"list_price={product.list_price}, standard_price={product.standard_price}"
            )

    # ── Misc computes ──────────────────────────────────────────────────────────

    @api.depends('daily_report_ids.irrigation_duration', 'daily_report_ids.state')
    def _compute_total_irrigation_hours(self):
        """Calculate the total irrigation hours from confirmed and done daily reports"""
        for project in self:
            reports = self.env['farm.daily.report'].search([
                ('project_id', '=', project.id),
                ('operation_type', '=', 'irrigation'),
                ('state', 'in', ['confirmed', 'done']),
            ])
            project.total_irrigation_hours = sum(
                report.irrigation_duration for report in reports
            ) if reports else 0.0

    # ── Translation helpers ────────────────────────────────────────────────────

    def _get_translated_selection_values(self, field_name):
        return dict(self._fields[field_name].selection)

    def _get_translated_state_name(self, state_code):
        states = self._get_translated_selection_values('state')
        return _(states.get(state_code, ''))

    def _get_translated_yield_quality(self, quality_code):
        qualities = self._get_translated_selection_values('yield_quality')
        return _(qualities.get(quality_code, ''))
