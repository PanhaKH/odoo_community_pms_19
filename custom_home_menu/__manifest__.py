{
    'name': 'Premium Home Menu - Community Edition',
    'version': '19.0.1.0.0',
    'category': 'Web',
    'summary': 'Custom full-page grid layout for home menu',
    'description': """
        This module replaces the default Odoo home menu dropdown with a 
        full-page grid layout showing app icons on a light purple background.
    """,
    'author': 'Rashid Habib',
    'depends': ['web'],
    'data': [
        # No data files needed - pure JavaScript implementation
    ],
    'assets': {
        'web.assets_backend': [
            'custom_home_menu/static/src/js/custom_home_menu.js',
            'custom_home_menu/static/src/scss/custom_home_menu.scss',
        ],
    },
    'installable': True,
    'auto_install': False,
    'application': True,
    'license': 'OPL-1',
    'price': 0.00,
    'currency': 'USD',
    'images': ['static/description/screenshot_main.png'],
}
