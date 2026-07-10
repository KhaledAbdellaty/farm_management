from odoo import fields, models, api, _
from odoo.exceptions import ValidationError

# Note: We're now re-enabling mail.thread but with special handling to avoid PostgreSQL 
# jsonb_path_query_first compatibility issues. We implement _get_thread_with_access ourselves.


class CropBOM(models.Model):
    _name = 'farm.crop.bom'
    _description = 'Crop Bill of Materials'
    _inherit = ['mail.thread', 'mail.activity.mixin']
    _order = 'name'
    
    name = fields.Char(string='BOM Name', required=True, tracking=True, translate=False)
    code = fields.Char(string='BOM Code', required=True, tracking=True, readonly=True, default=lambda self: 'New')
    active = fields.Boolean(default=True, tracking=True)
    
    crop_id = fields.Many2one('farm.crop', string='Crop', required=True, 
                            ondelete='cascade', tracking=True)
    is_default = fields.Boolean(string='Default BOM', help="Set as default BOM for this crop", tracking=True)
    
    area = fields.Float(string='Reference Area', default=1.0, required=True,
                     help="Reference area for input calculations (e.g., 1 feddan)", tracking=True)
    area_unit = fields.Selection([
        ('feddan', 'Feddan'),
        ('acre', 'Acre'),
        ('sqm', 'Square Meter'),
    ], string='Area Unit', default='feddan', required=True, tracking=True)
    
    notes = fields.Html(string='Notes', translate=False)  # Disable translation to avoid PostgreSQL issues
    
    # Input lines
    line_ids = fields.One2many('farm.crop.bom.line', 'bom_id', string='Input Lines', copy=True)
    
    # Costing
    currency_id = fields.Many2one('res.currency', string='Currency', 
                                default=lambda self: self.env.company.currency_id)
    total_cost = fields.Monetary('Total Cost', compute='_compute_total_cost', 
                              store=True, currency_field='currency_id')
    company_id = fields.Many2one('res.company', string='Company', 
                                default=lambda self: self.env.company)
    
    # Special handling for thread access
    def _get_thread_with_access(self, thread_id, **kwargs):
        """Implement _get_thread_with_access to support mail thread API
        without disabling tracking."""
        return self.browse(int(thread_id))
        
    def get_translated_field_labels(self):
        """Return field labels properly translated at runtime"""
        return {
            'bom_name': _('BOM Name'),
            'bom_code': _('BOM Code'),
            'crop': _('Crop'),
            'default_bom': _('Default BOM'),
            'reference_area': _('Reference Area'),
            'area_unit': _('Area Unit'),
            'notes': _('Notes'),
            'input_lines': _('Input Lines'),
            'total_cost': _('Total Cost')
        }
        
    def get_translated_area_units(self):
        """Return area units properly translated at runtime"""
        return [
            ('feddan', _('Feddan')),
            ('acre', _('Acre')),
            ('sqm', _('Square Meter'))
        ]
        
    def get_translated_help_texts(self):
        """Return help texts properly translated at runtime"""
        return {
            'is_default': _("Set as default BOM for this crop"),
            'area': _("Reference area for input calculations (e.g., 1 feddan)")
        }
        
    _sql_constraints = [
        ('code_unique', 'UNIQUE(code)', 'BOM code must be unique!')
    ]

    @api.model_create_multi
    def create(self, vals_list):
        """If new BOM is set as default, unset any existing default for the crop.
        Also generate sequence for code field."""
        # Generate sequence for records with 'New' code
        for vals in vals_list:
            if vals.get('code', 'New') == 'New':
                vals['code'] = self.env['ir.sequence'].next_by_code('farm.crop.bom') or 'New'
        
        # Create records with full tracking enabled but disable translation to avoid PostgreSQL issues
        self = self.with_context(lang=None)
        records = super(CropBOM, self).create(vals_list)
        
        for record in records:
            if record.is_default:
                self._unset_other_defaults(record)
        return records
    
    def write(self, vals):
        """If BOM is set as default, unset any existing default for the crop"""
        # Write with full tracking but disable translation to avoid PostgreSQL issues
        self = self.with_context(lang=None)
        res = super(CropBOM, self).write(vals)
        
        if vals.get('is_default') or vals.get('crop_id'):
            for record in self:
                if record.is_default:
                    self._unset_other_defaults(record)
        return res
    
    def _unset_other_defaults(self, record):
        """Unset default flag on other BOMs for the same crop"""
        other_defaults = self.search([
            ('crop_id', '=', record.crop_id.id),
            ('id', '!=', record.id),
            ('is_default', '=', True)
        ])
        if other_defaults:
            # Update with full tracking
            other_defaults.write({'is_default': False})

    @api.depends('line_ids.subtotal', 'area')
    def _compute_total_cost(self):
        """Compute total cost from BOM lines"""
        for bom in self:
            bom.total_cost = sum(bom.line_ids.mapped('subtotal')) * bom.area
    
    def action_apply_to_project(self):
        """Apply this BOM to a cultivation project"""
        self.ensure_one()
        
        # Create context with tracking enabled
        ctx = {
            'default_bom_id': self.id
        }
                  
        return {
            'name': 'Apply BOM to Project',
            'view_mode': 'form',
            'res_model': 'farm.bom.apply.wizard',
            'type': 'ir.actions.act_window',
            'target': 'new',
            'context': ctx
        }
    
    # Methods removed to simplify and avoid JSON issues


class CropBOMLine(models.Model):
    _name = 'farm.crop.bom.line'
    _description = 'Crop BOM Line'
    _order = 'sequence, id'
    _check_company_auto = True

    @api.model
    def _valid_field_parameter(self, field, name):
        """Allow 'tracking' parameter for fields in this model"""
        return name == 'tracking' or super()._valid_field_parameter(field, name)

    sequence = fields.Integer('Sequence', default=10)
    bom_id = fields.Many2one('farm.crop.bom', string='BOM', required=True,
                          ondelete='cascade')
    company_id = fields.Many2one('res.company', related='bom_id.company_id', store=True)

    # Replace static selection with product category
    input_type_category_id = fields.Many2one(
        'product.category', 
        string='Input Type',
        required=True,
        tracking=True,
        domain="[('parent_id.id', '=', parent_farm_category_id)]",
        help="Category of farm input (seeds, fertilizers, etc.)"
    )
    
    # Field to store the parent farm category ID for domain filtering
    parent_farm_category_id = fields.Many2one(
        'product.category',
        string='Farm Management Category',
        default=lambda self: self.env['product.category'].search([('name', '=', 'Farm Management')], limit=1),
        store=False
    )
    
    product_id = fields.Many2one(
        'product.product',
        string='Product',
        required=True,
        tracking=True,
        check_company=True,
        domain="[('categ_id', 'child_of', input_type_category_id)] if input_type_category_id else [('categ_id', 'child_of', parent_farm_category_id), ('categ_id.name', '!=', 'Agricultural')]",
    )
    name = fields.Char(related='product_id.name', string='Name', readonly=True, 
                      store=True, translate=False)
    
    quantity = fields.Float('Quantity', required=True, default=1.0, tracking=True)
    uom_id = fields.Many2one('uom.uom', string='Unit of Measure', 
                           related='product_id.uom_id', readonly=True)
    
    # When to apply this input (days from planting)
    apply_days = fields.Integer('Apply Days from Planting', default=0,
                              help="Number of days from planting when this input should be applied", tracking=True)
    
    # Cost calculation
    unit_cost = fields.Float('Unit Cost', related='product_id.standard_price', 
                           readonly=True)
    currency_id = fields.Many2one('res.currency', related='bom_id.currency_id')
    subtotal = fields.Monetary('Subtotal', compute='_compute_subtotal', 
                             store=True, currency_field='currency_id')
    
    # Available stock
    available_stock = fields.Float('Available Stock', compute='_compute_available_stock',
                                  help="Quantity available in stock for this product")
    product_availability = fields.Selection([
        ('available', 'Available'),
        ('warning', 'Partially Available'),
        ('unavailable', 'Not Available'),
    ], string='Product Availability', compute='_compute_available_stock',
        help="Product availability status based on stock levels")
    
    notes = fields.Text('Application Notes', translate=False)  # Disable translation to avoid PostgreSQL issues
    
    @api.depends('quantity', 'unit_cost')
    def _compute_subtotal(self):
        """Compute subtotal cost for this line"""
        for line in self:
            line.subtotal = line.quantity * line.unit_cost
    
    @api.depends('product_id', 'quantity')
    def _compute_available_stock(self):
        """Compute the quantity available in stock for this product and availability status"""
        # ponytail: cache per (crop_id, company_id) instead of re-searching per line -
        # neither search varies within a BOM's lines, only across BOMs.
        project_cache = {}
        warehouse_cache = {}

        for line in self:
            if not line.product_id or not line.bom_id.company_id:
                line.available_stock = 0.0
                line.product_availability = 'unavailable'
                continue

            # For service products, we always set them as available and skip stock computation
            if line.product_id.type == 'service':
                line.available_stock = 0.0
                line.product_availability = 'available'
                continue

            # Try to find farms that have cultivation projects for this crop
            farm_location_id = False

            crop_key = line.bom_id.crop_id.id
            if crop_key not in project_cache:
                project_cache[crop_key] = self.env['farm.cultivation.project'].search([
                    ('crop_id', '=', crop_key)
                ], limit=1)
            projects = project_cache[crop_key]

            if projects and projects.farm_id and projects.farm_id.location_id:
                farm_location_id = projects.farm_id.location_id.id

            # Initialized to 0 in case we can't find any stock
            product_qty = 0.0

            # If we found a specific farm location, check availability there
            if farm_location_id:
                product_qty = line.product_id.with_context(location=farm_location_id).qty_available

            if product_qty <= 0:
                # If no stock in farm location, check warehouse stock
                company_key = line.bom_id.company_id.id
                if company_key not in warehouse_cache:
                    warehouse_cache[company_key] = self.env['stock.warehouse'].search(
                        [('company_id', '=', company_key)], limit=1)
                warehouse = warehouse_cache[company_key]
                if warehouse and warehouse.lot_stock_id:
                    product_qty = line.product_id.with_context(
                        location=warehouse.lot_stock_id.id).qty_available

            if product_qty <= 0:
                # As a last resort, get overall company stock
                product_qty = line.product_id.with_company(line.bom_id.company_id).qty_available

            line.available_stock = product_qty

            # Set the availability status based on required vs available quantity
            if line.quantity <= 0:
                line.product_availability = 'available'
            elif product_qty <= 0:
                line.product_availability = 'unavailable'
            elif product_qty < line.quantity:
                line.product_availability = 'warning'  # Partially available
            else:
                line.product_availability = 'available'
    
    @api.model_create_multi
    def create(self, vals_list):
        """Create BOM line records with normal tracking but disable translation to avoid PostgreSQL issues"""
        # Use with_context(lang=None) to avoid PostgreSQL jsonb_path_query_first error
        self = self.with_context(lang=None)
        return super(CropBOMLine, self).create(vals_list)
        
    def write(self, vals):
        """Update BOM line records with normal tracking but disable translation to avoid PostgreSQL issues"""
        # Use with_context(lang=None) to avoid PostgreSQL jsonb_path_query_first error
        self = self.with_context(lang=None)
        return super(CropBOMLine, self).write(vals)
        
    def unlink(self):
        """Delete BOM line records with normal tracking"""
        return super(CropBOMLine, self).unlink()
    
    @api.onchange('input_type_category_id')
    def _onchange_input_type_category(self):
        """Clear product when input type category changes to enforce proper domain filtering"""
        self.product_id = False

    @api.onchange('product_id')
    def _onchange_product_id(self):
        """Update input type category if not set but product has category"""
        self.input_type_category_id = self.product_id.categ_id.id if self.product_id else False
