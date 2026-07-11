from odoo.exceptions import UserError
from odoo.tests import TransactionCase, tagged


@tagged('post_install', '-at_install')
class TestFarmFieldBootstrap(TransactionCase):
    """Regression tests for the merged create() overrides on farm.farm and
    farm.field (previously two/three shadowed create() defs where only the
    last one ever ran)."""

    def test_farm_create_bootstraps_sequence_analytic_and_location(self):
        farm = self.env['farm.farm'].create({'name': 'Test Farm', 'area': 10.0})

        self.assertTrue(farm.code.startswith('FARM'), "sequence code not assigned")
        self.assertNotEqual(farm.code, 'New')
        self.assertTrue(farm.analytic_account_id, "analytic account not bootstrapped")
        self.assertTrue(farm.location_id, "stock location not bootstrapped")

    def test_field_create_bootstraps_sequence_only(self):
        farm = self.env['farm.farm'].create({'name': 'Test Farm 2', 'area': 10.0})
        field = self.env['farm.field'].create({
            'name': 'Test Field',
            'farm_id': farm.id,
            'area': 5.0,
        })

        self.assertTrue(field.code.startswith('FIELD'))
        self.assertNotEqual(field.code, 'New')
        self.assertEqual(field.state, 'available')
        self.assertEqual(field.company_id, farm.company_id)

    def test_field_create_does_not_leave_orphaned_locations(self):
        # Regression: field.py used to build a Customers > Farm > Field stock
        # location hierarchy that nothing ever read (the real hierarchy is
        # built lazily by daily_report.py/harvest_batch.py). That dead code
        # was deleted; this asserts it stays gone.
        farm = self.env['farm.farm'].create({'name': 'Orphan Check Farm', 'area': 10.0})
        field = self.env['farm.field'].create({
            'name': 'Orphan Check Field',
            'farm_id': farm.id,
            'area': 5.0,
        })

        orphans = self.env['stock.location'].search([
            ('name', 'in', [farm.name, field.name]),
        ])
        self.assertFalse(orphans, "field creation should not create any stray stock.location")

    def test_field_rename_does_not_raise(self):
        # Regression: Field.write() used to override rename behavior to sync
        # a (now-deleted) customer-location hierarchy. Plain ORM write() only.
        farm = self.env['farm.farm'].create({'name': 'Rename Farm', 'area': 10.0})
        field = self.env['farm.field'].create({
            'name': 'Rename Field',
            'farm_id': farm.id,
            'area': 5.0,
        })
        field.write({'name': 'Renamed Field'})
        self.assertEqual(field.name, 'Renamed Field')

    def test_crop_rejects_product_from_different_company(self):
        # Regression: farm.crop.product_id had no check_company=True, so a
        # crop could be linked to a product from a different company.
        company2 = self.env['res.company'].create({'name': 'Bootstrap Test Other Co'})
        other_product = self.env['product.product'].create({
            'name': 'Other Co Product', 'type': 'consu', 'is_storable': True,
            'company_id': company2.id,
        })
        with self.assertRaises(UserError):
            self.env['farm.crop'].create({
                'name': 'Cross Company Crop Test',
                'product_id': other_product.id,
            })
