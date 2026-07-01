from odoo import models, fields, api, _
from odoo.exceptions import AccessError, UserError

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
    feature_room_display = fields.Char(
        string="Room Number",
        compute='_compute_feature_room_display',
        compute_sudo=True,
    )
    submitted_by_id = fields.Many2one(
        'res.users',
        string="Submitted By",
        readonly=True,
        copy=False,
    )
    submitted_from = fields.Selection([
        ('feature_access', 'Feature Access'),
    ], string="Submitted From", readonly=True, copy=False)
    
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

    @api.depends('room_id', 'reservation_id.room_id.name')
    def _compute_feature_room_display(self):
        for request in self:
            safe_request = request.sudo()
            request.feature_room_display = safe_request.room_id.name or ''

    @api.model
    def _check_feature_submit_access(self):
        if not self.env.user.has_group('hotel_management.hotel_feature_guest_request_submit'):
            raise AccessError(_("You are not allowed to submit guest requests."))

    @api.model
    def _feature_submit_reservation_domain(self, room_id=None):
        biz_date = self.env.company.hotel_business_date or fields.Date.context_today(self)
        domain = [
            ('state', 'in', ['checkin', 'checkout_hold']),
            ('room_id', '!=', False),
            ('company_id', 'in', self.env.companies.ids),
            ('checkin_date', '<=', biz_date),
        ]
        if room_id:
            domain.append(('room_id', '=', int(room_id)))
        return domain

    @api.model
    def _get_feature_submit_room_selection(self):
        self._check_feature_submit_access()
        reservations = self.env['hotel.reservation'].sudo().search(
            self._feature_submit_reservation_domain(),
            order='room_id',
        )
        by_room = {}
        for reservation in reservations:
            by_room.setdefault(reservation.room_id.id, []).append(reservation)

        selections = []
        for room_id, room_reservations in by_room.items():
            if len(room_reservations) != 1:
                continue
            room = room_reservations[0].room_id
            selections.append((str(room_id), room.name or str(room_id)))
        return sorted(selections, key=lambda item: item[1])

    @api.model
    def _submit_feature_guest_request(self, room_ref, request_type, description):
        self._check_feature_submit_access()
        try:
            room_id = int(room_ref)
        except (TypeError, ValueError):
            raise UserError(_("Please select a valid occupied room."))

        allowed_request_types = {
            key for key, _label in self._fields['request_type'].selection
        }
        if request_type not in allowed_request_types:
            raise UserError(_("Please select a valid request type."))

        description = (description or '').strip()
        if not description:
            raise UserError(_("Please enter request details."))

        reservations = self.env['hotel.reservation'].sudo().search(
            self._feature_submit_reservation_domain(room_id=room_id)
        )
        if not reservations:
            raise UserError(_("There is no active in-house reservation for the selected room."))
        if len(reservations) > 1:
            raise UserError(_("Multiple active reservations were found for this room. Please contact Front Office."))

        reservation = reservations[0]
        if reservation.company_id not in self.env.companies:
            raise AccessError(_("You are not allowed to submit requests for this company."))

        return self.sudo().create({
            'reservation_id': reservation.id,
            'request_type': request_type,
            'description': description,
            'submitted_by_id': self.env.user.id,
            'submitted_from': 'feature_access',
        })

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
