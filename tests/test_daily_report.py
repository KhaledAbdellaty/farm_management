from datetime import date

from odoo.tests import TransactionCase, tagged


@tagged('post_install', '-at_install')
class TestDailyReport(TransactionCase):

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.farm = cls.env['farm.farm'].create({'name': 'DR Test Farm', 'area': 10.0})
        cls.field = cls.env['farm.field'].create({
            'name': 'DR Test Field', 'farm_id': cls.farm.id, 'area': 5.0,
        })
        cls.crop = cls.env['farm.crop'].create({'name': 'DR Test Wheat'})
        cls.project = cls.env['farm.cultivation.project'].create({
            'name': 'DR Test Project',
            'farm_id': cls.farm.id,
            'field_id': cls.field.id,
            'crop_id': cls.crop.id,
            'start_date': date(2026, 1, 1),
            'planned_end_date': date(2026, 4, 1),
        })

    def test_confirm_empty_report_happy_path(self):
        # No product lines at all — the true happy path: no stock, no PO,
        # no warehouse setup needed. Should confirm cleanly.
        report = self.env['farm.daily.report'].create({
            'project_id': self.project.id,
            'date': date(2026, 1, 5),
            'operation_type': 'inspection',
            'irrigation_duration': 0.0,
        })
        report.action_confirm()
        self.assertEqual(report.state, 'confirmed')

    def test_set_to_done_does_not_duplicate_analytic_lines(self):
        # Service product: no stock movement involved, so _compute_actual_cost
        # just does standard_price * quantity — no warehouse/picking needed.
        service_product = self.env['product.product'].create({
            'name': 'DR Test Consulting',
            'type': 'service',
            'standard_price': 50.0,
        })
        report = self.env['farm.daily.report'].create({
            'project_id': self.project.id,
            'date': date(2026, 1, 5),
            'operation_type': 'other',
            'irrigation_duration': 0.0,
            'other_product_lines': [(0, 0, {
                'product_id': service_product.id,
                'quantity': 2.0,
                'line_type': 'other',
            })],
        })
        report.action_confirm()
        report.action_set_to_done()

        self.assertEqual(report.state, 'done')
        line_count_first = len(report.analytic_line_ids)
        self.assertGreater(line_count_first, 0, "expected an analytic line for the service product cost")

        # Calling action_set_to_done() again must not create duplicate entries
        # — the guard is `if not report.analytic_line_ids` in action_set_to_done().
        report.action_set_to_done()
        self.assertEqual(len(report.analytic_line_ids), line_count_first)
