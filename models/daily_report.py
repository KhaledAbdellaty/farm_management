from odoo import fields, models, api, _
from odoo.exceptions import ValidationError
from datetime import date
import logging

_logger = logging.getLogger(__name__)


class DailyReport(models.Model):
    _name = 'farm.daily.report'
    _description = 'Daily Farm Operation Report'
    _inherit = ['mail.thread', 'mail.activity.mixin']
    _order = 'date desc, id desc'
    _check_company_auto = True

    name = fields.Char(string='Reference', required=True, copy=False, readonly=True,
                     default=lambda self: 'New')
    date = fields.Date(string='Date', required=True, default=fields.Date.today, tracking=True)

    user_id = fields.Many2one('res.users', string='Reported By',
                            default=lambda self: self.env.user, tracking=True)

    # Project and location information
    # ponytail: no check_company here — this model's own company_id is
    # related='project_id.company_id' (derived FROM this field), so the same
    # circular-domain issue as farm.cultivation.project.farm_id applies:
    # zero projects would show on any new record for any company.
    project_id = fields.Many2one('farm.cultivation.project', string='Cultivation Project',
                              required=True, tracking=True, ondelete='cascade')
    farm_id = fields.Many2one('farm.farm', related='project_id.farm_id', 
                           string='Farm', store=True, readonly=True)
    field_id = fields.Many2one('farm.field', related='project_id.field_id', 
                            string='Field', store=True, readonly=True)
    crop_id = fields.Many2one('farm.crop', related='project_id.crop_id', 
                           string='Crop', store=True, readonly=True)
    
    # Default vendor for non-PO product lines — carried to analytic entries
    # for vendor traceability. PO-backed lines already know their vendor.
    partner_id = fields.Many2one(
        'res.partner',
        string='Default Vendor',
        domain="[('supplier_rank', '>', 0)]",
        tracking=True,
        help='Vendor for non-PO operations on this report. '
             'Passed to analytic entries so costs are traceable by supplier.',
    )

    # Operation details
    operation_type = fields.Selection([
        ('preparation', 'Field Preparation'),
        ('planting', 'Planting/Sowing'),
        ('fertilizer', 'Fertilizer Application'),
        ('pesticide', 'Pesticide Application'),
        ('irrigation', 'Irrigation'),
        ('weeding', 'Weeding'),
        ('harvesting', 'Harvesting'),
        ('maintenance', 'Maintenance'),
        ('inspection', 'Inspection'),
        ('other', 'Other'),
    ], string='Operation Type', required=True, tracking=True)
    
    # Irrigation-specific fields
    irrigation_duration = fields.Float(string='Irrigation Duration (hours)', tracking=True, required=True,
                                     help='Duration of irrigation in hours',
                                     digits=(10, 2))
    
    # Progress tracking
    stage = fields.Selection(related='project_id.state', string='Project Stage', 
                          readonly=True, store=True)
    
    # Report status
    state = fields.Selection([
        ('draft', 'Draft'),
        ('confirmed', 'Confirmed'),
        ('done', 'Done'),
    ], string='Status', default='draft', tracking=True)
    
    # Weather information
    temperature = fields.Float('Temperature (C)', tracking=True)
    humidity = fields.Float('Humidity (%)', tracking=True)
    rainfall = fields.Float('Rainfall (mm)', tracking=True)
    
    # Products used - split into two separate One2many fields
    product_lines = fields.One2many('farm.daily.report.line', 'report_id',
                                  string='All Products Used')
    labor_machinery_lines = fields.One2many('farm.daily.report.line', 'report_id',
                                  string='Labor and Machinery',
                                  domain=[('line_type', '=', 'labor_machinery')],
                                  context={'default_line_type': 'labor_machinery'})
    other_product_lines = fields.One2many('farm.daily.report.line', 'report_id',
                                  string='Other Products',
                                  domain=[('line_type', '=', 'other')],
                                  context={'default_line_type': 'other'})
    
    # Cost tracking
    cost_amount = fields.Monetary('Estimated Cost', currency_field='currency_id', tracking=True, store=True)
    actual_cost = fields.Monetary(string='Actual Cost', compute='_compute_actual_cost',
                                store=True, currency_field='currency_id')
    
    # Inventory tracking
    stock_move_ids = fields.One2many('stock.move', 'daily_report_id', string='Stock Moves')
    stock_picking_id = fields.Many2one('stock.picking', string='Inventory Operation',
                                     check_company=True)
    
    # Analytic accounting
    analytic_line_ids = fields.One2many('account.analytic.line', 'daily_report_id', 
                                      string='Analytic Lines')
    currency_id = fields.Many2one('res.currency', related='company_id.currency_id', 
                               readonly=True)
    company_id = fields.Many2one('res.company', related='project_id.company_id', 
                              readonly=True, store=True)
    
    # Observations and issues
    observation = fields.Text('Observations', translate=True, tracking=True)
    issues = fields.Text('Issues Encountered', translate=True, tracking=True)
    
    # Crop condition
    crop_condition = fields.Selection([
        ('excellent', 'Excellent'),
        ('good', 'Good'),
        ('fair', 'Fair'),
        ('poor', 'Poor'),
        ('critical', 'Critical'),
    ], string='Crop Condition', tracking=True)
    
    notes = fields.Html('Notes', translate=True)
    
    # Images for documentation
    image_ids = fields.Many2many('ir.attachment', string='Images')
    
    # Vendor Bills Integration
    vendor_bill_ids = fields.One2many(
        'account.move', 
        'daily_report_id',
        string='Generated Vendor Bills',
        domain=[('move_type', '=', 'in_invoice')]
    )
    vendor_bill_count = fields.Integer(
        string='Vendor Bills Count',
        compute='_compute_vendor_bill_count'
    )
    total_bill_amount = fields.Monetary(
        string='Total Bill Amount',
        compute='_compute_vendor_bill_total',
        currency_field='currency_id'
    )
    
    @api.depends('vendor_bill_ids')
    def _compute_vendor_bill_count(self):
        """Compute the number of generated vendor bills"""
        for report in self:
            report.vendor_bill_count = len(report.vendor_bill_ids)
    
    @api.depends('vendor_bill_ids.amount_total')
    def _compute_vendor_bill_total(self):
        """Compute total amount of all generated bills"""
        for report in self:
            report.total_bill_amount = sum(report.vendor_bill_ids.mapped('amount_total'))

    @api.model_create_multi
    def create(self, vals_list):
        """Generate unique report reference number"""
        for vals in vals_list:
            if vals.get('name', 'New') == 'New':
                vals['name'] = self.env['ir.sequence'].next_by_code('farm.daily.report') or 'New'
        return super().create(vals_list)
    
    @api.onchange('project_id', 'operation_type')
    def _onchange_project_id(self):
        """Set default product based on project context"""
        if self.project_id and self.project_id.crop_bom_id and self.operation_type:
            # Try to find a matching product from BOM lines based on operation type
            # Map operation types to category XML IDs
            matching_operation_types = {
                'planting': 'product_category_seed',
                'fertilizer': 'product_category_fertilizer',
                'pesticide': 'product_category_pesticide',
                'weeding': 'product_category_herbicide',
                'irrigation': 'product_category_water',
            }
            operation_category_xml_id = matching_operation_types.get(self.operation_type)
            bom_line = None  # Initialize bom_line to avoid UnboundLocalError
            
            if operation_category_xml_id:
                # Get the category ID from its XML ID
                category = self.env.ref(f'farm_management.{operation_category_xml_id}', raise_if_not_found=False)
                if category:
                    # Search for BOM line with matching category
                    bom_line = self.env['farm.crop.bom.line'].search([
                        ('bom_id', '=', self.project_id.crop_bom_id.id),
                        ('input_type_category_id', '=', category.id)
                    ], limit=1)
                    
            if bom_line:
                    # Create a new product line with the found product
                    # Determine which field to use based on the product category
                    category_name = bom_line.product_id.categ_id.name
                    if category_name in ['Labor Services', 'Machinery']:
                        field_name = 'labor_machinery_lines'
                        line_type = 'labor_machinery'
                    else:
                        field_name = 'other_product_lines'
                        line_type = 'other'
                        
                    if not getattr(self, field_name):
                        line_vals = {
                            'product_id': bom_line.product_id.id,
                            'quantity': bom_line.quantity,
                            'line_type': line_type
                        }
                        self[field_name] = [(0, 0, line_vals)]
    
    @api.onchange('labor_machinery_lines', 'other_product_lines')
    def _onchange_product_lines(self):
        """Calculate cost based on product lines"""
        all_product_lines = self.labor_machinery_lines + self.other_product_lines
        if all_product_lines:
            self.cost_amount = sum(line.product_id.standard_price * line.quantity for line in all_product_lines)
    @api.onchange('operation_type')
    def _onchange_operation_type(self):
        """Auto-update project state based on operation type if needed"""
        if not self.project_id:
            return
        
        operation_state_map = {
            'preparation': 'preparation',
            'planting': 'sowing',
            'harvesting': 'harvest',
        }
        
        if self.operation_type in operation_state_map:
            if self.project_id.state != 'done' and self.project_id.state != 'cancel':
                suggested_state = operation_state_map[self.operation_type]
                if suggested_state != self.project_id.state:
                    return {
                        'warning': {
                            'title': _('Project Stage Update'),
                            'message': _('Do you want to update the project stage to %s?') % 
                                dict(self.project_id._fields['state'].selection).get(suggested_state)
                        }
                    }
    
    @api.constrains('date')
    def _check_date(self):
        """Ensure report date is within project dates"""
        for report in self:
            if report.date and report.project_id:
                if report.date < report.project_id.start_date:
                    error_msgs = report.get_translated_error_messages()
                    raise ValidationError(error_msgs['date_before_start'])
                if report.project_id.actual_end_date and report.date > report.project_id.actual_end_date:
                    error_msgs = report.get_translated_error_messages()
                    raise ValidationError(error_msgs['date_after_end'])

    @api.depends('labor_machinery_lines.actual_cost', 'other_product_lines.actual_cost')
    def _compute_actual_cost(self):
        """Compute total cost from product lines and labor/machinery"""
        for report in self:
            labor_machinery_cost = sum(line.actual_cost for line in report.labor_machinery_lines)
            other_product_cost = sum(line.actual_cost for line in report.other_product_lines)
            report.actual_cost = labor_machinery_cost + other_product_cost
            
    def action_confirm(self):
        """Confirm the daily report and create stock moves and vendor bills"""
        for report in self:
            _logger.info(f"DEBUG: Starting confirmation for report {report.name}")
            
            # Check if there's sufficient stock for stockable/consumable products only
            all_product_lines = report.labor_machinery_lines + report.other_product_lines
            stockable_lines = all_product_lines.filtered(
                lambda l: l.product_id and l.product_id.type in ['combo', 'consu']
            )
            
            if stockable_lines:
                unavailable_products = []
                
                # Check stock availability for stockable/consumable products
                for line in stockable_lines:
                    # Check if we have enough quantity available (available_stock is computed automatically)
                    if line.quantity > line.available_stock:
                        unavailable_products.append({
                            'name': line.product_id.name,
                            'requested': line.quantity,
                            'available': line.available_stock,
                            'uom': line.uom_id.name
                        })
                
                # If any products are unavailable, show a validation error
                if unavailable_products:
                    error_msgs = self.get_translated_error_messages()
                    error_message = error_msgs['insufficient_inventory']
                    for product in unavailable_products:
                        error_message += error_msgs['inventory_line_error'] % (
                            product['name'], product['requested'], product['uom'],
                            product['available'], product['uom']
                        )
                    raise ValidationError(error_message)
            
            # SECOND: Generate vendor bills for labor and machinery services
            generated_bills = []
            if report.labor_machinery_lines:
                # Check if any lines have PO data
                po_lines = report.labor_machinery_lines.filtered(lambda l: l.purchase_order_line_id)
                if po_lines:
                    generated_bills = report._generate_vendor_bills_for_services()
            
            # THIRD: Handle stock movements if needed
            stockable_lines = all_product_lines.filtered(
                lambda l: l.product_id.type in ['combo', 'consu'] and l.quantity > 0
            )
            
            if stockable_lines and not report.stock_picking_id:
                _logger.info(f"DEBUG: Creating stock movements for {len(stockable_lines)} stockable lines")
                report._create_stock_movements()
            
            # FOURTH: Force update PO fields and calculate costs directly
            for line in report.labor_machinery_lines + report.other_product_lines:
                if line.line_type == 'labor_machinery' and line.purchase_order_line_id:

                    # Direct calculation and update for labor/machinery lines
                    po_line = line.purchase_order_line_id
                    po_price = po_line.price_unit
                    vendor = po_line.order_id.partner_id
                    calculated_cost = po_price * line.quantity
                    
                    # Direct write of all PO-related fields
                    line.with_context(force_write=True).write({
                        'po_unit_price': po_price,
                        'vendor_id': vendor.id,
                        'purchase_order_id': po_line.order_id.id,
                        'actual_cost': calculated_cost
                    })
                                        
                    _logger.info(f"DEBUG: Updated line {line.id} - PO Price: {line.po_unit_price}, Cost: {line.actual_cost}")
                else:
                    # For other product lines, use standard computation
                    line.with_context(force_write=True)._compute_actual_cost()
            
            # Force refresh to show updated field values
            # report.invalidate_recordset()
            
            # Set state to confirmed for this report
            _logger.info(f"DEBUG: Setting state to confirmed for report {report.name}")
            report.with_context(force_write=True).write({'state': 'confirmed'})
            
            _logger.info(f"DEBUG: Confirmation completed for report {report.name}, final state: {report.state}")
        
        # Show notification if bills were generated
        total_bills = sum(len(generated_bills) for generated_bills in [generated_bills] if generated_bills)
        if total_bills > 0:
            message = _("%d vendor bill(s) generated successfully") % total_bills
            return {
                'type': 'ir.actions.client',
                'tag': 'display_notification',
                'params': {
                    'title': _('Daily Report Confirmed'),
                    'message': message,
                    'type': 'success',
                    'sticky': False,
                    'next': {'type': 'ir.actions.act_window_close'}
                }
            }
        
        # If no bills generated, just close/refresh
        return {'type': 'ir.actions.act_window_close'}
    
    def action_set_to_done(self):
        """Set report to done and update analytic accounting"""
        for report in self:
            # Create analytic entries if they don't exist yet
            if not report.analytic_line_ids:
                report._create_analytic_entries()
                
            # Update project actual cost
            report._update_project_cost()
            
            # Use force_write context to bypass field protection
            report.with_context(force_write=True).write({'state': 'done'})
        return True
    
    def action_reset_to_draft(self):
        """Reset to draft and delete any stock moves and analytic entries"""
        for report in self:
            # Only delete stock moves if they exist and are not done yet
            if report.stock_picking_id and report.stock_picking_id.state not in ['done', 'cancel']:
                report.stock_picking_id.action_cancel()
                report.stock_picking_id.unlink()
                
            # Delete analytic lines
            if report.analytic_line_ids:
                report.analytic_line_ids.unlink()
                
            # Use force_write context to bypass field protection
            report.with_context(force_write=True).write({'state': 'draft'})
        return True
    
    def _create_stock_movements(self):
        """Create delivery stock moves for the products used in the report using outgoing delivery orders"""
        for report in self:
            all_product_lines = report.labor_machinery_lines + report.other_product_lines
            if not all_product_lines:
                continue
                
            # Find the warehouse first
            warehouse = self.env['stock.warehouse'].search([('company_id', '=', report.company_id.id)], limit=1)
            if not warehouse:
                error_msgs = report.get_translated_error_messages()
                raise ValidationError(error_msgs['no_warehouse'])
            
            # Use warehouse stock location as source (just like in sales orders)
            source_location = warehouse.lot_stock_id
            if not source_location:
                source_location = self.env.ref('stock.stock_location_stock', raise_if_not_found=False)
                if not source_location:
                    source_location = self.env['stock.location'].search([
                        ('usage', '=', 'internal'),
                        ('company_id', '=', report.company_id.id),
                        ('name', 'ilike', 'Stock')
                    ], limit=1)
            
            if not source_location:
                error_msgs = report.get_translated_error_messages()
                raise ValidationError(error_msgs['no_stock_location'])
                
            # Still keep track of farm location for references, but don't use it as source
            farm_location = report.project_id.farm_id.location_id
            if not farm_location:
                # Auto-create a location for the farm if missing
                parent_location = self.env.ref('stock.stock_location_locations', raise_if_not_found=False)
                if not parent_location:
                    parent_location = self.env['stock.location'].search([('usage', '=', 'view')], limit=1)
                
                if not parent_location:
                    error_msgs = report.get_translated_error_messages()
                    raise ValidationError(error_msgs['no_parent_location'])
                    
                farm_location = self.env['stock.location'].create({
                    'name': report.project_id.farm_id.name,
                    'usage': 'internal',
                    'location_id': parent_location.id,
                    'company_id': report.project_id.farm_id.company_id.id,
                })
                # Update the farm record
                report.project_id.farm_id.location_id = farm_location.id
            
            # Create a clean hierarchical location structure: Farm → Field → Project
            # Get the Physical Locations parent
            physical_locations = self.env.ref('stock.stock_location_locations', raise_if_not_found=False)
            if not physical_locations:
                physical_locations = self.env['stock.location'].search([
                    ('name', '=', 'Physical Locations'),
                    ('usage', '=', 'view')
                ], limit=1)
                
            if not physical_locations:
                error_msgs = report.get_translated_error_messages()
                raise ValidationError(error_msgs['no_physical_locations'])
            
            # 1. Create or find farm-level location (directly under Physical Locations)
            farm_name = report.farm_id.name
            farm_dest_location = self.env['stock.location'].search([
                ('name', '=', f"Farm: {farm_name}"),
                ('location_id', '=', physical_locations.id),
                ('company_id', '=', report.company_id.id)
            ], limit=1)
            
            if not farm_dest_location:
                farm_dest_location = self.env['stock.location'].create({
                    'name': f"Farm: {farm_name}",
                    'usage': 'production',  # Using production type for farm operations
                    'location_id': physical_locations.id,
                    'company_id': report.company_id.id,
                })
            
            # 2. Create or find field-level location under farm
            field_name = report.field_id.name
            field_dest_location = self.env['stock.location'].search([
                ('name', '=', f"Field: {field_name}"),
                ('location_id', '=', farm_dest_location.id),
                ('company_id', '=', report.company_id.id)
            ], limit=1)
            
            if not field_dest_location:
                field_dest_location = self.env['stock.location'].create({
                    'name': f"Field: {field_name}",
                    'usage': 'production',  # Using production type for field operations
                    'location_id': farm_dest_location.id,
                    'company_id': report.company_id.id,
                })
            
            # 3. Create or find project-level location (the actual destination)
            project_name = report.project_id.name 
            crop_name = report.crop_id.name if report.crop_id else 'N/A'
            project_crop_name = f"Project: {project_name} - {crop_name}"
            dest_location = self.env['stock.location'].search([
                ('name', '=', project_crop_name),
                ('location_id', '=', field_dest_location.id),
                ('company_id', '=', report.company_id.id)
            ], limit=1)
            
            if not dest_location:
                dest_location = self.env['stock.location'].create({
                    'name': project_crop_name,
                    'usage': 'production',  # Using production type for project operations
                    'location_id': field_dest_location.id,
                    'company_id': report.company_id.id,
                })
            
            # Find the warehouse
            warehouse = self.env['stock.warehouse'].search([('company_id', '=', report.company_id.id)], limit=1)
            if not warehouse:
                error_msgs = report.get_translated_error_messages()
                raise ValidationError(error_msgs['no_warehouse'])
                
            # Use the outgoing/delivery picking type
            picking_type = warehouse.out_type_id
            
            if not picking_type:
                # Fall back to any outgoing picking type
                picking_type = self.env['stock.picking.type'].search([
                    ('code', '=', 'outgoing'),
                    ('warehouse_id', '=', warehouse.id)
                ], limit=1)
            
            if not picking_type:
                # Create a new outgoing picking type for farm operations
                # Use standard sequence format (WH/OUT/000) but with farm-specific default locations
                sequence = self.env['ir.sequence'].search([
                    ('code', '=', 'stock.picking.out'),
                    ('company_id', '=', report.company_id.id)
                ], limit=1)
                
                if not sequence:
                    sequence = self.env['ir.sequence'].create({
                        'name': 'Stock Outgoing',
                        'code': 'stock.picking.out',
                        'prefix': 'WH/OUT/',
                        'padding': 5,
                        'company_id': report.company_id.id,
                    })
                
                picking_type = self.env['stock.picking.type'].create({
                    'name': 'Farm Operations',
                    'code': 'outgoing',
                    'sequence_code': 'OUT',
                    'default_location_src_id': source_location.id,  # From warehouse stock
                    'default_location_dest_id': dest_location.id,   # To farm-specific location
                    'sequence_id': sequence.id,
                    'warehouse_id': warehouse.id,
                    'company_id': report.company_id.id,
                })
            
            # Create a delivery order (outgoing) for farm consumption
            operation_name = dict(report._fields['operation_type'].selection).get(report.operation_type, 'Consumption')
            
            # Get descriptive information for reference in the note
            field_name = report.field_id.name if report.field_id else "N/A"
            project_name = report.project_id.name or "N/A"
            crop_name = report.crop_id.name if report.crop_id else "N/A"
            
            # Create the picking - don't set 'name' to let Odoo use the sequence (WH/OUT/000...)
            picking_vals = {
                'location_id': source_location.id,  # Use warehouse stock location as source
                'location_dest_id': dest_location.id,
                'picking_type_id': picking_type.id,
                'scheduled_date': report.date,
                'origin': f'Report {report.name} - {operation_name}',
                'company_id': report.company_id.id,
                'move_type': 'direct',  # Direct transfer (as opposed to 'one' which is partial)
                'partner_id': False,  # No partner is fine for farm operations
                'note': f"Farm/{field_name}/{project_name} - {crop_name} - {operation_name}",
                # Don't set name - let Odoo use the standard sequence (WH/OUT/000)
            }
            
            picking = self.env['stock.picking'].create(picking_vals)
            report.stock_picking_id = picking.id
            
            # Log the inventory movement creation
            report.message_post(
                body=_("📦 Inventory Movement Created\n\n"
                      "Picking Reference: %s\n"
                      "Status: Draft - pending confirmation") % (picking.name,),
                message_type='notification'
            )
            _logger.info(f"Inventory movement created for report {report.name}: {picking.name}")
            
            # Create stock moves for the delivery order
            all_product_lines = report.labor_machinery_lines + report.other_product_lines
            # Filter product lines to only include stockable/consumable products with quantity > 0
            valid_lines = all_product_lines.filtered(
                lambda l: l.product_id.type == 'consu' and l.quantity > 0
            )
            
            # If no valid lines exist, don't create an empty picking
            if not valid_lines:
                # If a picking was already created but has no valid moves, unlink it
                if picking:
                    picking.unlink()
                    report.stock_picking_id = False
                    # Log that no inventory movement was needed
                    report.message_post(
                        body=_("No inventory movement required - report contains only service/labor items or zero quantities"),
                        message_type='notification'
                    )
                    _logger.info(f"No inventory movement created for report {report.name} - no stockable products")
                # Update report state with force_write context to bypass restrictions
                report.with_context(force_write=True).write({
                    'state': 'confirmed'
                })
                continue
                
            for line in valid_lines:
                    
                operation_name = dict(report._fields['operation_type'].selection).get(report.operation_type, 'Consumption')
                
                # Include field/project/crop in the move description
                field_name = report.field_id.name if report.field_id else "N/A"
                project_name = report.project_id.name or "N/A"
                crop_name = report.crop_id.name if report.crop_id else "N/A"
                
                move_vals = {
                    'name': f"{line.product_id.name}",
                    'product_id': line.product_id.id,
                    'product_uom_qty': line.quantity,
                    'product_uom': line.uom_id.id,
                    'picking_id': picking.id,
                    'location_id': source_location.id,  # Use warehouse stock location as source
                    'location_dest_id': dest_location.id,
                    'state': 'draft',
                    'company_id': report.company_id.id,
                    'daily_report_id': report.id,
                    'origin': f'Report {report.name}',
                    'description_picking': f"{line.product_id.name} - Farm/{field_name}/{project_name}",
                }
                
                self.env['stock.move'].create(move_vals)
                
            # Confirm the picking to make products show as "outgoing" in inventory
            # Only if we have valid moves
            if picking and picking.move_ids:
                # Just confirm the picking (will update outgoing quantities automatically)
                picking.action_confirm()
                
                # Try to reserve quantities
                picking.action_assign()
                
                # Log the status but don't auto-validate - this will be done manually
                if all(move.state == 'assigned' for move in picking.move_ids):
                    _logger.info(f"Picking {picking.name} is ready for manual validation")
                    # Log the detailed status in the report
                    product_list = ", ".join([f"{move.product_id.name} ({move.product_uom_qty} {move.product_uom.name})" 
                                            for move in picking.move_ids])
                    report.message_post(
                        body=_("🚚 Inventory Movement Created Successfully!\n\n"
                              "Picking Reference: %s\n"
                              "Products: %s\n"
                              "Status: All products reserved and ready for manual validation\n\n"
                              "The inventory movement is now ready for processing.") % 
                              (picking.name, product_list),
                        message_type='notification'
                    )
                else:
                    _logger.info(f"Picking {picking.name} is partially ready for manual validation")
                    # Log partial availability status
                    available_moves = [move for move in picking.move_ids if move.state == 'assigned']
                    pending_moves = [move for move in picking.move_ids if move.state != 'assigned']
                    
                    available_list = ", ".join([f"{move.product_id.name} ({move.product_uom_qty} {move.product_uom.name})" 
                                              for move in available_moves]) if available_moves else "None"
                    pending_list = ", ".join([f"{move.product_id.name} ({move.product_uom_qty} {move.product_uom.name})" 
                                            for move in pending_moves]) if pending_moves else "None"
                    
                    report.message_post(
                        body=_("⚠️ Inventory Movement Created with Partial Availability\n\n"
                              "Picking Reference: %s\n"
                              "Available Products: %s\n"
                              "Pending Products: %s\n\n"
                              "Action Required: Check stock availability before validation.\n"
                              "Some products may need restocking.") % 
                              (picking.name, available_list, pending_list),
                        message_type='notification'
                    )
                    
                # Create move lines to make validation easier later
                for move in picking.move_ids:
                    if not move.move_line_ids:
                        # Create move lines manually with basic values
                        move_line_vals = {
                            'move_id': move.id,
                            'product_id': move.product_id.id,
                            'product_uom_id': move.product_uom.id,
                            'location_id': move.location_id.id,
                            'location_dest_id': move.location_dest_id.id,
                            'picking_id': move.picking_id.id,
                            'company_id': move.company_id.id,
                            'quantity': move.product_uom_qty,
                        }
                        self.env['stock.move.line'].create(move_line_vals)
                        
                    # Set quantities on move lines
                    for line in move.move_line_ids:
                        if line.quantity <= 0:
                            line.quantity = move.product_uom_qty
                            
                # Update report state with force_write context to bypass restrictions
                report.with_context(force_write=True).write({
                    'state': 'confirmed'
                })
    
    def _create_analytic_entries(self):
        """Create analytic entries for costs related to the daily report"""
        for report in self:
            # Get the analytic account from the cultivation project's analytic_account_id field
            # not from project.project which doesn't have this field in Odoo v18
            if not report.project_id or not report.project_id.analytic_account_id:
                continue
                
            analytic_account = report.project_id.analytic_account_id
            
            # Create analytic line for each type of cost
            
            # 1. Product costs
            all_product_lines = report.labor_machinery_lines + report.other_product_lines
            for line in all_product_lines:
                # Skip PO-backed labor/machinery lines — these already have
                # analytic_distribution set on the vendor bill line created by
                # _generate_vendor_bills_for_services(). Odoo will create the
                # analytic entry automatically when the accountant posts the bill.
                # Creating a direct analytic entry here would double-count the cost.
                if line.line_type == 'labor_machinery' and line.purchase_order_line_id:
                    _logger.info(
                        "Skipping analytic entry for '%s' — cost will be posted via vendor bill",
                        line.product_id.name,
                    )
                    continue

                # Recompute so the SVL-based cost is current before reading it.
                line.with_context(force_write=True)._compute_actual_cost()

                analytic_amount = -line.actual_cost

                if not analytic_amount:
                    _logger.warning(
                        "Skipping analytic entry for '%s' — cost is zero after recompute",
                        line.product_id.name,
                    )
                    continue
                
                # Create the analytic entry
                operation_type_name = dict(report._fields['operation_type'].selection).get(report.operation_type, 'Operation')
                entry_vals = {
                    'name': f"{operation_type_name}: {line.product_id.name} - {report.name}",
                    'date': report.date,
                    'account_id': analytic_account.id,
                    'amount': analytic_amount,  # Negative amount for costs
                    'unit_amount': line.quantity,
                    'product_id': line.product_id.id,
                    'product_uom_id': line.uom_id.id,
                    'daily_report_id': report.id,
                    'category': 'vendor_bill',
                    'ref': report.name,
                    # user_id omitted here — set below paired with employee_id.
                    # Writing user_id alone triggers hr_timesheet to recompute
                    # employee_id; if no employee is found it becomes False and
                    # Odoo clears project_id to satisfy the SQL constraint,
                    # causing all Gross Margin rows to group under "None".
                }

                # GL account — prefer product category expense account
                if line.product_id.categ_id and line.product_id.categ_id.property_account_expense_categ_id:
                    entry_vals['general_account_id'] = line.product_id.categ_id.property_account_expense_categ_id.id

                # Partner — use report-level default vendor for non-PO lines
                if report.partner_id:
                    entry_vals['partner_id'] = report.partner_id.id
                
                # Log the values for debugging
                _logger.info(f"Creating analytic entry with amount: {entry_vals['amount']}, product: {line.product_id.name}")

                # Create WITHOUT project_id to bypass hr_timesheet.create()
                # ValidationError ("Timesheets must be created with an active
                # employee"). hr_timesheet.write() has no such restriction, so
                # project_id is patched immediately after via write().
                analytic_line = self.env['account.analytic.line'].create(entry_vals)
                if report.project_id.project_id:
                    analytic_line.write({'project_id': report.project_id.project_id.id})
                    # hr_timesheet._timesheet_preprocess_get_accounts() injects
                    # account_id into the write vals, which triggers
                    # _timesheet_postprocess() to recompute amount as
                    # standard_price × unit_amount.  For AVCO/FIFO products
                    # standard_price is often 0, zeroing out the stock-valuation
                    # cost we calculated above.  Restore the correct amount.
                    analytic_line.with_context(check_move_validity=False).write(
                        {'amount': analytic_amount}
                    )


            # Labor and machinery costs are now tracked through product lines
            
    def _update_project_cost(self):
        """Update project's actual cost with costs from this report"""
        for report in self:
            if report.state == 'done' and report.actual_cost > 0:
                # Trigger recomputation of project costs
                report.project_id._compute_actual_cost()

    def get_translated_error_messages(self):
        """Helper method to provide translated error messages.
        
        Returns:
            dict: A dictionary of translated error messages
        """
        return {
            'date_before_start': _("Report date cannot be before project start date."),
            'date_after_end': _("Report date cannot be after project end date."),
            'insufficient_inventory': _("Insufficient inventory for the following products:\n"),
            'inventory_line_error': _("- %s: Requested %s %s but only %s %s available.\n"),
            'no_warehouse': _("No warehouse found for this company."),
            'no_stock_location': _("No stock location found for this company."),
            'no_physical_locations': _("No physical locations found for this company."),
            'no_parent_location': _("No parent location found to create farm location."),
            'no_stockable_products': _("No stockable products with quantities found. Skipping inventory operation creation.")
        }

    def action_view_vendor_bills(self):
        """Smart button action to view generated vendor bills"""
        self.ensure_one()
        action = self.env.ref('account.action_move_in_invoice_type').read()[0]
        
        if len(self.vendor_bill_ids) > 1:
            action['domain'] = [('id', 'in', self.vendor_bill_ids.ids)]
        elif len(self.vendor_bill_ids) == 1:
            action['views'] = [(self.env.ref('account.view_move_form').id, 'form')]
            action['res_id'] = self.vendor_bill_ids.id
        else:
            action = {'type': 'ir.actions.act_window_close'}
        
        action['context'] = {
            'default_move_type': 'in_invoice',
            'default_daily_report_id': self.id,
        }
        return action

    def _generate_vendor_bills_for_services(self):
        """Generate vendor bills for labor and machinery services (PO-based only)"""
        from collections import defaultdict
        
        _logger.info(f"DEBUG: Starting bill generation for report {self.name}")
        
        # Get labor/machinery lines - ALL must have PO lines
        service_lines = self.labor_machinery_lines.filtered(
            lambda l: l.line_type == 'labor_machinery' and l.purchase_order_line_id
        )
        
        _logger.info(f"DEBUG: Found {len(service_lines)} service lines for bill generation")
        _logger.info(f"DEBUG: Total labor_machinery_lines: {len(self.labor_machinery_lines)}")
        
        # Debug each line
        for line in self.labor_machinery_lines:
            _logger.info(f"DEBUG: Line - Product: {line.product_id.name if line.product_id else 'None'}, "
                        f"PO Line: {line.purchase_order_line_id.id if line.purchase_order_line_id else 'None'}, "
                        f"Line Type: {line.line_type}")
        
        if not service_lines:
            _logger.warning("DEBUG: No service lines with PO found for bill generation")
            return []
        
        # Group by vendor and PO (get vendor from PO, not from line)
        vendor_po_groups = defaultdict(list)
        for line in service_lines:
            # Get vendor from Purchase Order, not from line.vendor_id
            po_vendor_id = line.purchase_order_line_id.order_id.partner_id.id
            po_id = line.purchase_order_line_id.order_id.id
            key = (po_vendor_id, po_id)
            vendor_po_groups[key].append(line)
        
        generated_bills = []
        
        # Create one bill per vendor per PO
        for (vendor_id, po_id), lines in vendor_po_groups.items():
            try:
                _logger.info(f"DEBUG: Creating bill for vendor {vendor_id}, PO {po_id} with {len(lines)} lines")
                bill = self._create_vendor_bill_for_services(vendor_id, po_id, lines)
                generated_bills.append(bill)
                
                _logger.info(f"DEBUG: Bill created successfully: {bill.name} (ID: {bill.id})")
                
                # Post message to daily report
                self.message_post(
                    body=_("Vendor bill %s created for %s (Amount: %s)") % (
                        bill.name,
                        bill.partner_id.name,
                        bill.amount_total
                    ),
                    message_type='notification'
                )
                
            except Exception as e:
                _logger.error(f"Failed to create vendor bill for vendor {vendor_id}, PO {po_id}: {str(e)}")
                import traceback
                _logger.error(f"Full traceback: {traceback.format_exc()}")
                continue
        
        return generated_bills

    def _create_vendor_bill_for_services(self, vendor_id, po_id, service_lines):
        """Create vendor bill using data exclusively from Purchase Orders"""
        vendor = self.env['res.partner'].browse(vendor_id)
        purchase_order = self.env['purchase.order'].browse(po_id)
        
        # Prepare invoice line values using ONLY PO data
        invoice_line_vals = []
        for line in service_lines:
            # Use product from PO line (guaranteed to exist)
            product_id = line.purchase_order_line_id.product_id
            _logger.info(f"DEBUG: Using product from PO line: {product_id.name}")
            
            # Get proper expense account
            account_id = (
                product_id.property_account_expense_id.id or
                product_id.categ_id.property_account_expense_categ_id.id or
                self.env['ir.property']._get('property_account_expense_categ_id', 'product.category').id
            )
            
            # Prepare analytic distribution (Odoo 18 format)
            analytic_distribution = {}
            if self.project_id.analytic_account_id:
                analytic_distribution[str(self.project_id.analytic_account_id.id)] = 100.0
                _logger.info(f"DEBUG: Setting analytic account: {self.project_id.analytic_account_id.name}")
            
            # Use ONLY PO price - no fallbacks
            price_unit = line.purchase_order_line_id.price_unit
            _logger.info(f"DEBUG: Using PO price: {price_unit}")
            
            line_vals = {
                'product_id': product_id.id,
                'name': f"{product_id.name} - {self.name}",
                'quantity': line.quantity,
                'price_unit': price_unit,
                'product_uom_id': product_id.uom_id.id,
                'account_id': account_id,
                'analytic_distribution': analytic_distribution,
                # ponytail: shared (company_id=False) products can carry
                # supplier taxes from more than one company at once; only
                # the bill's own company's taxes are valid here, otherwise
                # check_company fails later (e.g. on reset to draft).
                'tax_ids': [(6, 0, product_id.supplier_taxes_id.filtered(
                    lambda t: not t.company_id or t.company_id == self.company_id
                ).ids)],
                'purchase_line_id': line.purchase_order_line_id.id,  # Link to PO line
            }
            
            invoice_line_vals.append((0, 0, line_vals))
        
        # Create vendor bill following Odoo standards
        bill_vals = {
            'move_type': 'in_invoice',  # Vendor bill
            'partner_id': vendor_id,
            'invoice_date': self.date,
            'date': self.date,
            'ref': f"Farm Services - {self.name} - {purchase_order.name}",
            'invoice_origin': f"{self.name}, {purchase_order.name}",
            'currency_id': purchase_order.currency_id.id,
            'company_id': self.company_id.id,
            'invoice_line_ids': invoice_line_vals,
            'purchase_id': po_id,  # Link to purchase order
            'daily_report_id': self.id,  # Link back to daily report
        }
        
        # Create the vendor bill with explicit partner assignment
        vendor_bill = self.env['account.move'].with_context(
            default_move_type='in_invoice',
            default_partner_id=vendor_id
        ).create(bill_vals)
        
        # Double-check that the partner is correctly set
        if not vendor_bill.partner_id:
            _logger.error(f"ERROR: Partner not set on vendor bill! Setting manually...")
            vendor_bill.partner_id = vendor_id
        
        # Ensure proper sequence number is assigned
        if vendor_bill.name in ['/', False]:
            vendor_bill._compute_name()
        
        _logger.info(f"DEBUG: Created bill {vendor_bill.name} with partner {vendor_bill.partner_id.name}")
        _logger.info(f"Created vendor bill {vendor_bill.name} for {vendor.name} from daily report {self.name}")

        return vendor_bill


class StockMove(models.Model):
    _inherit = 'stock.move'
    
    # Add link to daily report
    daily_report_id = fields.Many2one('farm.daily.report', string='Daily Report',
                                    index=True, ondelete='set null')
    
    def write(self, vals):
        """Override write to update daily report state when stock moves are validated"""
        result = super(StockMove, self).write(vals)
        
        # If state changed to 'done', update associated daily report
        if 'state' in vals and vals['state'] == 'done':
            # Get all unique daily reports from these moves
            report_ids = self.mapped('daily_report_id')
            
            if report_ids:
                # Log the state change for debugging
                _logger.info(f"Stock moves validated for daily reports: {report_ids.mapped('name')}")
                
                # In Odoo 18, make sure move line quantities are confirmed properly
                for move in self:
                    if move.state == 'done':
                        # Log accounting information for debugging
                        _logger.info(f"Validated move {move.id} for product {move.product_id.name}, "
                                    f"quantity: {move.product_uom_qty}")
                        
                        # If this is a valued move, log additional details
                        try:
                            if hasattr(move, 'account_move_ids'):
                                account_moves = move.account_move_ids
                                if account_moves:
                                    _logger.info(f"Move {move.id} has accounting entries: "
                                                f"{account_moves.mapped('name')}")
                                    for amove in account_moves:
                                        if hasattr(amove, 'line_ids'):
                                            for line in amove.line_ids:
                                                _logger.info(f"Account move line: {line.name}, "
                                                            f"account: {line.account_id.name}, "
                                                            f"balance: {line.balance}")
                        except Exception as e:
                            _logger.error(f"Error accessing accounting data: {str(e)}")
                
                # Process each related daily report
                for report in report_ids.filtered(lambda r: r.state == 'confirmed'):
                    # If all stock moves for this report are done, set report to done
                    related_moves = self.env['stock.move'].search([
                        ('daily_report_id', '=', report.id)
                    ])
                    
                    done_moves = related_moves.filtered(lambda m: m.state == 'done')
                    
                    # If all required moves are done
                    if all(move.state == 'done' for move in related_moves if move.product_id.type == 'consu'):
                        _logger.info(f"Setting daily report {report.name} to 'done' due to stock move validation")
                        report.with_context(force_write=True).write({'state': 'done'})
                        
                        # Force recompute of product line costs based on validated stock moves before creating analytic entries
                        all_product_lines = report.labor_machinery_lines + report.other_product_lines
                        for line in all_product_lines:
                            validated_moves = done_moves.filtered(lambda m: m.product_id.id == line.product_id.id)
                            if validated_moves:
                                _logger.info(f"Product {line.product_id.name} has {len(validated_moves)} validated moves")
                        
                        # Create analytic entries with updated costs
                        if not report.analytic_line_ids:
                            report._create_analytic_entries()
        
        return result


class DailyReportLine(models.Model):
    _name = 'farm.daily.report.line'
    _description = 'Daily Report Product Line'
    
    # Link to parent report
    report_id = fields.Many2one('farm.daily.report', string='Daily Report', required=True, ondelete='cascade')
    
    # Product information - enhanced for labor/machinery
    product_id = fields.Many2one('product.product', string='Product')
    quantity = fields.Float(string='Quantity', default=1.0, required=True)
    uom_id = fields.Many2one('uom.uom', string='Unit of Measure',
                           compute='_compute_uom_id', store=True, readonly=False)
    
    # NEW: Purchase Order integration for labor/machinery
    purchase_order_id = fields.Many2one(
        'purchase.order',
        string='Purchase Order',
        help='Select purchase order for labor/machinery services'
    )
    purchase_order_line_id = fields.Many2one(
        'purchase.order.line',
        string='Purchase Order Line',
        compute='_compute_po_line_from_po',
        store=True,
        help='Purchase order line computed from selected PO and product'
    )
    vendor_id = fields.Many2one(
        'res.partner',
        string='Vendor',
        compute='_compute_po_fields',
        store=True,
        readonly=True,
        help='Vendor from Purchase Order'
    )
    po_unit_price = fields.Monetary(
        string='PO Unit Price',
        compute='_compute_po_fields',
        store=True,
        readonly=True,
        currency_field='currency_id'
    )
    
    # Line type to distinguish labor/machinery from other products
    line_type = fields.Selection([
        ('labor_machinery', 'Labor & Machinery'),
        ('other', 'Other Products')
    ], string='Line Type', required=True, default='other')

    # UI helper field
    po_fields_visible = fields.Boolean(
        string='PO Fields Visible',
        compute='_compute_po_fields_visible'
    )
    
    # Cost calculation
    actual_cost = fields.Monetary(string='Cost', currency_field='currency_id',
                                compute='_compute_actual_cost', store=True)
    currency_id = fields.Many2one('res.currency', related='report_id.currency_id', readonly=True)
    
    # Inventory tracking
    available_stock = fields.Float(string='Available Stock', compute='_compute_available_stock')
    product_availability = fields.Selection([
        ('available', 'Available'),
        ('low_stock', 'Low Stock'),
        ('no_stock', 'Out of Stock'),
        ('not_tracked', 'Not Tracked')
    ], string='Availability', compute='_compute_available_stock')

    # Forecast tracking
    forecasted_issue = fields.Boolean(string='Forecasted Issue', 
                                    compute='_compute_forecasted_issue', store=True)

    @api.depends('product_id', 'purchase_order_line_id', 'line_type')
    def _compute_uom_id(self):
        """Compute UOM based on line type and product/PO selection"""
        for line in self:
            if line.line_type == 'labor_machinery':
                # For labor/machinery, use PO line UOM if available
                if line.purchase_order_line_id:
                    line.uom_id = line.purchase_order_line_id.product_uom
                elif line.product_id and line.product_id.uom_id:
                    line.uom_id = line.product_id.uom_id
                else:
                    line.uom_id = False
            else:
                # For other lines, use product UOM
                if line.product_id and line.product_id.uom_id:
                    line.uom_id = line.product_id.uom_id
                else:
                    line.uom_id = False

    @api.depends('line_type')
    def _compute_po_fields_visible(self):
        """Show PO fields only for labor and machinery lines"""
        for line in self:
            line.po_fields_visible = (line.line_type == 'labor_machinery')

    @api.depends('product_id', 'quantity', 'purchase_order_line_id', 'purchase_order_line_id.price_unit', 'line_type', 'po_unit_price', 'report_id.stock_move_ids.state')
    def _compute_actual_cost(self):
        """
        Compute the actual cost for each DR line.

        Labor/machinery (PO-backed): PO unit price × quantity.
        Service products:            standard_price × quantity  (no stock moves).
        Stock/consumable products:   sum of stock.valuation.layer values for the
                                     validated moves of this report + product.
                                     SVL is frozen at validation time and is immune
                                     to subsequent AVCO/FIFO standard_price updates,
                                     so it stays in sync with the analytic entry
                                     created by _create_analytic_entries().
                                     Falls back to standard_price only when no
                                     validated moves exist yet (pre-validation state).
        """
        self = self.with_context(force_write=True)

        # ponytail: cache moves/valuation-layers per report_id instead of
        # re-searching per line - a report's lines all share the same moves.
        moves_by_report = {}
        layers_by_move = {}

        for line in self:
            # ── Labor / machinery (PO-backed) ────────────────────────────────
            if line.line_type == 'labor_machinery':
                if line.purchase_order_line_id:
                    line.actual_cost = line.purchase_order_line_id.price_unit * line.quantity
                else:
                    line.actual_cost = 0.0
                    _logger.warning("Labor/machinery line %s has no PO data", line.id)
                continue

            # ── Service products (no stock movement) ─────────────────────────
            if line.product_id.type == 'service':
                line.actual_cost = (line.product_id.standard_price or 0.0) * line.quantity
                continue

            # ── Stock / consumable products ───────────────────────────────────
            # Primary source: stock.valuation.layer (SVL).
            # SVL is created at picking validation and frozen; it is never
            # affected by later AVCO recalculations, making it the only source
            # that stays consistent with the analytic entry amount.
            report_id = line.report_id.id
            if report_id not in moves_by_report:
                all_moves = self.env['stock.move'].search([
                    ('daily_report_id', '=', report_id),
                    ('state', '=', 'done'),
                ])
                by_product = {}
                for move in all_moves:
                    by_product.setdefault(move.product_id.id, self.env['stock.move'])
                    by_product[move.product_id.id] |= move
                moves_by_report[report_id] = by_product

                all_layers = self.env['stock.valuation.layer'].search([
                    ('stock_move_id', 'in', all_moves.ids),
                ])
                for layer in all_layers:
                    layers_by_move.setdefault(layer.stock_move_id.id, self.env['stock.valuation.layer'])
                    layers_by_move[layer.stock_move_id.id] |= layer

            moves = moves_by_report[report_id].get(line.product_id.id, self.env['stock.move'])
            if moves:
                layers = self.env['stock.valuation.layer']
                for move in moves:
                    layers |= layers_by_move.get(move.id, self.env['stock.valuation.layer'])
                if layers:
                    line.actual_cost = sum(abs(layer.value) for layer in layers)
                    continue

            # Fallback: no validated moves yet — use standard_price (pre-validation).
            line.actual_cost = (line.product_id.standard_price or 0.0) * line.quantity

    @api.depends('product_id', 'quantity', 'report_id.company_id')
    def _compute_available_stock(self):
        """Compute available stock for the product with accurate on-hand quantities"""
        for line in self:
            # For services or non-tracked products, set appropriate values
            if not line.product_id or line.product_id.type == 'service':
                line.available_stock = 0.0
                line.product_availability = 'not_tracked'
                continue
                
            # For stockable and consumable products, compute real available stock
            if line.product_id.type == 'consu':
                try:
                    # Get the company context for accurate stock calculation
                    company_id = line.report_id.company_id.id or self.env.company.id
                    
                    # Use Odoo's standard method with company context
                    available_qty = line.product_id.with_company(company_id).qty_available
                    
                    # Store the result
                    line.available_stock = available_qty
                    
                except Exception as e:
                    _logger.error(f"Error calculating available stock: {str(e)}")
                    # Fallback to standard qty_available in case of error
                    line.available_stock = line.product_id.with_company(company_id).qty_available
                
                # Set availability status based on available quantity
                if line.available_stock <= 0:
                    line.product_availability = 'no_stock'
                elif line.available_stock < line.quantity:
                    line.product_availability = 'low_stock'
                else:
                    line.product_availability = 'available'
            else:
                # For any other product types
                line.available_stock = 0.0
                line.product_availability = 'not_tracked'

    @api.depends('product_id', 'quantity', 'report_id.date')
    def _compute_forecasted_issue(self):
        """Compute if there's a forecasted stock issue for the product"""
        for line in self:
            line.forecasted_issue = False
            if line.product_id and line.product_id.type == 'consu':
                try:
                    # Get company context for accurate forecast calculation
                    company_id = self.env.company.id
                    if line.report_id and line.report_id.company_id:
                        company_id = line.report_id.company_id.id
                    
                    # Calculate forecasted availability considering the report date
                    to_date = fields.Date.today()  # Default to today
                    if line.report_id and line.report_id.date:
                        to_date = line.report_id.date
                    
                    virtual_available = line.product_id.with_context(
                        company_id=company_id, 
                        to_date=to_date
                    ).virtual_available
                    
                    # Check if forecasted quantity will be negative after this consumption
                    quantity = line.quantity or 0.0
                    if virtual_available - quantity < 0:
                        line.forecasted_issue = True
                        
                except Exception as e:
                    _logger.warning(f"Error calculating forecasted issue for product {line.product_id.name}: {str(e)}")
                    line.forecasted_issue = False

    @api.onchange('product_id', 'quantity')
    def _onchange_quantity(self):
        """Update forecast when quantity or product changes"""
        if self.product_id:
            # Force recompute of forecasted issue for immediate UI feedback
            self._compute_forecasted_issue()
            
            # Also recompute available stock
            self._compute_available_stock()
            
            # If we have quantity, also recompute actual cost
            if self.quantity:
                self.with_context(force_write=True)._compute_actual_cost()
    
    @api.model
    def _get_editable_fields_in_confirmed_state(self):
        """Return a list of fields that can be edited when the report is confirmed or done"""
        # Only allow editing notes, observations, and issues after confirmation
        # Also include fields that get updated during stock validation process
        return [
            'notes', 'observation', 'issues', 'actual_cost', 'available_stock', 
            'product_availability', 'uom_id', 'forecasted_issue'
        ]
    
    def write(self, vals):
        """Restrict field updates after the report is confirmed
        Only allow notes and observations to be modified after confirmation,
        but always allow stock validation, state changes, and force_write contexts"""
        
        # Always allow updates with force_write context (used in confirmation)
        if self.env.context.get('force_write', False):
            return super().write(vals)
        
        # Always allow updates during record creation/import
        if self.env.context.get('install_mode', False) or self.env.context.get('import_file', False):
            return super().write(vals)
        
        # Allow updates from onchange methods (they should not be restricted)
        if self.env.context.get('onchange', False):
            return super().write(vals)
        
        # Special handling for stock validation and state changes
        state_change = 'state' in vals
        cost_update = 'actual_cost' in vals
        stock_validation = self.env.context.get('from_stock_validation', False)
        
        # Always allow state changes and cost updates from validation
        if (state_change or cost_update) and stock_validation:
            return super().write(vals)
            
        # No restrictions in draft state
        records_not_in_draft = self.filtered(lambda r: r.report_id and r.report_id.state != 'draft')
        if not records_not_in_draft:
            return super().write(vals)
            
        # For records not in draft, only allow specific fields to be updated
        editable_fields = self._get_editable_fields_in_confirmed_state()
        restricted_fields = [f for f in vals.keys() if f not in editable_fields]
        
        if restricted_fields:
            # Check if someone is trying to modify restricted fields
            restricted_names = [self._fields[field].string for field in restricted_fields if field in self._fields]
            raise ValidationError(_(
                "You cannot modify the following fields after report confirmation: %s. "
                "Only notes, issues, and observations can be updated after stock movements have been created."
            ) % ", ".join(restricted_names))
        
        return super().write(vals)

    def _get_state_label(self):
        """Get translated label for state at runtime"""
        state_labels = {
            'draft': _('Draft'),
            'confirmed': _('Confirmed'),
            'done': _('Done'),
        }
        return state_labels.get(self.state, self.state)
    
    def _get_crop_condition_label(self):
        """Get translated label for crop condition at runtime"""
        condition_labels = {
            'excellent': _('Excellent'),
            'good': _('Good'),
            'fair': _('Fair'),
            'poor': _('Poor'),
            'critical': _('Critical'),
        }
        return condition_labels.get(self.crop_condition, self.crop_condition)
    
    def _get_availability_label(self):
        """Get translated label for product availability at runtime"""
        availability_labels = {
            'not_tracked': _('Not Tracked'),
            'no_stock': _('No Stock'),
            'low_stock': _('Low Stock'),
            'available': _('Available'),
        }
        return availability_labels.get(self.product_availability, self.product_availability)
    
    def get_translated_field_labels(self):
        """Return field labels properly translated at runtime"""
        return {
            'reference': _('Reference'),
            'date': _('Date'),
            'reported_by': _('Reported By'),
            'cultivation_project': _('Cultivation Project'),
            'farm': _('Farm'),
            'field': _('Field'),
            'crop': _('Crop'),
            'operation_type': _('Operation Type'),
            'project_stage': _('Project Stage'),
            'status': _('Status'),
            'temperature': _('Temperature (C)'),
            'humidity': _('Humidity (%)'),
            'rainfall': _('Rainfall (mm)'),
            'labor_hours': _('Labor Hours'),
            'machinery_hours': _('Machinery Hours'),
            'products_used': _('Products Used'),
            'cost': _('Cost'),
            'observations': _('Observations'),
            'issues_encountered': _('Issues Encountered'),
            'crop_condition': _('Crop Condition'),
            'notes': _('Notes')
        }
        
    def get_translated_operation_types(self):
        """Return operation types properly translated at runtime"""
        return [
            ('preparation', _('Field Preparation')),
            ('planting', _('Planting/Sowing')),
            ('fertilizer', _('Fertilizer Application')),
            ('pesticide', _('Pesticide Application')),
            ('irrigation', _('Irrigation')),
            ('weeding', _('Weeding')),
            ('harvesting', _('Harvesting')),
            ('maintenance', _('Maintenance')),
            ('inspection', _('Inspection')),
            ('other', _('Other'))
        ]
        
    def get_translated_states(self):
        """Return states properly translated at runtime"""
        return [
            ('draft', _('Draft')),
            ('confirmed', _('Confirmed')),
            ('done', _('Done'))
        ]
        
    def get_translated_crop_conditions(self):
        """Return crop conditions properly translated at runtime"""
        return [
            ('excellent', _('Excellent')),
            ('good', _('Good')),
            ('fair', _('Fair')),
            ('poor', _('Poor')),
            ('critical', _('Critical'))
        ]
        
    def get_translated_error_messages(self):
        """Return error messages properly translated at runtime"""
        return {
            'date_before_start': _("Report date cannot be before project start date."),
            'date_after_end': _("Report date cannot be after project end date."),
            'insufficient_inventory': _("Cannot confirm report due to insufficient inventory:\n\n"),
            'inventory_line_error': _("- %s: Requested %s %s, Available: %s %s\n"),
            'no_warehouse': _("No warehouse found for this company."),
            'no_stock_location': _("No stock location found in warehouse."),
            'no_parent_location': _("No parent stock location found to create farm location."),
            'no_physical_locations': _("No Physical Locations found to create farm location hierarchy.")
        }

    def action_product_forecast(self):
        """Open the product forecast report for this line's product"""
        if not self.product_id:
            return {'type': 'ir.actions.client', 'tag': 'display_notification',
                    'params': {'message': _('Please select a product first'), 'type': 'warning'}}
        
        # Use Odoo's built-in forecast report action for the product
        action = self.env.ref('stock.stock_forecasted_product_product_action').read()[0]
        action['context'] = {
            'default_product_id': self.product_id.id,
            'active_model': 'product.product',
            'active_id': self.product_id.id,
        }
        return action
    
    @api.depends('purchase_order_id', 'product_id')
    def _compute_po_line_from_po(self):
        """Compute PO line from selected PO and product"""
        for line in self:
            if line.purchase_order_id and line.product_id:
                # Find the PO line for this product in the selected PO
                po_line = line.purchase_order_id.order_line.filtered(
                    lambda l: l.product_id == line.product_id
                )
                if po_line:
                    line.purchase_order_line_id = po_line[0]  # Take the first match
                else:
                    line.purchase_order_line_id = False
            else:
                line.purchase_order_line_id = False

    @api.depends('purchase_order_line_id', 'purchase_order_id')
    def _compute_po_fields(self):
        """Compute PO-related fields from selected PO line or PO"""
        for line in self:
            if line.purchase_order_line_id:
                po_line = line.purchase_order_line_id
                line.vendor_id = po_line.order_id.partner_id
                line.po_unit_price = po_line.price_unit
            elif line.purchase_order_id:
                line.vendor_id = line.purchase_order_id.partner_id
                line.po_unit_price = 0.0
            else:
                line.vendor_id = False
                line.po_unit_price = 0.0

    @api.depends('product_id')
    def _compute_available_po_lines(self):
        """Compute available Purchase Orders for selected product, excluding locked POs"""
        for line in self:
            if line.product_id and line.line_type == 'labor_machinery':
                # Domain to get available POs that contain this product
                domain = [
                    ('order_line.product_id', '=', line.product_id.id),
                    ('state', 'in', ['purchase', 'to approve']),
                    ('partner_id.supplier_rank', '>', 0),
                    ('order_line.product_id.categ_id.name', 'in', ['Labor Services', 'Machinery'])
                ]
                
                available_pos = self.env['purchase.order'].search(domain)
                line.available_po_lines = [(6, 0, available_pos.ids)]
            else:
                line.available_po_lines = [(5, 0, 0)]
    
    # Add computed field for available PO lines
    available_po_lines = fields.Many2many(
        'purchase.order',
        compute='_compute_available_po_lines',
        string='Available Purchase Orders',
        help='Available purchase orders for this product'
    )
    
    # Computed field for product domain filtering
    available_product_ids = fields.Many2many(
        'product.product',
        compute='_compute_available_products',
        string='Available Products',
        help='Products that have available purchase order lines'
    )
    
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
    
    @api.model
    def _get_products_with_po_lines(self):
        """Get products that have available Purchase Orders in Labor Services or Machinery categories"""
        # Base domain for Purchase Orders
        domain = [
            ('state', 'in', ['purchase', 'to approve']),
            ('partner_id.supplier_rank', '>', 0),
            ('order_line.product_id.categ_id.name', 'in', ['Labor Services', 'Machinery'])
        ]
        
        # Get all POs matching criteria
        pos = self.env['purchase.order'].search(domain)
        
        # Extract unique product IDs from PO lines
        product_ids = pos.mapped('order_line.product_id').filtered(
            lambda p: p.categ_id.name in ['Labor Services', 'Machinery']
        ).ids
        
        return product_ids
    
    @api.model
    def _get_labor_machinery_product_domain(self):
        """Get domain for labor/machinery products that have available PO lines"""
        product_ids = self._get_products_with_po_lines()
        
        return [
            ('id', 'in', product_ids),
            ('categ_id.name', 'in', ['Labor Services', 'Machinery'])
        ]

    @api.onchange('product_id')
    def _onchange_product_id(self):
        """Update available POs when product changes and reset PO selection"""
        if self.line_type == 'labor_machinery':
            if self.product_id:
                # Compute available POs for the selected product
                self._compute_available_po_lines()
                # Reset PO selection when product changes
                self.purchase_order_id = False
                self.purchase_order_line_id = False
                
                # Auto-select if only one PO available
                if len(self.available_po_lines) == 1:
                    self.purchase_order_id = self.available_po_lines[0]
            else:
                self.purchase_order_id = False
                self.purchase_order_line_id = False
        else:
            # For non-labor/machinery lines, trigger UOM computation
            if self.product_id:
                # Trigger compute methods for immediate UI feedback
                self._compute_po_fields()  # This will ensure other fields are maintained
            # UOM will be computed automatically by _compute_uom_id

    @api.onchange('purchase_order_id')
    def _onchange_purchase_order_id(self):
        """Update related fields when PO changes"""
        if self.purchase_order_id and self.line_type == 'labor_machinery':
            # Trigger computation of PO line and related fields
            self._compute_po_line_from_po()
            self._compute_po_fields()
            
            # Also trigger cost computation
            self.with_context(force_write=True)._compute_actual_cost()

    @api.onchange('line_type')
    def _onchange_line_type(self):
        """Clear product and PO selections when line type changes"""
        if self.line_type == 'labor_machinery':
            # Clear product selection to force reselection from filtered domain
            self.product_id = False
            self.purchase_order_id = False
            self.purchase_order_line_id = False
        else:
            # For other line types, clear PO-related fields
            self.purchase_order_id = False
            self.purchase_order_line_id = False
            self.vendor_id = False
            self.po_unit_price = 0.0
        # UOM will be computed automatically by _compute_uom_id

    @api.constrains('purchase_order_id', 'product_id', 'line_type')
    def _check_labor_machinery_po_requirements(self):
        """Validate that labor/machinery lines have proper PO setup"""
        for line in self:
            if line.line_type == 'labor_machinery':
                if not line.purchase_order_id:
                    raise ValidationError(_('Labor and machinery lines must have a purchase order selected.'))
                
                if not line.product_id:
                    raise ValidationError(_('Labor and machinery lines must have a product selected.'))
                
                # Validate that the selected PO contains the product
                po_has_product = line.purchase_order_id.order_line.filtered(
                    lambda l: l.product_id == line.product_id
                )
                if not po_has_product:
                    raise ValidationError(_('The selected purchase order must contain the selected product.'))
                
                # Check if PO is in a state that shouldn't be used (cancelled)
                if line.purchase_order_id.state == 'cancel':
                    raise ValidationError(_('Cannot use cancelled purchase orders.'))
                
                # Validate product category
                if line.product_id.categ_id.name not in ['Labor Services', 'Machinery']:
                    raise ValidationError(_('Product must be in Labor Services or Machinery category.'))

    @api.model
    def get_available_products_for_labor_machinery(self):
        """Public method to get available products for labor/machinery lines"""
        return self._get_products_with_po_lines()

    def _get_po_display_name(self, po_line):
        """Get display name for PO line selection"""
        if not po_line:
            return ''

        po = po_line.order_id
        vendor = po.partner_id.name
        price = po_line.price_unit
        currency = po.currency_id.symbol or po.currency_id.name

        return f"{po.name} - {vendor} - {price} {currency}"
