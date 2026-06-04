from odoo import models, fields, api, _

class HotelServiceRequest(models.Model):
    _name = 'hotel.service.request'
    _description = 'Guest Service Request'
    _inherit = ['mail.thread', 'mail.activity.mixin']
    _order = 'create_date desc'

    name = fields.Char(string="Request ID", required=True, copy=False, readonly=True, default=lambda self: _('New'))
    
    # Link to the specific stay
    reservation_id = fields.Many2one('hotel.reservation', string="Reservation", required=True)
    partner_id = fields.Many2one(related='reservation_id.partner_id', string="Guest", store=True)
    room_id = fields.Many2one(related='reservation_id.room_id', string="Room", store=True)
    
    request_type = fields.Selection([
        ('housekeeping', 'Housekeeping (Towels, Cleaning)'),
        ('food', 'Food & Drink'),
        ('maintenance', 'Maintenance Issue'),
        ('transport', 'Transportation / Taxi'),
        ('other', 'Other'),
    ], string="Type", required=True, default='housekeeping')
    
    description = fields.Text(string="Details", required=True)
    
    state = fields.Selection([
        ('new', 'New'),
        ('progress', 'In Progress'),
        ('done', 'Completed'),
        ('cancel', 'Cancelled'),
    ], string="Status", default='new', tracking=True)

    @api.model_create_multi
    def create(self, vals_list):
        for vals in vals_list:
            if vals.get('name', _('New')) == _('New'):
                vals['name'] = self.env['ir.sequence'].next_by_code('hotel.service.request') or _('New')
        return super().create(vals_list)

    def action_progress(self):
        self.state = 'progress'
        type_label = dict(self._fields['request_type'].selection).get(self.request_type)
        msg = f"⏳ <b>Update:</b> We have received your request for {type_label} and are working on it now!"
        # The 'subtype_xmlid' is the secret key that makes it visible to the public guest!
        self.reservation_id.sudo().message_post(
            body=msg, 
            message_type="comment", 
            subtype_xmlid="mail.mt_comment"
        )

    def action_done(self):
        self.state = 'done'
        type_label = dict(self._fields['request_type'].selection).get(self.request_type)
        msg = f"✅ <b>Completed:</b> Your request for {type_label} has been resolved! Please let us know if you need anything else."
        self.reservation_id.sudo().message_post(
            body=msg, 
            message_type="comment", 
            subtype_xmlid="mail.mt_comment"
        )

    def action_cancel(self):
        self.state = 'cancel'