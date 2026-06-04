from odoo import models, fields, api

class HotelNoshowWizard(models.TransientModel):
    _name = 'hotel.noshow.wizard'
    _description = 'Handle No-Show'

    reservation_id = fields.Many2one('hotel.reservation', string="Reservation", readonly=True)
    reason = fields.Text(string="Reason")

    def action_confirm_noshow(self):
        self.reservation_id.action_noshow(source='manual', reason=self.reason)
