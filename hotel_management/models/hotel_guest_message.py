import logging
import re

from odoo import api, fields, models, _
from odoo.exceptions import AccessError
from odoo.tools import html2plaintext


_logger = logging.getLogger(__name__)


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
        ('email_reply', 'Email Reply'),
    ], string='Source', required=True, default='reservation_portal', index=True)
    mail_message_id = fields.Many2one(
        'mail.message',
        string='Source Email Message',
        readonly=True,
        copy=False,
        index=True,
        ondelete='set null',
    )
    is_read = fields.Boolean(string='Read', default=False, index=True)
    read_by = fields.Many2one('res.users', string='Read By', readonly=True, copy=False)
    read_datetime = fields.Datetime(string='Read At', readonly=True, copy=False)

    _sql_constraints = [
        (
            'unique_mail_message_id',
            'unique(mail_message_id)',
            'This incoming email reply is already linked to a guest message.',
        ),
    ]

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
            is_incoming_email_reply = bool(
                getattr(message, 'incoming_email_to', False)
                or getattr(message, 'incoming_email_cc', False)
            )
            if (
                message.model != 'hotel.reservation'
                or message.message_type != 'comment'
                or has_internal_author
                or (
                    not message.author_id
                    and not is_incoming_email_reply
                    and not self.env.context.get('message_post_store')
                )
            ):
                continue
            body = html2plaintext(message.body or '').strip()
            reservation = self.env['hotel.reservation'].sudo().browse(message.res_id).exists()
            if reservation and body and not guest_message_model.search_count([('mail_message_id', '=', message.id)]):
                guest_message_model.create({
                    'reservation_id': reservation.id,
                    'partner_id': (message.author_id or reservation.partner_id).id,
                    'message_body': body,
                    'source': 'email_reply' if is_incoming_email_reply else 'reservation_portal',
                    'mail_message_id': message.id,
                })
                if is_incoming_email_reply:
                    reservation._create_email_audit(
                        'incoming_guest_reply',
                        message.email_from or message.author_id.email or reservation.partner_email or '-',
                        'received',
                        message.subject or _('Incoming Guest Reply'),
                    )
        return messages


class MailThreadHotelReservationRouting(models.AbstractModel):
    _inherit = 'mail.thread'

    @api.model
    def _hotel_find_reservation_from_incoming_email(self, message_dict):
        subject = message_dict.get('subject') or ''
        body = html2plaintext(message_dict.get('body') or '')
        haystack = '%s\n%s' % (subject, body)
        references = {
            reference.upper()
            for reference in re.findall(r'\b[A-Z]{2,10}/\d{4}/\d{3,10}\b', haystack, flags=re.IGNORECASE)
        }
        if not references:
            return self.env['hotel.reservation']

        reservations = self.env['hotel.reservation'].sudo().search([('name', 'in', list(references))])
        if len(reservations) == 1:
            return reservations

        _logger.warning(
            "Incoming guest email could not be routed by reservation reference. "
            "reference_count=%s reservation_match_count=%s subject=%s message_id=%s",
            len(references),
            len(reservations),
            subject,
            message_dict.get('message_id'),
        )
        return self.env['hotel.reservation']

    @api.model
    def message_route(self, message, message_dict, model=None, thread_id=None, custom_values=None):
        try:
            return super().message_route(message, message_dict, model=model, thread_id=thread_id, custom_values=custom_values)
        except (ValueError, TypeError):
            reservation = self._hotel_find_reservation_from_incoming_email(message_dict)
            if not reservation:
                raise
            _logger.info(
                "Routing incoming guest email to reservation chatter by reservation reference. "
                "reservation_id=%s message_id=%s",
                reservation.id,
                message_dict.get('message_id'),
            )
            return [(
                'hotel.reservation',
                reservation.id,
                custom_values or {},
                self.env.uid,
                self.env['mail.alias'],
            )]
