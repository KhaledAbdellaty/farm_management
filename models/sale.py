from odoo import fields, models, api, _
import logging

_logger = logging.getLogger(__name__)


class SaleOrder(models.Model):
    _inherit = 'sale.order'

    cultivation_project_id = fields.Many2one(
        'farm.cultivation.project',
        string='Cultivation Project',
        tracking=True,
        help="The cultivation project this sale order is related to"
    )

    # ── Analytic distribution helpers ─────────────────────────────────────────

    def _apply_cultivation_analytic_distribution(self):
        """
        Set analytic_distribution = 100 % to the project's analytic account
        on every order line that has a product set.

        This ensures that when the sale order is invoiced and the invoice is
        posted, Odoo automatically creates account.analytic.line records that
        carry the project's analytic account — making revenue visible in the
        Analytic Account Gross Margin report.
        """
        for order in self:
            account = order.cultivation_project_id.analytic_account_id
            if not account:
                continue
            distribution = {str(account.id): 100.0}
            lines_with_product = order.order_line.filtered('product_id')
            if lines_with_product:
                lines_with_product.write({'analytic_distribution': distribution})
                _logger.debug(
                    "Applied analytic distribution (account %s) to %d lines of sale order %s",
                    account.id, len(lines_with_product), order.name,
                )

    # ── Onchange — show distribution before confirmation ──────────────────────

    @api.onchange('cultivation_project_id')
    def _onchange_cultivation_project_id(self):
        """
        Update analytic distribution on existing lines when the linked
        cultivation project is changed, so the user can review it before
        confirming the order.
        """
        self._apply_cultivation_analytic_distribution()

    # ── action_confirm override ───────────────────────────────────────────────

    def action_confirm(self):
        """
        Before confirming (and thereby potentially locking) the sale order,
        ensure every line linked to a cultivation project carries the correct
        analytic distribution so that invoiced amounts flow into the
        Analytic Account Gross Margin. Must run before super() because a
        locked order forbids writing analytic_distribution on its lines.
        """
        farm_orders = self.filtered('cultivation_project_id')
        if farm_orders:
            farm_orders._apply_cultivation_analytic_distribution()
        return super().action_confirm()

    # ── Display helper ────────────────────────────────────────────────────────

    def _get_cultivation_project_display_name(self):
        """Returns the display name with translation applied at runtime"""
        self.ensure_one()
        if self.cultivation_project_id:
            return _("Cultivation Project: %s") % self.cultivation_project_id.name
        return ""


class SaleOrderLine(models.Model):
    _inherit = 'sale.order.line'

    def _prepare_invoice_line(self, **optional_kwargs):
        """
        Carry analytic_distribution forward onto the customer invoice line so
        that posting the invoice creates analytic lines under the project's
        analytic account.

        Odoo 18 propagates analytic_distribution automatically when it is set
        on the order line, but we explicitly ensure it here as a safety net
        in case the standard propagation is bypassed.
        """
        vals = super()._prepare_invoice_line(**optional_kwargs)
        if (self.analytic_distribution and
                not vals.get('analytic_distribution')):
            vals['analytic_distribution'] = self.analytic_distribution
        return vals
