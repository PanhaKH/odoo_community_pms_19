from odoo import api, fields, models, _


class HotelGuestRequestSubmitWizard(models.TransientModel):
    _name = 'hotel.guest.request.submit.wizard'
    _description = 'Submit Guest Request'

    room_ref = fields.Selection(
        selection='_get_occupied_room_selection',
        string="Occupied Room",
        required=True,
    )
    request_type = fields.Selection(
        selection='_get_request_type_selection',
        string="Type",
        required=True,
        default='housekeeping',
    )
    description = fields.Text(string="Details", required=True)

    @api.model
    def _get_occupied_room_selection(self):
        return self.env['hotel.service.request']._get_feature_submit_room_selection()

    @api.model
    def _get_request_type_selection(self):
        return self.env['hotel.service.request']._fields['request_type'].selection

    def action_submit_guest_request(self):
        self.ensure_one()
        self.env['hotel.service.request']._submit_feature_guest_request(
            self.room_ref,
            self.request_type,
            self.description,
        )
        return {
            'type': 'ir.actions.client',
            'tag': 'display_notification',
            'params': {
                'title': _('Guest Request Submitted'),
                'message': _('The guest request was submitted successfully.'),
                'type': 'success',
                'sticky': False,
                'next': {
                    'type': 'ir.actions.act_window',
                    'name': _('Guest Requests'),
                    'res_model': 'hotel.service.request',
                    'view_mode': 'list,form',
                    'target': 'current',
                    'views': [
                        (self.env.ref('hotel_management.view_hotel_service_request_feature_tree').id, 'list'),
                        (self.env.ref('hotel_management.view_hotel_service_request_feature_form').id, 'form'),
                    ],
                },
            },
        }
