from odoo import fields, models, api

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

class AccountAnalyticLine(models.Model):
    _inherit = 'account.analytic.line'
    
    daily_report_id = fields.Many2one('farm.daily.report', string='Daily Report',
                                    index=True, ondelete='cascade')
