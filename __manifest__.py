{
    'name': 'Farm Management System',
    'version': '18.0.1.1.3',
    'summary': 'Comprehensive farm management for Odoo 18',
    'description': """
        This module provides a complete Farm Management System for Odoo 18.
        Features include:
        - Farm and Field Management
        - Crop Planning and Tracking
        - Cultivation Projects with Cost Analysis
        - Input and Resource Management
        - Seasonal Planning
        - Daily Operations and Reporting
        - Integration with Inventory, Accounting and Project Management
    """,
    'category': 'Agriculture',
    'author': 'Khaled Abdellaty',
    'website': 'https://www.yourcompany.com',
    'license': 'LGPL-3',
    'depends': [
        'stock',
        'account',
        'analytic',
        'project',
        'hr_timesheet',
        'web',
        'sale',
        'sale_stock',
        'purchase',
        'product',
    ],
    # Translation settings
    'application': True,
    'installable': True,
    'auto_install': False,
    'sequence': 1,  # Higher priority for translation extraction
    'data': [
        'security/farm_security.xml',
        'security/ir.model.access.csv',
        'data/farm_sequence.xml',
        'data/crop_sequence.xml',
        'data/product_category_data.xml',
        'views/farm_views.xml',
        'views/field_views.xml',
        'views/crop_views.xml',
        'views/cultivation_project_views.xml',
        'views/crop_bom_views.xml',
        'views/daily_report_views.xml',
        'views/cost_analysis_views.xml',
        'views/farm_stock_views.xml',
        'views/farm_menu.xml',
    ],
    'demo': [],
    'images': ['static/description/icon.png'],
}
