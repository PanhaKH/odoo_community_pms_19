from odoo import fields, models, _
from odoo.exceptions import UserError


class HotelReservationDocumentPrintWizard(models.TransientModel):
    _name = 'hotel.reservation.document.print.wizard'
    _description = 'Reservation Document Print'

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

    def action_print_reservation_confirmation(self):
        return self._get_reservation().action_print_reservation_confirmation()

    def action_print_registration_card(self):
        return self._get_reservation().action_print_registration_card()

    def action_print_tax_invoice(self):
        return self._get_reservation().action_print_tax_invoice()

    def action_print_commercial_invoice(self):
        return self._get_reservation().action_print_commercial_invoice()
