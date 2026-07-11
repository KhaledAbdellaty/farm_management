from datetime import date

from odoo.exceptions import AccessError

from odoo.tests import TransactionCase, tagged


@tagged('post_install', '-at_install')
class TestSecurityRules(TransactionCase):
    """Regression tests for the ir.rule scoping added to narrow
    group_farm_user/group_farm_manager access on shared core models to only
    farm-linked records, instead of every record of that model."""

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.partner = cls.env['res.partner'].create({'name': 'Security Test Partner'})
        cls.farm = cls.env['farm.farm'].create({'name': 'Sec Test Farm', 'area': 10.0})
        cls.field = cls.env['farm.field'].create({
            'name': 'Sec Test Field', 'farm_id': cls.farm.id, 'area': 5.0,
        })
        cls.crop = cls.env['farm.crop'].create({'name': 'Sec Test Crop'})
        cls.project = cls.env['farm.cultivation.project'].create({
            'name': 'Sec Test Project',
            'farm_id': cls.farm.id,
            'field_id': cls.field.id,
            'crop_id': cls.crop.id,
            'start_date': date(2026, 1, 1),
            'planned_end_date': date(2026, 4, 1),
        })
        cls.farm_user = cls.env['res.users'].create({
            'name': 'Farm User Test',
            'login': 'farm_user_security_test',
            'groups_id': [(6, 0, [cls.env.ref('farm_management.group_farm_user').id])],
        })
        cls.farm_manager = cls.env['res.users'].create({
            'name': 'Farm Manager Test',
            'login': 'farm_manager_security_test',
            'email': 'farm_manager_security_test@example.com',
            'groups_id': [(6, 0, [cls.env.ref('farm_management.group_farm_manager').id])],
        })

    def test_farm_user_only_sees_sale_orders_linked_to_a_project(self):
        unrelated_order = self.env['sale.order'].create({'partner_id': self.partner.id})
        farm_order = self.env['sale.order'].create({
            'partner_id': self.partner.id,
            'cultivation_project_id': self.project.id,
        })

        visible = self.env['sale.order'].with_user(self.farm_user).search([
            ('id', 'in', (unrelated_order | farm_order).ids),
        ])
        self.assertEqual(visible, farm_order)

    def test_farm_user_only_sees_stock_moves_linked_to_a_daily_report(self):
        report = self.env['farm.daily.report'].create({
            'project_id': self.project.id,
            'date': date(2026, 1, 5),
            'operation_type': 'inspection',
            'irrigation_duration': 0.0,
        })
        warehouse = self.env['stock.warehouse'].search([('company_id', '=', self.env.company.id)], limit=1)
        unrelated_move = self.env['stock.move'].create({
            'name': 'Unrelated move',
            'product_id': self.env['product.product'].search([('type', '=', 'consu')], limit=1).id,
            'product_uom_qty': 1.0,
            'product_uom': self.env.ref('uom.product_uom_unit').id,
            'location_id': warehouse.lot_stock_id.id,
            'location_dest_id': warehouse.lot_stock_id.id,
        })
        farm_move = self.env['stock.move'].create({
            'name': 'Farm move',
            'product_id': unrelated_move.product_id.id,
            'product_uom_qty': 1.0,
            'product_uom': self.env.ref('uom.product_uom_unit').id,
            'location_id': warehouse.lot_stock_id.id,
            'location_dest_id': warehouse.lot_stock_id.id,
            'daily_report_id': report.id,
        })

        visible = self.env['stock.move'].with_user(self.farm_user).search([
            ('id', 'in', (unrelated_move | farm_move).ids),
        ])
        self.assertEqual(visible, farm_move)

    def test_farm_manager_can_create_harvest_batch_receipt(self):
        # Regression test: stock_move_farm_rule originally only allowed moves
        # with daily_report_id set, which broke action_create_receipt() for
        # any non-admin farm user — harvest batch receipts have no
        # daily_report_id, only harvest_batch_id. Also regression-tests the
        # stock.location ACL (previously missing entirely) and confirms
        # group_farm_manager's implied stock.group_stock_user is enough for
        # picking.action_confirm()'s internal reordering-rule checks.
        # Only group_farm_manager (not group_farm_user) can do this — see
        # the "Create Receipt"/"Validate Receipt" button `groups=` in
        # cultivation_project_views.xml.
        product = self.env['product.product'].create({
            'name': 'Sec Test Harvest Crop',
            'type': 'consu',
            'is_storable': True,
        })
        self.crop.write({'product_id': product.id})

        batch = self.env['farm.harvest.batch'].with_user(self.farm_manager).create({
            'project_id': self.project.id,
            'date': date(2026, 2, 1),
            'quantity': 100.0,
            'uom_id': self.env.ref('uom.product_uom_unit').id,
            'price_unit': 5.0,
        })
        batch.with_user(self.farm_manager).action_create_receipt()

        self.assertEqual(batch.state, 'receipt_created')
        self.assertTrue(batch.picking_id)
        farm_move = batch.picking_id.move_ids
        self.assertTrue(farm_move.harvest_batch_id, "stock.move should carry harvest_batch_id")

        visible = self.env['stock.move'].with_user(self.farm_manager).search([
            ('id', 'in', farm_move.ids),
        ])
        self.assertEqual(visible, farm_move)

    def test_farm_user_sees_stock_moves_from_a_farm_sale_order_delivery(self):
        # Regression test: stock_move_farm_rule only accounted for
        # daily_report_id/harvest_batch_id, missing the standard sale_stock
        # flow entirely — a delivery's stock.move for a farm-linked sale
        # order links back via sale_line_id, not either of those two fields.
        # This made deliveries for farm sale orders appear to have "no
        # products" to farm users, since every move was invisibly filtered.
        product = self.env['product.product'].create({
            'name': 'Sec Test Sale Crop', 'type': 'consu', 'is_storable': True,
        })
        order = self.env['sale.order'].create({
            'partner_id': self.partner.id,
            'cultivation_project_id': self.project.id,
        })
        order_line = self.env['sale.order.line'].create({
            'order_id': order.id,
            'product_id': product.id,
            'product_uom_qty': 1.0,
        })
        warehouse = self.env['stock.warehouse'].search([('company_id', '=', self.env.company.id)], limit=1)
        unrelated_move = self.env['stock.move'].create({
            'name': 'Unrelated move',
            'product_id': product.id,
            'product_uom_qty': 1.0,
            'product_uom': self.env.ref('uom.product_uom_unit').id,
            'location_id': warehouse.lot_stock_id.id,
            'location_dest_id': warehouse.lot_stock_id.id,
        })
        sale_move = self.env['stock.move'].create({
            'name': 'Sale delivery move',
            'product_id': product.id,
            'product_uom_qty': 1.0,
            'product_uom': self.env.ref('uom.product_uom_unit').id,
            'location_id': warehouse.lot_stock_id.id,
            'location_dest_id': warehouse.lot_stock_id.id,
            'sale_line_id': order_line.id,
        })

        visible = self.env['stock.move'].with_user(self.farm_user).search([
            ('id', 'in', (unrelated_move | sale_move).ids),
        ])
        self.assertEqual(visible, sale_move)

    def test_farm_user_sees_pickings_and_move_lines_from_a_farm_sale_order(self):
        # Regression test: stock.picking and stock.move.line both had ACL
        # grants for group_farm_user but NO ir.rule at all — a farm user
        # could see every delivery/receipt/transfer and every move line in
        # the company, completely bypassing the scoping built for
        # stock.move. Found during a security audit, not a user report.
        product = self.env['product.product'].create({
            'name': 'Sec Test Picking Crop', 'type': 'consu', 'is_storable': True,
        })
        order = self.env['sale.order'].create({
            'partner_id': self.partner.id,
            'cultivation_project_id': self.project.id,
        })
        order_line = self.env['sale.order.line'].create({
            'order_id': order.id,
            'product_id': product.id,
            'product_uom_qty': 1.0,
        })
        warehouse = self.env['stock.warehouse'].search([('company_id', '=', self.env.company.id)], limit=1)

        unrelated_picking = self.env['stock.picking'].create({
            'picking_type_id': warehouse.out_type_id.id,
            'location_id': warehouse.lot_stock_id.id,
            'location_dest_id': self.env.ref('stock.stock_location_customers').id,
        })
        unrelated_move = self.env['stock.move'].create({
            'name': 'Unrelated move',
            'product_id': product.id,
            'product_uom_qty': 1.0,
            'product_uom': self.env.ref('uom.product_uom_unit').id,
            'location_id': warehouse.lot_stock_id.id,
            'location_dest_id': self.env.ref('stock.stock_location_customers').id,
            'picking_id': unrelated_picking.id,
        })
        unrelated_move_line = self.env['stock.move.line'].create({
            'move_id': unrelated_move.id,
            'product_id': product.id,
            'product_uom_id': self.env.ref('uom.product_uom_unit').id,
            'location_id': warehouse.lot_stock_id.id,
            'location_dest_id': self.env.ref('stock.stock_location_customers').id,
            'picking_id': unrelated_picking.id,
            'quantity': 1.0,
        })

        farm_picking = self.env['stock.picking'].create({
            'picking_type_id': warehouse.out_type_id.id,
            'location_id': warehouse.lot_stock_id.id,
            'location_dest_id': self.env.ref('stock.stock_location_customers').id,
        })
        farm_move = self.env['stock.move'].create({
            'name': 'Farm sale delivery move',
            'product_id': product.id,
            'product_uom_qty': 1.0,
            'product_uom': self.env.ref('uom.product_uom_unit').id,
            'location_id': warehouse.lot_stock_id.id,
            'location_dest_id': self.env.ref('stock.stock_location_customers').id,
            'picking_id': farm_picking.id,
            'sale_line_id': order_line.id,
        })
        farm_move_line = self.env['stock.move.line'].create({
            'move_id': farm_move.id,
            'product_id': product.id,
            'product_uom_id': self.env.ref('uom.product_uom_unit').id,
            'location_id': warehouse.lot_stock_id.id,
            'location_dest_id': self.env.ref('stock.stock_location_customers').id,
            'picking_id': farm_picking.id,
            'quantity': 1.0,
        })

        visible_pickings = self.env['stock.picking'].with_user(self.farm_user).search([
            ('id', 'in', (unrelated_picking | farm_picking).ids),
        ])
        self.assertEqual(visible_pickings, farm_picking)

        visible_move_lines = self.env['stock.move.line'].with_user(self.farm_user).search([
            ('id', 'in', (unrelated_move_line | farm_move_line).ids),
        ])
        self.assertEqual(visible_move_lines, farm_move_line)

    def test_farm_user_sees_invoice_from_a_farm_sale_order(self):
        # Same gap as above, for account_move_farm_rule: a customer invoice
        # generated from a farm sale order links back via
        # invoice_line_ids.sale_line_ids, not daily_report_id (which is only
        # ever set on vendor bills from daily reports).
        product = self.env['product.product'].create({
            'name': 'Sec Test Invoice Crop', 'type': 'consu', 'is_storable': True,
        })
        order = self.env['sale.order'].create({
            'partner_id': self.partner.id,
            'cultivation_project_id': self.project.id,
        })
        order_line = self.env['sale.order.line'].create({
            'order_id': order.id,
            'product_id': product.id,
            'product_uom_qty': 1.0,
        })
        unrelated_invoice = self.env['account.move'].create({
            'move_type': 'out_invoice',
            'partner_id': self.partner.id,
        })
        farm_invoice = self.env['account.move'].create({
            'move_type': 'out_invoice',
            'partner_id': self.partner.id,
            'invoice_line_ids': [(0, 0, {
                'product_id': product.id,
                'quantity': 1.0,
                'price_unit': 10.0,
                'sale_line_ids': [(6, 0, [order_line.id])],
            })],
        })

        visible = self.env['account.move'].with_user(self.farm_user).search([
            ('id', 'in', (unrelated_invoice | farm_invoice).ids),
        ])
        self.assertEqual(visible, farm_invoice)

    def test_farm_accountant_only_sees_journal_entries_linked_to_farm_sale_orders(self):
        # Regression test: account_move_farm_rule's `groups` only listed
        # group_farm_user, even though group_farm_accountant has its own
        # read-only ACL grant on account.move (access_account_move_farm_accountant)
        # and is documented as a "read-only financial view of farm operations".
        # Without the rule covering this group too, a user with ONLY
        # group_farm_accountant could read every journal entry/vendor bill in
        # the company, not just farm-linked ones.
        farm_accountant = self.env['res.users'].create({
            'name': 'Farm Accountant Test',
            'login': 'farm_accountant_security_test',
            'groups_id': [(6, 0, [self.env.ref('farm_management.group_farm_accountant').id])],
        })
        product = self.env['product.product'].create({
            'name': 'Sec Test Accountant Crop', 'type': 'consu', 'is_storable': True,
        })
        order = self.env['sale.order'].create({
            'partner_id': self.partner.id,
            'cultivation_project_id': self.project.id,
        })
        order_line = self.env['sale.order.line'].create({
            'order_id': order.id, 'product_id': product.id, 'product_uom_qty': 1.0,
        })
        unrelated_invoice = self.env['account.move'].create({
            'move_type': 'out_invoice', 'partner_id': self.partner.id,
        })
        farm_invoice = self.env['account.move'].create({
            'move_type': 'out_invoice',
            'partner_id': self.partner.id,
            'invoice_line_ids': [(0, 0, {
                'product_id': product.id, 'quantity': 1.0, 'price_unit': 10.0,
                'sale_line_ids': [(6, 0, [order_line.id])],
            })],
        })

        visible = self.env['account.move'].with_user(farm_accountant).search([
            ('id', 'in', (unrelated_invoice | farm_invoice).ids),
        ])
        self.assertEqual(visible, farm_invoice)

    def test_farm_user_cannot_create_harvest_batch_receipt(self):
        # A plain farm_user (not manager) lacks stock.group_stock_user, so
        # the underlying stock-module permission checks correctly deny this
        # even though farm.harvest.batch's own ACL would otherwise allow it.
        product = self.env['product.product'].create({
            'name': 'Sec Test Harvest Crop 2',
            'type': 'consu',
            'is_storable': True,
        })
        self.crop.write({'product_id': product.id})

        batch = self.env['farm.harvest.batch'].with_user(self.farm_user).create({
            'project_id': self.project.id,
            'date': date(2026, 2, 1),
            'quantity': 50.0,
            'uom_id': self.env.ref('uom.product_uom_unit').id,
            'price_unit': 5.0,
        })
        with self.assertRaises(AccessError):
            batch.with_user(self.farm_user).action_create_receipt()

    def test_crop_bom_line_multi_company_rule(self):
        # Regression test: farm.crop.bom.line has its own company_id field
        # (added for check_company support) and full ACL grants, but had no
        # multi-company ir.rule — found via a security audit, not a report.
        # A user restricted to the default company must not see BOM lines
        # belonging to a different company's BOM.
        company2 = self.env['res.company'].create({'name': 'Sec Test Other Co'})
        category = self.env['product.category'].create({'name': 'Sec Test Category'})
        product = self.env['product.product'].create({
            'name': 'Sec Test BOM Product', 'type': 'consu', 'is_storable': True,
            'categ_id': category.id,
        })
        other_bom = self.env['farm.crop.bom'].create({
            'name': 'Other Co BOM', 'crop_id': self.crop.id, 'company_id': company2.id,
        })
        other_line = self.env['farm.crop.bom.line'].create({
            'bom_id': other_bom.id,
            'input_type_category_id': category.id,
            'product_id': product.id,
        })

        single_company_user = self.env['res.users'].create({
            'name': 'Single Company Test User',
            'login': 'single_company_bom_test',
            'company_id': self.env.company.id,
            'company_ids': [(6, 0, [self.env.company.id])],
            'groups_id': [(6, 0, [self.env.ref('farm_management.group_farm_manager').id])],
        })

        visible = self.env['farm.crop.bom.line'].with_user(single_company_user).search([
            ('id', '=', other_line.id),
        ])
        self.assertFalse(visible, "BOM line from a different company must not be visible")

    def test_daily_report_line_multi_company_rule(self):
        # Regression test: farm.daily.report.line has no own company_id but
        # is reachable via report_id.company_id, and had full CRUD ACL
        # (including unlink) with no multi-company ir.rule at all.
        company2 = self.env['res.company'].create({'name': 'Sec Test Other Co 2'})
        farm2 = self.env['farm.farm'].create({
            'name': 'Other Co Farm', 'area': 10.0, 'company_id': company2.id,
        })
        field2 = self.env['farm.field'].create({
            'name': 'Other Co Field', 'farm_id': farm2.id, 'area': 5.0,
        })
        crop2 = self.env['farm.crop'].create({'name': 'Other Co Crop', 'company_id': company2.id})
        project2 = self.env['farm.cultivation.project'].create({
            'name': 'Other Co Project',
            'farm_id': farm2.id,
            'field_id': field2.id,
            'crop_id': crop2.id,
            'start_date': date(2026, 1, 1),
            'planned_end_date': date(2026, 4, 1),
        })
        report2 = self.env['farm.daily.report'].create({
            'project_id': project2.id,
            'date': date(2026, 1, 5),
            'operation_type': 'inspection',
            'irrigation_duration': 0.0,
        })
        product = self.env['product.product'].create({
            'name': 'Sec Test Report Line Product', 'type': 'service',
        })
        other_line = self.env['farm.daily.report.line'].create({
            'report_id': report2.id,
            'product_id': product.id,
            'quantity': 1.0,
            'line_type': 'other',
        })

        single_company_user = self.env['res.users'].create({
            'name': 'Single Company Test User 2',
            'login': 'single_company_report_test',
            'company_id': self.env.company.id,
            'company_ids': [(6, 0, [self.env.company.id])],
            'groups_id': [(6, 0, [self.env.ref('farm_management.group_farm_manager').id])],
        })

        visible = self.env['farm.daily.report.line'].with_user(single_company_user).search([
            ('id', '=', other_line.id),
        ])
        self.assertFalse(visible, "Daily report line from a different company must not be visible")
