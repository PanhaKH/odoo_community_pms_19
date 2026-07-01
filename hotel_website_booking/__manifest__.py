{
    'name': 'Hotel Website Booking',
    'version': '19.0.1.0.0',
    'category': 'Website/Hotel',
    'summary': 'Hotel website landing page with live room availability and booking requests',
    'author': 'Your Name or Company',
    'license': 'LGPL-3',
    'depends': ['hotel_management', 'website'],
    'application': False,
    'installable': True,
    'data': [
        'security/ir.model.access.csv',
        'views/hotel_room_type_views.xml',
        'views/hotel_reservation_views.xml',
        'views/hotel_website_templates.xml',
    ],
    'assets': {
        'web.assets_frontend': [
            'hotel_website_booking/static/src/css/hotel_website_booking.css',
            'hotel_website_booking/static/src/js/hotel_booking_validation.js',
        ],
        'website.website_builder_assets': [
            'hotel_website_booking/static/src/css/hotel_website_booking.css',
            'hotel_website_booking/static/src/js/hotel_booking_validation.js',
            'hotel_website_booking/static/src/website_builder/hotel_editable_blocks_plugin.js',
        ],
        'website.assets_inside_builder_iframe': [
            'hotel_website_booking/static/src/css/hotel_website_booking.css',
            'hotel_website_booking/static/src/js/hotel_booking_validation.js',
        ],
    },
}
