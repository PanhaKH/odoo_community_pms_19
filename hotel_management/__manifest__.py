{
    'name': 'Hotel Management System',
    'version': '19.0.1.0.0',
    'summary': 'Complete Hotel Reservation, Front Desk, and Housekeeping System',
    'sequence': -100,
    'description': """Hotel Management Solution""",
    'category': 'Industries/Hotel',
    'images': ['static/description/icon.png'],
    'author': 'Your Name or Company',
    'website': 'https://www.yourcompany.com',
    'depends': ['base', 'mail', 'sale_management', 'maintenance', 'portal', 'website', 'account', 'point_of_sale'],
    'data': [
        'security/hotel_security.xml',
        'security/ir.model.access.csv',
        'data/hotel_nationality_data.xml',
        'data/sequence.xml',
        'data/mail_template_data.xml',  # <-- ADD THIS NEW LINE HERE
        'data/hotel_cron.xml',
        'data/hotel_pos_data.xml',  # <--- ADD YOUR NEW AUTOMATION FILE HERE
        'data/hotel_default_accounts.xml',
        'data/hotel_default_products.xml',
        'data/hotel_default_journals.xml',
        'data/hotel_guest_classification_data.xml',
        'data/hotel_document_template_data.xml',
        'data/hotel_daily_transaction_refresh.xml',
        # --- VIEWS ---
        'views/hotel_room_views.xml',    
        'views/hotel_rate_plan_views.xml',  
        'data/hotel_booking_source_data.xml',
        'views/hotel_reservation_views.xml',
        'views/hotel_dashboard_views.xml',
        'report/hotel_folio_reports.xml',
        'views/pre_arrival_portal_views.xml',
        'wizard/hotel_room_block_wizard_views.xml',
        'views/hotel_housekeeping_views.xml',
        
        'views/hotel_maintenance_views.xml',
        'views/hotel_lost_found_views.xml',
        'views/hotel_service_request_views.xml',
        'views/hotel_email_audit_views.xml',
        'views/hotel_guest_message_views.xml',
        'views/hotel_portal_templates.xml',
        
        # --- NEW PAYMENT & POS VIEWS ---
        'views/hotel_payment_views.xml',
        'views/pos_payment_method_views.xml', # Configuration for "Is Room Charge"
        
        'views/hotel_daily_stats_views.xml',
        'views/hotel_change_log_views.xml',
        
        'views/hotel_print_reports.xml', # <-- ADD THIS LINE!
        'views/hotel_document_template_views.xml',
        # ... other files ...
        'wizard/hotel_split_line_wizard_views.xml',
        # --- MENUS (Load Last) ---
        'views/res_config_settings_views.xml',
        'views/hotel_default_setup_views.xml',
        'views/hotel_menus.xml', 
        'views/hotel_guest_duplicate_review_views.xml',
        'views/hotel_floor_plan_views.xml',
        'views/minibar_charge_wizard_views.xml',
        'views/hotel_housekeeping_mobile_views.xml',
        
    ],
    'assets': {
        'web.assets_backend': [
            # Tape Chart & Grid
            'hotel_management/static/src/css/rooming_board.css',
            'hotel_management/static/src/css/hotel_tape_chart.css',
            'hotel_management/static/src/xml/hotel_tape_chart.xml',
            'hotel_management/static/src/js/hotel_tape_chart.js',
            'hotel_management/static/src/scss/hotel_reservation_form.scss',
            'hotel_management/static/src/scss/availability_grid.scss',
            'hotel_management/static/src/xml/availability_grid.xml',
            'hotel_management/static/src/js/availability_grid.js',
            'hotel_management/static/src/css/tax_audit.css',
            # Occupancy & Reporting
            'hotel_management/static/src/css/hotel_occupancy.css',
            'hotel_management/static/src/js/hotel_occupancy_comparison.js',
            'hotel_management/static/src/xml/hotel_occupancy_comparison.xml',

            'https://cdn.jsdelivr.net/npm/jsqr@1.4.0/dist/jsQR.min.js', # The Scanner "Eyes"
            'hotel_management/static/src/js/express_checkin_barcode.js',
            # Floor Plan / Map
            'hotel_management/static/src/js/hotel_floor_plan.js',
            'hotel_management/static/src/js/hotel_billing_target_field.js',
            #'hotel_management/static/src/js/pos_room_charge.js',
            # Load the Javascript first
            'hotel_management/static/src/js/hotel_quick_toolbar.js',
            # Then load the XML template
            'hotel_management/static/src/xml/hotel_quick_toolbar.xml',
            # The CSS file to shrink the floor plan columns
            'hotel_management/static/src/scss/hotel_floor_plan.scss',
            # Front desk guest chat unread alerts
            'hotel_management/static/src/css/hotel_guest_chat_alert.css',
            'hotel_management/static/src/js/hotel_guest_chat_alert.js',
            'hotel_management/static/src/css/hotel_dashboard_layout.css',
        ],
        
        # --- NEW: POS ASSETS (Required for Restaurant Integration) ---
        'point_of_sale._assets_pos': [
            'hotel_management/static/src/xml/pos_hotel.xml',
            'hotel_management/static/src/js/pos_hotel.js',
            
        ],
    },
    'installable': True,
    'application': True,
    'auto_install': False,
    'license': 'LGPL-3',
    'pre_init_hook': 'pre_init_hook',
    'post_init_hook': 'post_init_hook',
}
