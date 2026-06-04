from odoo import models, fields, api

class AccountPayment(models.Model):
    _inherit = 'account.payment'

    hotel_receipt_number = fields.Char(string="Hotel Receipt No.", help="Manual receipt number.")
    
    # Links
    hotel_reservation_id = fields.Many2one('hotel.reservation', string="Reservation", compute='_compute_hotel_info', store=True)
    folio_id = fields.Many2one('sale.order', string="Folio", compute='_compute_hotel_info', store=True)
    
    # --- FIX: Changed store=True so you can SORT by Invoice Number ---
    hotel_invoice_ref = fields.Char(string="Invoice No.", compute='_compute_invoice_ref', store=True)
    hotel_payment_activity_type = fields.Selection(
        [
            ('advance_deposit', 'Advance Deposit'),
            ('invoice_payment', 'Invoice Payment'),
            ('deposit_void', 'Deposit Void / Refund'),
            ('other', 'Other Hotel Payment'),
        ],
        string="Activity",
        compute='_compute_hotel_payment_activity_type',
        store=True,
    )

    @api.depends('memo', 'partner_id', 'date', 'reconciled_invoice_ids.invoice_origin', 'reconciled_invoice_ids.invoice_line_ids.sale_line_ids')
    def _compute_hotel_info(self):
        for rec in self:
            found_res = False
            
            # 1. Explicit Reference Match (Advance Deposits)
            if rec.memo:
                found_res = self.env['hotel.reservation'].search([('name', '=', rec.memo)], limit=1)

            # 2. THE FIX: Trace back through the connected Invoice to the Folio!
            if not found_res and rec.reconciled_invoice_ids:
                for inv in rec.reconciled_invoice_ids:
                    # Approach A: Look through the invoice lines directly to the Sale Order
                    sale_orders = inv.invoice_line_ids.mapped('sale_line_ids.order_id')
                    if sale_orders:
                        found_res = self.env['hotel.reservation'].search([('sale_order_id', 'in', sale_orders.ids)], limit=1)
                    
                    # Approach B: Text matching fallback
                    if not found_res and inv.invoice_origin:
                        # Did it match the Folio name? (e.g. S00004)
                        folio = self.env['sale.order'].search([('name', '=', inv.invoice_origin)], limit=1)
                        if folio:
                            found_res = self.env['hotel.reservation'].search([('sale_order_id', '=', folio.id)], limit=1)
                        # Did it match the Reservation name directly?
                        if not found_res:
                            found_res = self.env['hotel.reservation'].search([('name', '=', inv.invoice_origin)], limit=1)
                            
                    if found_res:
                        break

            # 3. Fallback: Find an active In-House guest
            if not found_res and rec.partner_id:
                found_res = self.env['hotel.reservation'].search([
                    ('partner_id', '=', rec.partner_id.id),
                    ('checkin_date', '<=', rec.date),
                    ('checkout_date', '>=', rec.date),
                    ('state', '!=', 'cancel')
                ], limit=1, order='id desc')

            rec.hotel_reservation_id = found_res.id if found_res else False
            rec.folio_id = found_res.sale_order_id.id if found_res else False

    # FIX: Added 'move_id.line_ids' dependency to ensure it updates when you reconcile
    @api.depends('reconciled_invoice_ids', 'reconciled_bill_ids', 'move_id.line_ids')
    def _compute_invoice_ref(self):
        for rec in self:
            invoices = rec.reconciled_invoice_ids
            if invoices:
                rec.hotel_invoice_ref = ", ".join(invoices.mapped('name'))
            else:
                rec.hotel_invoice_ref = ""

    @api.depends('is_advance_deposit', 'payment_type', 'hotel_invoice_ref')
    def _compute_hotel_payment_activity_type(self):
        for rec in self:
            if rec.is_advance_deposit and rec.payment_type == 'outbound':
                rec.hotel_payment_activity_type = 'deposit_void'
            elif rec.is_advance_deposit:
                rec.hotel_payment_activity_type = 'advance_deposit'
            elif rec.hotel_invoice_ref:
                rec.hotel_payment_activity_type = 'invoice_payment'
            else:
                rec.hotel_payment_activity_type = 'other'

    def _get_hotel_receipt_reservation(self):
        self.ensure_one()
        reservation = self.hotel_reservation_id
        if not reservation and self.memo:
            reservation = self.env['hotel.reservation'].search([('name', '=', self.memo)], limit=1)
        if not reservation and self.folio_id:
            reservation = self.folio_id.hotel_reservation_ids.filtered(lambda res: res.state != 'cancel')[:1]
        return reservation

    def _get_advance_deposit_receipt_data(self):
        self.ensure_one()
        reservation = self._get_hotel_receipt_reservation()
        total_value = reservation._get_hotel_document_total_amount() if reservation else (self.amount or 0.0)
        remaining_balance = max(total_value - (reservation.folio_paid if reservation else self.amount), 0.0)
        generated_on_display = fields.Datetime.context_timestamp(
            self, fields.Datetime.now()
        ).strftime('%Y-%m-%d %H:%M:%S')

        if reservation and reservation.folio_type == 'group_master' and reservation.city_ledger_id:
            account_name = reservation.city_ledger_id.name
        elif reservation and reservation.partner_id:
            account_name = reservation.partner_id.name
        else:
            account_name = self.partner_id.name or ''

        return {
            'reservation': reservation,
            'receipt_number': self.hotel_receipt_number or self.name,
            'business_date': self.hotel_business_date or self.date,
            'reservation_number': reservation.name if reservation else (self.memo or ''),
            'account_name': account_name,
            'guest_name': reservation.partner_id.name if reservation and reservation.partner_id else (self.partner_id.name or ''),
            'folio_type': reservation.folio_type if reservation else '',
            'stay_from': reservation.checkin_date if reservation else False,
            'stay_to': reservation.checkout_date if reservation else False,
            'payment_method': self.journal_id.name or '',
            'cashier_name': self.create_uid.name or '',
            'deposit_received': self.amount or 0.0,
            'total_reservation_value': total_value,
            'remaining_balance': remaining_balance,
            'generated_on_display': generated_on_display,
        }

    def action_print_advance_deposit_receipt(self):
        self.ensure_one()
        return self.env.ref('hotel_management.action_report_advance_deposit_receipt').report_action(self)

class AccountPaymentRegister(models.TransientModel):
    _inherit = 'account.payment.register'

    hotel_receipt_number = fields.Char(string="Hotel Receipt No.")
    hotel_reservation_id = fields.Many2one('hotel.reservation', string="Reservation")
    folio_id = fields.Many2one('sale.order', string="Folio / Order")
    hotel_business_date = fields.Date(string="Hotel Business Date")
    is_advance_deposit = fields.Boolean(string="Advance Deposit")

    def _add_hotel_payment_vals(self, payment_vals):
        if self.hotel_reservation_id:
            payment_vals['hotel_reservation_id'] = self.hotel_reservation_id.id
        if self.hotel_business_date:
            payment_vals['hotel_business_date'] = self.hotel_business_date
        if self.is_advance_deposit and self.hotel_reservation_id:
            payment_vals['memo'] = self.hotel_reservation_id.name
        return payment_vals

    def _create_payment_vals_from_wizard(self, batch_result):
        payment_vals = super()._create_payment_vals_from_wizard(batch_result)
        return self._add_hotel_payment_vals(payment_vals)

    def _create_payment_vals_from_batch(self, batch_result):
        payment_vals = super()._create_payment_vals_from_batch(batch_result)
        return self._add_hotel_payment_vals(payment_vals)

    def _create_payments(self):
        payments = super()._create_payments()
        for payment in payments:
            payment.write({
                'hotel_receipt_number': self.hotel_receipt_number,
            })
        return payments
