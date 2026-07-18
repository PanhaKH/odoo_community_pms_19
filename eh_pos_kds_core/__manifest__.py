# Part of the ERP Heritage POS Displays suite.
{
    'name': 'Kitchen Display Core',
    'version': '19.0.1.0.0',
    'category': 'Point of Sale',
    'summary': 'Shared backend for the ERP Heritage Point of Sale display suite for Odoo 19 Community: the data model, the order routing engine, the realtime backbone and the brand mark behind the Kitchen Display and the Order Status Screen.',
    'description': 'The shared backend for the ERP Heritage Point of Sale display suite. It provides the data model, the order routing engine that sends each product to the right board and lane, the realtime backbone that keeps every screen live, and the server rendered brand mark. Install the Kitchen Display or the Order Status Screen and this comes with them. It depends only on Odoo Community, never on Enterprise.',
    'author': 'ERP Heritage',
    'website': 'https://www.erpheritage.com.au',
    'license': 'OPL-1',
    'depends': ['point_of_sale', 'bus', 'web'],
    'data': [
        'security/ir.model.access.csv',
        'data/eh_kds_cron.xml',
        'views/eh_kds_board_views.xml',
        'views/eh_kds_menus.xml',
    ],
    'assets': {
        'web.assets_backend': ['eh_pos_kds_core/static/src/scss/eh_kds_variables.scss'],
        'point_of_sale._assets_pos': [
            'eh_pos_kds_core/static/src/pos/show_kitchen_status.js',
        ],
    },
    'post_init_hook': 'post_init_hook',
    'installable': True,
    'application': False,
    'auto_install': False,
    'images': ['static/description/banner.gif'],
}
