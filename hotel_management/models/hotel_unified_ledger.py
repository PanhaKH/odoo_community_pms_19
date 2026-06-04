from odoo import models, fields, api, tools

class HotelUnifiedLedger(models.Model):
    _name = 'hotel.unified.ledger'
    _description = 'Unified Folio T-Account (Read-Only)'
    _auto = False

    reservation_id = fields.Many2one('hotel.reservation', string="Reservation")
    date = fields.Datetime(string="Date")
    name = fields.Char(string="Description")
    reference = fields.Char(string="Type")
    debit = fields.Monetary(string="Charge (+)", currency_field='currency_id')
    credit = fields.Monetary(string="Payment (-)", currency_field='currency_id')
    running_balance = fields.Monetary(string="Running Balance", currency_field='currency_id')
    currency_id = fields.Many2one('res.currency')
    
    # --- NEW FIELDS ADDED FOR UI COLUMNS ---
    hotel_payment_activity_type = fields.Char(string="Activity")
    partner_id = fields.Many2one('res.partner', string="Guest/Account")
    journal_id = fields.Many2one('account.journal', string="Payment Method")
    
    def init(self):
        tools.drop_view_if_exists(self.env.cr, self._table)
        self.env.cr.execute("""
            CREATE OR REPLACE VIEW %s AS (
                WITH ledger_entries AS (
                    -- 1. Charges from the Folio (Sale Order Lines)
                    SELECT 
                        sol.id AS id,
                        hr.id AS reservation_id,
                        sol.create_date AS date,
                        sol.name AS name,
                        'Charge' AS reference,
                        sol.price_total AS debit,
                        0.0 AS credit,
                        sol.currency_id AS currency_id,
                        -- Injecting NULLs and missing data for Charges
                        NULL::varchar AS hotel_payment_activity_type,
                        hr.partner_id AS partner_id,
                        NULL::integer AS journal_id
                    FROM sale_order_line sol
                    JOIN hotel_reservation hr ON hr.sale_order_id = sol.order_id
                    WHERE sol.is_downpayment IS NOT TRUE 
                      AND (sol.display_type IS NULL OR sol.display_type = '')
                    
                    UNION ALL
                    
                    -- 2. Payments from the Accounting Ledger (account.payment)
                    SELECT 
                        -ap.id AS id, -- Negative ID prevents database collisions
                        ap.hotel_reservation_id AS reservation_id,
                        ap.create_date AS date,
                        COALESCE(ap.hotel_receipt_number, am.name, 'Advance Deposit / Payment') AS name,
                        'Payment' AS reference,
                        0.0 AS debit,
                        ap.amount AS credit,
                        ap.currency_id AS currency_id,
                        -- THE FIX: Injecting actual payment data for Payments
                        ap.hotel_payment_activity_type AS hotel_payment_activity_type,
                        ap.partner_id AS partner_id,
                        ap.journal_id AS journal_id
                    FROM account_payment ap
                    LEFT JOIN account_move am ON ap.move_id = am.id
                    WHERE ap.hotel_reservation_id IS NOT NULL 
                      AND am.state IN ('posted', 'in_process')
                )
                
                -- Calculate the Running Balance using a SQL Window Function
                SELECT 
                    id,
                    reservation_id,
                    date,
                    name,
                    reference,
                    debit,
                    credit,
                    currency_id,
                    hotel_payment_activity_type,
                    partner_id,
                    journal_id,
                    SUM(debit - credit) OVER (PARTITION BY reservation_id ORDER BY date ASC, id ASC) AS running_balance
                FROM ledger_entries
            )
        """ % (self._table,))