from odoo import fields, models, api, _
import logging
from datetime import datetime

_logger = logging.getLogger(__name__)

class StockMoveLine(models.Model):
    _inherit = 'stock.move.line'
    
    daily_report_id = fields.Many2one(related='move_id.daily_report_id', string='Farm Operation', 
                                     store=True, index=True)

class ProductProduct(models.Model):
    _inherit = 'product.product'
    
    is_used_in_farm = fields.Boolean(string='Used in Farm', compute='_compute_farm_usage', store=True)
    last_farm_usage_date = fields.Date(string='Last Farm Usage', compute='_compute_farm_usage', store=True)
    
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

class AccountAnalyticLine(models.Model):
    _inherit = 'account.analytic.line'
    
    daily_report_id = fields.Many2one('farm.daily.report', string='Daily Report',
                                    index=True, ondelete='cascade')
