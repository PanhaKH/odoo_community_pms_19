from odoo import api, fields, models, _
from odoo.exceptions import AccessError
from odoo.tools import html2plaintext


class HotelGuestMessage(models.Model):
    _name = 'hotel.guest.message'
    _description = 'Hotel Guest Message'
    _order = 'create_date desc'

    reservation_id = fields.Many2one(
        'hotel.reservation',
        string='Reservation',
        required=True,
        ondelete='cascade',
        index=True,
    )
    partner_id = fields.Many2one(
        'res.partner',
        string='Guest',
        required=True,
        index=True,
    )
    message_body = fields.Text(string='Message', required=True)
    source = fields.Selection([
        ('pre_arrival', 'Pre-Arrival'),
        ('customer_portal', 'Customer Portal'),
        ('reservation_portal', 'Reservation Portal'),
    ], string='Source', required=True, default='reservation_portal', index=True)
    is_read = fields.Boolean(string='Read', default=False, index=True)
    read_by = fields.Many2one('res.users', string='Read By', readonly=True, copy=False)
    read_datetime = fields.Datetime(string='Read At', readonly=True, copy=False)

    @api.model
    def _check_staff_access(self):
        if not self.env.user.has_group('hotel_management.group_hotel_front_office'):
            raise AccessError(_("Only front office hotel staff can view guest messages."))

    @api.model
    def _table_is_ready(self):
        self.env.cr.execute("SELECT to_regclass(%s)", (self._table,))
        return bool(self.env.cr.fetchone()[0])

    @api.model
    def get_unread_status(self):
        self._check_staff_access()
        if not self._table_is_ready():
            return {'count': 0, 'latest_message_id': False, 'has_unread': False}
        messages = self.sudo()
        domain = [('is_read', '=', False)]
        latest_message = messages.search(domain, order='id desc', limit=1)
        count = messages.search_count(domain)
        return {
            'count': count,
            'latest_message_id': latest_message.id or 0,
            'has_unread': bool(count),
        }

    def action_mark_as_read(self):
        self._check_staff_access()
        if not self._table_is_ready():
            return True
        unread_messages = self.filtered(lambda message: not message.is_read)
        if unread_messages:
            unread_messages.write({
                'is_read': True,
                'read_by': self.env.user.id,
                'read_datetime': fields.Datetime.now(),
            })
        return True


class MailMessageGuestMessageCapture(models.Model):
    _inherit = 'mail.message'

    @api.model_create_multi
    def create(self, vals_list):
        messages = super().create(vals_list)
        if self.env.context.get('skip_hotel_guest_message_tracking'):
            return messages
        guest_message_model = self.env['hotel.guest.message'].sudo()
        if not guest_message_model._table_is_ready():
            return messages

        for message in messages:
            has_internal_author = message.author_id.user_ids.filtered(
                lambda user: user.has_group('base.group_user')
            )
            if (
                message.model != 'hotel.reservation'
                or message.message_type != 'comment'
                or has_internal_author
                or (not message.author_id and not self.env.context.get('message_post_store'))
            ):
                continue
            body = html2plaintext(message.body or '').strip()
            reservation = self.env['hotel.reservation'].sudo().browse(message.res_id).exists()
            if reservation and body:
                guest_message_model.create({
                    'reservation_id': reservation.id,
                    'partner_id': reservation.partner_id.id,
                    'message_body': body,
                    'source': 'reservation_portal',
                })
        return messages
