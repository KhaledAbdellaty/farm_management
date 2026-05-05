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


class AccountMoveLine(models.Model):
    """
    Inject project_id into analytic lines at creation time.

    Odoo 18 blocks writes to account.analytic.line records that have
    move_line_id set ("This analytic item was created by a journal item…").
    The only safe window to set project_id is inside
    _prepare_analytic_distribution_line(), which builds the creation dict
    before the analytic line exists.

    This ensures that every analytic line created from analytic_distribution
    on a cultivation project's analytic account (vendor bill, customer
    invoice, or manual journal entry) is born with the correct project_id
    and therefore appears under the project name — not the "None" group —
    in the Analytic Account Gross Margin report.
    """
    _inherit = 'account.move.line'

    def _prepare_analytic_distribution_line(
        self, distribution, account_ids, distribution_on_each_plan
    ):
        vals = super()._prepare_analytic_distribution_line(
            distribution, account_ids, distribution_on_each_plan
        )

        analytic_account_id = vals.get('account_id')
        if analytic_account_id:
            project = self.env['farm.cultivation.project'].search([
                ('analytic_account_id', '=', analytic_account_id),
                ('project_id', '!=', False),
            ], limit=1)
            if project:
                # hr_timesheet requires employee_id whenever project_id is set
                # on an account.analytic.line.  Only inject project_id when the
                # current user has an active linked employee in the company —
                # otherwise the constraint fires with:
                #   "Timesheets must be created with an active employee…"
                employee = self.env['hr.employee'].search([
                    ('user_id', '=', self.env.uid),
                    ('company_id', '=', (
                        project.company_id.id or self.env.company.id
                    )),
                    ('active', '=', True),
                ], limit=1)
                if employee:
                    vals['project_id'] = project.project_id.id
                    vals['employee_id'] = employee.id
                    _logger.debug(
                        "Analytic line for account %s linked to project %s "
                        "(employee %s)",
                        analytic_account_id,
                        project.project_id.name,
                        employee.name,
                    )
                else:
                    _logger.debug(
                        "Skipped project_id on analytic line for account %s — "
                        "no active employee found for user %s in company %s. "
                        "Line will appear in the 'None' project group.",
                        analytic_account_id,
                        self.env.uid,
                        project.company_id.name,
                    )

        return vals
