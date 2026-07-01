{
    'name': 'Housekeeping Mobile App',
    'version': '1.0',
    'category': 'Operations',
    'summary': 'Standalone mobile app for hotel cleaning staff',
    'author': 'Your Name or Company',
    'license': 'LGPL-3',
    # THE INHERITANCE: We depend on your main hotel module!
    'depends': ['hotel_management'],
    'application': True,
    'installable': True,
    'data': [
        'security/housekeeping_security.xml',
        'security/ir.model.access.csv',
        'views/housekeeping_inspection_views.xml',
        'views/housekeeping_inspection_templates.xml',
        'views/housekeeping_app_menus.xml',
        'views/housekeeping_reservation_review_views.xml',
    ],
}
