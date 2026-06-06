import base64
import logging

from markupsafe import Markup

from odoo import models, fields, api, _


_logger = logging.getLogger(__name__)

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
        deposit_received_to_date = reservation.guest_deposit_paid_total if reservation else (self.amount or 0.0)
        remaining_balance = max(total_value - deposit_received_to_date, 0.0)
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
            'deposit_received_to_date': deposit_received_to_date,
            'total_reservation_value': total_value,
            'remaining_balance': remaining_balance,
            'generated_on_display': generated_on_display,
        }

    def action_print_advance_deposit_receipt(self):
        self.ensure_one()
        return self.env.ref('hotel_management.action_report_advance_deposit_receipt').report_action(self)

    def _send_advance_deposit_receipt_email_safely(self):
        for payment in self:
            reservation = payment._get_hotel_receipt_reservation()
            if (
                not reservation
                or not payment.is_advance_deposit
                or payment.payment_type != 'inbound'
                or not reservation.company_id.hotel_deposit_required
                or not reservation.company_id.hotel_auto_email_deposit_receipt
            ):
                continue

            recipient = (reservation.partner_email or reservation.partner_id.email or payment.partner_id.email or '').strip()
            subject = _("Deposit Receipt - %s") % (reservation.name or payment.name or '')
            if not recipient:
                reservation._create_email_audit(
                    'deposit_receipt',
                    '-',
                    'failed',
                    subject,
                    failure_reason=_("Guest email is missing."),
                )
                reservation.message_post(
                    body=_("Deposit Receipt email was not sent: guest email is missing."),
                    subtype_xmlid='mail.mt_note',
                )
                continue

            try:
                pdf_content, _content_type = self.env['ir.actions.report'].sudo()._render_qweb_pdf(
                    'hotel_management.action_report_advance_deposit_receipt',
                    res_ids=payment.id,
                )
                attachment = self.env['ir.attachment'].sudo().create({
                    'name': 'Deposit_Receipt_%s.pdf' % (payment.name or payment.id),
                    'type': 'binary',
                    'datas': base64.b64encode(pdf_content),
                    'res_model': 'account.payment',
                    'res_id': payment.id,
                    'mimetype': 'application/pdf',
                })
                template = self.env.ref('hotel_management.email_template_advance_deposit_receipt', raise_if_not_found=False)
                if template:
                    mail_id = template.with_context(deposit_receipt_attachment_id=attachment.id).send_mail(
                        payment.id,
                        force_send=True,
                        email_values={'attachment_ids': [(4, attachment.id)]},
                    )
                    mail = self.env['mail.mail'].sudo().browse(mail_id).exists()
                else:
                    body = _(
                        "Dear %(guest)s,<br/><br/>"
                        "Thank you for your deposit payment.<br/><br/>"
                        "Please find attached your Deposit Receipt.<br/><br/>"
                        "Reservation: %(reservation)s<br/>"
                        "Guest: %(guest)s<br/><br/>"
                        "We look forward to welcoming you.<br/><br/>"
                        "Best Regards,<br/>%(company)s"
                    ) % {
                        'guest': reservation.partner_id.name or payment.partner_id.name or _('Guest'),
                        'reservation': reservation.name or '',
                        'company': reservation.company_id.name or '',
                    }
                    mail = self.env['mail.mail'].sudo().create({
                        'subject': subject,
                        'email_to': recipient,
                        'body_html': body,
                        'attachment_ids': [(4, attachment.id)],
                    })
                    mail.send()

                reservation._create_email_audit(
                    'deposit_receipt',
                    recipient,
                    'sent',
                    subject,
                    mail=mail,
                    attachment=attachment,
                )
                reservation.message_post(
                    body=Markup("<b>Deposit Receipt emailed to guest.</b><br/>Recipient: %s") % recipient,
                    subtype_xmlid='mail.mt_note',
                )
            except Exception as error:
                _logger.exception("Deposit receipt email failed for payment_id=%s reservation_id=%s", payment.id, reservation.id)
                reservation._create_email_audit(
                    'deposit_receipt',
                    recipient,
                    'failed',
                    subject,
                    failure_reason=str(error),
                )
                reservation.message_post(
                    body=_("Deposit Receipt email failed for %(email)s: %(reason)s")
                    % {'email': recipient, 'reason': str(error)},
                    subtype_xmlid='mail.mt_note',
                )

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
