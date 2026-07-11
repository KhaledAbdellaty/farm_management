from odoo import fields, models, api, _
from odoo.exceptions import ValidationError
import logging

_logger = logging.getLogger(__name__)


class Crop(models.Model):
    _name = 'farm.crop'
    _description = 'Crop'
    _inherit = ['mail.thread', 'mail.activity.mixin']
    _order = 'name'
    _check_company_auto = True

    name = fields.Char(string='Crop Name', required=True, tracking=True, translate=True)
    code = fields.Char(string='Crop Code', required=True, tracking=True, readonly=True, default=lambda self: 'New')
    active = fields.Boolean(default=True, tracking=True)
    growing_cycle = fields.Integer(string='Growing Cycle (Days)', tracking=True, 
                                  help="Average number of days for the crop's growing cycle")
    
    # Units of Measure for the crop
    uom_id = fields.Many2one('uom.uom', string='Unit of Measure', 
                            required=True, tracking=True,
                            default=lambda self: self.env.ref('uom.product_uom_unit').id,
                            help="Default unit of measure for the crop product")
    

    # Product association
    product_id = fields.Many2one(
        'product.product',
        string='Product',
        required=False,  # Not required on input as we'll auto-create it
        tracking=True,
        readonly=False,  # Not readonly in the model, only in the view
        check_company=True,
        help="The product associated with this crop for inventory and sales - auto-created on save"
    )
    
    # Cultivation history
    project_ids = fields.One2many('farm.cultivation.project', 'crop_id', 
                                string='Cultivation Projects')
    project_count = fields.Integer(compute='_compute_project_count', 
                                 string='Project Count')
    
    # BOM for inputs needed for this crop
    bom_ids = fields.One2many('farm.crop.bom', 'crop_id', string='Input BOMs', copy=True)
    bom_count = fields.Integer(compute='_compute_bom_count', string='BOM Count')
    
    notes = fields.Html('Notes', translate=False)
    
    # Crop image
    image = fields.Binary("Crop Image", attachment=True)
    
    company_id = fields.Many2one('res.company', string='Company', 
                                default=lambda self: self.env.company)
    
    _sql_constraints = [
        ('code_unique', 'UNIQUE(code)', 'Crop code must be unique!'),
    ]
    
    def _compute_project_count(self):
        """Compute the number of cultivation projects for this crop"""
        for crop in self:
            crop.project_count = len(crop.project_ids)
    
    def _compute_bom_count(self):
        """Compute the number of BOMs for this crop"""
        for crop in self:
            crop.bom_count = len(crop.bom_ids)
    
    def action_view_projects(self):
        """Smart button action to view cultivation projects for this crop"""
        self.ensure_one()
        return {
            'name': _('Cultivation Projects'),
            'view_mode': 'list,form',
            'res_model': 'farm.cultivation.project',
            'domain': [('crop_id', '=', self.id)],
            'type': 'ir.actions.act_window',
            'context': {'default_crop_id': self.id}
        }
    
    def action_view_boms(self):
        """Smart button action to view BOMs for this crop"""
        self.ensure_one()
        return {
            'name': _('Crop BOMs'),
            'view_mode': 'list,form',
            'res_model': 'farm.crop.bom',
            'domain': [('crop_id', '=', self.id)],
            'type': 'ir.actions.act_window',
            'context': {'default_crop_id': self.id}
        }

    @api.onchange('product_id')
    def _onchange_product_id(self):
        """Update product type and settings when selected"""
        if self.product_id:
            # Make sure the product is properly configured for inventory
            if self.product_id.type != 'consu':
                self.product_id.type = 'consu'
                return {
                    'warning': {
                        'title': _('Product Type Updated'),
                        'message': _('The product type has been updated to "Goods" to ensure proper inventory management.')
                    }
                }
    
    def action_configure_routes(self):
        """Configure the sales routes for the product"""
        self.ensure_one()
        
        if not self.product_id:
            raise ValidationError(_("No product associated with this crop. Please select a product first."))
        
        # Get the warehouse
        warehouse = self.env['stock.warehouse'].search([
            ('company_id', '=', self.company_id.id)
        ], limit=1)
        
        if not warehouse:
            raise ValidationError(_("No warehouse found for this company."))
        
        # Configure product
        self.product_id.write({
            'type': 'consu',  # Goods (stockable product)
            'sale_ok': True,
            'route_ids': [(4, warehouse.route_ids.filtered(lambda r: r.name == 'Deliver from Stock').id)] if warehouse.route_ids else []
        })
        
        return {
            'type': 'ir.actions.client',
            'tag': 'display_notification',
            'params': {
                'title': _('Routes Configured'),
                'message': _('Product routes have been configured successfully.'),
                'type': 'success',
                'sticky': False,
            }
        }
    
    def get_translated_field_labels(self):
        """Return field labels properly translated at runtime"""
        return {
            'crop_name': _('Crop Name'),
            'crop_code': _('Crop Code'),
            'growing_cycle': _('Growing Cycle (Days)'),
            'unit_of_measure': _('Unit of Measure'),
            'product': _('Product')
        }
        
    def get_translated_help_texts(self):
        """Return help texts properly translated at runtime"""
        return {
            'growing_cycle': _("Average number of days for the crop's growing cycle"),
            'uom_id': _("Default unit of measure for the crop product"),
            'product_id': _("The product associated with this crop for inventory and sales - auto-created on save")
        }
        
    @api.model_create_multi
    def create(self, vals_list):
        """Create crop record and auto-create associated product"""
        for vals in vals_list:
            # Assign sequence for code if it's 'New'
            if vals.get('code', 'New') == 'New':
                vals['code'] = self.env['ir.sequence'].next_by_code('farm.crop') or 'New'
                
            # If no product_id is provided, create one automatically
            if not vals.get('product_id'):
                # Get the Agricultural category using robust, concise search-based fallback logic
                agricultural_category = self.env['product.category'].search([
                    ('name', '=', 'Agricultural'),
                    ('parent_id.name', '=', 'Farm Management')
                ], limit=1) or self.env['product.category'].search([
                    ('name', '=', 'Agricultural')
                ], limit=1)
                
                # If category doesn't exist, create the required hierarchy
                if not agricultural_category:
                    # Find or create Farm Management parent category
                    farm_management_category = self.env['product.category'].search([
                        ('name', '=', 'Farm Management')
                    ], limit=1)
                    
                    if not farm_management_category:
                        farm_management_category = self.env['product.category'].create({
                            'name': 'Farm Management',
                            'property_cost_method': 'average',
                            'property_valuation': 'manual_periodic',
                        })
                        _logger.info("Created Farm Management category with ID %s", farm_management_category.id)
                    
                    # Create Agricultural subcategory
                    agricultural_category = self.env['product.category'].create({
                        'name': 'Agricultural',
                        'parent_id': farm_management_category.id,
                        'property_cost_method': 'average',
                        'property_valuation': 'manual_periodic',
                    })
                    _logger.info("Created Agricultural category with ID %s under parent %s", 
                                agricultural_category.id, farm_management_category.id)
                
                # Ensure category was found or created successfully
                if not agricultural_category:
                    # This should never happen with our fallbacks, but just in case
                    _logger.error("Failed to find or create Agricultural product category")
                    raise ValidationError(_(
                        "Failed to find or create required product category 'Agricultural'. "
                        "Please contact your system administrator or create this category manually."
                    ))
                
                # Ensure proper valuation to avoid accounting errors
                if hasattr(agricultural_category, 'property_valuation') and agricultural_category.property_valuation == 'real_time':
                    agricultural_category.write({'property_valuation': 'manual_periodic'})
                    _logger.info("Updated category %s valuation to manual_periodic", agricultural_category.name)
                
                # Create stockable product with crop name
                crop_name = vals.get('name', 'New Crop')
                crop_code = vals.get('code', 'NEW')
                
                # Get UoM from vals or default to Units
                uom_id = vals.get('uom_id', False) or self.env.ref('uom.product_uom_unit').id
                
                product_vals = {
                    'name': crop_name,
                    'type': 'consu',  # Goods (stockable product)
                    'categ_id': agricultural_category.id,
                    'sale_ok': True,
                    'purchase_ok': False,
                    'is_storable': True,
                    'default_code': crop_code,
                    'company_id': vals.get('company_id', self.env.company.id),
                    'uom_id': uom_id,  # Set the selected UoM
                    'uom_po_id': uom_id,  # Set the same UoM for purchase
                }
                
                product = self.env['product.product'].create(product_vals)
                vals['product_id'] = product.id
                
                # Configure product routes
                warehouse = self.env['stock.warehouse'].search([
                    ('company_id', '=', vals.get('company_id', self.env.company.id))
                ], limit=1)
                
                if warehouse and warehouse.route_ids:
                    deliver_route = warehouse.route_ids.filtered(lambda r: r.name == 'Deliver from Stock')
                    if deliver_route:
                        product.write({'route_ids': [(4, deliver_route.id)]})
        
        # Call super to create the records
        return super().create(vals_list)
    
    def copy(self, default=None):
        """When duplicating a crop, create a new product for it"""
        default = default or {}
        default['product_id'] = False  # Force creation of a new product
        return super().copy(default)
    
    def write(self, vals):
        """Update associated product when crop name changes"""
        result = super().write(vals)
        
        # If name is updated, update product name too
        if 'name' in vals:
            for crop in self:
                if crop.product_id:
                    crop.product_id.write({'name': crop.name})
        
        # If UoM is updated, update product UoM too
        if 'uom_id' in vals:
            for crop in self:
                if crop.product_id:
                    crop.product_id.write({
                        'uom_id': crop.uom_id.id,
                        'uom_po_id': crop.uom_id.id
                    })
        
        return result

