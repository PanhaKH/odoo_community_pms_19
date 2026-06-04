from odoo import models, fields, tools

class HotelRevenueReport(models.Model):
    _name = 'hotel.revenue.report'
    _description = 'Daily Revenue & Occupancy Report'
    _auto = False  # This tells Odoo not to make a standard table, but to use our SQL view!

    date = fields.Date(string="Transaction Date", readonly=True)
    reservation_id = fields.Many2one('hotel.reservation', string="Reservation", readonly=True)
    room_id = fields.Many2one('hotel.room', string="Room", readonly=True)
    room_type_id = fields.Many2one('hotel.room.type', string="Room Type", readonly=True)
    revenue_type = fields.Selection([
        ('forecast', 'Forecast'),
        ('actual', 'Actual'),
    ], string="Revenue Type", readonly=True)
    state = fields.Selection([
        ('draft', 'Draft'), ('confirm', 'Confirmed'), ('checkin', 'In-House'),
        ('checkout_hold', 'Checkout Hold'), ('checkout', 'Checked Out'),
        ('blocked', 'Blocked')
    ], string="Status", readonly=True)
    
    # Daily Metrics for the Graph
    daily_revenue = fields.Float(string="Daily Revenue", readonly=True)
    folio_total = fields.Float(string="Folio Total", readonly=True)
    occupied_count = fields.Integer(string="Rooms Occupied", readonly=True)

    def init(self):
        tools.drop_view_if_exists(self.env.cr, self._table)
        self.env.cr.execute("""
            CREATE OR REPLACE VIEW %s AS (
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
                actual_line_totals AS (
                    SELECT
                        COALESCE(sol.hotel_reservation_id, uor.reservation_id) AS reservation_id,
                        sol.hotel_business_date::date AS business_date,
                        SUM(sol.price_subtotal) AS daily_revenue,
                        SUM(sol.price_total) AS folio_total
                    FROM sale_order_line sol
                    LEFT JOIN unique_order_reservation uor
                        ON uor.order_id = sol.order_id
                    WHERE sol.display_type IS NULL
                      AND sol.hotel_business_date IS NOT NULL
                      AND COALESCE(sol.hotel_reservation_id, uor.reservation_id) IS NOT NULL
                    GROUP BY
                        COALESCE(sol.hotel_reservation_id, uor.reservation_id),
                        sol.hotel_business_date::date
                ),
                forecast_rows AS (
                    SELECT
                        res.id AS reservation_id,
                        res.room_id AS room_id,
                        res.room_type_id AS room_type_id,
                        res.state AS state,
                        'forecast'::varchar AS revenue_type,
                        d.date::date AS date,
                        COALESCE(res.total_amount / NULLIF(res.duration, 0), 0.0) AS daily_revenue,
                        COALESCE(res.total_amount / NULLIF(res.duration, 0), 0.0) AS folio_total,
                        1 AS occupied_count
                    FROM hotel_reservation res
                    JOIN res_company company
                        ON company.id = res.company_id
                    CROSS JOIN LATERAL generate_series(
                        (res.checkin_date + interval '1 day')::timestamp,
                        res.checkout_date::timestamp,
                        interval '1 day'
                    ) AS d(date)
                    WHERE res.state = 'confirm'
                      AND res.is_desk_folio = FALSE
                      AND res.checkin_date < res.checkout_date
                      AND d.date::date >= COALESCE(company.hotel_business_date, res.checkin_date)
                ),
                actual_rows AS (
                    SELECT
                        res.id AS reservation_id,
                        res.room_id AS room_id,
                        res.room_type_id AS room_type_id,
                        res.state AS state,
                        'actual'::varchar AS revenue_type,
                        d.date::date AS date,
                        COALESCE(alt.daily_revenue, 0.0) AS daily_revenue,
                        COALESCE(alt.folio_total, 0.0) AS folio_total,
                        1 AS occupied_count
                    FROM hotel_reservation res
                    JOIN res_company company
                        ON company.id = res.company_id
                    CROSS JOIN LATERAL generate_series(
                        (res.checkin_date + interval '1 day')::timestamp,
                        (
                            CASE
                                WHEN res.state IN ('checkin', 'checkout_hold')
                                    THEN LEAST(res.checkout_date, COALESCE(company.hotel_business_date, res.checkout_date))
                                ELSE res.checkout_date
                            END
                        )::timestamp,
                        interval '1 day'
                    ) AS d(date)
                    LEFT JOIN actual_line_totals alt
                        ON alt.reservation_id = res.id
                       AND alt.business_date = d.date::date
                    WHERE res.state IN ('checkin', 'checkout_hold', 'checkout')
                      AND res.is_desk_folio = FALSE
                      AND res.checkin_date < (
                          CASE
                              WHEN res.state IN ('checkin', 'checkout_hold')
                                  THEN LEAST(res.checkout_date, COALESCE(company.hotel_business_date, res.checkout_date))
                              ELSE res.checkout_date
                          END
                      )
                ),
                actual_adjustment_rows AS (
                    SELECT
                        res.id AS reservation_id,
                        res.room_id AS room_id,
                        res.room_type_id AS room_type_id,
                        res.state AS state,
                        'actual'::varchar AS revenue_type,
                        alt.business_date AS date,
                        alt.daily_revenue AS daily_revenue,
                        alt.folio_total AS folio_total,
                        0 AS occupied_count
                    FROM actual_line_totals alt
                    JOIN hotel_reservation res
                        ON res.id = alt.reservation_id
                    WHERE res.state IN ('checkin', 'checkout_hold', 'checkout')
                      AND res.is_desk_folio = FALSE
                      AND NOT EXISTS (
                          SELECT 1
                          FROM generate_series(
                              (res.checkin_date + interval '1 day')::timestamp,
                              res.checkout_date::timestamp,
                              interval '1 day'
                          ) AS d(date)
                          WHERE d.date::date = alt.business_date
                      )
                ),
                combined AS (
                    SELECT * FROM forecast_rows
                    UNION ALL
                    SELECT * FROM actual_rows
                    UNION ALL
                    SELECT * FROM actual_adjustment_rows
                )
                SELECT
                    row_number() OVER (ORDER BY combined.date, combined.reservation_id, combined.revenue_type) AS id,
                    combined.date AS date,
                    combined.reservation_id AS reservation_id,
                    combined.room_id AS room_id,
                    combined.room_type_id AS room_type_id,
                    combined.revenue_type AS revenue_type,
                    combined.state AS state,
                    combined.daily_revenue AS daily_revenue,
                    combined.folio_total AS folio_total,
                    combined.occupied_count AS occupied_count
                FROM combined
            )
        """ % (self._table,))
