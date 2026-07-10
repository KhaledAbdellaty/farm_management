from odoo import fields, models, api, _
from odoo.exceptions import ValidationError


class Farm(models.Model):
    _name = 'farm.farm'
    _description = 'Farm'
    _inherit = ['mail.thread', 'mail.activity.mixin']
    _order = 'name'
    _check_company_auto = True

    @api.model
    def _get_area_unit_selection(self):
        """Return selection values for area units with translation support at runtime"""
        return [
            ('feddan', 'Feddan'),
            ('acre', 'Acre'),
            ('sqm', 'Square Meter'),
        ]

    name = fields.Char(string='Farm Name', required=True, tracking=True, translate=True)
    code = fields.Char(string='Farm Code', required=True, tracking=True, readonly=True, default=lambda self: 'New')
    active = fields.Boolean(default=True, tracking=True)
    
    location = fields.Char(string='Location', translate=True, tracking=True)
    area = fields.Float(string='Total Area (Feddan)', tracking=True)
    area_unit = fields.Selection(
        selection=_get_area_unit_selection,
        string='Area Unit', 
        default='feddan', 
        required=True, 
        tracking=True
    )
    
    owner_id = fields.Many2one('res.partner', string='Owner', tracking=True)
    manager_id = fields.Many2one('res.users', string='Farm Manager', tracking=True)
    
    company_id = fields.Many2one('res.company', string='Company', 
                                 default=lambda self: self.env.company)
    currency_id = fields.Many2one('res.currency', related='company_id.currency_id')
    # Stock location for inventory operations
    location_id = fields.Many2one('stock.location', string='Stock Location',
                               check_company=True,
                               help="Location where farm supplies and products are stored")
    property_value = fields.Monetary(string='Property Value', currency_field='currency_id', tracking=True)
    
    field_ids = fields.One2many('farm.field', 'farm_id', string='Fields')
    field_count = fields.Integer(compute='_compute_field_count', string='Field Count')
    
    cultivation_project_ids = fields.One2many('farm.cultivation.project', 'farm_id', 
                                             string='Cultivation Projects')
    project_count = fields.Integer(compute='_compute_project_count', 
                                  string='Cultivation Project Count')
    
    notes = fields.Html('Notes', translate=True)
    
    # Image field for farm photos/maps
    image = fields.Binary("Farm Image", attachment=True)
    
    
    # Analytic account for cost tracking
    analytic_account_id = fields.Many2one('account.analytic.account', 
                                          string='Analytic Account',
                                          tracking=True)
    
    _sql_constraints = [
        ('code_unique', 'UNIQUE(code)', 'Farm code must be unique!'),
    ]
    
    @api.model_create_multi
    def create(self, vals_list):
        """Generate sequence code, create an analytic account for each farm if none is
        provided, then bootstrap the farm's stock locations."""
        for vals in vals_list:
            if vals.get('code', 'New') == 'New':
                vals['code'] = self.env['ir.sequence'].next_by_code('farm.farm') or 'New'
            if not vals.get('analytic_account_id'):
                # Get the default analytic plan (required in Odoo 18)
                default_plan = self.env['account.analytic.plan'].search([], limit=1)
                if not default_plan:
                    # Create a default plan if none exists
                    default_plan = self.env['account.analytic.plan'].create({
                        'name': _('Farm Management'),
                        'default_applicability': 'optional'
                    })
                
                analytic_account = self.env['account.analytic.account'].create({
                    'name': vals.get('name', 'New Farm'),
                    'code': vals.get('code', ''),
                    'company_id': vals.get('company_id', self.env.company.id),
                    'plan_id': default_plan.id,  # Required field in Odoo 18
                })
                vals['analytic_account_id'] = analytic_account.id
                
        records = super().create(vals_list)
        
        # Create stock locations for farms that don't have one
        for record in records:
            if not record.location_id:
                # Create internal location for farm supplies
                parent_location = self.env.ref('stock.stock_location_locations', raise_if_not_found=False)
                if not parent_location:
                    parent_location = self.env['stock.location'].search([('usage', '=', 'view')], limit=1)
                
                if parent_location:
                    # Create the farm's internal location for inventory
                    # This is the reference location for the farm
                    location = self.env['stock.location'].create({
                        'name': f"Farm: {record.name}",
                        'usage': 'internal',
                        'location_id': parent_location.id,
                        'company_id': record.company_id.id,
                    })
                    record.location_id = location.id
                    
                    # Also create a farm destination location in the same hierarchy for consumption
                    farm_dest_location = self.env['stock.location'].search([
                        ('name', '=', f"Farm: {record.name}"),
                        ('location_id', '=', parent_location.id),
                        ('usage', '=', 'production'),
                        ('company_id', '=', record.company_id.id)
                    ], limit=1)
                    
                    if not farm_dest_location:
                        # Create a production location under the same parent
                        self.env['stock.location'].create({
                            'name': f"Farm: {record.name}",
                            'usage': 'production',  # Better for farm operations than 'customer'
                            'location_id': parent_location.id,
                            'company_id': record.company_id.id,
                        })
        
        return records
    
    def _compute_field_count(self):
        """Compute the number of fields in the farm"""
        for farm in self:
            farm.field_count = len(farm.field_ids)
    
    def _compute_project_count(self):
        """Compute the number of cultivation projects in the farm"""
        for farm in self:
            farm.project_count = len(farm.cultivation_project_ids)
    
    def action_view_fields(self):
        """Smart button action to view fields"""
        self.ensure_one()
        return {
            'name': _('Fields'),
            'view_mode': 'list,form',
            'res_model': 'farm.field',
            'domain': [('farm_id', '=', self.id)],
            'type': 'ir.actions.act_window',
            'context': {'default_farm_id': self.id}
        }
    
    def action_view_projects(self):
        """Smart button action to view cultivation projects"""
        self.ensure_one()
        return {
            'name': _('Cultivation Projects'),
            'view_mode': 'list,form',
            'res_model': 'farm.cultivation.project',
            'domain': [('farm_id', '=', self.id)],
            'type': 'ir.actions.act_window',
            'context': {'default_farm_id': self.id}
        }
    
    @api.constrains('area')
    def _check_area(self):
        """Ensure area is positive"""
        for record in self:
            if record.area <= 0:
                raise ValidationError(_("Farm area must be greater than zero."))
    
    def get_area_unit_label(self, area_unit=None):
        """Get the translated label for an area unit at runtime"""
        if area_unit is None:
            area_unit = self.area_unit
            
        selection_dict = dict(self._fields['area_unit'].selection)
        unit_label = selection_dict.get(area_unit, '')
        return _(unit_label) if unit_label else ''
    
    def get_area_unit_selection(self):
        """Get the translated selection values for area units at runtime"""
        selection_dict = dict(self._fields['area_unit'].selection)
        return [(code, _(label)) for code, label in selection_dict.items()]
    
    @api.model
    def get_error_message(self, constraint):
        """Return translated error message for constraints"""
        messages = {
            'code_unique': _('Farm code must be unique!'),
        }
        return messages.get(constraint, '')
