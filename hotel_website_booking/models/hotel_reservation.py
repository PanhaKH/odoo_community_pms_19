import json

from odoo import fields, models

class HotelReservation(models.Model):
    _inherit = 'hotel.reservation'

    website_partner_id = fields.Many2one(
        'res.partner',
        string="Website Customer",
        readonly=True,
        copy=False,
        index=True,
        help="Logged-in website customer that submitted this booking request.",
    )
    website_booking_email = fields.Char(string="Website Booking Email", readonly=True, copy=False, index=True)
    website_booking_phone = fields.Char(string="Website Booking Phone", readonly=True, copy=False)
    website_booking_payload = fields.Text(string="Website Booking Data", readonly=True, copy=False)
    website_payment_status = fields.Selection([
        ('none', 'No Payment'),
        ('pending_verification', 'Pending Manual Verification'),
        ('paid', 'Paid'),
        ('failed', 'Failed'),
    ], string="Website Payment Status", default='none', readonly=True, copy=False, tracking=True)
    website_deposit_amount = fields.Monetary(
        string="Website Deposit Amount",
        currency_field='currency_id',
        readonly=True,
        copy=False,
    )
    def _website_parse_booking_payload(self):
        self.ensure_one()
        if not self.website_booking_payload:
            return {}
        try:
            return json.loads(self.website_booking_payload)
        except Exception:
            return {}
