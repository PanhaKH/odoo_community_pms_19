from odoo import fields, models, _
from odoo.exceptions import UserError


class HotelTaxInvoiceSignPrintWizard(models.TransientModel):
    _name = 'hotel.tax.invoice.sign.print.wizard'
    _description = 'Tax Invoice Sign and Print'

    reservation_id = fields.Many2one(
        'hotel.reservation',
        string='Reservation',
        required=True,
        readonly=True,
    )

    def _get_reservation(self):
        self.ensure_one()
        reservation = self.reservation_id.exists()
        if not reservation:
            raise UserError(_("The reservation is no longer available."))
        return reservation

    def action_sign_and_print(self):
        reservation = self._get_reservation()
        if not reservation.tax_invoice_staff_signature:
            reservation._snapshot_tax_invoice_staff_signature()
        return reservation._action_print_tax_invoice_report()

    def action_print_without_signature(self):
        reservation = self._get_reservation()
        return reservation._action_print_tax_invoice_report()
