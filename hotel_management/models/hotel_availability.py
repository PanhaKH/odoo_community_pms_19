from odoo import models, fields, api, tools

class HotelAvailabilityReport(models.Model):
    _name = 'hotel.availability.report'
    _description = 'Room Availability Analysis'
    _auto = False  # This tells Odoo to read from a SQL Query, not a normal table
    _order = 'checkin_date desc'

    # Reporting Fields
    checkin_date = fields.Date(string="Date", readonly=True)
    room_id = fields.Many2one('hotel.room', string="Room", readonly=True)
    room_type_id = fields.Many2one('hotel.room.type', string="Room Type", readonly=True)
    partner_id = fields.Many2one('res.partner', string="Guest", readonly=True)
    state = fields.Selection([
        ('draft', 'Draft'),
        ('confirm', 'Confirmed'),
        ('checkin', 'In-House'),
        ('checkout', 'Checked Out'),
        ('noshow', 'No-Show'),
        ('cancel', 'Cancelled'),
    ], string="Booking Status", readonly=True)
    
    # Measures for Charts
    nbr = fields.Integer(string="Count", readonly=True)
    total_revenue = fields.Float(string="Revenue", readonly=True)

    def init(self):
        """
        This SQL query automatically builds the report table 
        whenever you update the module.
        """
        tools.drop_view_if_exists(self.env.cr, self._table)
        self.env.cr.execute("""
            CREATE OR REPLACE VIEW hotel_availability_report AS (
                WITH unique_order_reservation AS (
                    SELECT
                        sale_order_id AS order_id,
                        MIN(id) AS reservation_id
                    FROM hotel_reservation
                    WHERE sale_order_id IS NOT NULL
                      AND is_desk_folio = FALSE
                      AND state != 'cancel'
                    GROUP BY sale_order_id
                    HAVING COUNT(*) = 1
                ),
                allocatable_folio_totals AS (
                    SELECT
                        COALESCE(sol.hotel_reservation_id, uor.reservation_id) AS reservation_id,
                        SUM(sol.price_total) AS total_revenue
                    FROM sale_order_line sol
                    LEFT JOIN unique_order_reservation uor
                        ON uor.order_id = sol.order_id
                    WHERE sol.display_type IS NULL
                      AND COALESCE(sol.hotel_reservation_id, uor.reservation_id) IS NOT NULL
                    GROUP BY COALESCE(sol.hotel_reservation_id, uor.reservation_id)
                )
                SELECT
                    r.id as id,
                    r.checkin_date as checkin_date,
                    r.room_id as room_id,
                    rm.room_type_id as room_type_id,
                    r.partner_id as partner_id,
                    r.state as state,
                    1 as nbr,
                    COALESCE(aft.total_revenue, 0.0) as total_revenue
                FROM
                    hotel_reservation r
                LEFT JOIN 
                    hotel_room rm ON (r.room_id = rm.id)
                LEFT JOIN
                    allocatable_folio_totals aft ON (aft.reservation_id = r.id)
                WHERE
                    r.state != 'cancel' AND r.is_desk_folio = FALSE
            )
        """)
