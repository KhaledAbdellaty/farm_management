from odoo import fields, models, api, _
from odoo.exceptions import ValidationError


class Field(models.Model):
    _name = 'farm.field'
    _description = 'Farm Field'
    _inherit = ['mail.thread', 'mail.activity.mixin']
    _order = 'name'

    name = fields.Char(string='Field Name', required=True, tracking=True, translate=True)
    code = fields.Char(string='Field Code', required=True, tracking=True, readonly=True, default=lambda self: 'New')
    active = fields.Boolean(default=True, tracking=True)
    
    farm_id = fields.Many2one('farm.farm', string='Farm', required=True, 
                             tracking=True, ondelete='cascade')
    
    area = fields.Float(string='Area', tracking=True, required=True)
    area_unit = fields.Selection(
        selection='_get_area_unit_selection',
        string='Area Unit', 
        default='feddan', 
        required=True, 
        tracking=True
    )
    
    @api.model
    def _get_area_unit_selection(self):
        """Return selection values for area units with translation support at runtime"""
        return [
            ('feddan', 'Feddan'),
            ('acre', 'Acre'),
            ('sqm', 'Square Meter'),
        ]
    
    
    current_crop_id = fields.Many2one('farm.crop', string='Current Crop', 
                                     tracking=True)
    
    project_ids = fields.One2many('farm.cultivation.project', 'field_id', 
                                string='Cultivation Projects')
    project_count = fields.Integer(compute='_compute_project_count', 
                                 string='Project Count')
    
    notes = fields.Html(string='Notes', translate=True)
    
    # Field status
    @api.model
    def _get_state_selection(self):
        """Return selection values for field state with translation support at runtime"""
        return [
            ('available', _('Available')),
            ('preparation', _('In Preparation')),
            ('cultivated', _('Cultivated')),
            ('harvested', _('Harvested')),
            ('fallow', _('Fallow')),
        ]
        
    state = fields.Selection(
        selection='_get_state_selection',
        string='Status', 
        default='available', 
        tracking=True
    )
    
    # Field image or map
    image = fields.Binary("Field Image", attachment=True)
    
    company_id = fields.Many2one('res.company', related='farm_id.company_id', 
                                string='Company', store=True, readonly=True)
    
    _sql_constraints = [
        ('farm_code_unique', 'UNIQUE(farm_id, code)', 'Field code must be unique per farm!'),
    ]
    
    
    def _compute_project_count(self):
        """Compute the number of cultivation projects on this field"""
        for field in self:
            field.project_count = len(field.project_ids)
    
    def action_view_projects(self):
        """Smart button action to view cultivation projects for this field"""
        self.ensure_one()
        return {
            'name': _('Cultivation Projects'),
            'view_mode': 'list,form',
            'res_model': 'farm.cultivation.project',
            'domain': [('field_id', '=', self.id)],
            'type': 'ir.actions.act_window',
            'context': {'default_field_id': self.id, 'default_farm_id': self.farm_id.id}
        }
    
    @api.constrains('area')
    def _check_area(self):
        """Ensure area is positive"""
        for record in self:
            if record.area <= 0:
                raise ValidationError(_("Field area must be greater than zero."))
    
    @api.model_create_multi
    def create(self, vals_list):
        """Generate a unique code for new fields using the sequence"""
        for vals in vals_list:
            if vals.get('code', 'New') == 'New':
                vals['code'] = self.env['ir.sequence'].next_by_code('farm.field') or 'New'
        return super().create(vals_list)
    
    # Translation helper methods
    def _get_translated_selection_values(self, field_name):
        """Get translated selection field values as a dictionary"""
        return dict(self._fields[field_name].selection)
    
    def _get_translated_state_name(self, state_code=None):
        """Get the translated name of a state based on its code"""
        state = state_code or self.state
        selection = dict(self._get_state_selection())
        return selection.get(state, '')
    
    def _get_translated_area_unit(self, unit_code=None):
        """Get the translated name of an area unit based on its code"""
        units = dict(self._get_area_unit_selection())
        unit = unit_code or self.area_unit
        return units.get(unit, '')
