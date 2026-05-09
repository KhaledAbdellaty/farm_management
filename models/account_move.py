from odoo import fields, models, _
import logging

_logger = logging.getLogger(__name__)


class AccountMove(models.Model):
    """Extend account.move to link vendor bills back to daily reports."""
    _inherit = 'account.move'

    daily_report_id = fields.Many2one(
        'farm.daily.report',
        string='Daily Report',
        help='Daily report that generated this vendor bill',
        readonly=True
    )

    def _get_name_invoice_report(self):
        """Override to show daily report reference in bill"""
        result = super()._get_name_invoice_report()
        if self.daily_report_id:
            result += _(" (Farm Report: %s)") % self.daily_report_id.name
        return result

    def action_post(self):
        """
        After posting, clean up any cost-analysis analytic lines that are now
        superseded by this invoice's own analytic lines.

        When a vendor bill is posted Odoo creates authoritative analytic lines
        (move_line_id set) from analytic_distribution.  Any farm.cost.analysis
        record linked to this invoice will have its own ghost analytic line
        (no move_line_id).  Guard 1 in _sync_analytic_line() removes it.
        """
        result = super().action_post()
        cost_analyses = self.env['farm.cost.analysis'].search([
            ('invoice_id', 'in', self.ids),
        ])
        if cost_analyses:
            cost_analyses._sync_analytic_line()
        return result


