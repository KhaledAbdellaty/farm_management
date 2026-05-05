from odoo import fields, models, api, _
from odoo.exceptions import ValidationError
import logging

_logger = logging.getLogger(__name__)


class FarmHarvestBatch(models.Model):
    _name = 'farm.harvest.batch'
    _description = 'Harvest Batch'
    _order = 'date desc, id desc'
    _inherit = ['mail.thread']
    _rec_name = 'display_name'

    project_id = fields.Many2one(
        'farm.cultivation.project', string='Cultivation Project',
        required=True, ondelete='cascade', index=True
    )
    date = fields.Date(string='Harvest Date', required=True, default=fields.Date.today, tracking=True)
    quantity = fields.Float(string='Quantity', required=True, digits=(16, 3), tracking=True)
    price_unit = fields.Monetary(string='Price / Unit', required=True, tracking=True,
                                 currency_field='currency_id',
                                 help="Price per unit of yield for this harvest batch")
    uom_id = fields.Many2one('uom.uom', string='Unit of Measure', required=True, tracking=True)
    notes = fields.Char(string='Notes')
    state = fields.Selection([
        ('draft', 'Draft'),
        ('receipt_created', 'Receipt Created'),
        ('validated', 'Validated'),
    ], string='Status', default='draft', required=True, tracking=True)

    picking_id = fields.Many2one('stock.picking', string='Stock Receipt', readonly=True, copy=False)
    subtotal = fields.Monetary(string='Subtotal', compute='_compute_subtotal',
                               currency_field='currency_id', store=True)

    # Related fields from project
    company_id = fields.Many2one('res.company', related='project_id.company_id', store=True)
    currency_id = fields.Many2one('res.currency', related='project_id.currency_id')
    crop_id = fields.Many2one('farm.crop', related='project_id.crop_id')
    farm_id = fields.Many2one('farm.farm', related='project_id.farm_id')
    field_id = fields.Many2one('farm.field', related='project_id.field_id')

    @api.depends('project_id.code', 'date', 'quantity', 'uom_id.name')
    def _compute_display_name(self):
        for batch in self:
            project_code = batch.project_id.code or '?'
            date_str = str(batch.date) if batch.date else '?'
            qty_str = f"{batch.quantity:g} {batch.uom_id.name}" if batch.uom_id else str(batch.quantity)
            batch.display_name = f"{project_code} / {date_str} / {qty_str}"

    @api.depends('quantity', 'price_unit')
    def _compute_subtotal(self):
        for batch in self:
            batch.subtotal = batch.quantity * batch.price_unit

    @api.constrains('quantity')
    def _check_quantity(self):
        for batch in self:
            if batch.quantity <= 0:
                raise ValidationError(_("Harvest quantity must be greater than zero."))

    @api.constrains('price_unit')
    def _check_price(self):
        for batch in self:
            if batch.price_unit <= 0:
                raise ValidationError(_("Harvest price must be greater than zero."))

    def _get_or_create_source_location(self):
        """
        Build the Farm → Field → Project location hierarchy and return
        the project-level production location as stock move source.
        """
        self.ensure_one()
        project = self.project_id

        physical_locations = self.env.ref('stock.stock_location_locations', raise_if_not_found=False)
        if not physical_locations:
            physical_locations = self.env['stock.location'].search([
                ('name', '=', 'Physical Locations'),
                ('usage', '=', 'view'),
            ], limit=1)
        if not physical_locations:
            raise ValidationError(_("Physical Locations root not found. Cannot create farm location hierarchy."))

        # Farm level
        farm_location = self.env['stock.location'].search([
            ('name', '=', f"Farm: {project.farm_id.name}"),
            ('location_id', '=', physical_locations.id),
            ('company_id', '=', project.company_id.id),
        ], limit=1)
        if not farm_location:
            farm_location = self.env['stock.location'].create({
                'name': f"Farm: {project.farm_id.name}",
                'usage': 'production',
                'location_id': physical_locations.id,
                'company_id': project.company_id.id,
            })

        # Field level
        field_location = self.env['stock.location'].search([
            ('name', '=', f"Field: {project.field_id.name}"),
            ('location_id', '=', farm_location.id),
            ('company_id', '=', project.company_id.id),
        ], limit=1)
        if not field_location:
            field_location = self.env['stock.location'].create({
                'name': f"Field: {project.field_id.name}",
                'usage': 'production',
                'location_id': farm_location.id,
                'company_id': project.company_id.id,
            })

        # Project/crop level
        project_loc_name = f"Project: {project.name} - {project.crop_id.name}"
        project_location = self.env['stock.location'].search([
            ('name', '=', project_loc_name),
            ('location_id', '=', field_location.id),
            ('company_id', '=', project.company_id.id),
        ], limit=1)
        if not project_location:
            project_location = self.env['stock.location'].create({
                'name': project_loc_name,
                'usage': 'production',
                'location_id': field_location.id,
                'company_id': project.company_id.id,
            })

        return project_location

    def action_create_receipt(self):
        """
        Create a stock receipt (incoming picking) for this harvest batch.
        Moves the harvested crop from the field location into warehouse stock.
        """
        self.ensure_one()

        if self.state != 'draft':
            raise ValidationError(_("A receipt has already been created for this batch."))

        project = self.project_id
        product = project.crop_id.product_id

        if not product:
            raise ValidationError(_("The crop linked to this project has no product configured."))

        if product.type != 'consu':
            raise ValidationError(_(
                "Product '%s' is not a storable product. Only storable products "
                "can generate inventory receipts.", product.name
            ))

        warehouse = self.env['stock.warehouse'].search(
            [('company_id', '=', project.company_id.id)], limit=1
        )
        if not warehouse:
            raise ValidationError(_("No warehouse found for this company."))

        dest_location = warehouse.lot_stock_id
        if not dest_location:
            raise ValidationError(_("No stock location found in warehouse."))

        source_location = self._get_or_create_source_location()
        picking_type = warehouse.in_type_id
        if not picking_type:
            picking_type = self.env['stock.picking.type'].search([
                ('code', '=', 'incoming'),
                ('warehouse_id', '=', warehouse.id),
            ], limit=1)
        if not picking_type:
            raise ValidationError(_("No incoming receipt operation type found for the warehouse."))

        picking = self.env['stock.picking'].create({
            'picking_type_id': picking_type.id,
            'location_id': source_location.id,
            'location_dest_id': dest_location.id,
            'origin': f"Harvest Batch: {project.code} — {self.date}",
            'scheduled_date': self.date,
            'company_id': project.company_id.id,
            'move_type': 'direct',
            'partner_id': project.farm_id.owner_id.id if project.farm_id.owner_id else False,
            'note': (
                f"Harvest batch receipt\n"
                f"Project: {project.name} ({project.code})\n"
                f"Crop: {product.name}\n"
                f"Farm: {project.farm_id.name} / Field: {project.field_id.name}\n"
                f"Batch date: {self.date}"
            ),
        })

        self.env['stock.move'].create({
            'name': f"{_('Harvest Receipt')}: {product.name}",
            'product_id': product.id,
            'product_uom_qty': self.quantity,
            'product_uom': self.uom_id.id,
            'picking_id': picking.id,
            'location_id': source_location.id,
            'location_dest_id': dest_location.id,
            'company_id': project.company_id.id,
            'state': 'draft',
            'price_unit': self.price_unit,
            'description_picking': (
                f"{product.name} — batch harvest on {self.date} "
                f"from field {project.field_id.name}"
            ),
        })

        # Confirm + reserve the picking
        picking.action_confirm()
        picking.action_assign()

        # Pre-create move lines so validation is straightforward
        for move in picking.move_ids:
            if not move.move_line_ids:
                self.env['stock.move.line'].create({
                    'move_id': move.id,
                    'product_id': move.product_id.id,
                    'product_uom_id': move.product_uom.id,
                    'location_id': move.location_id.id,
                    'location_dest_id': move.location_dest_id.id,
                    'picking_id': picking.id,
                    'company_id': move.company_id.id,
                    'quantity': 0,  # set during validation
                })

        self.write({'picking_id': picking.id, 'state': 'receipt_created'})

        _logger.info(
            "Created harvest receipt %s for batch (project=%s, qty=%s, price=%s)",
            picking.name, project.name, self.quantity, self.price_unit,
        )

        project.message_post(
            body=_(
                "Harvest batch receipt %(picking)s created — %(qty)s %(uom)s of %(product)s "
                "@ %(price)s (%(date)s)"
            ) % {
                'picking': picking.name,
                'qty': self.quantity,
                'uom': self.uom_id.name,
                'product': product.name,
                'price': self.price_unit,
                'date': self.date,
            },
            message_type='comment',
        )

        return {
            'type': 'ir.actions.act_window',
            'name': _('Harvest Receipt'),
            'res_model': 'stock.picking',
            'view_mode': 'form',
            'res_id': picking.id,
            'target': 'current',
        }

    def action_validate_receipt(self):
        """
        Validate the stock receipt for this batch, updating on-hand inventory.
        Sets batch state to 'validated' and triggers recompute of project totals.
        """
        self.ensure_one()

        if self.state == 'draft':
            raise ValidationError(_("Please create the receipt before validating."))
        if self.state == 'validated':
            raise ValidationError(_("This batch has already been validated."))

        picking = self.picking_id
        if not picking:
            raise ValidationError(_("No receipt found for this batch."))

        if picking.state == 'done':
            # Already validated externally — just sync state
            self.write({'state': 'validated'})
            return True

        # Ensure quantities are set on every move line
        for move in picking.move_ids:
            if move.product_uom_qty != self.quantity:
                move.product_uom_qty = self.quantity
            if move.price_unit != self.price_unit:
                move.price_unit = self.price_unit
            for ml in move.move_line_ids:
                if ml.quantity <= 0:
                    ml.quantity = self.quantity

        # Reserve if needed
        if picking.state not in ['assigned', 'done']:
            picking.action_assign()

        # Validate
        try:
            picking.with_context(skip_backorder=True).button_validate()
        except Exception as e:
            _logger.warning("Standard validation failed: %s — trying _action_done", e)
            try:
                for move in picking.move_ids:
                    for ml in move.move_line_ids:
                        ml.quantity = move.product_uom_qty
                picking._action_done()
            except Exception as e2:
                _logger.error("Harvest batch validation failed: %s", e2)
                raise ValidationError(_(
                    "Failed to validate harvest receipt %(name)s:\n%(error)s\n\n"
                    "Ensure the product is storable and all locations are correctly configured."
                ) % {'name': picking.name, 'error': str(e2)})

        if picking.state != 'done':
            raise ValidationError(_(
                "Validation did not complete. Receipt is still in state: %(state)s.",
            ) % {'state': picking.state})

        self.write({'state': 'validated'})

        # Recompute project totals
        self.project_id._compute_actual_yield()
        self.project_id._compute_harvest_price()

        project = self.project_id
        product = project.crop_id.product_id
        current_qty = product.with_context(
            location=picking.location_dest_id.id
        ).qty_available

        _logger.info(
            "Validated harvest receipt %s — product %s now has %s %s in stock",
            picking.name, product.name, current_qty, self.uom_id.name,
        )

        project.message_post(
            body=_(
                "Harvest batch validated — %(qty)s %(uom)s of %(product)s added to inventory.\n"
                "Receipt: %(picking)s\nCurrent stock in %(location)s: %(current)s %(uom)s"
            ) % {
                'qty': self.quantity,
                'uom': self.uom_id.name,
                'product': product.name,
                'picking': picking.name,
                'location': picking.location_dest_id.name,
                'current': current_qty,
            },
            message_type='comment',
        )

        return True

    def action_view_receipt(self):
        """Open the stock receipt form for this batch."""
        self.ensure_one()
        if not self.picking_id:
            return {
                'type': 'ir.actions.client',
                'tag': 'display_notification',
                'params': {
                    'title': _('No Receipt'),
                    'message': _('No receipt has been created for this batch yet.'),
                    'sticky': False,
                    'type': 'warning',
                },
            }
        return {
            'type': 'ir.actions.act_window',
            'name': _('Harvest Receipt'),
            'res_model': 'stock.picking',
            'view_mode': 'form',
            'res_id': self.picking_id.id,
            'target': 'current',
        }

    def unlink(self):
        for batch in self:
            if batch.state == 'validated':
                raise ValidationError(_(
                    "Cannot delete a validated harvest batch (%(date)s — %(qty)s %(uom)s). "
                    "Validated batches are part of the stock history."
                ) % {'date': batch.date, 'qty': batch.quantity, 'uom': batch.uom_id.name})
        return super().unlink()
