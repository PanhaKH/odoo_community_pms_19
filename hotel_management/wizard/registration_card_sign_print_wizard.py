from odoo import fields, models, _
from odoo.exceptions import UserError


class HotelRegistrationCardSignPrintWizard(models.TransientModel):
    _name = 'hotel.registration.card.sign.print.wizard'
    _description = 'Registration Card Sign and Print'

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
        if not reservation.registration_staff_signature:
            reservation._snapshot_registration_staff_signature()
        return reservation._action_print_registration_card_report()

    def action_print_without_signature(self):
        reservation = self._get_reservation()
        return reservation._action_print_registration_card_report()
