from odoo import models, fields, api, _
from odoo.exceptions import AccessError, MissingError, ValidationError, UserError
from odoo.fields import Command
from datetime import datetime, time, timedelta
from markupsafe import Markup 
import base64
import logging
import uuid  
 

_logger = logging.getLogger(__name__)

class ResCompanyHotel(models.Model):
    _inherit = 'res.company'
    
    hotel_business_date = fields.Date(
        string="Hotel Business Date", 
        default=fields.Date.context_today,
        required=True
    )
    hotel_advance_deposit_account_id = fields.Many2one(
        'account.account',
        string="Advance Deposit Liability Account",
        domain="[('account_type', 'in', ('liability_current', 'liability_non_current', 'liability_payable')), ('deprecated', '=', False)]",
        help="Liability account used for Opera-style advance deposits until the final folio invoice is issued.",
    )
    hotel_deposit_required = fields.Boolean(
        string="Deposit Required",
        default=False,
        help="When enabled, reservations must collect the configured minimum deposit before accepting a deposit receipt.",
    )
    hotel_confirmation_deposit_percent = fields.Float(
        string="Reservation Deposit Requirement (%)",
        default=50.0,
        help="Deposit percentage shown on the Reservation Confirmation / Proforma document.",
    )
    hotel_deposit_tax_proportional = fields.Boolean(
        string="Apply Proportional Taxes to Hotel Deposits",
        help="Apply the accommodation taxes to advance-deposit invoices while treating the collected deposit as tax-inclusive.",
    )
    hotel_auto_email_deposit_receipt = fields.Boolean(
        string="Auto Email Deposit Receipt",
        default=False,
        help="Automatically email the Advance Deposit Receipt PDF after a deposit is successfully posted.",
    )
    hotel_attach_confirmation_pdf_to_booking_email = fields.Boolean(
        string="Attach Confirmation / Proforma PDF to Booking Email",
        default=True,
        help="Attach the Reservation Confirmation / Proforma PDF to deposit-required booking emails.",
    )
    hotel_online_payment_link_enabled = fields.Boolean(
        string="Online Payment Link Enabled",
        default=False,
        help="Show the configured payment URL or instruction in deposit-required booking emails.",
    )
    hotel_online_payment_instruction = fields.Html(
        string="Online Payment URL / Instruction",
        help="URL or payment instructions shown on deposit-required booking emails when online payment is enabled.",
    )
    hotel_auto_noshow_enabled = fields.Boolean(
        string="Enable Auto No-Show",
        default=False,
        help="When disabled, the scheduled Auto No-Show cron logs and exits without changing reservations.",
    )
    hotel_auto_noshow_cutoff_time = fields.Float(
        string="Auto No-Show Cutoff Time",
        default=23.9833333333,
        help="Hotel-local cutoff time after which same-business-date arrivals can be considered no-show.",
    )
    hotel_auto_noshow_grace_hours = fields.Float(
        string="Auto No-Show Grace Hours",
        default=0.0,
        help="Extra hours after the cutoff before automation can mark eligible reservations no-show.",
    )
    hotel_auto_noshow_apply_to = fields.Selection([
        ('non_guaranteed', 'Non-guaranteed reservations only'),
        ('guaranteed', 'Guaranteed reservations only'),
        ('all', 'All confirmed arrivals'),
    ], string="Auto No-Show Apply To", default='non_guaranteed')
    hotel_auto_noshow_exclude_deposit = fields.Boolean(
        string="Exclude Reservations with Deposit",
        default=True,
        help="Reservations with deposits or payments are skipped for manual review.",
    )
    hotel_cancellation_policy = fields.Html(
        string="Cancellation Policy",
        default="""
            <p>Cancellation and amendment requests are subject to the booked rate policy and hotel approval.</p>
            <p>Please contact Reservations directly for any changes before arrival.</p>
        """,
    )
    hotel_payment_instructions = fields.Html(
        string="Payment Instructions",
        default="""
            <p>Please quote the reservation number on all remittances and bank transfers.</p>
            <p>Send payment proof to the Reservations team so the advance deposit can be matched promptly.</p>
        """,
    )
    
    hotel_udf_label_1 = fields.Char(default="Nationality / Region")
    hotel_udf_label_2 = fields.Char(default="Primary Language")
    hotel_udf_label_3 = fields.Char(default="Special Occasion")
    hotel_udf_label_4 = fields.Char(default="Dietary Preference")
    hotel_udf_label_5 = fields.Char(default="Arrival Transport")
    hotel_udf_label_6 = fields.Char(default="Industry / Profession")
    hotel_udf_label_7 = fields.Char(default="Accompanying Guest")
    hotel_udf_label_8 = fields.Char(default="Room Location Pref.")
    hotel_udf_label_9 = fields.Char(default="Bedding Preference")
    hotel_udf_label_10 = fields.Char(default="Communication App")

class HotelGuestAttribute(models.Model):
    _name = 'hotel.guest.attribute'
    _description = 'Hotel Guest Attribute Option'
    _order = 'udf_number, sequence, name'

    name = fields.Char(string="Dropdown Option", required=True)
    sequence = fields.Integer(default=10)
    udf_number = fields.Selection([
        ('1', 'Attribute 1 (Nationality/Region)'),
        ('2', 'Attribute 2 (Language)'),
        ('3', 'Attribute 3 (Occasion)'),
        ('4', 'Attribute 4 (Diet)'),
        ('5', 'Attribute 5 (Transport)'),
        ('6', 'Attribute 6 (Industry)'),
        ('7', 'Attribute 7 (Accompanying)'),
        ('8', 'Attribute 8 (Room Pref)'),
        ('9', 'Attribute 9 (Bedding)'),
        ('10', 'Attribute 10 (App)'),
    ], string="Belongs To Attribute", required=True)

class HotelDailyTransaction(models.Model):
    _name = 'hotel.daily.transaction'
    _description = 'Daily Revenue Transaction'
    _order = 'date asc'

    date = fields.Date(string="Date", required=True, index=True)
    reservation_id = fields.Many2one('hotel.reservation', string="Reservation", required=True, ondelete='cascade')
    partner_id = fields.Many2one(related='reservation_id.partner_id', store=True, string="Guest")
    description = fields.Char(string="Description")
    revenue = fields.Monetary(string="Daily Revenue", required=True)
    room_nights = fields.Integer(string="Room Nights", default=1)
    currency_id = fields.Many2one(related='reservation_id.currency_id', store=True)
    rate_plan_id = fields.Many2one(related='reservation_id.rate_plan_id', store=True, string="Rate Plan")
    tax_amount = fields.Monetary(string="Tax", compute='_compute_amounts', store=True)
    line_total = fields.Monetary(string="Total", compute='_compute_amounts', store=True)
    is_posted = fields.Boolean(string="Posted", compute='_compute_is_posted', store=True)
    posted_sale_line_id = fields.Many2one('sale.order.line', string="Posted Folio Line", readonly=True, copy=False)
    is_manual_rate_override = fields.Boolean(string="Manual Override", default=False, copy=False)
    rate_override_reason = fields.Char(string="Override Reason", copy=False)

    state = fields.Selection(related='reservation_id.state', store=True, string="Status")
    room_id = fields.Many2one(related='reservation_id.room_id', store=True, string="Room")
    room_type_id = fields.Many2one(related='reservation_id.room_type_id', store=True, string="Room Type")
    adults = fields.Integer(string="Adults", default=2, required=True)
    children = fields.Integer(string="Children", default=0)
    
    source_id = fields.Many2one(related='reservation_id.source_id', store=True, string="Source")
    market_segment_id = fields.Many2one(related='reservation_id.market_segment_id', store=True, string="Market Segment")
    guest_classify_id = fields.Many2one(related='reservation_id.guest_classify_id', store=True, string="Guest Class")

    udf_value_1 = fields.Many2one(related='reservation_id.udf_value_1', store=True)
    udf_value_2 = fields.Many2one(related='reservation_id.udf_value_2', store=True)
    udf_value_3 = fields.Many2one(related='reservation_id.udf_value_3', store=True)
    udf_value_4 = fields.Many2one(related='reservation_id.udf_value_4', store=True)
    udf_value_5 = fields.Many2one(related='reservation_id.udf_value_5', store=True)
    udf_value_6 = fields.Many2one(related='reservation_id.udf_value_6', store=True)
    udf_value_7 = fields.Many2one(related='reservation_id.udf_value_7', store=True)
    udf_value_8 = fields.Many2one(related='reservation_id.udf_value_8', store=True)
    udf_value_9 = fields.Many2one(related='reservation_id.udf_value_9', store=True)
    udf_value_10 = fields.Many2one(related='reservation_id.udf_value_10', store=True)

    @api.depends('posted_sale_line_id')
    def _compute_is_posted(self):
        for line in self:
            line.is_posted = bool(line.posted_sale_line_id)

    @api.depends('revenue', 'posted_sale_line_id', 'posted_sale_line_id.price_total', 'posted_sale_line_id.price_subtotal')
    def _compute_amounts(self):
        for line in self:
            if line.posted_sale_line_id:
                line.tax_amount = line.posted_sale_line_id.price_total - line.posted_sale_line_id.price_subtotal
                line.line_total = line.posted_sale_line_id.price_total
                continue

            if line.reservation_id:
                taxes_res = line.reservation_id._get_confirmation_tax_compute(
                    line.revenue,
                )
                line.tax_amount = taxes_res['total_included'] - taxes_res['total_excluded']
                line.line_total = taxes_res['total_included']
            else:
                line.tax_amount = 0.0
                line.line_total = line.revenue

    @api.model
    def refresh_unposted_estimated_amounts(self):
        """Refresh display-only estimate totals for unposted daily room rates."""
        lines = self.search([('posted_sale_line_id', '=', False)])
        lines._compute_amounts()
        return True

    def write(self, vals):
        if self.env.context.get('skip_hotel_daily_rate_audit'):
            return super().write(vals)

        protected_fields = {'date', 'description', 'revenue', 'room_nights', 'rate_override_reason'}
        if protected_fields.intersection(vals):
            for line in self.filtered('is_posted'):
                raise ValidationError(
                    _("Posted daily room rate lines are read-only. Please reverse the posted folio line before updating the business date %s.")
                    % (line.date or '')
                )

        if 'revenue' in vals:
            differing_lines = self.filtered(lambda line: vals['revenue'] != line.revenue)
            if differing_lines:
                vals = dict(vals)
                vals['is_manual_rate_override'] = True
            for line in self:
                if vals['revenue'] == line.revenue:
                    continue
                reservation = line.reservation_id
                if not reservation:
                    continue
                reason = vals.get('rate_override_reason', line.rate_override_reason)
                new_value = str(vals['revenue'])
                if reason:
                    new_value = _("%s (Reason: %s)") % (new_value, reason)
                self.env['hotel.change.log'].log_reservation_event(
                    reservation,
                    _("Nightly Rate (%s)") % (line.date or ''),
                    str(line.revenue),
                    new_value,
                    reason=reason,
                    source_document=line,
                )

        return super().write(vals)

class HotelReservation(models.Model):
    _name = 'hotel.reservation'
    _description = 'Hotel Reservation'
    _inherit = ['mail.thread', 'mail.activity.mixin']
    _order = 'checkin_date desc'

    name = fields.Char(string='Reservation No', required=True, copy=False, readonly=True, default=lambda self: _('New'))
    partner_id = fields.Many2one('res.partner', string='Guest', required=True, tracking=True)
    partner_passport = fields.Char(related='partner_id.passport_number', string="Passport / ID", readonly=False)

    passport_image = fields.Image(
        related='partner_id.passport_image', 
        readonly=False, 
        string="Passport/ID Image",
        help="Capture the guest's ID using the device camera. This saves directly to their profile."
    )

    guest_nationality_id = fields.Many2one('hotel.nationality', related='partner_id.nationality_id', readonly=False, string='Nationality')
    guest_country_id = fields.Many2one('res.country', related='partner_id.country_id', readonly=False, string='Country')
    guest_signature = fields.Binary(string='Guest Signature', attachment=True)
    registration_staff_signature = fields.Binary(
        string='Registration Staff Signature',
        attachment=True,
        copy=False,
        readonly=True,
    )
    registration_signed_by_id = fields.Many2one(
        'res.users',
        string='Registration Signed By',
        copy=False,
        readonly=True,
    )
    registration_signed_by_name = fields.Char(
        string='Registration Signed By Name',
        copy=False,
        readonly=True,
    )
    registration_signed_at = fields.Datetime(
        string='Registration Signed At',
        copy=False,
        readonly=True,
    )
    tax_invoice_staff_signature = fields.Binary(
        string='Tax Invoice Staff Signature',
        attachment=True,
        copy=False,
        readonly=True,
    )
    tax_invoice_signed_by_id = fields.Many2one(
        'res.users',
        string='Tax Invoice Signed By',
        copy=False,
        readonly=True,
    )
    tax_invoice_signed_by_name = fields.Char(
        string='Tax Invoice Signed By Name',
        copy=False,
        readonly=True,
    )
    tax_invoice_signed_at = fields.Datetime(
        string='Tax Invoice Signed At',
        copy=False,
        readonly=True,
    )
    commercial_invoice_staff_signature = fields.Binary(
        string='Commercial Invoice Staff Signature',
        attachment=True,
        copy=False,
        readonly=True,
    )
    commercial_invoice_signed_by_id = fields.Many2one(
        'res.users',
        string='Commercial Invoice Signed By',
        copy=False,
        readonly=True,
    )
    commercial_invoice_signed_by_name = fields.Char(
        string='Commercial Invoice Signed By Name',
        copy=False,
        readonly=True,
    )
    commercial_invoice_signed_at = fields.Datetime(
        string='Commercial Invoice Signed At',
        copy=False,
        readonly=True,
    )
    stay_guest_ids = fields.One2many('hotel.reservation.guest', 'reservation_id', string='Registered Stay Guests')
    email_audit_ids = fields.One2many('hotel.email.audit', 'reservation_id', string='Email Communication')
    stay_guest_count = fields.Integer(compute='_compute_stay_guest_count', string='Registered Guests')
    is_repeat_guest = fields.Boolean(compute='_compute_repeat_guest_status', search='_search_is_repeat_guest', string='Repeat Guest')
    vip_level = fields.Selection(
        related='partner_id.vip_level',
        readonly=False,
        store=True,
        string='VIP Level',
    )
    rooming_board_label = fields.Char(
        string='Rooming Board Label',
        compute='_compute_rooming_board_label',
    )

    def _compute_rooming_board_label(self):
        for rec in self:
            if rec.is_desk_folio and rec.group_id:
                rec.rooming_board_label = 'PAYMASTER'
            elif rec.group_id:
                rec.rooming_board_label = 'ROOM'
            else:
                rec.rooming_board_label = ''

    group_folio_role = fields.Selection(
        [
            ('normal', 'Normal'),
            ('room', 'Group Room'),
            ('paymaster', 'Group Paymaster'),
        ],
        string='Group Role',
        compute='_compute_group_folio_role',
    )

    @api.constrains('room_type_id', 'is_desk_folio')
    def _check_room_type_not_desk_folio_for_guest_reservation(self):
        for rec in self:
            if not rec.is_desk_folio and rec.room_type_id:
                room_type_name = (rec.room_type_id.name or '').strip().lower()
                if room_type_name == 'desk folio':
                    raise ValidationError(_("Desk Folio room type cannot be selected for a normal guest reservation."))

    def _compute_group_folio_role(self):
        for rec in self:
            if rec.is_desk_folio and rec.group_id:
                rec.group_folio_role = 'paymaster'
            elif rec.group_id and not rec.is_desk_folio:
                rec.group_folio_role = 'room'
            else:
                rec.group_folio_role = 'normal'

    # --- PRE-ARRIVAL & PREFERENCES ---
    estimated_arrival = fields.Selection([
        ('morning', 'Morning (8:00 AM - 12:00 PM)'),
        ('afternoon', 'Afternoon (12:00 PM - 4:00 PM)'),
        ('evening', 'Evening (4:00 PM - 8:00 PM)'),
        ('late', 'Late Night (After 8:00 PM)')
    ], string="Estimated Arrival (ETA)")

    smoking_preference = fields.Selection([
        ('non_smoking', 'Non-Smoking'),
        ('smoking', 'Smoking')
    ], string="Smoking Preference", default='non_smoking')

    bed_preference = fields.Selection([
        ('king', '1 King Bed'),
        ('twin', '2 Twin Beds'),
        ('any', 'No Preference')
    ], string="Bed Preference", default='any')

    is_vip = fields.Boolean(string="VIP Guest", compute="_compute_is_vip", store=True)

    # --- MASTER FOLIO & ROUTING LOGIC ---
    master_reservation_id = fields.Many2one(
        'hotel.reservation', 
        string="Route Charges To (Master)", 
        help="If set, all room charges and POS bills will route to this folio.",
        tracking=True
    )
    sub_reservation_ids = fields.One2many(
        'hotel.reservation', 
        'master_reservation_id', 
        string="Accompanying Rooms"
    )
    routing_relationship = fields.Selection([
        ('family', 'Family Member'),
        ('colleague', 'Corporate Colleague'),
        ('friend', 'Friend / Group'),
        ('other', 'Other')
    ], string="Relationship to Master", tracking=True)

    @api.model
    def _is_housekeeping_reservation_review_user(self):
        if self.env.su or self.env.user.has_group('base.group_system'):
            return False
        housekeeping_group_xmlids = (
            'hotel_housekeeping_app.group_housekeeping_user',
            'hotel_housekeeping_app.group_housekeeping_supervisor',
            'hotel_housekeeping_app.group_housekeeping_manager',
        )
        return any(
            self.env.user.has_group(xmlid)
            for xmlid in housekeeping_group_xmlids
            if self.env.ref(xmlid, raise_if_not_found=False)
        )

    @api.model
    def _has_reservation_write_access(self):
        if self._is_housekeeping_reservation_review_user():
            return False
        return (
            self.env.su
            or self.env.context.get('install_mode')
            or self.env.context.get('hotel_reservation_security_bypass')
            or self.env.user.has_group('hotel_management.group_hotel_front_office')
            or self.env.user.has_group('hotel_management.group_hotel_front_office_manager')
            or self.env.user.has_group('hotel_management.group_hotel_manager')
            or self.env.user.has_group('base.group_system')
        )

    @api.model
    def user_can_manage_reservations(self):
        if self._is_housekeeping_reservation_review_user():
            return False
        return bool(self._has_reservation_write_access())

    @api.model
    def _check_reservation_write_access(self, operation='modify'):
        if self._has_reservation_write_access():
            return

        if self.env.user.has_group('hotel_management.group_hotel_housekeeper'):
            raise AccessError(_(
                "Housekeeping users can review reservations only and cannot move or modify bookings."
            ))

        operation_label = {
            'create': _('create'),
            'write': _('modify'),
            'unlink': _('delete'),
        }.get(operation, _('modify'))
        raise AccessError(
            _("Only Front Office can %s reservations. Housekeeping has read-only access.") % operation_label
        )

    @api.model
    def _check_reservation_movement_access(self):
        if self._has_reservation_write_access():
            return
        if self.env.user.has_group('hotel_management.group_hotel_housekeeper'):
            raise AccessError(_(
                "Housekeeping users can review reservations only and cannot move or modify bookings."
            ))
        self._check_reservation_write_access('write')

    def _sync_room_state(self):
        """
        Ensure room status always follows reservation state (5-star PMS rule)
        """
        for rec in self:
            # Desk folios are non-room folios and must not inherit reservation lifecycle.
            if rec.is_desk_folio:
                continue
            if not rec.room_id:
                continue

            room = rec.room_id

            if rec.state in ['checkin', 'checkout_hold']:
                room.with_context(hotel_reservation_room_workflow=True).write({
                    'occupancy_status': 'occupied',
                    'availability_status': 'available',
                    'minibar_check_required': True,
                    'minibar_checked': False,
                    'turndown_completed': False,
                })
            elif rec.state == 'checkout':
                room.with_context(hotel_reservation_room_workflow=True).write({
                    'occupancy_status': 'vacant',
                    'housekeeping_status': 'dirty',
                    'availability_status': 'available',
                    'do_not_disturb': False,
                    'turndown_required': False,
                    'turndown_completed': False,
                    'minibar_check_required': False,
                    'minibar_checked': False,
                    'linen_change_required': False,
                    'linen_changed': False,
                })
            elif rec.state == 'blocked':
                room.with_context(hotel_reservation_room_workflow=True).write({'availability_status': 'out_of_order'})

        self._reconcile_room_operational_status()

    def _reconcile_room_operational_status(self, rooms=None):
        rooms = rooms or self.env['hotel.room'].browse((self.mapped('room_id')).ids)
        if rooms:
            rooms._reconcile_operational_status()
            rooms._sync_housekeeping_task_records()

    def _get_other_inhouse_conflict(self, room):
        self.ensure_one()
        biz_date = self.env.company.hotel_business_date or fields.Date.context_today(self)
        return self.search([
            ('id', '!=', self.id),
            ('room_id', '=', room.id),
            # A due-out guest still blocks the room until they are actually checked out.
            ('state', 'in', ['checkin', 'checkout_hold']),
            ('checkin_date', '<=', biz_date),
        ], limit=1)

    def _get_other_active_block(self, room):
        self.ensure_one()
        biz_date = self.env.company.hotel_business_date or fields.Date.context_today(self)
        legacy_block = self.search([
            ('id', '!=', self.id),
            ('room_id', '=', room.id),
            ('state', '=', 'blocked'),
            ('checkin_date', '<=', biz_date),
            ('checkout_date', '>', biz_date),
        ], limit=1)
        if legacy_block:
            return legacy_block
        return self.env['hotel.room.block'].sudo().search([
            ('room_id', '=', room.id),
            ('state', '=', 'active'),
            ('date_from', '<=', biz_date),
            ('date_to', '>', biz_date),
        ], limit=1)

    def _get_overlapping_room_block(self, room=None, checkin_date=None, checkout_date=None):
        self.ensure_one()
        room = room or self.room_id
        checkin_date = fields.Date.to_date(checkin_date or self.checkin_date)
        checkout_date = fields.Date.to_date(checkout_date or self.checkout_date)
        if not room or not checkin_date or not checkout_date:
            return self.env['hotel.room.block']
        return self.env['hotel.room.block'].sudo().search([
            ('room_id', '=', room.id),
            ('state', '=', 'active'),
            ('date_from', '<', checkout_date),
            ('date_to', '>', checkin_date),
        ], limit=1)

    def _get_room_block_message(self, block):
        self.ensure_one()
        reason = _("maintenance") if block.source == 'maintenance' else _("room block")
        return _(
            "Room %(room)s is blocked for %(reason)s from %(date_from)s to %(date_to)s."
        ) % {
            'room': block.room_id.display_name,
            'reason': reason,
            'date_from': fields.Date.to_string(block.date_from),
            'date_to': fields.Date.to_string(block.date_to),
        }

    @api.constrains('city_ledger_id', 'billing_routing')
    def _check_city_ledger_routing_logic(self):
        for rec in self:
            company_lines = rec.sale_order_id.order_line.filtered(
                lambda line: not line.display_type and (line.billing_target or 'guest') == 'company'
            )
            if rec.billing_routing in ['master_room', 'master_all'] and company_lines and not rec.city_ledger_id:
                raise ValidationError(
                    _(
                        "Company-routed folio lines require a City Ledger account before invoicing."
                    )
                )

    # Compatibility flag for existing views/reports. VIP is always selected manually.
    @api.depends('vip_level')
    def _compute_is_vip(self):
        for rec in self:
            rec.is_vip = rec.vip_level in ('vip', 'vvip')

    def _compute_stay_guest_count(self):
        for rec in self:
            rec.stay_guest_count = len(rec.stay_guest_ids)

    def _compute_repeat_guest_status(self):
        for rec in self:
            rec.is_repeat_guest = rec._get_partner_visit_count(rec.partner_id) > 1

    def _search_is_repeat_guest(self, operator, value):
        reservations = self.search([
            ('partner_id', '!=', False),
            ('state', 'not in', ['cancel', 'noshow', 'blocked']),
            ('is_desk_folio', '=', False),
        ]).filtered(lambda reservation: reservation._get_partner_visit_count(reservation.partner_id) > 1)
        is_positive = (
            (operator in ('=', '==') and value)
            or (operator in ('!=', '<>') and not value)
            or (operator == 'in' and True in value)
        )
        return [('id', 'in' if is_positive else 'not in', reservations.ids or [0])]

    accompanying_guest_ids = fields.Many2many('res.partner', string="Accompanying Guests")
    partner_phone = fields.Char(related='partner_id.phone', string="Phone", readonly=False)
    partner_email = fields.Char(related='partner_id.email', string="Email", readonly=False)
    reference = fields.Char(string="Reference", help="External booking reference.")
    group_id = fields.Many2one('hotel.group.master', string="Group Block", readonly=True, ondelete='set null')
    rate_plan_id = fields.Many2one('hotel.rate.plan', string='Master Rate Plan')
    # Billing instruction only:
    # This tells the stay/folio which company may be billed for room or routed charges.
    # It does NOT mean the amount is already a City Ledger receivable.
    city_ledger_id = fields.Many2one(
        'res.partner', 
        string='City Ledger / Bill To', 
        domain="[('is_company', '=', True)]", 
        tracking=True, 
        help="If set, the folio will be billed to this company and the guest can checkout with an unpaid ."
    )

    # 1. Now a Many2one pointing to the dynamic category table
    booking_source_category_id = fields.Many2one('hotel.booking.source.category', string="Source Category")

    # 2. Domain updated to look at 'category_id'
    booking_sub_source_id = fields.Many2one(
        'hotel.booking.source', 
        string="Sub-Source",
        domain="[('category_id', '=', booking_source_category_id)]"
    )
    
    market_segment_id = fields.Many2one('hotel.market.segment', string="Market Segment")
    guest_classification_id = fields.Many2one('hotel.guest.classification', string="Guest Class")

    # Reservation routing = operational billing instruction.
    # City Ledger recognition happens later, only when a posted customer invoice exists for the company account.
    billing_routing = fields.Selection([
        ('guest', 'Guest Pays All'),
        ('master_room', 'Master Pays Room, Guest Pays Incidentals'),
        ('master_all', 'Master Pays All')
    ], string="Billing Routing", default='guest', tracking=True)

    @api.onchange('city_ledger_id')
    def _onchange_city_ledger_auto_routing(self):
        """
        Automates the Billing Routing based on City Ledger selection.
        """
        for rec in self:
            if rec.city_ledger_id:
                # Automate to Master Pays All when a company is attached
                rec.billing_routing = 'master_all'
            else:
                # Revert to Guest Pays All if the company is removed
                rec.billing_routing = 'guest'

    @api.onchange('rate_plan_id', 'room_type_id', 'checkin_date', 'checkout_date')
    def _onchange_calculate_dynamic_rate(self):
        for rec in self:
            # 1. Check if we have all the required puzzle pieces
            if not (rec.rate_plan_id and rec.room_type_id and rec.checkin_date):
                continue
                
            # PRO-TIP: If the Front Desk checked the Override box, do not overwrite their custom price!
            if rec.is_manual_rate:
                continue
            
            # 2. Search for the rule
            domain = [
                ('plan_id', '=', rec.rate_plan_id.id),
                ('room_type_id', '=', rec.room_type_id.id),
                '|', 
                ('date_start', '=', False), 
                ('date_start', '<=', rec.checkin_date)
            ]
            valid_rule = self.env['hotel.rate.plan.line'].search(domain, order='date_start desc', limit=1)

            # 3. Inject the Master Rate into the field and keep the override box OFF
            if valid_rule:
                rec.is_manual_rate = False
                rec.manual_rate = valid_rule.price 
            else:
                rec.is_manual_rate = False
                rec.manual_rate = 0.0              
                raise UserError(f"Missing Price Rule! The system cannot find a price in '{rec.rate_plan_id.name}' for the room type '{rec.room_type_id.name}'. Please check your Configuration!")

    @api.onchange('master_reservation_id')
    def _onchange_master_reservation_id(self):
        """
        Auto-fill dates, commercial data, and smartly select the connecting room.
        Order of assignment is critical to bypass UI domain restrictions.
        """
        if not self.master_reservation_id:
            return

        master = self.master_reservation_id

        # --- STEP 0: CLEAR THE GHOST ROOM ---
        # Temporarily clear the room so Odoo doesn't validate the OLD room against the NEW dates!
        self.room_id = False

        # --- STEP 1: COPY DATES ---
        if master.checkin_date:
            self.checkin_date = master.checkin_date
        if master.checkout_date:
            self.checkout_date = master.checkout_date

        # --- STEP 2: SMART CONNECTING ROOM AUTO-SELECT ---
        if master.room_id and master.room_id.physical_connecting_room_ids:
            
            # CRITICAL FIX: Filter out the master room itself to prevent Many2many self-referencing loops!
            valid_connecting_rooms = master.room_id.physical_connecting_room_ids.filtered(lambda r: r.id != master.room_id.id)
            
            if valid_connecting_rooms:
                conn_room = valid_connecting_rooms[0]
                
                # Set Room Type BEFORE Room
                if conn_room.room_type_id:
                    self.room_type_id = conn_room.room_type_id
                    
                # Set Room LAST in this block
                self.room_id = conn_room

        # --- STEP 3: COPY COMMERCIAL & BILLING ---
        if master.booking_source_category_id:
            self.booking_source_category_id = master.booking_source_category_id
            
        if master.booking_sub_source_id:
            self.booking_sub_source_id = master.booking_sub_source_id
            
        if hasattr(master, 'market_segment_id') and master.market_segment_id:
            self.market_segment_id = master.market_segment_id
        elif hasattr(master, 'market_segment') and master.market_segment:
            self.market_segment = master.market_segment
            
        if master.guest_classification_id:
            self.guest_classification_id = master.guest_classification_id
            
        if master.rate_plan_id:
            self.rate_plan_id = master.rate_plan_id

    @api.depends(
        'sale_order_id.invoice_ids.state',
        'sale_order_id.invoice_ids.move_type',
        'sale_order_id.order_line.qty_to_invoice',
        'sale_order_id.order_line.display_type',
    )
    def _compute_folio_invoice_status(self):
        for rec in self:
            if not rec.sale_order_id:
                rec.folio_invoice_status = 'none'
            else:
                order = rec.sale_order_id.sudo()
                invoices = order.invoice_ids.filtered(lambda inv: inv.move_type == 'out_invoice')
                billable_lines = order.order_line.filtered(lambda line: not line.display_type)
                invoiceable_lines = billable_lines.filtered(lambda line: line.qty_to_invoice > 0)

                if invoiceable_lines:
                    rec.folio_invoice_status = 'to_invoice'
                elif invoices.filtered(lambda inv: inv.state == 'draft'):
                    rec.folio_invoice_status = 'draft'
                elif invoices.filtered(lambda inv: inv.state == 'posted'):
                    rec.folio_invoice_status = 'posted'
                elif billable_lines:
                    rec.folio_invoice_status = 'to_invoice'
                else:
                    rec.folio_invoice_status = 'none'

    @api.depends(
        'is_desk_folio',
        'sale_order_id',
        'sale_order_id.order_line.display_type',
        'sale_order_id.order_line.qty_to_invoice',
        'sale_order_id.invoice_ids.move_type',
        'sale_order_id.invoice_ids.state',
        'sale_order_id.invoice_ids.payment_state',
        'sale_order_id.invoice_ids.amount_residual',
        'advance_deposit_payment_ids.state',
        'advance_deposit_payment_ids.amount',
        'advance_deposit_payment_ids.payment_type',
        'advance_deposit_payment_ids.is_advance_deposit',
        'deposit_application_line_ids.is_advance_deposit_application',
        'deposit_application_line_ids.price_total',
        'deposit_application_line_ids.move_id.state',
    )
    def _compute_desk_folio_status(self):
        for rec in self:
            if not rec.is_desk_folio:
                rec.desk_folio_status = False
                continue

            if not rec.sale_order_id:
                rec.desk_folio_status = 'draft'
                continue

            order = rec.sale_order_id.sudo()
            billable_lines = order.order_line.filtered(lambda line: not line.display_type)
            customer_invoices = rec.sudo()._get_folio_customer_invoices()
            invoiceable_lines = billable_lines.filtered(lambda line: line.qty_to_invoice > 0)

            if not customer_invoices:
                rec.desk_folio_status = 'draft'
            elif invoiceable_lines:
                rec.desk_folio_status = 'open'
            elif all(inv.state == 'posted' and inv.amount_residual <= 0.01 for inv in customer_invoices):
                rec.desk_folio_status = 'paid'
            else:
                rec.desk_folio_status = 'fully_invoiced'

    @api.depends('is_desk_folio', 'group_id')
    def _compute_folio_type(self):
        for rec in self:
            # Folio type is a billing-only classification layer.
            # It does not replace the reservation lifecycle.
            if rec.is_desk_folio and rec.group_id:
                rec.folio_type = 'group_master'
            elif rec.is_desk_folio:
                rec.folio_type = 'desk'
            else:
                rec.folio_type = 'guest'

    @api.depends(
        'deposit_invoice_ids.state',
        'deposit_invoice_ids.reversal_move_ids.state',
        'advance_deposit_payment_ids.state',
        'advance_deposit_payment_ids.payment_type',
        'advance_deposit_payment_ids.amount',
        'advance_deposit_payment_ids.is_advance_deposit',
        'deposit_application_line_ids.is_advance_deposit_application',
        'deposit_application_line_ids.price_total',
        'deposit_application_line_ids.move_id.state',
        'sale_order_id.invoice_ids.payment_state',
        'sale_order_id.invoice_ids.state',
        'guest_credit_balance',
    )
    def _compute_can_void_deposit(self):
        for rec in self:
            if not (
                rec.env.su
                or rec.env.user.has_group('hotel_management.group_hotel_front_office_manager')
                or rec.env.user.has_group('hotel_management.group_hotel_manager')
                or rec.env.user.has_group('account.group_account_manager')
                or rec.env.user.has_group('base.group_system')
                or rec.env.user.has_group('hotel_management.group_hotel_night_auditor')
            ):
                rec.can_void_deposit = False
                continue
            calc_rec = rec.sudo()
            rounding = calc_rec.currency_id.rounding or 0.01
            rec.can_void_deposit = bool(
                calc_rec._get_voidable_deposit_invoices()
                or calc_rec._get_voidable_advance_deposit_payments()
                or calc_rec._get_operational_advance_deposit_credit_amount() > rounding
                or calc_rec.guest_credit_balance > rounding
            )

    @api.depends('is_desk_folio', 'folio_type', 'state', 'folio_paid', 'folio_total', 'total_amount')
    def _compute_can_register_deposit(self):
        for rec in self:
            rec.can_register_deposit = bool(
                rec.folio_type == 'guest'
                and not rec.is_desk_folio
                and rec.state in ['draft', 'confirm', 'checkin', 'checkout_hold']
                and rec._get_remaining_deposit_capacity() > 0.01
            )

    @api.depends(
        'company_id.hotel_deposit_required',
        'company_id.hotel_confirmation_deposit_percent',
        'advance_deposit_payment_ids.state',
        'advance_deposit_payment_ids.amount',
        'advance_deposit_payment_ids.payment_type',
        'advance_deposit_payment_ids.is_advance_deposit',
        'checkin_date',
        'checkout_date',
        'room_rate',
        'manual_rate',
        'is_manual_rate',
        'rate_id',
        'rate_plan_id',
        'currency_id',
    )
    def _compute_deposit_policy_amounts(self):
        for rec in self:
            percent = rec.company_id.hotel_confirmation_deposit_percent if rec.company_id.hotel_deposit_required else 0.0
            required_amount = rec._get_required_deposit_amount() if rec.company_id.hotel_deposit_required else 0.0
            received_amount = rec._get_posted_advance_deposit_amount()
            rec.hotel_required_deposit_percent = percent or 0.0
            rec.hotel_required_deposit_amount = required_amount
            rec.hotel_deposit_received_amount = received_amount
            rec.hotel_remaining_deposit_required = max(required_amount - received_amount, 0.0)

    folio_invoice_status = fields.Selection([
        ('none', 'No Folio'),
        ('to_invoice', 'Pending Invoice'),
        ('draft', 'Draft Invoice'),
        ('posted', 'Invoice Issued')
    ], string='Invoice Status', compute='_compute_folio_invoice_status')
    folio_type = fields.Selection([
        ('guest', 'Guest'),
        ('desk', 'Desk'),
        ('group_master', 'Group Master'),
    ], string='Folio Type', compute='_compute_folio_type', store=True, readonly=True,
       help="Billing-only folio classification. This does not change reservation lifecycle or room operations.")
    desk_folio_status = fields.Selection([
        ('draft', 'Draft'),
        ('open', 'Open'),
        ('fully_invoiced', 'Fully Invoiced'),
        ('paid', 'Paid'),
    ], string='Desk Folio Status', compute='_compute_desk_folio_status', store=True)

    guest_note = fields.Text(string="Guest Notes")
    block_reason = fields.Char(string="Block Reason")
    can_register_deposit = fields.Boolean(
        string="Can Register Deposit",
        compute='_compute_can_register_deposit',
    )
    can_void_deposit = fields.Boolean(
        string="Can Void Deposit",
        compute='_compute_can_void_deposit',
    )

    room_type_id = fields.Many2one('hotel.room.type', string="Room Type", required=True, tracking=True)
    room_id = fields.Many2one('hotel.room', string="Room", required=False, tracking=True)

    available_room_ids = fields.Many2many(
    'hotel.room',
    compute='_compute_available_room_ids',
    string='Available Rooms'
    )

    adults = fields.Integer(string="Adults", default=2, required=True, tracking=True)
    children = fields.Integer(string="Children", default=0, tracking=True)
    checkin_date = fields.Date(string='From Date', required=True, tracking=True, default=fields.Date.today)
    checkout_date = fields.Date(string='To Date', required=True, tracking=True)
    duration = fields.Integer(string='Duration', compute='_compute_duration', store=True, readonly=False)

    # Room Rate Override Fields
    is_manual_rate = fields.Boolean(
        string="Override Room Rate", 
        default=False, 
        tracking=True, 
        help="Check this box to apply a custom manual rate for this reservation."
    )
    manual_rate = fields.Float(
        string="Manual Rate", 
        tracking=True, 
        help="Enter the custom nightly rate."
    )
    room_rate = fields.Float(string="Room Rate", tracking=True, readonly=True)

    source_id = fields.Many2one('hotel.booking.source', string='Source')
    market_segment_id = fields.Many2one('hotel.market.segment', string='Market Segment')
    guest_classify_id = fields.Many2one('hotel.guest.classify', string='Guest Classification')
    
    rate_id = fields.Many2one('hotel.room.rate', string='Rate Plan')
    # Desk folio is a non-room folio and must not inherit reservation lifecycle.
    is_desk_folio = fields.Boolean(string="Is a House Account / Desk Folio", default=False)
    sale_order_id = fields.Many2one('sale.order', string='Folio / Order', readonly=True, copy=False)
    invoice_status = fields.Selection(related='sale_order_id.invoice_status', string="Invoice Status")
    deposit_invoice_ids = fields.Many2many('account.move', string='Deposit Invoices', readonly=True)
    advance_deposit_payment_ids = fields.One2many('account.payment', 'hotel_reservation_id', string='Advance Deposit Payments', readonly=True)
    deposit_application_line_ids = fields.One2many('account.move.line', 'hotel_reservation_id', string='Deposit Applications', readonly=True)
    daily_transaction_ids = fields.One2many('hotel.daily.transaction', 'reservation_id', string='Daily Rates', copy=False)

    access_token = fields.Char('Security Token', copy=False, default=lambda self: str(uuid.uuid4()))
    
    folio_total = fields.Monetary(string="Folio Total", compute='_compute_folio_status', store=True)
    folio_paid = fields.Monetary(string="Paid Amount", compute='_compute_folio_status', store=True)
    folio_balance = fields.Monetary(string="Current Balance Due", compute='_compute_folio_status', store=True)
    deposit_balance = fields.Monetary(string="Advance Deposit Balance", compute='_compute_folio_status', store=True)
    guest_total_charges = fields.Monetary(string="Total Guest Charges", compute='_compute_folio_status', store=True)
    guest_tax_included_amount = fields.Monetary(string="Tax Included Amount", compute='_compute_folio_status', store=True)
    advance_deposit_credit = fields.Monetary(string="Advance Deposit Credit", compute='_compute_folio_status', store=True)
    remaining_deposit_available = fields.Monetary(string="Remaining Deposit Available", compute='_compute_folio_status', store=True)
    guest_invoice_payments = fields.Monetary(string="Invoice Payments", compute='_compute_folio_status', store=True)
    guest_deposit_paid_total = fields.Monetary(string="Deposit / Paid", compute='_compute_folio_status', store=True)
    guest_balance_due = fields.Monetary(string="Guest Balance Due", compute='_compute_folio_status', store=True)
    guest_net_position = fields.Monetary(string="Guest Net Position", compute='_compute_folio_status', store=True)
    guest_credit_balance = fields.Monetary(string="Guest Credit Balance", compute='_compute_folio_status', store=True)
    company_pending_billing = fields.Monetary(string="Company Pending Billing", compute='_compute_folio_status', store=True)
    company_city_ledger_ar = fields.Monetary(string="Company City Ledger A/R", compute='_compute_folio_status', store=True)
    guest_balance_button_amount = fields.Monetary(string="Guest Balance Button Amount", compute='_compute_folio_status', store=True)
    guest_balance_button_label = fields.Char(string="Guest Balance Button Label", compute='_compute_folio_status', store=True)
    hotel_deposit_policy_required = fields.Boolean(
        string="Deposit Required",
        related='company_id.hotel_deposit_required',
        readonly=True,
    )
    hotel_required_deposit_percent = fields.Float(
        string="Required Deposit %",
        compute='_compute_deposit_policy_amounts',
    )
    hotel_required_deposit_amount = fields.Monetary(
        string="Required Deposit Amount",
        compute='_compute_deposit_policy_amounts',
        currency_field='currency_id',
    )
    hotel_deposit_received_amount = fields.Monetary(
        string="Deposit Received",
        compute='_compute_deposit_policy_amounts',
        currency_field='currency_id',
    )
    hotel_remaining_deposit_required = fields.Monetary(
        string="Remaining Deposit Required",
        compute='_compute_deposit_policy_amounts',
        currency_field='currency_id',
    )
    
    total_amount = fields.Float(string='Estimated Total', compute='_compute_total_amount', store=True)
    revenue_category = fields.Selection([
        ('actual', 'Actual Revenue (In-House/Done)'),
        ('forecast', 'Forecast Revenue (Confirmed)')
    ], string="Revenue Category", compute='_compute_revenue_category', store=True)
    
    currency_id = fields.Many2one('res.currency', related='company_id.currency_id', store=True)
    company_id = fields.Many2one('res.company', string='Company', required=True, default=lambda self: self.env.company)
    
    guest_visit_count = fields.Integer(compute='_compute_visit_count', string="Visit Count")
    change_log_count = fields.Integer(compute='_compute_change_log_count', string='Change Logs')
    payment_count = fields.Integer(compute='_compute_payment_count', string="Receipts")
    payment_registered_total = fields.Monetary(
        string="Payment Registered",
        compute='_compute_payment_count',
        currency_field='currency_id',
    )
    invoice_count = fields.Integer(compute='_compute_invoice_count', string="Invoices")
    
    posting_journal_count = fields.Integer(compute='_compute_posting_journal_count', string='Guest Folio Entries')
    folio_count = fields.Integer(compute='_compute_folio_count', string='Guest Folios')

    state = fields.Selection([
        ('draft', 'Draft'),
        ('confirm', 'Confirmed'),
        ('guaranteed', 'Guaranteed'),
        ('waitlist', 'Waitlist'),
        ('checkin', 'In-House'),
        ('checkout_hold', 'Checkout Hold'), 
        ('checkout', 'Checked Out'),
        ('noshow', 'No-Show'),
        ('cancel', 'Cancelled'),
        ('blocked', 'Maintenance Block'), 
    ], string='Status', default='draft', tracking=True)
    is_business_arrival_today = fields.Boolean(
        string="Business Arrival Today",
        compute='_compute_business_today_flags',
        search='_search_is_business_arrival_today',
    )
    is_business_departure_today = fields.Boolean(
        string="Business Departure Today",
        compute='_compute_business_today_flags',
        search='_search_is_business_departure_today',
    )
    is_business_stayover_today = fields.Boolean(
        string="Business Stayover Today",
        compute='_compute_business_today_flags',
        search='_search_is_business_stayover_today',
    )
    no_show_datetime = fields.Datetime(string="No-Show Date/Time", copy=False, readonly=True)
    no_show_source = fields.Selection([
        ('auto', 'Automatic'),
        ('manual', 'Manual'),
    ], string="No-Show Source", copy=False, readonly=True)

    @api.model
    def _get_hotel_business_date(self):
        return self.env.company.hotel_business_date or fields.Date.context_today(self)

    @api.model
    def get_hotel_business_date_for_ui(self):
        business_date = self._get_hotel_business_date()
        return fields.Date.to_string(business_date)

    @api.model
    def _business_arrival_today_domain(self):
        biz_date = self._get_hotel_business_date()
        return [
            ('checkin_date', '=', biz_date),
            ('state', '=', 'confirm'),
            ('is_desk_folio', '=', False),
        ]

    @api.model
    def _business_departure_today_domain(self):
        biz_date = self._get_hotel_business_date()
        return [
            ('checkout_date', '=', biz_date),
            ('state', 'in', ['checkin', 'checkout_hold']),
            ('is_desk_folio', '=', False),
        ]

    @api.model
    def _business_stayover_today_domain(self):
        biz_date = self._get_hotel_business_date()
        return [
            ('checkin_date', '<=', biz_date),
            ('checkout_date', '>', biz_date),
            ('state', 'in', ['checkin', 'confirm']),
            ('is_desk_folio', '=', False),
        ]

    def _compute_business_today_flags(self):
        biz_date = self._get_hotel_business_date()
        for rec in self:
            rec.is_business_arrival_today = (
                rec.checkin_date == biz_date
                and rec.state == 'confirm'
                and not rec.is_desk_folio
            )
            rec.is_business_departure_today = (
                rec.checkout_date == biz_date
                and rec.state in ['checkin', 'checkout_hold']
                and not rec.is_desk_folio
            )
            rec.is_business_stayover_today = (
                rec.checkin_date
                and rec.checkout_date
                and rec.checkin_date <= biz_date
                and rec.checkout_date > biz_date
                and rec.state in ['checkin', 'confirm']
                and not rec.is_desk_folio
            )

    @api.model
    def _business_today_search_domain(self, operator, value, domain):
        positive = (operator in ('=', '==') and bool(value)) or (operator == '!=' and not bool(value))
        negative = (operator in ('=', '==') and not bool(value)) or (operator == '!=' and bool(value))
        if positive:
            return domain
        if negative:
            return list(~fields.Domain(domain))
        raise UserError(_("Unsupported operator for business-date filter: %s") % operator)

    @api.model
    def _search_is_business_arrival_today(self, operator, value):
        return self._business_today_search_domain(
            operator,
            value,
            self._business_arrival_today_domain(),
        )

    @api.model
    def _search_is_business_departure_today(self, operator, value):
        return self._business_today_search_domain(
            operator,
            value,
            self._business_departure_today_domain(),
        )

    @api.model
    def _search_is_business_stayover_today(self, operator, value):
        return self._business_today_search_domain(
            operator,
            value,
            self._business_stayover_today_domain(),
        )

    udf_label_1 = fields.Char(related='company_id.hotel_udf_label_1')
    udf_value_1 = fields.Many2one('hotel.guest.attribute', domain="[('udf_number', '=', '1')]")
    
    udf_label_2 = fields.Char(related='company_id.hotel_udf_label_2')
    udf_value_2 = fields.Many2one('hotel.guest.attribute', domain="[('udf_number', '=', '2')]")
    
    udf_label_3 = fields.Char(related='company_id.hotel_udf_label_3')
    udf_value_3 = fields.Many2one('hotel.guest.attribute', domain="[('udf_number', '=', '3')]")
    
    udf_label_4 = fields.Char(related='company_id.hotel_udf_label_4')
    udf_value_4 = fields.Many2one('hotel.guest.attribute', domain="[('udf_number', '=', '4')]")
    
    udf_label_5 = fields.Char(related='company_id.hotel_udf_label_5')
    udf_value_5 = fields.Many2one('hotel.guest.attribute', domain="[('udf_number', '=', '5')]")
    
    udf_label_6 = fields.Char(related='company_id.hotel_udf_label_6')
    udf_value_6 = fields.Many2one('hotel.guest.attribute', domain="[('udf_number', '=', '6')]")
    
    udf_label_7 = fields.Char(related='company_id.hotel_udf_label_7')
    udf_value_7 = fields.Many2one('hotel.guest.attribute', domain="[('udf_number', '=', '7')]")
    
    udf_label_8 = fields.Char(related='company_id.hotel_udf_label_8')
    udf_value_8 = fields.Many2one('hotel.guest.attribute', domain="[('udf_number', '=', '8')]")
    
    udf_label_9 = fields.Char(related='company_id.hotel_udf_label_9')
    udf_value_9 = fields.Many2one('hotel.guest.attribute', domain="[('udf_number', '=', '9')]")
    
    udf_label_10 = fields.Char(related='company_id.hotel_udf_label_10')
    udf_value_10 = fields.Many2one('hotel.guest.attribute', domain="[('udf_number', '=', '10')]")

    def _generate_daily_transactions(self):
        for rec in self:
            existing_lines = rec.daily_transaction_ids.sorted(
                lambda line: (line.date or fields.Date.context_today(self), line.id)
            )
            expected_dates = {fields.Date.to_date(stay_date) for stay_date in rec._get_stay_business_dates()}

            if rec.is_desk_folio or rec.state in ['cancel', 'noshow', 'blocked'] or not expected_dates:
                existing_lines.filtered(lambda line: not line.is_posted).with_context(
                    skip_hotel_daily_rate_audit=True
                ).unlink()
                continue

            kept_lines_by_date = {}
            duplicate_unposted_lines = self.env['hotel.daily.transaction']
            sorted_lines = existing_lines.sorted(
                lambda line: (line.date or fields.Date.context_today(self), 0 if line.is_posted else 1, line.id)
            )
            for line in sorted_lines:
                stay_date = fields.Date.to_date(line.date)
                if stay_date not in kept_lines_by_date:
                    kept_lines_by_date[stay_date] = line
                    continue
                if not line.is_posted:
                    duplicate_unposted_lines |= line

            if duplicate_unposted_lines:
                duplicate_unposted_lines.with_context(skip_hotel_daily_rate_audit=True).unlink()

            obsolete_unposted_lines = existing_lines.filtered(
                lambda line: not line.is_posted and fields.Date.to_date(line.date) not in expected_dates
            )
            if obsolete_unposted_lines:
                obsolete_unposted_lines.with_context(skip_hotel_daily_rate_audit=True).unlink()

            for stay_date in sorted(expected_dates):
                line = kept_lines_by_date.get(stay_date)
                transaction_vals = rec._prepare_daily_transaction_vals(stay_date)
                if line:
                    if line.is_posted:
                        continue
                    sync_vals = {
                        'description': transaction_vals['description'],
                        'room_nights': transaction_vals['room_nights'],
                    }
                    if line.is_manual_rate_override:
                        line.with_context(skip_hotel_daily_rate_audit=True).write(sync_vals)
                        continue

                    sync_vals.update({
                        'revenue': transaction_vals['revenue'],
                        'is_manual_rate_override': False,
                    })
                    if abs((line.revenue or 0.0) - (transaction_vals['revenue'] or 0.0)) > (rec.currency_id.rounding or 0.01):
                        sync_vals['rate_override_reason'] = False
                    line.with_context(skip_hotel_daily_rate_audit=True).write(sync_vals)
                else:
                    self.env['hotel.daily.transaction'].with_context(skip_hotel_daily_rate_audit=True).create(transaction_vals)

    def _compute_posting_journal_count(self):
        for rec in self:
            rec.posting_journal_count = self.env['hotel.posting.journal'].search_count([
                ('reservation_id', '=', rec.id),
                ('folio_billing_target', '!=', 'company'),
            ])

    def _compute_folio_count(self):
        Order = self.env['sale.order'].sudo()
        for rec in self:
            orders = rec.sale_order_id.sudo() | Order.search([
                ('hotel_reservation_ids', 'in', rec.id),
            ])
            rec.folio_count = len(orders.exists())
            
    @api.depends(
        'partner_id',
        'city_ledger_id',
        'sale_order_id.order_line.price_total',
        'sale_order_id.order_line.price_unit',
        'sale_order_id.order_line.product_uom_qty',
        'sale_order_id.order_line.discount',
        'sale_order_id.order_line.tax_ids',
        'sale_order_id.order_line.qty_to_invoice',
        'sale_order_id.order_line.display_type',
        'sale_order_id.order_line.billing_target',
        'sale_order_id.order_line.is_downpayment',
        'sale_order_id.order_line.name',
        'sale_order_id.invoice_ids.state',
        'sale_order_id.invoice_ids.payment_state',
        'sale_order_id.invoice_ids.amount_residual',
        'sale_order_id.invoice_ids.amount_total',
        'sale_order_id.invoice_ids.partner_id',
        'sale_order_id.invoice_ids.hotel_billing_target',
        'sale_order_id.invoice_ids.invoice_line_ids.price_total',
        'sale_order_id.invoice_ids.invoice_line_ids.display_type',
        'sale_order_id.invoice_ids.invoice_line_ids.is_advance_deposit_application',
        'sale_order_id.invoice_ids.reversal_move_ids.state',
        'sale_order_id.invoice_ids.reversal_move_ids.payment_state',
        'sale_order_id.invoice_ids.reversal_move_ids.amount_residual',
        'deposit_invoice_ids.state',
        'deposit_invoice_ids.payment_state',
        'deposit_invoice_ids.amount_residual',
        'deposit_invoice_ids.amount_total',
        'deposit_invoice_ids.reversal_move_ids.state',
        'deposit_invoice_ids.reversal_move_ids.payment_state',
        'deposit_invoice_ids.reversal_move_ids.amount_residual',
        'deposit_invoice_ids.reversal_move_ids.amount_total',
        'advance_deposit_payment_ids.state',
        'advance_deposit_payment_ids.amount',
        'advance_deposit_payment_ids.payment_type',
        'advance_deposit_payment_ids.is_advance_deposit',
        'deposit_application_line_ids.is_advance_deposit_application',
        'deposit_application_line_ids.price_total',
        'deposit_application_line_ids.move_id.state',
    )
    def _compute_folio_status(self):
        for rec in self:
            # Operational PMS balance is always transaction based:
            # guest debit activity minus real credits. Invoice documents only
            # change invoice status; they do not pay the folio.
            calc_rec = rec.sudo()
            position = calc_rec._get_operational_folio_position()
            rec.folio_total = position['folio_total_debit']
            rec.folio_paid = position['folio_total_credit']
            rec.deposit_balance = calc_rec._get_deposit_balance_amount()
            rec.guest_total_charges = position['folio_total_debit']
            rec.guest_tax_included_amount = position['folio_total_debit']
            rec.advance_deposit_credit = position['deposit_credit']
            rec.remaining_deposit_available = calc_rec._get_operational_advance_deposit_credit_amount()
            rec.guest_invoice_payments = position['payments_received']
            rec.guest_deposit_paid_total = position['folio_total_credit']
            rec.guest_balance_due = position['balance_due']
            rec.guest_net_position = position['operational_balance']
            rec.guest_credit_balance = position['credit_balance']
            rec.guest_balance_button_amount = rec.guest_balance_due or rec.guest_credit_balance
            # Group Paymaster correction:
            # If the group advance deposit was already applied to the invoice,
            # do not keep showing it as an unused guest ledger credit.
            if rec.is_desk_folio and rec.group_id:
                available_deposit = calc_rec._get_deposit_balance_amount()

                rec.deposit_balance = available_deposit
                rec.advance_deposit_credit = available_deposit
                rec.remaining_deposit_available = available_deposit

                if available_deposit <= 0.01:
                    rec.guest_balance_due = 0.0
                    rec.guest_credit_balance = 0.0
                    rec.guest_net_position = 0.0
                    rec.folio_balance = 0.0
                else:
                    rec.guest_credit_balance = available_deposit
                    rec.guest_balance_due = 0.0
                    rec.guest_net_position = -available_deposit
                    rec.folio_balance = 0.0
            if rec.guest_credit_balance > 0.01 and rec.guest_balance_due <= 0.01:
                rec.guest_balance_button_label = _('Guest Credit Balance')
            elif rec.guest_balance_due > 0.01:
                rec.guest_balance_button_label = _('Guest Balance Due')
            else:
                rec.guest_balance_button_label = _('Settled')
            rec.folio_balance = rec.guest_balance_due
            rec.company_pending_billing = calc_rec._get_company_pending_billing_amount()
            rec.company_city_ledger_ar = calc_rec._get_company_outstanding_amount()

    def _refresh_operational_folio_status(self):
        """Recompute stored folio balance fields after posting-journal-only activity."""
        records = self.exists()
        if not records:
            return
        field_names = [
            'folio_total',
            'folio_paid',
            'folio_balance',
            'deposit_balance',
            'guest_total_charges',
            'guest_tax_included_amount',
            'advance_deposit_credit',
            'remaining_deposit_available',
            'guest_invoice_payments',
            'guest_deposit_paid_total',
            'guest_balance_due',
            'guest_net_position',
            'guest_credit_balance',
            'guest_balance_button_amount',
            'guest_balance_button_label',
            'company_pending_billing',
            'company_city_ledger_ar',
        ]
        for field_name in field_names:
            records.env.add_to_compute(records._fields[field_name], records)
        records._recompute_recordset(field_names)
        records.flush_recordset(field_names)

    @api.depends('checkin_date', 'checkout_date')
    def _compute_duration(self):
        for rec in self:
            rec.duration = (rec.checkout_date - rec.checkin_date).days if rec.checkin_date and rec.checkout_date else 0

    @api.onchange('duration')
    def _onchange_duration(self):
        if self.checkin_date and self.duration:
            self.checkout_date = self.checkin_date + timedelta(days=self.duration)

    @api.onchange('checkout_date', 'state')
    def _onchange_checkout_date(self):
        if self.state == 'blocked': 
            pass
        elif self.checkin_date and self.checkout_date and self.checkout_date <= self.checkin_date:
            self.duration = 1
            self.checkout_date = self.checkin_date + timedelta(days=1)

    @api.depends(
        'checkin_date',
        'checkout_date',
        'rate_plan_id',
        'is_manual_rate',
        'manual_rate',
        'room_type_id',
        'adults',
        'daily_transaction_ids.date',
        'daily_transaction_ids.revenue',
    )
    def _compute_total_amount(self):
        for rec in self:
            if not rec.checkin_date or not rec.checkout_date:
                rec.total_amount = 0.0
                continue
                
            delta = (rec.checkout_date - rec.checkin_date).days
            if delta <= 0: delta = 1
            
            total = 0.0
            for i in range(delta):
                dt = rec.checkin_date + timedelta(days=i)
                total += rec._get_daily_room_charge_amount(dt)
                    
            rec.total_amount = total

    @api.depends('state')
    def _compute_revenue_category(self):
        for rec in self:
            if rec.state in ['checkin', 'checkout_hold', 'checkout']:
                rec.revenue_category = 'actual'
            elif rec.state == 'confirm':
                rec.revenue_category = 'forecast'
            else:
                rec.revenue_category = False

    @api.depends('room_type_id', 'checkin_date', 'checkout_date')
    def _compute_available_room_ids(self):
        for rec in self:
            rooms = self.env['hotel.room']

            if not rec.room_type_id:
                rec.available_room_ids = rooms
                continue

            rooms = self.env['hotel.room'].search([
                ('room_type_id', '=', rec.room_type_id.id)
            ])

            if rec.checkin_date and rec.checkout_date:
                conflict_domain = [
                    ('room_id', '!=', False),
                    ('state', 'not in', ['cancel', 'noshow', 'checkout']),
                    ('checkin_date', '<', rec.checkout_date),
                    ('checkout_date', '>', rec.checkin_date),
                ]

                if rec._origin and rec._origin.id:
                    conflict_domain.append(('id', '!=', rec._origin.id))

                conflicts = self.env['hotel.reservation'].search(conflict_domain)
                booked_room_ids = conflicts.mapped('room_id').ids

                rooms = rooms.filtered(lambda r: r.id not in booked_room_ids)
                room_blocks = self.env['hotel.room.block'].sudo().search([
                    ('room_id', 'in', rooms.ids),
                    ('state', '=', 'active'),
                    ('date_from', '<', rec.checkout_date),
                    ('date_to', '>', rec.checkin_date),
                ])
                blocked_room_ids = room_blocks.mapped('room_id').ids
                rooms = rooms.filtered(lambda r: r.id not in blocked_room_ids)

            rec.available_room_ids = rooms

    @api.depends('partner_id')
    def _compute_visit_count(self):
        for rec in self:
            rec.guest_visit_count = rec._get_partner_visit_count(rec.partner_id)

    def _get_completed_stay_reservations_for_partner(self, partner):
        if not partner:
            return self.env['hotel.reservation']
        main_stays = self.search([
            ('partner_id', '=', partner.id),
            ('state', '=', 'checkout'),
            ('is_desk_folio', '=', False),
        ])
        tagged_stays = self.search([
            ('accompanying_guest_ids', 'in', partner.id),
            ('state', '=', 'checkout'),
            ('is_desk_folio', '=', False),
        ])
        structured_stays = self.env['hotel.reservation.guest'].search([
            ('partner_id', '=', partner.id),
            ('reservation_id.state', '=', 'checkout'),
            ('reservation_id.is_desk_folio', '=', False),
        ]).mapped('reservation_id')
        return (main_stays | tagged_stays | structured_stays).exists()

    def _partner_participates_in_reservation(self, reservation, partner):
        return bool(
            partner
            and (
                reservation.partner_id == partner
                or partner in reservation.accompanying_guest_ids
                or partner in reservation.stay_guest_ids.mapped('partner_id')
            )
        )

    def _get_partner_visit_count(self, partner):
        if not partner:
            return 0
        completed = self._get_completed_stay_reservations_for_partner(partner)
        current_count = 1 if self and len(self) == 1 and self.state not in ['cancel', 'noshow', 'blocked'] else 0
        if self and len(self) == 1 and self.id in completed.ids:
            current_count = 0
        return len(completed) + current_count

    def _is_repeat_guest_partner(self, partner):
        self.ensure_one()
        if not partner:
            return False
        completed = self._get_completed_stay_reservations_for_partner(partner).filtered(lambda res: res.id != self.id)
        if self.checkin_date:
            completed = completed.filtered(lambda res: not res.checkout_date or res.checkout_date <= self.checkin_date)
        return bool(completed)

    def _has_any_repeat_stay_guest(self):
        self.ensure_one()
        partners = (
            self.partner_id
            | self.accompanying_guest_ids
            | self.stay_guest_ids.mapped('partner_id')
        )
        return any(self._is_repeat_guest_partner(partner) for partner in partners)

    def _get_repeat_guest_classification(self):
        return (
            self.env.ref('hotel_management.guest_classification_repeat_guest', raise_if_not_found=False)
            or self.env['hotel.guest.classification'].search([('code', '=', 'repeat_guest')], limit=1)
            or self.env['hotel.guest.classification'].create({
                'name': _('Repeat Guest'),
                'code': 'repeat_guest',
                'priority': 10,
            })
        )

    def _apply_repeat_guest_classification(self):
        repeat_class = self._get_repeat_guest_classification()
        for rec in self:
            current_class = rec.guest_classification_id
            is_normal = bool(
                current_class
                and (
                    current_class.code == 'normal'
                    or (current_class.name or '').strip().lower() == 'normal'
                )
            )
            if rec.partner_id and rec._is_repeat_guest_partner(rec.partner_id) and (not current_class or is_normal):
                rec.with_context(skip_repeat_guest_classification=True).guest_classification_id = repeat_class.id

    def _sync_stay_guests_from_reservation_partners(self):
        StayGuest = self.env['hotel.reservation.guest'].sudo()
        for rec in self:
            if rec.is_desk_folio:
                continue
            if rec.partner_id and not rec.stay_guest_ids.filtered(lambda guest: guest.is_primary):
                StayGuest.create({
                    'reservation_id': rec.id,
                    'partner_id': rec.partner_id.id,
                    'name': rec.partner_id.name,
                    'phone': rec.partner_id.phone,
                    'email': rec.partner_id.email,
                    'passport_no': rec.partner_id.passport_number,
                    'nationality_id': rec.partner_id.nationality_id.id,
                    'country_id': rec.partner_id.country_id.id,
                    'date_of_birth': rec.partner_id.hotel_date_of_birth,
                    'gender': rec.partner_id.hotel_gender,
                    'guest_type': 'main',
                    'is_primary': True,
                })
            existing_partner_ids = set(rec.stay_guest_ids.mapped('partner_id').ids)
            for partner in rec.accompanying_guest_ids:
                if partner.id in existing_partner_ids:
                    continue
                StayGuest.create({
                    'reservation_id': rec.id,
                    'partner_id': partner.id,
                    'name': partner.name,
                    'phone': partner.phone,
                    'email': partner.email,
                    'passport_no': partner.passport_number,
                    'nationality_id': partner.nationality_id.id,
                    'country_id': partner.country_id.id,
                    'date_of_birth': partner.hotel_date_of_birth,
                    'gender': partner.hotel_gender,
                    'guest_type': 'accompanying',
                    'is_primary': False,
                })

    def _missing_required_guest_profiles(self):
        self.ensure_one()
        expected_count = max((self.adults or 0) + (self.children or 0), 1)
        completed_guests = self.stay_guest_ids.filtered(
            lambda guest: guest.name and (guest.passport_no or guest.partner_id.passport_number)
        )
        if len(completed_guests) >= expected_count:
            return self.env['hotel.reservation.guest']
        return self.stay_guest_ids - completed_guests

    def _compute_change_log_count(self):
        for rec in self:
            rec.change_log_count = self.env['hotel.change.log'].search_count([
                ('reservation_id', '=', rec.id)
            ])

    def _log_exchange_event(
        self,
        field_name,
        old_value=False,
        new_value=False,
        *,
        change_type='field',
        reason=False,
        source_document=False,
        user=False,
        change_date=False,
    ):
        logger = self.env['hotel.change.log']
        for rec in self:
            logger.log_reservation_event(
                rec,
                field_name,
                old_value,
                new_value,
                change_type=change_type,
                reason=reason,
                source_document=source_document or rec,
                user=user,
                change_date=change_date,
            )

    def _get_registered_payment_records(self):
        self.ensure_one()
        payments = self.env['account.payment']

        direct_payments = self.env['account.payment'].search([
            ('hotel_reservation_id', '=', self.id),
            ('state', 'in', ('in_process', 'paid')),
            ('payment_type', '=', 'inbound'),
        ])
        payments |= direct_payments

        folio_invoices = self._get_folio_customer_invoices().filtered(lambda inv: inv.state == 'posted')
        for inv in folio_invoices:
            payments |= inv._get_reconciled_payments().filtered(
                lambda pay: (
                    pay.state in ('in_process', 'paid')
                    and pay.payment_type == 'inbound'
                    and not pay.is_advance_deposit
                )
            )

        return payments.filtered(
            lambda pay: not pay.advance_deposit_void_payment_ids.filtered(lambda void: void.state != 'cancel')
        )

    def _compute_payment_count(self):
        for rec in self:
            payments = rec._get_registered_payment_records()
            rec.payment_count = len(payments)
            rec.payment_registered_total = sum(payments.mapped('amount'))

    def _create_email_audit(self, audit_type, recipient, status, subject, mail=False, attachment=False, failure_reason=False):
        Audit = self.env['hotel.email.audit'].sudo()
        for rec in self:
            Audit.create({
                'reservation_id': rec.id,
                'audit_type': audit_type,
                'recipient': recipient or rec.partner_email or rec.partner_id.email or '-',
                'status': status,
                'subject': subject or '-',
                'mail_id': mail.id if mail else False,
                'attachment_id': attachment.id if attachment else False,
                'failure_reason': failure_reason or False,
            })

    @api.depends(
        'sale_order_id.invoice_ids.move_type',
        'sale_order_id.invoice_ids.state',
        'deposit_invoice_ids.move_type',
        'deposit_invoice_ids.state',
    )
    def _compute_invoice_count(self):
        for rec in self:
            rec.invoice_count = len(rec._get_reservation_customer_invoices())

    @api.onchange('is_desk_folio', 'room_type_id', 'checkin_date', 'checkout_date')
    def _onchange_room_type_id(self):
        if self.state == 'blocked':
            return

        if self.is_desk_folio:
            self.room_id = False
            self.rate_id = False
            return

        if not self.room_type_id:
            self.room_id = False
            self.rate_id = False
            return
       
        # Keep your rate auto-fill
        rate = self.env['hotel.room.rate'].search([
            ('room_type_id', '=', self.room_type_id.id)
        ], limit=1)
        self.rate_id = rate.id if rate else False

        # Step 1: get all rooms of selected type
        rooms = self.env['hotel.room'].search([
            ('room_type_id', '=', self.room_type_id.id)
        ])

        # Step 2: remove rooms already booked/blocked in overlapping dates
        if self.checkin_date and self.checkout_date:
            conflict_domain = [
                ('room_id', '!=', False),
                ('state', 'not in', ['cancel', 'noshow', 'checkout']),
                ('checkin_date', '<', self.checkout_date),
                ('checkout_date', '>', self.checkin_date),
            ]

            # Exclude current reservation itself when editing
            if self._origin and self._origin.id:
                conflict_domain.append(('id', '!=', self._origin.id))

            conflicts = self.env['hotel.reservation'].search(conflict_domain)
            blocked_room_ids = conflicts.mapped('room_id').ids
            rooms = rooms.filtered(lambda r: r.id not in blocked_room_ids)
            room_blocks = self.env['hotel.room.block'].sudo().search([
                ('room_id', 'in', rooms.ids),
                ('state', '=', 'active'),
                ('date_from', '<', self.checkout_date),
                ('date_to', '>', self.checkin_date),
            ])
            blocked_room_ids = room_blocks.mapped('room_id').ids
            rooms = rooms.filtered(lambda r: r.id not in blocked_room_ids)

        # Step 3: for future booking, trust reservation overlap/block logic first.
        # Do NOT exclude a room just because it is occupied today.
        # Only exclude truly non-sellable physical states if your room model uses them.
        sellable_rooms = rooms

        # Step 4: prefer clean rooms first, but do not hard-block future booking
        ready_rooms = sellable_rooms.filtered(
            lambda r: r.availability_status == 'available'
            and r.occupancy_status == 'vacant'
            and r.release_ready
        )
        clean_rooms = sellable_rooms.filtered(
            lambda r: r.availability_status == 'available'
            and r.occupancy_status == 'vacant'
            and r.housekeeping_status in ['clean', 'inspected']
            and not r.release_ready
        )
        dirty_rooms = sellable_rooms.filtered(
            lambda r: r.availability_status == 'available'
            and r.occupancy_status == 'vacant'
            and r.housekeeping_status == 'dirty'
        )
        other_rooms = sellable_rooms.filtered(lambda r: r.id not in (ready_rooms | clean_rooms | dirty_rooms).ids)

        # Do not auto-change room if user already selected a room from Room Chart/manual selection
        if self.room_id:
            return {
                'domain': {
                    'room_id': [('id', 'in', sellable_rooms.ids)],
                    'rate_id': [('room_type_id', '=', self.room_type_id.id)],
                }
            }

        # Step 5: auto-assign by priority
        
        if ready_rooms:
            self.room_id = ready_rooms[0]
        elif clean_rooms:
            self.room_id = clean_rooms[0]
        elif dirty_rooms:
            self.room_id = dirty_rooms[0]
            return {
                'domain': {
                    'room_id': [('id', 'in', sellable_rooms.ids)],
                    'rate_id': [('room_type_id', '=', self.room_type_id.id)],
                },
                'warning': {
                    'title': "Dirty Room Assigned",
                    'message': "No release-ready room is currently available, so the system assigned a dirty room. Housekeeping must clean and inspect it before check-in."
                }
            }
        elif other_rooms:
            self.room_id = other_rooms[0]
        else:
            self.room_id = False
            return {
                'domain': {
                    'room_id': [('id', 'in', sellable_rooms.ids)],
                    'rate_id': [('room_type_id', '=', self.room_type_id.id)],
                },
                'warning': {
                    'title': "No Room Available",
                    'message': "No room is available for this room type and date range."
                }
            }

        return {
            'domain': {
                'room_id': [('id', 'in', sellable_rooms.ids)],
                'rate_id': [('room_type_id', '=', self.room_type_id.id)],
            }
        }
    
    @api.onchange('room_id')
    def _onchange_room_id(self):
        if self.room_id:
            self.room_type_id = self.room_id.room_type_id

    @api.onchange('room_id', 'checkin_date', 'checkout_date')
    def _onchange_validate_room(self):
        for rec in self:
            if not rec.room_id or not rec.checkin_date or not rec.checkout_date:
                continue

            domain = [
                ('room_id', '=', rec.room_id.id),
                ('state', 'not in', ['cancel', 'noshow', 'checkout']),
                ('checkin_date', '<', rec.checkout_date),
                ('checkout_date', '>', rec.checkin_date),
            ]

            if rec._origin and rec._origin.id:
                domain.append(('id', '!=', rec._origin.id))

            block = rec._get_overlapping_room_block()
            if block:
                rec.room_id = False
                return {
                    'warning': {
                        'title': "Room Not Available",
                        'message': rec._get_room_block_message(block),
                    }
                }

            conflict = self.env['hotel.reservation'].search(domain, limit=1)

            if conflict:
                rec.room_id = False
                return {
                    'warning': {
                        'title': "Room Not Available",
                        'message': f"Room already booked from {conflict.checkin_date} to {conflict.checkout_date}"
                    }
                }

    @api.constrains('room_id', 'checkin_date', 'checkout_date', 'state')
    def _check_overlap(self):
        for rec in self:
            if not rec.room_id:
                continue

            if rec.state in ['cancel', 'noshow', 'checkout']:
                continue

            if rec.checkin_date and rec.checkout_date and rec.checkin_date >= rec.checkout_date:
                raise ValidationError("Check-out must be after Check-in.")

            domain = [
                ('room_id', '=', rec.room_id.id),
                ('state', 'not in', ['cancel', 'noshow', 'checkout']),
                ('checkin_date', '<', rec.checkout_date),
                ('checkout_date', '>', rec.checkin_date),
            ]

            if rec.id:
                domain.append(('id', '!=', rec.id))

            block = rec._get_overlapping_room_block()
            if block:
                raise ValidationError(rec._get_room_block_message(block))

            conflict = self.search(domain, limit=1)

            if conflict:
                if conflict.state == 'blocked':
                    raise ValidationError(
                        f"Room is BLOCKED (Maintenance) from "
                        f"{conflict.checkin_date} to {conflict.checkout_date}"
                    )

                raise ValidationError(
                    f"Room {rec.room_id.name} is already booked\n"
                    f"From: {conflict.checkin_date}\n"
                    f"To: {conflict.checkout_date}"
                )

    @api.constrains('rate_id', 'rate_plan_id', 'is_manual_rate', 'state', 'block_reason')
    def _check_rate_provided(self):
        for rec in self:
            if rec.state in ['cancel', 'noshow', 'blocked'] or rec.block_reason:
                continue

            if not rec.is_manual_rate and not rec.rate_id and not rec.rate_plan_id:
                raise ValidationError(
                    _("Revenue Protection: You must select a 'Master Rate Plan', an old 'Rate Plan', or check 'Override Room Rate' before saving!")
                )

    @api.constrains('state', 'partner_passport', 'room_id')
    def _check_requirements_at_checkin(self):
        for rec in self:
            if rec.state != 'checkin' or rec.is_desk_folio:
                continue

            if not rec.room_id:
                raise ValidationError(f"Stop! You must assign a specific Room Number before checking in '{rec.partner_id.name}'.")

            rec.room_id._ensure_operational_axes()
            block_conflict = rec._get_other_active_block(rec.room_id)
            occupied_conflict = rec._get_other_inhouse_conflict(rec.room_id)

            if block_conflict or rec.room_id.availability_status != 'available':
                raise ValidationError(f"Stop! Room {rec.room_id.name} is currently Out of Order. Please release it before check-in.")

            if occupied_conflict:
                raise ValidationError(f"Stop! Room {rec.room_id.name} is already occupied. Please assign a different room.")

            if rec.room_id.housekeeping_status == 'dirty':
                raise ValidationError(
                    f"Stop! Room {rec.room_id.name} is currently {rec.room_id.state}. "
                    "You cannot check a guest into a dirty room. Please assign a different room or rush Housekeeping."
                )

            if not rec.room_id.release_ready:
                raise ValidationError(
                    f"Stop! Room {rec.room_id.name} is cleaned but not release-ready yet. "
                    "Supervisor inspection must be completed before check-in."
                )

    def _ensure_folio_order_ready(self, order, auto_confirm=True):
        order = order.exists()
        if not order:
            return order

        if order.state == 'cancel':
            raise UserError(_("Hotel folio %s was cancelled. Please reopen or recreate the folio before continuing.") % (order.name or order.id))

        if not order.state:
            order.write({'state': 'draft'})

        if auto_confirm and order.state in ['draft', 'sent']:
            order.action_confirm()

        return order

    def _get_folio_customer_invoices(self):
        self.ensure_one()
        if not self.sale_order_id:
            return self.env['account.move'].sudo()
        return self.sudo().sale_order_id.invoice_ids.filtered(
            lambda inv: inv.move_type == 'out_invoice' and inv.state != 'cancel'
        )

    def _is_invoice_linked_to_reservation_folio(self, invoice):
        self.ensure_one()
        invoice = invoice.sudo()
        if invoice.move_type not in ('out_invoice', 'out_refund'):
            return False
        if invoice.hotel_folio_id and invoice.hotel_folio_id.id == self.sale_order_id.id:
            return True
        invoice_lines = invoice.invoice_line_ids
        if invoice_lines.filtered(lambda line: line.hotel_reservation_id.id == self.id):
            return True
        sale_lines = invoice_lines.mapped('sale_line_ids')
        return bool(
            sale_lines.filtered(
                lambda line: line.hotel_reservation_id.id == self.id
                or line.order_id.id == self.sale_order_id.id
            )
        )

    def _get_deposit_customer_invoices(self):
        self.ensure_one()
        Move = self.env['account.move'].sudo()
        reservation = self.sudo()
        return (reservation.deposit_invoice_ids | Move.search([
            ('invoice_origin', '=', self.name),
            ('move_type', '=', 'out_invoice'),
            ('state', '!=', 'cancel'),
        ])).filtered(lambda inv: inv.move_type == 'out_invoice' and inv.state != 'cancel')

    def _get_reservation_customer_invoices(self):
        self.ensure_one()
        # Deposit Receipt Only mode (V1): reservation invoice smart buttons show
        # stay/final tax invoices only. Legacy deposit invoices remain available
        # through the void-deposit flow for historical records.
        return self._get_folio_customer_invoices().exists()

    def _get_advance_deposit_payments(self, posted_only=False, inbound_only=False):
        self.ensure_one()
        payments = self.advance_deposit_payment_ids.filtered(lambda pay: pay.is_advance_deposit)
        if posted_only:
            payments = payments.filtered(lambda pay: pay.state in ('in_process', 'paid', 'posted'))
        if inbound_only:
            payments = payments.filtered(lambda pay: pay.payment_type == 'inbound')
        return payments

    def _get_posted_advance_deposit_amount(self):
        self.ensure_one()

        payment_total = sum(
            pay.amount if pay.payment_type == 'inbound' else -pay.amount
            for pay in self._get_advance_deposit_payments(posted_only=True)
        )

        transfer_entries = self.env['hotel.posting.journal'].search([
            ('reservation_id', '=', self.id),
            ('journal_type', '=', 'payment'),
            '|',
            ('description', 'ilike', 'Deposit Transfer Out%'),
            ('description', 'ilike', 'Deposit Transfer In%'),
        ])

        transfer_total = sum(-entry.amount for entry in transfer_entries)

        return payment_total + transfer_total

    def _get_active_advance_deposit_application_lines(self):
        self.ensure_one()
        return self.sudo().deposit_application_line_ids.filtered(
            lambda line: (
                line.is_advance_deposit_application
                and line.move_id.state != 'cancel'
                and line.move_id.move_type == 'out_invoice'
            )
        )

    def _get_posted_advance_deposit_application_lines(self):
        self.ensure_one()
        return self._get_active_advance_deposit_application_lines().filtered(
            lambda line: line.move_id.state == 'posted'
        )

    def _get_applied_advance_deposit_amount(self, posted_only=True):
        self.ensure_one()
        application_lines = (
            self._get_posted_advance_deposit_application_lines()
            if posted_only
            else self._get_active_advance_deposit_application_lines()
        )
        return sum(abs(line.price_total) for line in application_lines)

    def _get_advance_deposit_applied_to_invoice_amount(self):
        self.ensure_one()

        lines = self.env['account.move.line'].sudo().search([
            ('move_id.move_type', '=', 'out_invoice'),
            ('move_id.state', '!=', 'cancel'),
            ('hotel_reservation_id', '=', self.id),
            ('is_advance_deposit_application', '=', True),
        ])

        amount = abs(sum(lines.mapped('price_total')))
        return amount    
    
    def _get_deposit_balance_amount(self):
        self.ensure_one()
        currency = self.currency_id or self.company_id.currency_id

        posted_deposit = self._get_posted_advance_deposit_amount()
        applied_internal = self._get_applied_advance_deposit_amount()
        applied_to_invoice = self._get_advance_deposit_applied_to_invoice_amount()

        remaining = max(
            posted_deposit - applied_internal - applied_to_invoice,
            0.0
        )

        return currency.round(remaining) if currency else remaining

    def _get_operational_advance_deposit_credit_amount(self):
        self.ensure_one()

        is_group_paymaster = bool(self.is_desk_folio and self.group_id)

        if not is_group_paymaster and (self.is_desk_folio or self.folio_type != 'guest'):
            return 0.0

        return self._get_deposit_balance_amount()

    def _get_available_advance_deposit_credit_payments(self):
        self.ensure_one()
        rounding = self.currency_id.rounding or 0.01
        allocation_map = self._get_advance_deposit_payment_application_map(
            include_draft_applications=True
        )
        return self._get_advance_deposit_payments(posted_only=True, inbound_only=True).filtered(
            lambda pay: (pay.amount - allocation_map.get(pay.id, 0.0)) > rounding
        )

    def _get_deposit_refund_moves(self):
        self.ensure_one()
        deposit_invoices = self._get_deposit_customer_invoices()
        if not deposit_invoices:
            return self.env['account.move']
        return self.env['account.move'].search([
            ('reversed_entry_id', 'in', deposit_invoices.ids),
            ('move_type', '=', 'out_refund'),
            ('state', '!=', 'cancel'),
        ])

    def _get_voidable_deposit_invoices(self):
        self.ensure_one()
        return self._get_deposit_customer_invoices().filtered(
            lambda inv: not inv.reversal_move_ids.filtered(lambda refund: refund.state != 'cancel')
        )

    def _get_voidable_advance_deposit_payments(self):
        self.ensure_one()
        return self._get_advance_deposit_payments(inbound_only=True).filtered(
            lambda pay: (
                pay.state in ('draft', 'in_process', 'paid')
                and not pay.advance_deposit_void_payment_ids.filtered(lambda void: void.state != 'cancel')
            )
        )

    def _get_advance_deposit_payment_application_map(self, include_draft_applications=False):
        self.ensure_one()
        applied_amount = self._get_applied_advance_deposit_amount(
            posted_only=not include_draft_applications
        )
        rounding = self.currency_id.rounding or 0.01
        allocation_map = {}
        payments = self._get_voidable_advance_deposit_payments().filtered(
            lambda pay: pay.state in ('in_process', 'paid')
        ).sorted(lambda pay: (pay.date or fields.Date.context_today(self), pay.id))

        for payment in payments:
            if applied_amount <= rounding:
                allocation_map[payment.id] = 0.0
                continue
            allocated_amount = min(payment.amount, applied_amount)
            allocation_map[payment.id] = allocated_amount
            applied_amount -= allocated_amount

        return allocation_map

    def _is_advance_deposit_payment_applied(self, payment, include_draft_applications=True):
        self.ensure_one()
        if not payment or payment not in self._get_advance_deposit_payments(inbound_only=True):
            return False
        applied_amount = self._get_advance_deposit_payment_application_map(
            include_draft_applications=include_draft_applications
        ).get(payment.id, 0.0)
        return applied_amount > (self.currency_id.rounding or 0.01)

    def _check_deposit_void_access(self):
        self.ensure_one()
        if (
            self.env.su
            or self.env.user.has_group('hotel_management.group_hotel_manager')
            or self.env.user.has_group('hotel_management.group_hotel_front_office_manager')
            or self.env.user.has_group('account.group_account_manager')
            or self.env.user.has_group('hotel_management.group_hotel_night_auditor')
        ):
            return
        raise AccessError(_("Only Front Office Managers, Hotel Managers, or Accounting Managers can settle deposits."))

    def _get_linked_deposit_order_lines(self, deposit_invoice):
        self.ensure_one()
        if not self.sale_order_id:
            return self.env['sale.order.line']

        linked_lines = self.sale_order_id.order_line.filtered(
            lambda line: getattr(line, 'deposit_invoice_id', False) == deposit_invoice
        )
        if linked_lines:
            return linked_lines

        amount = abs(deposit_invoice.amount_total or 0.0)
        product_names = {'advance deposit', 'advance deposit applied'}
        return self.sale_order_id.order_line.filtered(
            lambda line: (
                not line.display_type
                and line.hotel_reservation_id == self
                and line.product_uom_qty
                and line.price_unit < 0
                and abs(abs(line.price_unit) - amount) <= (self.currency_id.rounding or 0.01)
                and (
                    (line.product_id and (line.product_id.display_name or '').strip().lower() in product_names)
                    or 'advance deposit' in (line.name or '').lower()
                )
            )
        )

    def _neutralize_deposit_order_lines(self, deposit_invoice, reason):
        self.ensure_one()
        deposit_lines = self._get_linked_deposit_order_lines(deposit_invoice)
        if not deposit_lines:
            return self.env['sale.order.line']

        note_suffix = _("Voided: %s") % reason
        for line in deposit_lines.filtered(lambda l: l.product_uom_qty):
            line.write({
                'product_uom_qty': 0.0,
                'name': "%s [%s]" % (line.name or _('Advance Deposit applied'), note_suffix),
            })
        return deposit_lines

    def _get_total_folio_amount(self):
        self.ensure_one()
        return self._get_operational_folio_position()['folio_total_debit']

    def _get_total_paid_amount(self):
        self.ensure_one()
        return self._get_operational_folio_position()['folio_total_credit']

    def _get_deposit_base_total(self):
        self.ensure_one()
        # Advance deposits for room reservations must follow the same tax-included
        # stay total shown on the Reservation Confirmation / Proforma document.
        if not self.is_desk_folio and self.folio_type == 'guest':
            currency = self.currency_id or self.company_id.currency_id
            total_stay_amount = self._get_reservation_confirmation_data().get('total_stay_amount', 0.0)
            return currency.round(max(total_stay_amount, 0.0)) if currency else max(total_stay_amount, 0.0)

        # Desk and group-master folios are excluded elsewhere and do not use this flow.
        return max(self.folio_total, self.total_amount, 0.0)

    def _get_required_deposit_amount(self):
        self.ensure_one()
        if not self.company_id.hotel_deposit_required:
            return 0.0
        currency = self.currency_id or self.company_id.currency_id
        percent = max(self.company_id.hotel_confirmation_deposit_percent or 0.0, 0.0)
        amount = self._get_deposit_base_total() * (percent / 100.0)
        return currency.round(amount) if currency else amount

    def _get_remaining_deposit_capacity(self):
        self.ensure_one()
        currency = self.currency_id or self.company_id.currency_id
        remaining_capacity = max(self._get_deposit_base_total() - self._get_deposit_balance_amount(), 0.0)
        return currency.round(remaining_capacity) if currency else remaining_capacity

    def _get_advance_deposit_liability_account(self):
        self.ensure_one()
        return self.company_id.hotel_advance_deposit_account_id

    def _get_configured_accommodation_product(self):
        self.ensure_one()
        setup = self.env['hotel.config.setup'].sudo()
        configured_product = (
            setup._get_config_record(self.company_id, 'hotel_accommodation_product_id', 'product.product')
            or setup._get_config_record(self.company_id, 'hotel_room_charge_product_id', 'product.product')
        )
        if configured_product:
            return configured_product
        return self.env['product.product'].search([
            ('name', 'in', ['Accommodation / Room Charge', 'Accommodation'])
        ], limit=1)

    def _get_advance_deposit_taxes(self):
        """Return the room/accommodation taxes used for a deposit invoice."""
        self.ensure_one()
        accommodation_lines = self.sale_order_id.order_line.filtered(
            lambda line: (
                not line.display_type
                and not line.is_downpayment
                and self._is_room_charge_billing_line(line)
            )
        ) if self.sale_order_id else self.env['sale.order.line']
        taxed_lines = accommodation_lines.filtered('tax_ids')
        if taxed_lines:
            tax_combinations = {tuple(sorted(line.tax_ids.ids)) for line in taxed_lines}
            if len(tax_combinations) > 1:
                raise UserError(_(
                    "Accommodation lines use different tax combinations. "
                    "A single advance deposit cannot allocate VAT accurately; "
                    "use consistent accommodation taxes before registering the deposit."
                ))
            return taxed_lines[:1].tax_ids

        accommodation_product = self._get_configured_accommodation_product()
        taxes = accommodation_product.taxes_id.filtered(
            lambda tax: tax.company_id == self.company_id
        ) if accommodation_product else self.env['account.tax']
        if taxes and self.sale_order_id.fiscal_position_id:
            taxes = self.sale_order_id.fiscal_position_id.map_tax(taxes)
        return taxes

    def _get_tax_inclusive_deposit_price_unit(self, total_amount, taxes):
        """Get a unit price whose tax-included invoice total equals the collected deposit."""
        self.ensure_one()
        if not taxes:
            return total_amount

        currency = self.currency_id or self.company_id.currency_id
        product = self._get_configured_accommodation_product()
        compute_kwargs = {
            'currency': currency,
            'quantity': 1.0,
            'product': product,
            'partner': self.partner_id,
        }
        tax_included_base = taxes.with_context(force_price_include=True).compute_all(
            total_amount, **compute_kwargs
        )['total_excluded']
        candidates = [tax_included_base, total_amount]
        for candidate in candidates:
            result = taxes.compute_all(candidate, **compute_kwargs)
            if currency.compare_amounts(result['total_included'], total_amount) == 0:
                return candidate

        # Covers mixed price-included/excluded configurations while keeping the collected total fixed.
        lower, upper = 0.0, max(total_amount, 1.0)
        while taxes.compute_all(upper, **compute_kwargs)['total_included'] < total_amount:
            upper *= 2
        for _index in range(60):
            candidate = (lower + upper) / 2.0
            if taxes.compute_all(candidate, **compute_kwargs)['total_included'] < total_amount:
                lower = candidate
            else:
                upper = candidate
        return currency.round(upper) if currency else upper

    def _get_deposit_application_target_invoice(self, invoices):
        self.ensure_one()
        invoices = invoices.filtered(lambda move: move.move_type == 'out_invoice' and move.state != 'cancel')
        guest_invoice = invoices.filtered(
            lambda move: move.hotel_billing_target == 'guest' and move.partner_id == self.partner_id
        )[:1]
        if guest_invoice:
            return guest_invoice
        single_invoice = invoices[:1] if len(invoices) == 1 else self.env['account.move']
        return single_invoice

    def _apply_advance_deposit_to_invoices(self, invoices):
        self.ensure_one()
        invoices = invoices.filtered(lambda move: move.move_type == 'out_invoice' and move.state != 'cancel')
        is_group_paymaster = bool(self.is_desk_folio and self.group_id)

        if not invoices:
            return self.env['account.move.line']

        if not is_group_paymaster and (self.is_desk_folio or self.folio_type != 'guest'):
            return self.env['account.move.line']

        deposit_account = self._get_advance_deposit_liability_account()
        if not deposit_account:
            raise UserError(_("Please configure the Advance Deposit Liability Account in Hotel Settings before applying deposits."))

        target_invoice = self._get_deposit_application_target_invoice(invoices)
        if not target_invoice or target_invoice.state == 'posted':
            return self.env['account.move.line']

        existing_lines = target_invoice.invoice_line_ids.filtered(
            lambda line: line.is_advance_deposit_application and line.hotel_reservation_id == self
        )
        if existing_lines:
            return existing_lines

        applied_amount_including_drafts = self._get_applied_advance_deposit_amount(posted_only=False)
        available_balance = max(self._get_posted_advance_deposit_amount() - applied_amount_including_drafts, 0.0)
        application_amount = min(available_balance, max(target_invoice.amount_total, 0.0))
        rounding = self.currency_id.rounding or 0.01
        if application_amount <= rounding:
            return self.env['account.move.line']

        # Deposit Receipt Only mode (V1): deposits are liability receipts and
        # are applied as a clean liability line on the final tax invoice. Taxed
        # deposit invoice/application mode is deferred to Version 2.
        application_taxes = self.env['account.tax']
        application_price_unit = -application_amount
        application_line = self.env['account.move.line'].create({
            'move_id': target_invoice.id,
            'name': _("Advance Deposit Applied"),
            'quantity': 1.0,
            'price_unit': application_price_unit,
            'tax_ids': [Command.set(application_taxes.ids)],
            'account_id': deposit_account.id,
            'hotel_reservation_id': self.id,
            'is_advance_deposit_application': True,
        })
        target_invoice.message_post(
            body=_("Advance deposit of %s%.2f applied from reservation %s.")
                 % ((self.currency_id.symbol or ''), application_amount, self.name),
            subtype_xmlid='mail.mt_note',
        )
        if hasattr(self, '_refresh_operational_folio_status'):
            self._refresh_operational_folio_status()
        if hasattr(self, '_compute_folio_status'):
            self._compute_folio_status()
        return application_line

    def _is_room_charge_billing_line(self, line):
        self.ensure_one()
        product = self.env['product.product']
        line_name = ''
        is_night_audit = False

        if isinstance(line, dict):
            product = self.env['product.product'].browse(line.get('product_id'))
            line_name = line.get('name') or ''
            is_night_audit = bool(line.get('is_night_audit_charge'))
        else:
            product = line.product_id
            line_name = line.name or ''
            is_night_audit = bool(getattr(line, 'is_night_audit_charge', False))

        category_name = product.categ_id.complete_name if product and product.categ_id else ''
        haystack = " ".join(filter(None, [line_name, product.display_name if product else '', category_name])).lower()
        room_keywords = ('room charge', 'accommodation', 'lodging')

        return is_night_audit or any(keyword in haystack for keyword in room_keywords)

    def _compute_default_billing_target(self, line):
        self.ensure_one()
        routing = self.billing_routing or 'guest'
        if routing == 'master_all':
            return 'company'
        if routing == 'master_room':
            return 'company' if self._is_room_charge_billing_line(line) else 'guest'
        return 'guest'

    def _get_routed_folio_lines(self, billing_target=None, invoiceable_only=False):
        self.ensure_one()
        if not self.sale_order_id:
            return self.env['sale.order.line']

        lines = self.sale_order_id.order_line.filtered(lambda line: not line.display_type)
        if billing_target:
            lines = lines.filtered(lambda line: line._get_resolved_billing_target() == billing_target)
        if invoiceable_only:
            lines = lines.filtered(lambda line: line.qty_to_invoice > 0)
        return lines

    def _get_routed_folio_invoices(self, billing_target):
        self.ensure_one()
        invoices = self._get_folio_customer_invoices()
        if billing_target == 'company':
            return invoices.filtered(
                lambda inv: (
                    inv.hotel_billing_target == 'company'
                    and self.city_ledger_id
                    and inv.partner_id == self.city_ledger_id
                )
            )

        return invoices.filtered(
            lambda inv: (
                (inv.hotel_billing_target == 'guest' and inv.partner_id == self.partner_id)
                or (
                    not inv.hotel_billing_target
                    and not self.city_ledger_id
                    and inv.partner_id == self.partner_id
                )
                )
            )

    def _get_folio_line_outstanding_amount(self, line):
        self.ensure_one()
        if line.display_type or line.qty_to_invoice <= 0:
            return 0.0

        currency = line.currency_id or line.order_id.currency_id or self.currency_id
        discounted_unit_price = line.price_unit * (1 - ((line.discount or 0.0) / 100.0))
        taxes_res = line.tax_ids.compute_all(
            discounted_unit_price,
            currency=currency,
            quantity=line.qty_to_invoice,
            product=line.product_id,
            partner=line.order_id.partner_shipping_id or line.order_id.partner_id,
        )
        return taxes_res['total_included']

    def _get_operational_folio_charge_lines(self, billing_target='guest'):
        self.ensure_one()
        return self._get_routed_folio_lines(billing_target, invoiceable_only=False).filtered(
            lambda line: (
                not line.display_type
                and not getattr(line, 'is_downpayment', False)
                and not getattr(line, 'deposit_invoice_id', False)
                and 'advance deposit' not in (line.name or '').lower()
            )
        )

    def _get_operational_payment_credit_amount(self, billing_target='guest'):
        self.ensure_one()
        all_folio_invoices = self._get_routed_folio_invoices(billing_target)

        # Count payments on normal invoices (out_invoice)
        invoices = all_folio_invoices.filtered(
            lambda inv: inv.move_type == 'out_invoice' and inv.state in ('posted', 'draft')
        )
        payments = self.env['account.payment']
        for invoice in invoices:
            payments |= invoice._get_reconciled_payments().filtered(
                lambda pay: pay.state in ('in_process', 'paid') and not pay.is_advance_deposit
            )
        inbound_total = sum(
            payment.amount if payment.payment_type == 'inbound' else -payment.amount
            for payment in payments
        )

        # Subtract payments on credit notes (out_refund) linked to folio invoices
        credit_notes = self.sale_order_id.invoice_ids.filtered(
            lambda inv: inv.move_type == 'out_refund' and inv.state == 'posted'
        ) if self.sale_order_id else self.env['account.move']
        refund_payments = self.env['account.payment']
        for cn in credit_notes:
            refund_payments |= cn._get_reconciled_payments().filtered(
                lambda pay: pay.state in ('in_process', 'paid')
            )
        refund_total = sum(
            pay.amount if pay.payment_type == 'outbound' else -pay.amount
            for pay in refund_payments
        )

        return inbound_total - refund_total

    def _get_operational_folio_position(self, billing_target='guest'):
        self.ensure_one()
        currency = self.currency_id or self.company_id.currency_id
        rounding = currency.round if currency else (lambda amount: amount)

        charge_lines = self._get_operational_folio_charge_lines(billing_target)
        line_debits = sum(max(line.price_total or 0.0, 0.0) for line in charge_lines)
        line_credits = sum(abs(min(line.price_total or 0.0, 0.0)) for line in charge_lines)

        deposit_credit = 0.0
        if billing_target == 'guest':
            deposit_credit = self._get_posted_advance_deposit_amount()

        payments_received = self._get_operational_payment_credit_amount(billing_target)
        folio_total_debit = rounding(line_debits)
        folio_total_credit = rounding(line_credits + deposit_credit + payments_received)
        operational_balance = rounding(folio_total_debit - folio_total_credit)
        # Group Paymaster correction:
        # Historical deposit paid can remain visible, but once the deposit
        # is applied to an invoice, it must not remain as unused ledger credit.
        if self.is_desk_folio and self.group_id:
            available_deposit = self._get_deposit_balance_amount()

            deposit_credit = available_deposit
            balance_due = 0.0
            credit_balance = available_deposit
            operational_balance = -available_deposit if available_deposit > 0.01 else 0.0

        return {
            'folio_total_debit': folio_total_debit,
            'folio_total_credit': folio_total_credit,
            'operational_balance': operational_balance,
            'balance_due': rounding(max(operational_balance, 0.0)),
            'credit_balance': rounding(max(-operational_balance, 0.0)),
            'deposit_credit': rounding(deposit_credit),
            'payments_received': rounding(payments_received),
        }

    def _get_guest_financial_position(self):
        self.ensure_one()
        currency = self.currency_id or self.company_id.currency_id
        rounding = currency.round if currency else (lambda amount: amount)

        position = self._get_operational_folio_position()
        pending_charges = self._get_guest_pending_charges_amount()
        draft_guest_invoices = self._get_routed_folio_invoices('guest').filtered(
            lambda inv: inv.state == 'draft'
        )
        posted_guest_invoices = self._get_routed_folio_invoices('guest').filtered(
            lambda inv: inv.state == 'posted'
        )
        posted_invoice_charges = self._get_guest_invoice_charge_amount(posted_guest_invoices)
        posted_unpaid = sum(
            posted_guest_invoices.filtered(lambda inv: inv.amount_residual > 0.01).mapped('amount_residual')
        )
        draft_invoice_total = sum(draft_guest_invoices.mapped('amount_total'))

        return {
            'pending_charges': rounding(pending_charges),
            'draft_invoices': rounding(draft_invoice_total),
            'posted_invoice_charges': rounding(posted_invoice_charges),
            'posted_unpaid': rounding(posted_unpaid),
            'guest_charges': position['folio_total_debit'],
            'tax_included_charges': position['folio_total_debit'],
            'advance_deposit_credit': position['deposit_credit'],
            'invoice_payments': position['payments_received'],
            'guest_net_position': position['operational_balance'],
            'guest_balance_due': position['balance_due'],
            'guest_credit_balance': position['credit_balance'],
        }

    def _get_guest_invoice_charge_amount(self, invoices):
        self.ensure_one()
        if not invoices:
            return 0.0
        charge_lines = invoices.mapped('invoice_line_ids').filtered(
            lambda line: (
                not line.display_type
                and not line.is_advance_deposit_application
                and line.price_total > 0
            )
        )
        return sum(charge_lines.mapped('price_total'))

    def _get_guest_invoice_credit_amount(self, invoices):
        self.ensure_one()
        if not invoices:
            return 0.0
        credit_lines = invoices.mapped('invoice_line_ids').filtered(
            lambda line: (
                not line.display_type
                and (line.is_advance_deposit_application or line.price_total < 0)
            )
        )
        return sum(abs(line.price_total) for line in credit_lines)

    def _get_guest_outstanding_amount(self):
        self.ensure_one()
        return self._get_operational_folio_position()['balance_due']

    def _get_guest_net_position_amount(self):
        self.ensure_one()
        return self._get_operational_folio_position()['operational_balance']

    def _get_guest_pending_charges_amount(self):
        self.ensure_one()
        return sum(
            self._get_folio_line_outstanding_amount(line)
            for line in self._get_routed_folio_lines('guest', invoiceable_only=True)
        )

    def _get_guest_draft_invoices_amount(self):
        self.ensure_one()
        guest_invoices = self._get_routed_folio_invoices('guest')
        return sum(guest_invoices.filtered(lambda inv: inv.state == 'draft').mapped('amount_total'))

    def _get_guest_posted_unpaid_amount(self):
        self.ensure_one()
        return self._get_guest_financial_position()['posted_unpaid']

    def _get_guest_collected_amount(self):
        self.ensure_one()
        return self._get_operational_folio_position()['payments_received']

    def _get_guest_pending_billing_amount(self):
        self.ensure_one()
        # Guest Pending Billing = not yet posted guest responsibility.
        return self._get_guest_pending_charges_amount() + self._get_guest_draft_invoices_amount()

    def _get_company_pending_billing_amount(self):
        self.ensure_one()
        return self._get_company_city_ledger_position()['pending_billing']

    def _get_company_invoice_totals(self):
        self.ensure_one()
        company_invoices = self._get_routed_folio_invoices('company').filtered(
            lambda inv: inv.move_type == 'out_invoice' and inv.state in ('draft', 'posted')
        )
        posted_invoices = company_invoices.filtered(lambda inv: inv.state == 'posted')
        draft_invoices = company_invoices.filtered(lambda inv: inv.state == 'draft')
        return {
            'draft_total': sum(draft_invoices.mapped('amount_total')),
            'posted_total': sum(posted_invoices.mapped('amount_total')),
            'posted_residual': sum(posted_invoices.mapped('amount_residual')),
            'invoice_ids': company_invoices.ids,
        }

    def _get_company_city_ledger_position(self):
        self.ensure_one()
        currency = self.currency_id or self.company_id.currency_id
        rounding = currency.round if currency else (lambda amount: amount)

        position = self._get_operational_folio_position('company')
        invoice_totals = self._get_company_invoice_totals()

        routed_amount = rounding(position['folio_total_debit'])
        paid_amount = rounding(position['payments_received'])
        balance = rounding(max(routed_amount - paid_amount, 0.0))
        posted_residual = rounding(invoice_totals['posted_residual'])
        draft_total = rounding(invoice_totals['draft_total'])
        pending_billing = rounding(max(balance - posted_residual - draft_total, 0.0))

        _logger.debug(
            "City Ledger position reservation=%s group=%s company=%s routed=%s "
            "invoice_total=%s paid=%s residual=%s balance=%s pending=%s invoices=%s",
            self.id,
            self.group_id.id if self.group_id else False,
            self.city_ledger_id.id if self.city_ledger_id else False,
            routed_amount,
            rounding(invoice_totals['posted_total'] + invoice_totals['draft_total']),
            paid_amount,
            posted_residual,
            balance,
            pending_billing,
            invoice_totals['invoice_ids'],
        )

        return {
            'routed_amount': routed_amount,
            'invoice_total': rounding(invoice_totals['posted_total'] + invoice_totals['draft_total']),
            'paid_amount': paid_amount,
            'posted_residual': posted_residual,
            'balance': balance,
            'pending_billing': pending_billing,
            'invoice_ids': invoice_totals['invoice_ids'],
        }

    def _get_company_outstanding_amount(self):
        self.ensure_one()
        # City Ledger balance is the original company-routed billable amount
        # minus real reconciled payments. Invoice creation must not create a
        # second debit for the same routed folio charges.
        return self._get_company_city_ledger_position()['balance']

    def _get_guest_ledger_amount(self):
        self.ensure_one()
        return self._get_operational_folio_position()['operational_balance']

    def _get_checkout_outstanding_balance(self):
        self.ensure_one()
        return self._get_operational_folio_position()['balance_due']

    def action_create_folio(self):
        for rec in self:
            if not rec.sale_order_id:
                target_partner = rec.partner_id.id
                if rec.city_ledger_id and (rec.is_desk_folio or rec.billing_routing == 'master_all'):
                    target_partner = rec.city_ledger_id.id

                SaleOrder = self.env['sale.order']
                order_vals = {
                    'partner_id': target_partner,
                    'reference': f"{'Desk Folio' if rec.is_desk_folio else 'Stay'}: {rec.name}",
                    # Keep sale.order on normal sale states; never leak reservation lifecycle states.
                    'date_order': rec._get_hotel_business_datetime(),
                    'hotel_reservation_ids': [(4, rec.id)],
                }
                if 'quotation_document_ids' in SaleOrder._fields:
                    order_vals['quotation_document_ids'] = [(6, 0, [])]
                order = SaleOrder.create(order_vals)
                order = rec._ensure_folio_order_ready(order)

                rec.sale_order_id = order.id
            else:
                rec.sale_order_id = rec._ensure_folio_order_ready(rec.sale_order_id).id
        return True

    def action_confirm(self):
        for rec in self:
            rec._validate_required_guest_fields('reservation')
            rec.state = 'confirm'
            if not rec.access_token:
                rec.access_token = str(uuid.uuid4())
                
            template = self.env.ref('hotel_management.email_template_hotel_reservation_confirm', raise_if_not_found=False)
            if template and rec.partner_email:
                email_body = template._render_field('body_html', [rec.id])[rec.id]
                subject = template._render_field('subject', [rec.id])[rec.id]
                if rec.company_id.hotel_deposit_required and rec.company_id.hotel_attach_confirmation_pdf_to_booking_email:
                    rec._create_email_audit(
                        'booking_confirmation',
                        rec.partner_email,
                        'queued',
                        subject,
                    )
                else:
                    mail_id = template.send_mail(rec.id, force_send=False)
                    rec._create_email_audit(
                        'booking_confirmation',
                        rec.partner_email,
                        'queued',
                        subject,
                        mail=self.env['mail.mail'].sudo().browse(mail_id).exists(),
                    )
                
                rec.message_post(
                    body=Markup(f"<b>Booking Confirmation email queued to guest.</b><br/><br/>{email_body}"), 
                    subtype_xmlid='mail.mt_note'
                )
            elif not rec.partner_email:
                rec._create_email_audit(
                    'booking_confirmation',
                    rec.partner_email or rec.partner_id.email or '-',
                    'skipped',
                    _("Booking Confirmation - %s") % (rec.name or ''),
                    failure_reason=_("Guest has no email address saved."),
                )
                rec.message_post(
                    body=Markup("<b>Email Skipped:</b> Guest has no email address saved!"), 
                    subtype_xmlid='mail.mt_note'
                )
            if rec._is_inside_pre_arrival_automation_window() and not rec._has_existing_pre_arrival_communication():
                rec.action_send_pre_arrival_link()

    def action_checkin(self):
        for rec in self:
            rec._sync_stay_guests_from_reservation_partners()
            if rec.is_desk_folio:
                raise UserError(_("Desk Folios are standalone non-stay folios and do not support check-in."))
            rec._validate_checkin_business_date()
            rec._validate_required_guest_fields('checkin')
            if rec.room_id:
                rec.room_id._ensure_operational_axes()
                rec.room_id._reconcile_operational_status()
            if rec.room_id and rec._get_other_inhouse_conflict(rec.room_id):
                raise UserError(_("Room Occupied: This room is not empty."))
            if rec.room_id and not rec.room_id.release_ready:
                raise UserError(_("Room Release Required: This room must be cleaned and released before check-in."))
            
            rec.with_context(
                skip_future_checkin_validation=True,
                skip_required_checkin_validation=True,
            ).write({'state': 'checkin'})
            if rec.room_id: 
                rec.room_id.with_context(hotel_reservation_room_workflow=True).write({
                    'occupancy_status': 'occupied',
                    'availability_status': 'available',
                    'do_not_disturb': False,
                    'turndown_completed': False,
                    'minibar_check_required': True,
                    'minibar_checked': False,
                    'linen_changed': False,
                })
                
            # --- THE MISSING LINK: Automatically create the financial Folio on Check-In! ---
            if not rec.sale_order_id:
                rec.action_create_folio()

    @api.model
    def cron_send_queued_booking_confirmation_pdfs(self, limit=20):
        audits = self.env['hotel.email.audit'].sudo().search([
            ('audit_type', '=', 'booking_confirmation'),
            ('status', '=', 'queued'),
            ('mail_id', '=', False),
        ], order='create_date asc, id asc', limit=limit)
        template = self.env.ref('hotel_management.email_template_hotel_reservation_confirm', raise_if_not_found=False)
        for audit in audits:
            reservation = audit.reservation_id.exists()
            if not reservation or not template:
                audit.write({
                    'status': 'failed',
                    'failure_reason': _("Reservation or booking confirmation template is missing."),
                })
                continue
            try:
                pdf_content, _content_type = self.env['ir.actions.report'].sudo()._render_qweb_pdf(
                    'hotel_management.action_report_reservation_confirmation',
                    res_ids=reservation.id,
                )
                attachment = self.env['ir.attachment'].sudo().create({
                    'name': 'Reservation_Confirmation_%s.pdf' % (reservation.name or reservation.id),
                    'type': 'binary',
                    'datas': base64.b64encode(pdf_content),
                    'res_model': 'hotel.reservation',
                    'res_id': reservation.id,
                    'mimetype': 'application/pdf',
                })
                mail_id = template.send_mail(
                    reservation.id,
                    force_send=True,
                    email_values={'attachment_ids': [(4, attachment.id)]},
                )
                mail = self.env['mail.mail'].sudo().browse(mail_id).exists()
                audit.write({
                    'status': 'sent',
                    'mail_id': mail.id if mail else False,
                    'attachment_id': attachment.id,
                    'failure_reason': False,
                })
                reservation.message_post(
                    body=_("Booking Confirmation email sent to guest with PDF attachment: %s") % audit.recipient,
                    subtype_xmlid='mail.mt_note',
                )
            except Exception as error:
                _logger.exception(
                    "Queued booking confirmation email failed for audit_id=%s reservation_id=%s",
                    audit.id,
                    reservation.id,
                )
                audit.write({
                    'status': 'failed',
                    'failure_reason': str(error),
                })
                reservation.message_post(
                    body=_("Booking Confirmation email failed for %(email)s: %(reason)s")
                    % {'email': audit.recipient or '-', 'reason': str(error)},
                    subtype_xmlid='mail.mt_note',
                )
        return True

    def _validate_checkin_business_date(self):
        for rec in self:
            if not rec.checkin_date or rec.is_desk_folio:
                continue

            arrival_date = fields.Date.to_date(rec.checkin_date)
            business_date = fields.Date.to_date(
                rec.company_id.hotel_business_date
                or self.env.company.hotel_business_date
                or fields.Date.context_today(rec)
            )
            if not arrival_date or not business_date:
                continue

            if arrival_date > business_date:
                raise UserError(_(
                    "Cannot check in a future reservation. Please amend the arrival date "
                    "to the Hotel Business Date before check-in."
                ))

            if arrival_date < business_date:
                rec.message_post(
                    body=_(
                        "Late check-in recorded. Arrival Date: %(arrival_date)s, "
                        "Hotel Business Date: %(business_date)s."
                    ) % {
                        'arrival_date': fields.Date.to_string(arrival_date),
                        'business_date': fields.Date.to_string(business_date),
                    },
                    subtype_xmlid='mail.mt_note',
                )

    def _guest_requirement_param(self, stage, field_code):
        return 'hotel_management.guest_profile_required_%s_%s' % (stage, field_code)

    def _guest_requirement_enabled(self, stage, field_code):
        return self.env['ir.config_parameter'].sudo().get_param(
            self._guest_requirement_param(stage, field_code),
            'False',
        ) == 'True'

    def _get_required_guest_fields(self, stage):
        field_codes = [
            'nationality',
            'country',
            'passport_id',
            'date_of_birth',
            'gender',
            'email',
            'phone',
            'source_category',
            'sub_source',
            'market_segment',
            'guest_class',
            'guest_classification',
        ]
        field_codes += ['udf_%s' % index for index in range(1, 11)]
        return [
            field_code
            for field_code in field_codes
            if self._guest_requirement_enabled(stage, field_code)
        ]

    def _get_required_guest_field_labels(self):
        labels = {
            'nationality': _("Nationality"),
            'country': _("Country"),
            'passport_id': _("Passport/ID"),
            'date_of_birth': _("Date of Birth"),
            'gender': _("Gender"),
            'email': _("Email"),
            'phone': _("Phone"),
            'source_category': _("Source Category"),
            'sub_source': _("Sub Source"),
            'market_segment': _("Market Segment"),
            'guest_class': _("Guest Class"),
            'guest_classification': _("Guest Classification"),
        }
        for index in range(1, 11):
            label_field = 'udf_label_%s' % index
            labels['udf_%s' % index] = (
                self[label_field]
                if label_field in self._fields and self[label_field]
                else _("Guest Analysis %s") % index
            )
        return labels

    def _required_guest_field_is_missing(self, field_code):
        self.ensure_one()
        partner = self.partner_id
        if field_code.startswith('udf_'):
            udf_index = field_code.split('_', 1)[1]
            value_field = 'udf_value_%s' % udf_index
            if value_field not in self._fields:
                _logger.warning(
                    "Skipping required guest UDF validation because field %s does not exist on hotel.reservation.",
                    value_field,
                )
                return False
            return not self[value_field]

        checks = {
            'nationality': lambda: not (self.guest_nationality_id or partner.nationality_id),
            'country': lambda: not (self.guest_country_id or partner.country_id),
            'passport_id': lambda: not (self.partner_passport or partner.passport_number),
            'date_of_birth': lambda: not partner.hotel_date_of_birth,
            'gender': lambda: not partner.hotel_gender,
            'email': lambda: not self.partner_email,
            'phone': lambda: not self.partner_phone,
            'source_category': lambda: not self.booking_source_category_id,
            'sub_source': lambda: not self.booking_sub_source_id,
            'market_segment': lambda: not self.market_segment_id,
            'guest_class': lambda: not self.guest_classification_id,
            'guest_classification': lambda: not self.guest_classify_id,
        }
        return checks[field_code]()

    def _validate_required_stay_guest_fields(self):
        ICP = self.env['ir.config_parameter'].sudo()
        require_all_profiles = ICP.get_param(
            'hotel_management.guest_profile_required_checkin_all_stay_guest_profiles',
            'False',
        ) == 'True'
        require_all_passports = ICP.get_param(
            'hotel_management.guest_profile_required_checkin_all_stay_guest_passport',
            'False',
        ) == 'True'
        require_all_nationality = ICP.get_param(
            'hotel_management.guest_profile_required_checkin_all_stay_guest_nationality',
            'False',
        ) == 'True'

        if not (require_all_profiles or require_all_passports or require_all_nationality):
            return []

        self._sync_stay_guests_from_reservation_partners()
        expected_count = max((self.adults or 0) + (self.children or 0), 1)
        stay_guests = self.stay_guest_ids.sorted(lambda guest: (0 if guest.is_primary else 1, guest.id))
        errors = []

        if len(stay_guests) < expected_count:
            errors.append(
                _("Stay Guest Profiles (%(completed)s/%(expected)s)")
                % {'completed': len(stay_guests), 'expected': expected_count}
            )

        labels = []
        if require_all_passports:
            labels.append(_("Passport/ID"))
        if require_all_nationality:
            labels.append(_("Nationality"))

        for position, guest in enumerate(stay_guests[:expected_count], start=1):
            missing = []
            if require_all_profiles and not (guest.name or guest.partner_id.name):
                missing.append(_("Name"))
            if require_all_passports and not (guest.passport_no or guest.partner_id.passport_number):
                missing.append(_("Passport/ID"))
            if require_all_nationality and not (guest.nationality_id or guest.partner_id.nationality_id):
                missing.append(_("Nationality"))
            if missing:
                errors.append(
                    _("Stay Guest %(number)s: %(fields)s")
                    % {'number': position, 'fields': ', '.join(missing)}
                )

        if labels and len(stay_guests) < expected_count:
            errors.append(
                _("Missing %(fields)s for all expected stay guests")
                % {'fields': ', '.join(labels)}
            )
        return errors

    def _validate_required_guest_fields(self, stage):
        labels_by_code = self._get_required_guest_field_labels()
        for rec in self:
            required_fields = rec._get_required_guest_fields(stage)
            missing = [
                labels_by_code[field_code]
                for field_code in required_fields
                if rec._required_guest_field_is_missing(field_code)
            ]

            if stage == 'checkin':
                missing += rec._validate_required_stay_guest_fields()

            if missing:
                if stage == 'reservation':
                    raise UserError(
                        _("Please complete required reservation fields: %s.")
                        % ', '.join(missing)
                    )
                raise UserError(
                    _("Please complete required check-in fields: %s.")
                    % ', '.join(missing)
                )

    def action_reinstate(self):
        biz_date = self.env.company.hotel_business_date or fields.Date.context_today(self)
        for rec in self:
            if rec.is_desk_folio:
                raise UserError(_("Desk Folios are standalone non-stay folios and do not support reinstate / stay lifecycle actions."))
            if rec.checkout_date <= biz_date:
                raise UserError(_("Please extend the 'To Date' to a future date before reinstating the guest."))
            if rec.room_id:
                rec.room_id._ensure_operational_axes()
                rec.room_id._reconcile_operational_status()
            if rec.room_id and rec._get_other_inhouse_conflict(rec.room_id):
                raise UserError(_("This room was already given to a new guest! Please assign them a new room number first."))
            
            rec.write({'state': 'checkin'})
            if rec.room_id:
                rec.room_id.with_context(hotel_reservation_room_workflow=True).write({
                    'occupancy_status': 'occupied',
                    'housekeeping_status': 'dirty',
                    'availability_status': 'available',
                })
                
            # Ensure the Folio exists if they are reinstated!
            if not rec.sale_order_id:
                rec.action_create_folio()
    
    def action_checkout(self):
        biz_date = self.env.company.hotel_business_date or fields.Date.context_today(self)
        for rec in self:
            if rec.is_desk_folio:
                raise UserError(_("Desk Folios are standalone non-stay folios and do not support check-out."))
            if rec.state not in ['checkin', 'checkout_hold']: 
                raise UserError(_("Only In-House or Hold guests can check out."))
            
            position = rec._get_operational_folio_position()
            net_balance = position['operational_balance']

            if net_balance > 0.01:
                raise UserError(_("Please settle balance of %s before checking out.") % net_balance)

            if net_balance < -0.01:
                return {
                    'name': _('Deposit Settlement Required'),
                    'type': 'ir.actions.act_window',
                    'res_model': 'hotel.deposit.void.wizard',
                    'view_mode': 'form',
                    'target': 'new',
                    'context': {
                        'default_reservation_id': rec.id,
                        'default_deposit_source_type': 'payment',
                    },
                }
            
            if rec.city_ledger_id and rec.sale_order_id:
                guest_target_lines = rec.sale_order_id.order_line.filtered(
                    lambda line: not line.display_type and line._get_resolved_billing_target() == 'guest'
                )
                if not guest_target_lines:
                    rec.sale_order_id.partner_id = rec.city_ledger_id.id
            
            # Never collapse a same-day early checkout into an invalid zero-night stay.
            if rec.checkout_date > biz_date and rec.checkin_date < biz_date:
                rec.write({'checkout_date': biz_date})
            
            rec.with_context(hotel_allow_checkout_state_write=True).write({'state': 'checkout'})
            if rec.room_id:
                rec.room_id.with_context(hotel_reservation_room_workflow=True).write({
                    'occupancy_status': 'vacant',
                    'housekeeping_status': 'dirty',
                    'availability_status': 'available',
                })
                
            # ... (your existing state change and room dirty logic) ...
            
            # Queue one checkout email; group checkout must not wait for SMTP for every room.
            template = self.env.ref('hotel_management.email_template_hotel_reservation_checkout', raise_if_not_found=False)
            if template and rec.partner_email:
                mail_id = template.send_mail(rec.id, force_send=False)
                rec._create_email_audit(
                    'final_receipt',
                    rec.partner_email,
                    'queued',
                    template._render_field('subject', [rec.id])[rec.id],
                    mail=self.env['mail.mail'].sudo().browse(mail_id).exists(),
                )
                rec.message_post(
                    body=_("Final Receipt email queued to guest: %s") % rec.partner_email,
                    subtype_xmlid='mail.mt_note',
                )
            elif not rec.partner_email:
                rec._create_email_audit(
                    'final_receipt',
                    rec.partner_email or rec.partner_id.email or '-',
                    'skipped',
                    _("Final Receipt - %s") % (rec.name or ''),
                    failure_reason=_("Guest has no email address saved."),
                )
                rec.message_post(body=_("Email skipped: guest has no email address saved."), subtype_xmlid='mail.mt_note')
            
            if rec.city_ledger_id:
                message_body = Markup(
                    "<b>Check-Out Completed:</b> %s checked out. Company-routed charges remain on <b>%s</b>."
                ) % (Markup.escape(rec.partner_id.name or ""), Markup.escape(rec.city_ledger_id.name or ""))
            else:
                message_body = Markup(
                    "<b>Check-Out Completed:</b> %s checked out with the guest balance settled."
                ) % Markup.escape(rec.partner_id.name or "")

            rec.message_post(
                body=message_body,
                subject="Check-Out Confirmation",
                subtype_xmlid='mail.mt_note',
            )

    def action_noshow(self, source='manual', reason=False, cutoff_info=False):
        for rec in self:
            if rec.is_desk_folio:
                raise UserError(_("Desk Folios cannot be marked as No-Show."))
            room = rec.room_id
            rec.write({
                'state': 'noshow',
                'no_show_datetime': fields.Datetime.now(),
                'no_show_source': source,
            })
            if source == 'auto':
                message = _(
                    "<b>Auto No-Show by cron</b><br/>"
                    "Business Date: %(business_date)s<br/>"
                    "Physical Date: %(physical_date)s<br/>"
                    "Cutoff Time: %(cutoff)s<br/>"
                    "Grace Hours: %(grace)s"
                ) % {
                    'business_date': fields.Date.to_string(rec.company_id.hotel_business_date or fields.Date.context_today(rec)),
                    'physical_date': fields.Date.to_string(fields.Date.context_today(rec)),
                    'cutoff': cutoff_info.get('cutoff') if cutoff_info else rec.company_id.hotel_auto_noshow_cutoff_time,
                    'grace': cutoff_info.get('grace') if cutoff_info else rec.company_id.hotel_auto_noshow_grace_hours,
                }
            else:
                message = _("<b>No-Show marked manually.</b>")
            if reason:
                message += _("<br/>Reason: %s") % Markup.escape(reason)
            rec.message_post(body=Markup(message), subtype_xmlid='mail.mt_note')
            if room:
                room._reconcile_operational_status()

    def action_cancel(self): 
        self.write({'state': 'cancel'})

    def action_release_block(self):
        for rec in self:
            if rec.state == 'blocked':
                room = rec.room_id
                rec.unlink()
                if room:
                    room._reconcile_operational_status()

        return {
            'type': 'ir.actions.act_window',
            'name': _('Room Blocks'),
            'res_model': 'hotel.reservation',
            'view_mode': 'list,form',
            'domain': [('state', '=', 'blocked')],
            'target': 'current',
        }
    
    def action_open_move_room_wizard(self):
        self.ensure_one()
        return {
            'name': _('Move Room'),
            'type': 'ir.actions.act_window',
            'res_model': 'hotel.room.move.wizard',
            'view_mode': 'form',
            'target': 'new',
            'context': {
                'default_reservation_id': self.id,
                'default_new_room_type_id': self.room_type_id.id,
            }
        }

    def _validate_room_move_target(self, new_room):
        self.ensure_one()
        self._check_reservation_movement_access()
        if self.state not in ['checkin', 'checkout_hold']:
            raise UserError(_("Only In-House or Checkout Hold reservations can be moved from the Room Chart."))
        if not self.room_id:
            raise UserError(_("This reservation does not have a current room assignment."))
        if not new_room:
            raise UserError(_("Please select a valid destination room."))

        old_room = self.room_id

        if new_room == old_room:
            raise UserError(_("Please select a different room to move this guest."))

        if new_room.occupancy_status == 'occupied' or self._get_other_inhouse_conflict(new_room):
            raise UserError(_("The selected new room is currently occupied!"))

        if new_room.availability_status != 'available' or not new_room.release_ready:
            raise UserError(_(
                "The selected new room must be fully release-ready before moving a checked-in guest."
            ))

        return old_room, new_room

    def _perform_room_move(self, new_room, reason):
        self.ensure_one()
        old_room, new_room = self._validate_room_move_target(new_room)

        self.with_context(skip_exchange_journal_write=True).write({
            'room_type_id': new_room.room_type_id.id,
            'room_id': new_room.id,
        })

        old_room.with_context(hotel_reservation_room_workflow=True).write({
            'occupancy_status': 'vacant',
            'housekeeping_status': 'dirty',
            'availability_status': 'available',
            'do_not_disturb': False,
            'turndown_required': False,
            'turndown_completed': False,
            'minibar_check_required': False,
            'minibar_checked': False,
            'linen_change_required': False,
            'linen_changed': False,
        })
        new_room.with_context(hotel_reservation_room_workflow=True).write({
            'occupancy_status': 'occupied',
            'availability_status': 'available',
            'minibar_check_required': True,
            'minibar_checked': False,
            'turndown_completed': False,
            'linen_changed': False,
        })

        self.message_post(body=_(
            "Guest moved from <b>%s</b> to <b>%s</b>.<br/>"
            "<b>Reason:</b> %s"
        ) % (old_room.name, new_room.name, reason))
        self._log_exchange_event(
            _("Room Move"),
            old_room.display_name,
            new_room.display_name,
            change_type='action',
            reason=reason,
            source_document=new_room,
        )

        (old_room | new_room)._reconcile_operational_status()
        (old_room | new_room)._sync_housekeeping_task_records()
        return True

    def get_room_chart_move_preview(self, target_room_id):
        self.ensure_one()
        target_room = self.env['hotel.room'].browse(target_room_id).exists()
        old_room, new_room = self._validate_room_move_target(target_room)
        return {
            'reservation_name': self.name,
            'guest_name': self.partner_id.name or self.name,
            'old_room_name': old_room.name,
            'new_room_name': new_room.name,
            'checkin_date': fields.Date.to_string(self.checkin_date) if self.checkin_date else '',
            'checkout_date': fields.Date.to_string(self.checkout_date) if self.checkout_date else '',
            'new_room_type_name': new_room.room_type_id.name or '',
            'state': self.state,
        }

    def action_room_chart_move_to(self, target_room_id):
        self.ensure_one()
        target_room = self.env['hotel.room'].browse(target_room_id).exists()
        self._perform_room_move(target_room, _("Room Chart drag-and-drop"))
        return True

    def _prepare_room_chart_drag_preview(self, target_room, target_checkin_date):
        self.ensure_one()
        self._check_reservation_movement_access()
        biz_date = self.env.company.hotel_business_date or fields.Date.context_today(self)

        if self.state in ['checkin', 'checkout_hold']:
            old_room, new_room = self._validate_room_move_target(target_room)
            return {
                'mode': 'room_only',
                'guest_name': self.partner_id.name or self.name,
                'old_room_name': old_room.name,
                'new_room_name': new_room.name,
                'old_checkin_date': fields.Date.to_string(self.checkin_date) if self.checkin_date else '',
                'old_checkout_date': fields.Date.to_string(self.checkout_date) if self.checkout_date else '',
                'new_checkin_date': fields.Date.to_string(self.checkin_date) if self.checkin_date else '',
                'new_checkout_date': fields.Date.to_string(self.checkout_date) if self.checkout_date else '',
                'room_changed': old_room != new_room,
                'dates_changed': False,
                'duration_nights': max((self.checkout_date - self.checkin_date).days, 1) if self.checkin_date and self.checkout_date else 1,
                'summary_note': _("Stay dates remain unchanged for in-house guests."),
                'target_room_type_name': new_room.room_type_id.name or '',
            }

        if self.state not in ['draft', 'confirm']:
            raise UserError(_("Only Draft, Confirmed, In-House, or Checkout Hold reservations can be dragged on the Room Chart."))

        if not target_room:
            raise UserError(_("Please select a valid destination room."))

        if not target_checkin_date:
            raise UserError(_("Please drop the reservation on a valid arrival date."))

        target_checkin = fields.Date.to_date(target_checkin_date)
        if not target_checkin:
            raise UserError(_("Please drop the reservation on a valid arrival date."))

        if target_checkin < biz_date:
            raise UserError(_("Reservations cannot be moved before the current business date."))

        current_checkin = self.checkin_date or biz_date
        current_checkout = self.checkout_date or (current_checkin + timedelta(days=1))
        duration_nights = max((current_checkout - current_checkin).days, 1)
        target_checkout = target_checkin + timedelta(days=duration_nights)

        if (
            target_room == self.room_id
            and target_checkin == current_checkin
            and target_checkout == current_checkout
        ):
            raise UserError(_("Drop the booking on a different room or date to make a change."))

        overlap = self.search([
            ('id', '!=', self.id),
            ('room_id', '=', target_room.id),
            ('state', 'not in', ['cancel', 'noshow', 'checkout']),
            ('checkin_date', '<', target_checkout),
            ('checkout_date', '>', target_checkin),
        ], limit=1)
        if overlap:
            raise UserError(_(
                "The selected room is not available from %s to %s."
            ) % (target_checkin, target_checkout))

        return {
            'mode': 'reservation_move',
            'guest_name': self.partner_id.name or self.name,
            'old_room_name': self.room_id.name if self.room_id else _("Unassigned"),
            'new_room_name': target_room.name,
            'old_checkin_date': fields.Date.to_string(current_checkin),
            'old_checkout_date': fields.Date.to_string(current_checkout),
            'new_checkin_date': fields.Date.to_string(target_checkin),
            'new_checkout_date': fields.Date.to_string(target_checkout),
            'room_changed': target_room != self.room_id,
            'dates_changed': target_checkin != current_checkin or target_checkout != current_checkout,
            'duration_nights': duration_nights,
            'summary_note': _("Length of stay will be preserved while the booking is repositioned."),
            'target_room_type_name': target_room.room_type_id.name or '',
        }

    def get_room_chart_drag_preview(self, target_room_id, target_checkin_date):
        self.ensure_one()
        target_room = self.env['hotel.room'].browse(target_room_id).exists()
        return self._prepare_room_chart_drag_preview(target_room, target_checkin_date)

    def action_room_chart_drag_drop(self, target_room_id, target_checkin_date):
        self.ensure_one()
        target_room = self.env['hotel.room'].browse(target_room_id).exists()
        preview = self._prepare_room_chart_drag_preview(target_room, target_checkin_date)

        if preview['mode'] == 'room_only':
            self._perform_room_move(target_room, _("Room Chart drag-and-drop"))
            return True

        old_room = self.room_id
        new_checkin = fields.Date.to_date(preview['new_checkin_date'])
        new_checkout = fields.Date.to_date(preview['new_checkout_date'])
        self.write({
            'room_type_id': target_room.room_type_id.id,
            'room_id': target_room.id,
            'checkin_date': new_checkin,
            'checkout_date': new_checkout,
        })

        touched_rooms = (old_room | target_room).exists() if old_room else target_room
        if touched_rooms:
            touched_rooms._reconcile_operational_status()
            touched_rooms._sync_housekeeping_task_records()

        self.message_post(body=_(
            "<b>ROOM CHART UPDATE</b><br/>"
            "Room: <b>%s</b> to <b>%s</b><br/>"
            "Dates: <b>%s</b> to <b>%s</b>"
        ) % (
            preview['old_room_name'],
            preview['new_room_name'],
            "%s to %s" % (preview['old_checkin_date'], preview['old_checkout_date']),
            "%s to %s" % (preview['new_checkin_date'], preview['new_checkout_date']),
        ))
        return True
    
    def _get_share_url(self, redirect=False, signup_partner=False, pid=None):
        db_name = self.env.cr.dbname
        return f"/hotel/reservation/{self.id}?db={db_name}&access_token={self.access_token}"

    def _get_hotel_base_url(self):
        base_url = self.env['ir.config_parameter'].sudo().get_param('web.base.url') or ''
        base_url = base_url.strip().rstrip('/')
        if base_url and not base_url.startswith(('http://', 'https://')):
            base_url = 'http://%s' % base_url
        return base_url or (self.get_base_url() or '').rstrip('/')

    def _get_share_absolute_url(self):
        self.ensure_one()
        return f"{self._get_hotel_base_url()}{self._get_share_url()}"

    def _get_pre_arrival_url(self):
        self.ensure_one()
        db_name = self.env.cr.dbname
        return f"/pre-arrival/{self.id}?db={db_name}&access_token={self.access_token}"

    def _get_pre_arrival_absolute_url(self):
        self.ensure_one()
        return f"{self._get_hotel_base_url()}{self._get_pre_arrival_url()}"

    def action_preview_guest_portal(self):
        self.ensure_one()
        return {
            'type': 'ir.actions.act_url',
            'target': 'new',
            'url': self._get_share_absolute_url(),
        }

    def action_print_reservation_confirmation(self):
        self.ensure_one()
        return self.env.ref('hotel_management.action_report_reservation_confirmation').report_action(self)

    def _action_print_registration_card_report(self):
        self.ensure_one()
        self._create_email_audit(
            'registration_card',
            self.partner_email or self.partner_id.email or '-',
            'sent',
            _("Registration Card - %s") % (self.name or ''),
        )
        return self.env.ref('hotel_management.action_report_registration_card').report_action(self)

    def _snapshot_registration_staff_signature(self):
        self.ensure_one()
        if self.registration_staff_signature:
            return False
        if not self.env.user.hotel_staff_signature:
            raise UserError(_("Please add your Staff E-Signature on your user profile before signing the Registration Card."))

        self.write({
            'registration_staff_signature': self.env.user.hotel_staff_signature,
            'registration_signed_by_id': self.env.user.id,
            'registration_signed_by_name': self.env.user.name,
            'registration_signed_at': fields.Datetime.now(),
        })
        return True

    def action_print_registration_card(self):
        self.ensure_one()
        if self.registration_staff_signature:
            return self._action_print_registration_card_report()
        view = self.env.ref('hotel_management.view_registration_card_sign_print_wizard_form')
        return {
            'name': _('Print Registration Card'),
            'type': 'ir.actions.act_window',
            'res_model': 'hotel.registration.card.sign.print.wizard',
            'view_mode': 'form',
            'view_id': view.id,
            'target': 'new',
            'context': {
                'default_reservation_id': self.id,
            },
        }

    def action_sign_registration_card(self):
        self.ensure_one()
        if self.registration_staff_signature:
            raise UserError(_("This Registration Card is already signed. Reprinting will keep the existing staff signature."))

        self._snapshot_registration_staff_signature()
        return {
            'type': 'ir.actions.client',
            'tag': 'display_notification',
            'params': {
                'title': _('Registration Card Signed'),
                'message': _('The Registration Card staff signature snapshot has been saved.'),
                'type': 'success',
                'sticky': False,
            },
        }

    def _action_print_tax_invoice_report(self):
        self.ensure_one()
        return self.env.ref('hotel_management.action_report_hotel_tax_invoice').report_action(self)

    def _snapshot_tax_invoice_staff_signature(self):
        self.ensure_one()
        if self.tax_invoice_staff_signature:
            return False
        if not self.env.user.hotel_staff_signature:
            raise UserError(_("Please add your Staff E-Signature on your user profile before signing the Tax Invoice."))

        self.write({
            'tax_invoice_staff_signature': self.env.user.hotel_staff_signature,
            'tax_invoice_signed_by_id': self.env.user.id,
            'tax_invoice_signed_by_name': self.env.user.name,
            'tax_invoice_signed_at': fields.Datetime.now(),
        })
        return True

    def action_print_tax_invoice(self):
        self.ensure_one()
        if self.tax_invoice_staff_signature:
            return self._action_print_tax_invoice_report()
        view = self.env.ref('hotel_management.view_tax_invoice_sign_print_wizard_form')
        return {
            'name': _('Print Tax Invoice'),
            'type': 'ir.actions.act_window',
            'res_model': 'hotel.tax.invoice.sign.print.wizard',
            'view_mode': 'form',
            'view_id': view.id,
            'target': 'new',
            'context': {
                'default_reservation_id': self.id,
            },
        }

    def _action_print_commercial_invoice_report(self):
        self.ensure_one()
        return self.env.ref('hotel_management.action_report_hotel_commercial_invoice').report_action(self)

    def _snapshot_commercial_invoice_staff_signature(self):
        self.ensure_one()
        if self.commercial_invoice_staff_signature:
            return False
        if not self.env.user.hotel_staff_signature:
            raise UserError(_("Please add your Staff E-Signature on your user profile before signing the Commercial Invoice."))

        self.write({
            'commercial_invoice_staff_signature': self.env.user.hotel_staff_signature,
            'commercial_invoice_signed_by_id': self.env.user.id,
            'commercial_invoice_signed_by_name': self.env.user.name,
            'commercial_invoice_signed_at': fields.Datetime.now(),
        })
        return True

    def action_print_commercial_invoice(self):
        self.ensure_one()
        if self.commercial_invoice_staff_signature:
            return self._action_print_commercial_invoice_report()
        view = self.env.ref('hotel_management.view_commercial_invoice_sign_print_wizard_form')
        return {
            'name': _('Print Commercial Invoice'),
            'type': 'ir.actions.act_window',
            'res_model': 'hotel.commercial.invoice.sign.print.wizard',
            'view_mode': 'form',
            'view_id': view.id,
            'target': 'new',
            'context': {
                'default_reservation_id': self.id,
            },
        }

    def action_open_print_documents_wizard(self):
        self.ensure_one()
        view = self.env.ref('hotel_management.view_reservation_document_print_wizard_form')
        return {
            'name': _('Print Documents'),
            'type': 'ir.actions.act_window',
            'res_model': 'hotel.reservation.document.print.wizard',
            'view_mode': 'form',
            'view_id': view.id,
            'target': 'new',
            'context': {
                'default_reservation_id': self.id,
            },
        }

    def action_create_deposit(self):
        self.ensure_one()
        if self.is_desk_folio or self.folio_type in ['desk', 'group_master']:
            raise UserError(_("Advance deposits are only available for future room reservations."))
        if self._get_remaining_deposit_capacity() <= 0.01:
            raise UserError(_("This reservation is already fully prepaid."))
        if not self._get_advance_deposit_liability_account():
            raise UserError(_("Please configure the Advance Deposit Liability Account in Hotel Settings before registering deposits."))
            
        return {
            'name': _('Register Advance Deposit'),
            'type': 'ir.actions.act_window',
            'res_model': 'hotel.deposit.wizard',
            'view_mode': 'form',
            'target': 'new',
            'context': {'default_reservation_id': self.id}
        }

    def action_open_void_deposit_wizard(self):
        self.ensure_one()
        self._check_deposit_void_access()
        if not (
            self._get_voidable_deposit_invoices()
            or self._get_voidable_advance_deposit_payments()
            or self._get_operational_advance_deposit_credit_amount() > 0.01
            or self.guest_credit_balance > 0.01
        ):
            raise UserError(_("There is no credit balance to settle on this reservation."))
        return {
            'name': _('Deposit Settlement'),
            'type': 'ir.actions.act_window',
            'res_model': 'hotel.deposit.void.wizard',
            'view_mode': 'form',
            'target': 'new',
            'context': {'default_reservation_id': self.id},
        }

    def action_open_folio_invoicing(self):
        self.ensure_one()
        if not self.sale_order_id:
            self.action_create_folio()
        self._ensure_folio_order_ready(self.sale_order_id)
        action = self.env['ir.actions.actions']._for_xml_id('sale.action_orders')
        action.update({
            'res_id': self.sale_order_id.id,
            'view_mode': 'form',
            'views': [(self.env.ref('hotel_management.view_hotel_folio_order_form').id, 'form')],
            'view_id': self.env.ref('hotel_management.view_hotel_folio_order_form').id,
            'target': 'current',
        })
        return action

    def action_view_guest_history(self):
        self.ensure_one()
        partner = self.partner_id
        reservation_ids = self._get_completed_stay_reservations_for_partner(partner).ids
        if self._partner_participates_in_reservation(self, partner):
            reservation_ids.append(self.id)
        return {
            'type': 'ir.actions.act_window',
            'name': 'Guest History',
            'res_model': 'hotel.reservation',
            'view_mode': 'list,form',
            'domain': [('id', 'in', reservation_ids or [0])],
            'target': 'current',
        }

    def _get_guest_folio_orders(self):
        self.ensure_one()
        orders = self.sale_order_id | self.env['sale.order'].search([
            ('hotel_reservation_ids', 'in', self.id),
        ])
        return orders.exists()

    def action_view_folio(self):
        self.ensure_one()
        orders = self._get_guest_folio_orders()
        if not orders:
            return False
        ready_orders = self.env['sale.order']
        for order in orders:
            ready_orders |= self._ensure_folio_order_ready(order)
        action = self.env['ir.actions.actions']._for_xml_id('sale.action_orders')
        if len(ready_orders) == 1:
            action.update({
                'name': 'Folio',
                'res_id': ready_orders.id,
                'view_mode': 'form',
                'views': [(self.env.ref('hotel_management.view_hotel_folio_order_form').id, 'form')],
                'view_id': self.env.ref('hotel_management.view_hotel_folio_order_form').id,
                'target': 'current',
            })
            return action

        action.update({
            'name': _('Folios'),
            'view_mode': 'list,form',
            'views': [
                (self.env.ref('hotel_management.view_hotel_folio_order_tree').id, 'list'),
                (self.env.ref('hotel_management.view_hotel_folio_order_form').id, 'form'),
            ],
            'domain': [('id', 'in', ready_orders.ids)],
            'target': 'current',
        })
        return action

    def action_create_invoice_from_reservation(self):
        self.ensure_one()
        user = self.env.user
        if not (
            user.has_group('hotel_management.group_hotel_front_office')
            or user.has_group('hotel_management.group_hotel_front_office_manager')
            or user.has_group('hotel_management.group_hotel_manager')
            or user.has_group('account.group_account_manager')
            or user.has_group('base.group_system')
        ):
            raise AccessError(_("You are not allowed to create invoices from reservations."))

        if not self.sale_order_id:
            self.action_create_folio()
        order = self._ensure_folio_order_ready(self.sale_order_id)
        order.order_line.filtered(lambda line: not line.display_type and not line.billing_target)._hotel_assign_missing_billing_targets()
        billable_lines = order.order_line.filtered(lambda line: not line.display_type)
        if not billable_lines:
            raise UserError(_("There are no billable folio lines yet. Please post charges before creating an invoice."))
        existing_invoices = self._get_folio_customer_invoices()
        mixed_target_draft_invoices = existing_invoices.filtered(
            lambda inv: inv.state == 'draft'
            and len(
                set(
                    inv.invoice_line_ids.mapped('sale_line_ids').filtered(lambda line: not line.display_type).mapped(
                        lambda line: line._get_resolved_billing_target()
                    )
                )
            ) > 1
        )
        if mixed_target_draft_invoices:
            raise UserError(
                _("A draft invoice on this folio still mixes Guest and Company charges. Please cancel that draft invoice, then click Create Invoice again to rebuild the split correctly.")
            )

        invoiceable_lines = order._get_hotel_new_invoiceable_lines()
        invoiceable_charge_lines = invoiceable_lines.filtered(lambda line: not line.display_type)

        if invoiceable_charge_lines:
            guest_lines = invoiceable_charge_lines.filtered(
                lambda line: line._get_resolved_billing_target() == 'guest'
            )
            company_lines = invoiceable_charge_lines.filtered(
                lambda line: line._get_resolved_billing_target() == 'company'
            )
            if guest_lines and not self.partner_id:
                raise UserError(
                    _("Please select Guest / Account Name before invoicing guest-routed folio lines.")
                )
            if company_lines and not self.city_ledger_id:
                raise UserError(
                    _("Please select City Ledger / Bill To company before invoicing company-routed folio lines.")
                )

            invoices = order.sudo()._create_hotel_routed_invoices()
            if not (
                user.has_group('hotel_management.group_hotel_manager')
                or user.has_group('account.group_account_manager')
                or user.has_group('base.group_system')
            ):
                return self._action_open_safe_hotel_customer_invoices(invoices, name=_("Customer Invoice"))
            return order.action_view_invoice(invoices=invoices)

        raise UserError(_("All folio transactions are already invoiced."))

    def _action_open_safe_hotel_customer_invoices(self, invoices, name=None):
        return invoices._action_open_hotel_safe_invoice_view(name=name)

    def action_view_change_logs(self):
        self.ensure_one()
        return {
            'name': _('Exchange Journal'),
            'type': 'ir.actions.act_window',
            'res_model': 'hotel.change.log',
            'view_mode': 'list,form',
            'domain': [('reservation_id', '=', self.id)],
            'context': {'default_reservation_id': self.id},
        }
    
    def action_view_receipts(self):
        self.ensure_one()
        payments = self._get_registered_payment_records()

        return {
            'name': _('Payments & Credits'),
            'type': 'ir.actions.act_window',
            'res_model': 'account.payment',
            'view_mode': 'list,form',
            'domain': [('id', 'in', payments.ids)],
            'target': 'current',
            'views': [
                (self.env.ref('hotel_management.view_hotel_receipt_tree').id, 'list'),
                (False, 'form'),
            ],
        }

    def action_view_invoices(self):
        self.ensure_one()
        user = self.env.user
        can_open_full_invoice = (
            user.has_group('hotel_management.group_hotel_manager')
            or user.has_group('account.group_account_manager')
            or user.has_group('base.group_system')
        )
        if not (can_open_full_invoice or user.has_group('hotel_management.group_hotel_front_office')):
            raise AccessError(_("Only Hotel Front Office, Hotel Managers, or Accounting Managers can open hotel invoice records."))
        invoices = self._get_reservation_customer_invoices()
        if not can_open_full_invoice:
            return self._action_open_safe_hotel_customer_invoices(invoices)
        return {
            'name': _('Invoices'),
            'type': 'ir.actions.act_window',
            'res_model': 'account.move',
            'view_mode': 'list,form',
            'domain': [('id', 'in', invoices.ids)],
            'context': {'default_move_type': 'out_invoice'},
            'target': 'current',
            'views': [
                (self.env.ref('hotel_management.view_hotel_invoice_tree').id, 'list'),
                (self.env.ref('account.view_move_form').id, 'form'),
            ],
        }
        
    def _ensure_posting_journal_entry(
        self,
        journal_type,
        description,
        amount,
        business_date,
        *,
        entry_datetime=None,
        source_order=None,
        source_move=None,
        source_payment=None,
        source_sale_line=None,
        folio_billing_target='guest',
    ):
        self.ensure_one()
        journal = self.env['hotel.posting.journal']
        source_order = source_order or (source_sale_line.order_id if source_sale_line else self.sale_order_id)
        values = {
            'reservation_id': self.id,
            'journal_type': journal_type,
            'description': description,
            'amount': amount,
            'business_date': business_date,
            'date': entry_datetime or fields.Datetime.now(),
            'source_order_id': source_order.id if source_order else False,
            'source_move_id': source_move.id if source_move else False,
            'source_payment_id': source_payment.id if source_payment else False,
            'source_sale_line_id': source_sale_line.id if source_sale_line else False,
            'folio_billing_target': folio_billing_target or 'guest',
        }
        exact_domain = [
            ('reservation_id', '=', self.id),
            ('journal_type', '=', journal_type),
            ('description', '=', description),
            ('business_date', '=', business_date),
            ('folio_billing_target', '=', folio_billing_target or 'guest'),
        ]
        if source_move:
            exact_domain.append(('source_move_id', '=', source_move.id))
        elif source_payment:
            exact_domain.append(('source_payment_id', '=', source_payment.id))
        elif source_sale_line:
            exact_domain.append(('source_sale_line_id', '=', source_sale_line.id))
        elif source_order:
            exact_domain.append(('source_order_id', '=', source_order.id))
        else:
            exact_domain.append(('amount', '=', amount))
        existing_entry = journal.search(exact_domain, limit=1)
        if not existing_entry:
            fallback_domain = [
                ('reservation_id', '=', self.id),
                ('journal_type', '=', journal_type),
                ('description', '=', description),
                ('business_date', '=', business_date),
            ]
            if not (source_move or source_payment or source_sale_line or source_order):
                fallback_domain.append(('amount', '=', amount))
            existing_entry = journal.search(fallback_domain, limit=1)
        if existing_entry:
            existing_entry.write(values)
            return existing_entry
        return journal.create(values)

    def _sync_guest_financial_activity_journal(self):
        for rec in self:
            for invoice in rec._get_folio_customer_invoices():
                billing_label = dict(invoice._fields['hotel_billing_target'].selection).get(
                    invoice.hotel_billing_target or 'guest',
                    invoice.hotel_billing_target or _('Guest'),
                )
                state_label = dict(invoice._fields['state'].selection).get(invoice.state, invoice.state)
                invoice_name = invoice.name if invoice.name and invoice.name != '/' else _('Draft Invoice')
                rec._ensure_posting_journal_entry(
                    'system',
                    _("%s %s Invoice: %s") % (state_label, billing_label, invoice_name),
                    0.0,
                    invoice.hotel_business_date or invoice.invoice_date or rec.company_id.hotel_business_date,
                    entry_datetime=invoice.write_date if invoice.state == 'posted' else invoice.create_date,
                    source_order=invoice.hotel_folio_id or rec.sale_order_id,
                    source_move=invoice,
                    folio_billing_target=invoice.hotel_billing_target or 'guest',
                )

            for application_line in rec._get_active_advance_deposit_application_lines():
                invoice = application_line.move_id
                invoice_name = invoice.name if invoice.name and invoice.name != '/' else _('Draft Invoice')
                rec._ensure_posting_journal_entry(
                    'payment',
                    _("Advance Deposit Applied to %s") % invoice_name,
                    -abs(application_line.price_total),
                    invoice.hotel_business_date or invoice.invoice_date or rec.company_id.hotel_business_date,
                    entry_datetime=application_line.create_date or invoice.create_date,
                    source_order=invoice.hotel_folio_id or rec.sale_order_id,
                    source_move=invoice,
                    folio_billing_target='guest',
                )

            payments = rec._get_advance_deposit_payments(posted_only=True).sudo()
            posted_invoices = rec._get_folio_customer_invoices().filtered(
                lambda inv: inv.state == 'posted' and rec._is_invoice_linked_to_reservation_folio(inv)
            )
            for invoice in posted_invoices:
                payments |= invoice.sudo()._get_reconciled_payments().sudo()

            for payment in payments.sudo().filtered(lambda pay: pay.state in ('in_process', 'paid')):
                linked_invoices = payment.reconciled_invoice_ids.sudo().filtered(
                    lambda move: move.hotel_folio_id.id == rec.sale_order_id.id
                    and rec._is_invoice_linked_to_reservation_folio(move)
                )
                if not (
                    payment.hotel_reservation_id.id == rec.id
                    or payment.folio_id.id == rec.sale_order_id.id
                    or linked_invoices
                ):
                    continue
                journal_name = payment.journal_id.name or payment.name
                payment_type = payment.payment_type
                payment_amount = payment.amount
                payment_business_date = payment.hotel_business_date or payment.date or rec.company_id.hotel_business_date
                payment_create_date = payment.create_date
                is_advance_deposit = payment.is_advance_deposit
                billing_target = 'guest'
                if linked_invoices:
                    billing_target = linked_invoices[:1].hotel_billing_target or 'guest'
                if is_advance_deposit:
                    description = (
                        _("Advance Deposit Refunded (%s)") % journal_name
                        if payment_type == 'outbound'
                        else _("Advance Deposit Received (%s)") % journal_name
                    )
                else:
                    description = _("Payment Received (%s)") % journal_name
                amount = -payment_amount if payment_type == 'inbound' else payment_amount
                rec._ensure_posting_journal_entry(
                    'payment',
                    description,
                    amount,
                    payment_business_date,
                    entry_datetime=payment_create_date,
                    source_order=rec.sale_order_id,
                    source_payment=payment,
                    source_move=linked_invoices[:1] if linked_invoices else False,
                    folio_billing_target='guest' if is_advance_deposit else billing_target,
                )
        return True

    def action_view_guest_financial_activity(self):
        self.ensure_one()
        self._sync_guest_financial_activity_journal()
        action = self.env['ir.actions.actions']._for_xml_id('hotel_management.action_hotel_posting_journal')
        action.update({
            'name': _('Operational Guest Folio'),
            'domain': [
                ('reservation_id', '=', self.id),
                ('folio_billing_target', '!=', 'company'),
                ('entry_side', '!=', 'info'),
            ],
            'target': 'current',
            'context': {
                'default_reservation_id': self.id,
            },
            'views': [
                (self.env.ref('hotel_management.view_hotel_guest_folio_tree').id, 'list'),
                (False, 'form'),
            ],
        })
        return action

    def action_view_guest_folio(self):
        return self.action_view_guest_financial_activity()

    def action_view_posting_journal(self):
        self.ensure_one()
        self._sync_guest_financial_activity_journal()
        return {
            'name': _('Posting Journal'),
            'type': 'ir.actions.act_window',
            'res_model': 'hotel.posting.journal',
            'view_mode': 'list,form',
            'domain': [('reservation_id', '=', self.id)],
            'context': {'default_reservation_id': self.id},
        }

    def action_re_checkin(self):
        self.ensure_one()
        new_booking = self.copy({
            'name': _('New'),
            'state': 'draft',
            'checkin_date': fields.Date.today(),
            'checkout_date': fields.Date.today() + timedelta(days=1),
            'sale_order_id': False,
            'room_id': self.room_id.id,
        })
        return {
            'type': 'ir.actions.act_window', 'name': _('Verify New Booking'),
            'res_model': 'hotel.reservation', 'res_id': new_booking.id,
            'view_mode': 'form', 'target': 'current',
        }

    @api.model
    def cron_auto_noshow(self):
        company = self.env.company
        if not company.hotel_auto_noshow_enabled:
            _logger.info("Auto No-Show skipped because setting disabled.")
            return 0

        candidates = self._get_auto_noshow_candidates()
        cutoff_info = {
            'cutoff': self._format_float_time(company.hotel_auto_noshow_cutoff_time),
            'grace': company.hotel_auto_noshow_grace_hours,
        }
        for booking in candidates:
            booking.action_noshow(source='auto', cutoff_info=cutoff_info)
        _logger.info("Auto No-Show processed %s reservation(s).", len(candidates))
        return len(candidates)

    @api.model
    def _format_float_time(self, value):
        value = value or 0.0
        hours = int(value)
        minutes = int(round((value - hours) * 60))
        if minutes >= 60:
            hours += 1
            minutes -= 60
        return "%02d:%02d" % (hours % 24, minutes)

    @api.model
    def _get_auto_noshow_states(self, company=None):
        company = company or self.env.company
        apply_to = company.hotel_auto_noshow_apply_to or 'non_guaranteed'
        if apply_to == 'guaranteed':
            return ['guaranteed']
        if apply_to == 'all':
            return ['confirm', 'guaranteed']
        return ['confirm']

    def _has_auto_noshow_excluded_deposit(self):
        self.ensure_one()
        amounts = (
            self.guest_deposit_paid_total,
            self.deposit_balance,
            self.advance_deposit_credit,
        )
        return any(abs(amount or 0.0) > 0.01 for amount in amounts)

    def _is_auto_noshow_due(self, local_now=None):
        self.ensure_one()
        company = self.company_id or self.env.company
        if not self.checkin_date:
            return False
        business_date = company.hotel_business_date or fields.Date.context_today(self)
        if self.checkin_date > business_date:
            return False
        local_now = local_now or fields.Datetime.context_timestamp(self, fields.Datetime.now()).replace(tzinfo=None)
        cutoff_float = company.hotel_auto_noshow_cutoff_time or 0.0
        cutoff_hour = int(cutoff_float)
        cutoff_minute = int(round((cutoff_float - cutoff_hour) * 60))
        if cutoff_minute >= 60:
            cutoff_hour += 1
            cutoff_minute -= 60
        cutoff_hour %= 24
        cutoff_dt = datetime.combine(self.checkin_date, time(cutoff_hour, cutoff_minute))
        cutoff_dt += timedelta(hours=company.hotel_auto_noshow_grace_hours or 0.0)
        return local_now >= cutoff_dt

    @api.model
    def _get_auto_noshow_candidates(self):
        company = self.env.company
        local_now = fields.Datetime.context_timestamp(self, fields.Datetime.now()).replace(tzinfo=None)
        business_date = company.hotel_business_date or fields.Date.context_today(self)
        candidates = self.search([
            ('company_id', '=', company.id),
            ('state', 'in', self._get_auto_noshow_states(company)),
            ('checkin_date', '<=', business_date),
            ('is_desk_folio', '=', False),
        ])
        if company.hotel_auto_noshow_exclude_deposit:
            candidates = candidates.filtered(lambda res: not res._has_auto_noshow_excluded_deposit())
        return candidates.filtered(lambda res: res._is_auto_noshow_due(local_now=local_now))

    @api.model
    def action_process_noshow_review(self):
        candidates = self._get_auto_noshow_candidates()
        return {
            'name': _('Process No-Show Review'),
            'type': 'ir.actions.act_window',
            'res_model': 'hotel.reservation',
            'view_mode': 'list,form',
            'domain': [('id', 'in', candidates.ids or [0])],
            'context': {'create': False},
        }

    @api.model
    def cron_auto_checkout_hold(self, business_date=None, enforce_time_gate=True):
        return self._move_due_out_guests_to_checkout_hold(
            business_date=business_date,
            enforce_time_gate=enforce_time_gate,
        )

    # Legacy duplicate preserved for audit reference only; inactive after Phase 3B consolidation.
    def _legacy_check_overlap(self):
        for rec in self:
            # Skip if no room or invalid state
            if not rec.room_id:
                continue

            if rec.state in ['cancel', 'noshow', 'checkout']:
                continue

            # Validate date logic first
            if rec.checkin_date and rec.checkout_date:
                if rec.checkin_date >= rec.checkout_date:
                    raise ValidationError("Check-out must be after Check-in.")

            # Optimized domain
            domain = [
                ('room_id', '=', rec.room_id.id),
                ('state', 'not in', ['cancel', 'noshow', 'checkout']),
                ('checkin_date', '<', rec.checkout_date),
                ('checkout_date', '>', rec.checkin_date),
            ]

            # Safe protection only if the record already exists.
            if rec.id:
                domain.append(('id', '!=', rec.id))

            # IMPORTANT: limit=1 for performance
            conflict = self.search(domain, limit=1)

            if conflict:
                if conflict.state == 'blocked':
                    raise ValidationError(
                        f"Room is BLOCKED (Maintenance) from "
                        f"{conflict.checkin_date} to {conflict.checkout_date}"
                    )

                raise ValidationError(
                    f"Room {rec.room_id.name} is already booked\n"
                    f"From: {conflict.checkin_date}\n"
                    f"To: {conflict.checkout_date}"
                )

    # Legacy duplicate preserved for audit reference only; inactive after Phase 3B consolidation.
    def _legacy_check_rate_provided(self):
        for rec in self:
            # Skip rate validation for cancellations, no-shows, and room blocks
            if rec.state in ['cancel', 'noshow', 'blocked'] or rec.block_reason:
                continue

            if not rec.is_manual_rate and not rec.rate_id and not rec.rate_plan_id:
                raise ValidationError(
                    _("Revenue Protection: You must select a 'Master Rate Plan', an old 'Rate Plan', or check 'Override Room Rate' before saving!")
                )
                
    @api.model
    def get_availability_matrix(self, start_date_str, days=14):
        biz_date = self.env.company.hotel_business_date or fields.Date.today()
        try: 
            start_date = fields.Date.from_string(start_date_str) if start_date_str else biz_date
        except: 
            start_date = biz_date
            
        today = biz_date
        
        dates = []
        for i in range(days):
            current_date = start_date + timedelta(days=i)
            dates.append({
                'full': str(current_date), 'day': current_date.day, 'month': current_date.strftime('%b'),
                'weekday': current_date.strftime('%a'), 'is_weekend': current_date.weekday() >= 5, 
                'is_today': current_date == today, 'date_obj': current_date 
            })

        room_types = self.env['hotel.room.type'].search([
            ('name', '!=', 'Desk Folio'),
        ], order='sequence, name')
        rate_plans = self.env['hotel.rate.plan'].search([('active', '=', True)])
        type_data = []
        
        for rtype in room_types:
            total_capacity = self.env['hotel.room'].search_count([('room_type_id', '=', rtype.id)])
            
            rate_list = []
            for plan in rate_plans:
                rules = self.env['hotel.rate.plan.line'].search([
                    ('plan_id', '=', plan.id),
                    ('room_type_id', '=', rtype.id)
                ], order='date_start desc')
                
                daily_prices = []
                for d in dates:
                    valid_rule = next((r for r in rules if not r.date_start or r.date_start <= d['date_obj']), None)
                    daily_prices.append(valid_rule.price if valid_rule else 0.0)
                rate_list.append({'id': plan.id, 'name': plan.name, 'prices': daily_prices})
            
            if len(rate_list) == 0:
                rate_list.append({'id': 999, 'name': 'No Rate Setup', 'prices': [0.0] * days})
                
            type_data.append({'id': rtype.id, 'name': rtype.name, 'capacity': total_capacity, 'rates': rate_list, 'counts': []})
            
        totals_row, occ_row_include, occ_row_ignore, booked_row, capacity_row = [], [], [], [], []
        for d in dates:
            date_str = d['full']
            daily_total_avail, daily_total_capacity, daily_blocked, daily_booked = 0, 0, 0, 0
            
            for t_idx, t_data in enumerate(type_data):
                domain_date = [('checkin_date', '<=', date_str), ('checkout_date', '>', date_str)]
                domain_type = ['|', ('room_type_id', '=', t_data['id']), '&', ('room_type_id', '=', False), ('room_id.room_type_id', '=', t_data['id'])]
                
                booked_count = self.env['hotel.reservation'].search_count([('state', 'in', ['draft', 'confirm', 'checkin', 'checkout_hold']), ('is_desk_folio', '=', False)] + domain_date + domain_type)
                legacy_blocked_count = self.env['hotel.reservation'].search_count([('state', '=', 'blocked')] + domain_date + domain_type)
                room_blocked_count = self.env['hotel.room.block'].sudo().search_count([
                    ('state', '=', 'active'),
                    ('date_from', '<=', date_str),
                    ('date_to', '>', date_str),
                    ('room_type_id', '=', t_data['id']),
                ])
                blocked_count = legacy_blocked_count + room_blocked_count
                
                # --- THE FIX: ONLY COUNT GROUPS THAT ARE IN 'DRAFT' ---
                group_blocks = self.env['hotel.group.room.line'].search([
                    ('room_type_id', '=', t_data['id']),
                    ('group_id.state', '=', 'draft'), # We removed 'confirm' from here!
                    ('group_id.arrival_date', '<=', date_str),
                    ('group_id.departure_date', '>', date_str)
                ])
                allotment_count = sum(group_blocks.mapped('qty_blocked'))
                
                available = t_data['capacity'] - (booked_count + blocked_count + allotment_count)
                
                type_data[t_idx]['counts'].append({
                    'value': max(0, available), 
                    'color_class': 'text-success' if available > 2 else ('text-warning' if available > 0 else 'text-danger'), 
                    'is_zero': available <= 0
                })
                
                daily_total_avail += max(0, available)
                daily_total_capacity += t_data['capacity']
                daily_blocked += blocked_count
                daily_booked += (booked_count + allotment_count)
                
            totals_row.append(daily_total_avail)
            booked_row.append(daily_booked)        
            capacity_row.append(daily_total_capacity) 
            
            occ_inc = round((daily_booked / daily_total_capacity) * 100, 1) if daily_total_capacity > 0 else 0.0
            occ_row_include.append(f"{occ_inc}%")
            effective_cap = daily_total_capacity - daily_blocked
            occ_ign = round((daily_booked / effective_cap) * 100, 1) if effective_cap > 0 else (100.0 if daily_booked > 0 else 0.0)
            occ_row_ignore.append(f"{occ_ign}%")
            
        for d in dates:
            del d['date_obj']
            
        return {
            'dates': dates, 'room_types': type_data, 'totals': totals_row, 
            'booked_totals': booked_row, 'capacity_totals': capacity_row,  
            'occ_include': occ_row_include, 'occ_ignore': occ_row_ignore
        }

    # Legacy duplicate preserved for audit reference only; inactive after Phase 3B consolidation.
    def _legacy_check_requirements_at_checkin(self):
        for rec in self:
            # If the reservation is moving to "checkin" and it is NOT a desk folio...
            if rec.state == 'checkin' and not rec.is_desk_folio:
                
                # 1. Check for the Passport
                require_id_rule = self.env.company.hotel_require_id_checkin
                if require_id_rule:
                    if not rec.partner_id.passport_number: # (Keep your original field name here)
                        raise ValidationError("Stop! You cannot check in '%s' without entering their Passport / National ID." % rec.partner_id.name)
                
                # 2. Check if a Room is physically assigned
                if not rec.room_id:
                    raise ValidationError(f"Stop! You must assign a specific Room Number before checking in '{rec.partner_id.name}'.")
                
                rec.room_id._ensure_operational_axes()
                block_conflict = rec._get_other_active_block(rec.room_id)
                occupied_conflict = rec._get_other_inhouse_conflict(rec.room_id)

                if block_conflict or rec.room_id.availability_status != 'available':
                    raise ValidationError(f"Stop! Room {rec.room_id.name} is currently Out of Order. Please release it before check-in.")

                if occupied_conflict:
                    raise ValidationError(f"Stop! Room {rec.room_id.name} is already occupied. Please assign a different room.")

                if rec.room_id.housekeeping_status == 'dirty':
                    raise ValidationError(
                        f"Stop! Room {rec.room_id.name} is currently {rec.room_id.state}. "
                        "You cannot check a guest into a dirty room. Please assign a different room or rush Housekeeping."
                    )

                if not rec.room_id.release_ready:
                    raise ValidationError(
                        f"Stop! Room {rec.room_id.name} is cleaned but not release-ready yet. "
                        "Supervisor inspection must be completed before check-in."
                    )

    @api.constrains('is_desk_folio', 'state', 'room_id')
    def _check_desk_folio_lifecycle(self):
        invalid_states = {'checkin', 'checkout_hold', 'checkout', 'noshow', 'blocked'}
        for rec in self.filtered('is_desk_folio'):
            if rec.room_id:
                raise ValidationError(_("Desk Folios cannot carry a room assignment."))
            if rec.state in invalid_states:
                raise ValidationError(
                    _("Desk Folios are standalone non-stay folios and cannot use reservation lifecycle state '%s'.") % rec.state
                )

    @api.model
    def _get_or_create_desk_folio_room_type(self):
        desk_type = self.env['hotel.room.type'].search([('name', '=', 'Desk Folio')], limit=1)
        if not desk_type:
            desk_type = self.env['hotel.room.type'].create({'name': 'Desk Folio'})
        return desk_type

    @api.model
    def _get_hotel_business_datetime(self):
        biz_date = self.env.company.hotel_business_date or fields.Date.context_today(self)
        return datetime.combine(fields.Date.to_date(biz_date), datetime.min.time())

    @api.model
    def default_get(self, fields_list):
        res = super().default_get(fields_list)

        if self.env.context.get('default_is_desk_folio'):
            desk_type = self._get_or_create_desk_folio_room_type()
            res['room_type_id'] = desk_type.id

            today = fields.Date.context_today(self)
            res['checkin_date'] = today
            res['checkout_date'] = today + timedelta(days=365)
            res['adults'] = 0
            res['is_manual_rate'] = True
            res['manual_rate'] = 0.0
            res['state'] = 'draft'
            res['room_id'] = False

        return res

    @api.model_create_multi
    def create(self, vals_list):
        self._check_reservation_write_access('create')
        for vals in vals_list:
            if vals.get('is_desk_folio'):
                if not vals.get('room_type_id'):
                    vals['room_type_id'] = self._get_or_create_desk_folio_room_type().id

                vals['is_manual_rate'] = True
                vals['manual_rate'] = 0.0
                vals['room_id'] = False
                if vals.get('state') in ['checkin', 'checkout_hold', 'checkout', 'noshow', 'blocked'] or not vals.get('state'):
                    vals['state'] = 'draft'

            if vals.get('name', _('New')) == _('New'):
                if vals.get('state') == 'blocked':
                    vals['name'] = self.env['ir.sequence'].next_by_code('hotel.reservation.block') or 'BLK'
                else:
                    vals['name'] = self.env['ir.sequence'].next_by_code('hotel.reservation') or _('New')

            if vals.get('state') == 'blocked':
                biz_date = self.env.company.hotel_business_date or fields.Date.today()
                vals['checkin_date'] = biz_date

                if not vals.get('partner_id'):
                    vals['partner_id'] = self.env.user.partner_id.id

            if vals.get('state') == 'blocked' and vals.get('checkin_date') and vals.get('checkout_date'):
                c_in = fields.Date.from_string(vals['checkin_date'])
                c_out = fields.Date.from_string(vals['checkout_date'])
                if c_in == c_out:
                    vals['checkout_date'] = c_out + timedelta(days=1)

        records = super().create(vals_list)

        blocked_rooms = records.filtered(lambda r: r.state == 'blocked' and r.room_id).mapped('room_id')
        if blocked_rooms:
            blocked_rooms.write({'availability_status': 'out_of_order'})

        records._generate_daily_transactions()
        records._sync_stay_guests_from_reservation_partners()
        records._apply_repeat_guest_classification()
        for rec in records:
            reservation_mode = _("Desk Folio") if rec.is_desk_folio else _("Reservation")
            rec._log_exchange_event(
                _("Reservation Created"),
                '',
                _("%s created in status %s") % (reservation_mode, rec._format_value('state', rec.state)),
                change_type='action',
                source_document=rec,
            )
        return records

    def write(self, vals):
        if vals:
            self._check_reservation_write_access('write')
        # SECURITY: prevent any code from bypassing checkout balance protection
        if vals.get('state') == 'checkout' and not self.env.context.get('hotel_allow_checkout_state_write'):
            for rec in self:
                if rec.state != 'checkout':
                    rec.action_checkout()
            return True  
          
        if self.filtered('is_desk_folio'):
            if vals.get('room_id'):
                raise ValidationError(_("Desk Folios cannot carry a room assignment."))
            if vals.get('state') in ['checkin', 'checkout_hold', 'checkout', 'noshow', 'blocked']:
                raise ValidationError(
                    _("Desk Folios are standalone non-stay folios and cannot use reservation lifecycle state '%s'.") % vals['state']
                )
        if vals.get('state') == 'checkin' and not self.env.context.get('skip_future_checkin_validation'):
            self.filtered(lambda reservation: reservation.state != 'checkin')._validate_checkin_business_date()
        if vals.get('state') == 'checkin' and not self.env.context.get('skip_required_checkin_validation'):
            self.filtered(lambda reservation: reservation.state != 'checkin')._validate_required_guest_fields('checkin')

        checkin_date_snapshots = {
            rec.id: rec.checkin_date
            for rec in self
        } if 'checkin_date' in vals else {}

        if self.env.context.get('skip_exchange_journal_write'):
            res = super(HotelReservation, self).write(vals)
            self._post_arrival_date_change_messages(checkin_date_snapshots)
            trigger_fields = [
                'checkin_date',
                'checkout_date',
                'rate_id',
                'rate_plan_id',
                'room_type_id',
                'room_id',
                'adults',
                'state',
                'is_manual_rate',
                'manual_rate',
                'is_desk_folio',
            ]
            if any(f in vals for f in trigger_fields):
                self._generate_daily_transactions()
            return res

        tracked_fields = [
            'partner_id',
            'partner_passport',
            'partner_phone',
            'partner_email',
            'checkin_date',
            'checkout_date',
            'room_type_id',
            'room_id',
            'state',
            'rate_id',
            'rate_plan_id',
            'is_manual_rate',
            'manual_rate',
            'billing_routing',
            'city_ledger_id',
            'source_id',
            'market_segment_id',
            'guest_classify_id',
            'adults',
            'children',
        ]
        snapshots = {
            rec.id: {
                field: rec._format_value(field, rec[field])
                for field in tracked_fields
                if field in vals
            }
            for rec in self
        }

        # Execute normal write
        res = super(HotelReservation, self).write(vals)
        self._post_arrival_date_change_messages(checkin_date_snapshots)

        for rec in self:
            for field in tracked_fields:
                if field in vals:
                    old_val = snapshots.get(rec.id, {}).get(field, "Empty")
                    new_val = rec._format_new_value(field, vals[field])
                    if old_val != new_val:
                        reason = _("Reservation lifecycle updated") if field == 'state' else False
                        rec._log_exchange_event(
                            self._fields[field].string,
                            old_val,
                            new_val,
                            reason=reason,
                            source_document=rec,
                        )

        # --- AUTO-SYNC BILLING ROUTING TO EXISTING FOLIO LINES ---
        if 'city_ledger_id' in vals or 'billing_routing' in vals:
            for rec in self:
                if rec.sale_order_id:
                    # Find all charges that have not been invoiced yet
                    uninvoiced_lines = rec.sale_order_id.order_line.filtered(
                        lambda l: not l.display_type and l.qty_to_invoice > 0 and not getattr(l, 'is_downpayment', False)
                    )
                    for line in uninvoiced_lines:
                        # Recalculate target based on the new City Ledger/Routing settings
                        new_target = rec._compute_default_billing_target(line)
                        line.with_context(skip_hotel_billing_audit=True).write({'billing_target': new_target})
       
        # --- DAILY TRANSACTION TRIGGER ---
        trigger_fields = [
            'checkin_date',
            'checkout_date',
            'rate_id',
            'rate_plan_id',
            'room_type_id',
            'room_id',
            'adults',
            'state',
            'is_manual_rate',
            'manual_rate',
            'is_desk_folio',
        ]
        if any(f in vals for f in trigger_fields):
            self._generate_daily_transactions()

        if any(f in vals for f in ['partner_id', 'accompanying_guest_ids', 'state', 'guest_classification_id']):
            self._sync_stay_guests_from_reservation_partners()
            if not self.env.context.get('skip_repeat_guest_classification'):
                self._apply_repeat_guest_classification()

        return res

    def _post_arrival_date_change_messages(self, old_dates):
        if not old_dates:
            return
        user_name = self.env.user.display_name
        for rec in self:
            old_date = old_dates.get(rec.id)
            new_date = rec.checkin_date
            if old_date and new_date and old_date != new_date:
                rec.message_post(
                    body=_(
                        "Reservation arrival date changed from %(old_date)s to %(new_date)s by %(user)s."
                    ) % {
                        'old_date': fields.Date.to_string(old_date),
                        'new_date': fields.Date.to_string(new_date),
                        'user': user_name,
                    },
                    subtype_xmlid='mail.mt_note',
                )

    def unlink(self):
        self._check_reservation_write_access('unlink')
        touched_rooms = self.mapped('room_id')
        res = super().unlink()
        if touched_rooms:
            touched_rooms._reconcile_operational_status()
        return res

    def _format_value(self, field_name, value):
        if not value: return "Empty"
        if isinstance(value, models.Model): return value.display_name if hasattr(value, 'display_name') else str(value)
        return str(value)

    def _format_new_value(self, field_name, value):
        if not value: return "Empty"
        if self._fields[field_name].type == 'many2one':
            related_rec = self.env[self._fields[field_name].comodel_name].browse(value)
            return related_rec.display_name if related_rec.exists() else "Empty"
        return str(value)

    def _get_stay_business_dates(self):
        self.ensure_one()
        if not self.checkin_date or not self.checkout_date or self.checkout_date <= self.checkin_date:
            return []
        return [self.checkin_date + timedelta(days=i) for i in range((self.checkout_date - self.checkin_date).days)]

    def _get_daily_transaction_line(self, stay_date, create_if_missing=False):
        self.ensure_one()
        stay_date = fields.Date.to_date(stay_date)
        line = self.daily_transaction_ids.filtered(lambda daily: daily.date == stay_date).sorted(
            lambda daily: (0 if daily.is_posted else 1, daily.id)
        )[:1]
        if line or not create_if_missing:
            return line
        if stay_date not in {fields.Date.to_date(day) for day in self._get_stay_business_dates()}:
            return self.env['hotel.daily.transaction']
        return self.env['hotel.daily.transaction'].with_context(skip_hotel_daily_rate_audit=True).create(
            self._prepare_daily_transaction_vals(stay_date)
        )

    def _get_daily_rate_description(self, stay_date):
        self.ensure_one()
        room_name = self.room_id.name if self.room_id else _('Unassigned')
        date_str = stay_date.strftime('%Y-%m-%d') if hasattr(stay_date, 'strftime') else str(stay_date)
        return _("Room Charge %s - %s (%s)") % (date_str, room_name, self.name)

    def _get_default_daily_room_charge_amount(self, stay_date):
        self.ensure_one()
        stay_date = fields.Date.to_date(stay_date)
        if not stay_date:
            return 0.0

        daily_rate = 0.0
        extra_fee = 0.0

        if self.is_manual_rate:
            daily_rate = self.manual_rate
        elif self.rate_plan_id:
            rule = self.env['hotel.rate.plan.line'].search([
                ('plan_id', '=', self.rate_plan_id.id),
                ('room_type_id', '=', self.room_type_id.id),
                '|', ('date_start', '=', False), ('date_start', '<=', stay_date)
            ], order='date_start desc', limit=1)
            if rule:
                daily_rate = rule.price
                if rule.included_guests > 0 and self.adults > rule.included_guests:
                    extra_guests = self.adults - rule.included_guests
                    extra_fee = extra_guests * rule.extra_person_fee
        else:
            daily_rate = self.rate_id.unit_price if self.rate_id else 0.0

        return daily_rate + extra_fee

    def _prepare_daily_transaction_vals(self, stay_date):
        self.ensure_one()
        stay_date = fields.Date.to_date(stay_date)
        return {
            'date': stay_date,
            'reservation_id': self.id,
            'description': self._get_daily_rate_description(stay_date),
            'revenue': self._get_default_daily_room_charge_amount(stay_date),
            'room_nights': 1,
        }

    def _get_daily_room_charge_amount(self, stay_date):
        self.ensure_one()
        stay_date = fields.Date.to_date(stay_date)
        if not stay_date:
            return 0.0

        daily_line = self._get_daily_transaction_line(stay_date)
        if daily_line:
            return daily_line.revenue
        return self._get_default_daily_room_charge_amount(stay_date)

    def _get_night_audit_room_charge_amount(self, business_date):
        self.ensure_one()
        business_date = fields.Date.to_date(business_date)
        if not business_date:
            return 0.0
        return self._get_daily_room_charge_amount(business_date)

    def _get_night_audit_charge_line_name(self, business_date):
        self.ensure_one()
        return self._get_daily_rate_description(business_date)

    def _get_accommodation_estimate_product(self):
        self.ensure_one()
        setup = self.env['hotel.config.setup'].sudo()
        product = (
            setup._get_config_record(self.company_id, 'hotel_accommodation_product_id', 'product.product')
            or setup._get_config_record(self.company_id, 'hotel_room_charge_product_id', 'product.product')
        )
        if product:
            return product
        return self.env['product.product'].search([
            ('name', 'in', ['Accommodation / Room Charge', 'Accommodation', 'Room Charge'])
        ], limit=1)

    def _get_confirmation_tax_compute(self, base_amount, product=False):
        self.ensure_one()
        product = product or self._get_accommodation_estimate_product()
        taxes = product.taxes_id.filtered(
            lambda tax: not tax.company_id or tax.company_id == self.company_id
        ) if product else self.env['account.tax']
        if not taxes:
            return {
                'total_excluded': base_amount,
                'total_included': base_amount,
                'taxes': [],
            }

        return taxes.compute_all(
            base_amount,
            currency=self.currency_id,
            quantity=1.0,
            product=product,
            partner=self.partner_id or self.city_ledger_id or self.sale_order_id.partner_id,
        )

    def _get_hotel_document_account_name(self):
        self.ensure_one()
        if self.folio_type == 'group_master' and self.city_ledger_id:
            return self.city_ledger_id.name
        if self.partner_id:
            return self.partner_id.name
        if self.sale_order_id and self.sale_order_id.partner_id:
            return self.sale_order_id.partner_id.name
        if self.city_ledger_id:
            return self.city_ledger_id.name
        return ""

    def _get_reservation_confirmation_data(self):
        self.ensure_one()

        company = self.company_id
        currency = self.currency_id or company.currency_id
        business_date = company.hotel_business_date or fields.Date.context_today(self)
        generated_on_display = fields.Datetime.context_timestamp(
            self, fields.Datetime.now()
        ).strftime('%Y-%m-%d %H:%M:%S')
        stay_start = fields.Date.to_date(self.checkin_date) if self.checkin_date else False
        stay_end = fields.Date.to_date(self.checkout_date) if self.checkout_date else False
        if stay_start and stay_end and stay_end <= stay_start:
            stay_end = stay_start + timedelta(days=1)
        elif stay_start and not stay_end:
            stay_end = stay_start + timedelta(days=1)

        accommodation_product = self._get_accommodation_estimate_product()
        nightly_lines = []
        tax_summary = {}
        untaxed_total = 0.0
        tax_total = 0.0
        total_stay_amount = 0.0

        stay_date = stay_start
        while stay_date and stay_end and stay_date < stay_end:
            room_charge = self._get_daily_room_charge_amount(stay_date)
            taxes_res = self._get_confirmation_tax_compute(room_charge, product=accommodation_product)
            line_tax_amount = taxes_res['total_included'] - taxes_res['total_excluded']
            line_total = taxes_res['total_included']
            line_untaxed = taxes_res['total_excluded']

            nightly_lines.append({
                'business_date': stay_date,
                'room_charge': line_untaxed,
                'tax_amount': line_tax_amount,
                'line_total': line_total,
                'tax_lines': taxes_res['taxes'],
            })

            untaxed_total += line_untaxed
            tax_total += line_tax_amount
            total_stay_amount += line_total

            for tax_line in taxes_res['taxes']:
                tax_name = tax_line.get('name') or _('Taxes / Service')
                tax_summary[tax_name] = tax_summary.get(tax_name, 0.0) + tax_line.get('amount', 0.0)

            stay_date += timedelta(days=1)

        required_percent = max(company.hotel_confirmation_deposit_percent or 0.0, 0.0) if company.hotel_deposit_required else 0.0
        required_deposit_amount = currency.round(total_stay_amount * (required_percent / 100.0)) if currency else total_stay_amount * (required_percent / 100.0)
        paid_amount = min(self._get_posted_advance_deposit_amount(), total_stay_amount)
        remaining_balance = max(total_stay_amount - paid_amount, 0.0)

        return {
            'generated_on_display': generated_on_display,
            'business_date': business_date,
            'guest_name': self.partner_id.name or '',
            'passport': self.partner_passport or self.partner_id.passport_number or '',
            'phone': self.partner_phone or self.partner_id.phone or '',
            'email': self.partner_email or self.partner_id.email or '',
            'account_name': self._get_hotel_document_account_name(),
            'bill_to_name': self.city_ledger_id.name if self.city_ledger_id else '',
            'room_type_name': self.room_type_id.name or '',
            'room_name': self.room_id.name or '',
            'checkin_date_display': self.checkin_date.strftime('%m/%d/%Y') if self.checkin_date else '',
            'checkout_date_display': self.checkout_date.strftime('%m/%d/%Y') if self.checkout_date else '',
            'status_display': dict(self._fields['state'].selection).get(self.state, self.state or ''),
            'nightly_lines': nightly_lines,
            'tax_summary': sorted(tax_summary.items(), key=lambda item: item[0]),
            'untaxed_total': untaxed_total,
            'tax_total': tax_total,
            'total_stay_amount': total_stay_amount,
            'required_deposit_amount': required_deposit_amount,
            'required_deposit_percent': required_percent,
            'deposit_required': bool(company.hotel_deposit_required),
            'remaining_deposit_required': max(required_deposit_amount - paid_amount, 0.0),
            'deposit_received': paid_amount,
            'remaining_balance': remaining_balance,
            'cancellation_policy': company.hotel_cancellation_policy or '',
            'payment_instructions': company.hotel_payment_instructions or '',
        }

    def _get_registration_card_data(self):
        self.ensure_one()
        confirmation = self._get_reservation_confirmation_data()

        total_amount = confirmation['total_stay_amount']
        deposit_received = min(self.guest_deposit_paid_total or 0.0, total_amount)

        signature_attachment = self.env['ir.attachment'].sudo().search([
            ('res_model', '=', 'hotel.reservation'),
            ('res_id', '=', self.id),
            ('res_field', '=', 'guest_signature'),
        ], order='create_date desc, id desc', limit=1)
        signature_datetime_display = ''
        if signature_attachment.create_date:
            signature_datetime_display = fields.Datetime.context_timestamp(
                self, signature_attachment.create_date
            ).strftime('%Y-%m-%d %H:%M:%S')

        stay_guests = self.stay_guest_ids.filtered(
            lambda guest: not guest.is_primary
        ).sorted(lambda guest: guest.id)
        accompanying_guests = [{
            'name': guest.name or guest.partner_id.name or '',
            'passport': guest.passport_no or guest.partner_id.passport_number or '',
            'nationality': guest.nationality_id.name or guest.partner_id.nationality_id.name or '',
        } for guest in stay_guests]
        if not accompanying_guests:
            accompanying_guests = [{
                'name': partner.name or '',
                'passport': partner.passport_number or '',
                'nationality': partner.nationality_id.name or '',
            } for partner in self.accompanying_guest_ids]

        rate_name = ''
        if self.is_manual_rate:
            rate_name = _('Manual Rate')
        elif self.rate_plan_id:
            rate_name = self.rate_plan_id.display_name
        elif self.rate_id:
            rate_name = self.rate_id.display_name

        return {
            'generated_on_display': confirmation['generated_on_display'],
            'nightly_lines': confirmation['nightly_lines'],
            'tax_summary': confirmation['tax_summary'],
            'untaxed_amount': confirmation['untaxed_total'],
            'tax_amount': confirmation['tax_total'],
            'total_amount': total_amount,
            'required_deposit_amount': confirmation['required_deposit_amount'],
            'required_deposit_percent': confirmation['required_deposit_percent'],
            'deposit_received': deposit_received,
            'estimated_balance': max(total_amount - deposit_received, 0.0),
            'rate_name': rate_name,
            'accompanying_guests': accompanying_guests,
            'signature_datetime_display': signature_datetime_display,
            'hotel_terms': _(
                "The guest agrees to comply with hotel policies, settle all approved charges, "
                "and accept responsibility for room keys, damages, and registered occupants."
            ),
        }

    def _render_registration_card_html(self):
        self.ensure_one()
        Template = self.env['hotel.document.template'].sudo()
        template = Template._get_registration_card_template(self.company_id)
        if not template:
            template = Template.new({
                'name': _('Built-in Registration Card'),
                'document_type': 'registration_card',
                'company_id': self.company_id.id,
                'html_body': Template._default_registration_card_html(),
                'show_logo': True,
                'show_company_name': True,
                'logo_position': 'left',
                'logo_width': 180,
                'custom_css': Template._default_registration_card_css(),
            })
        return template._render_for_reservation(self)

    def _get_hotel_document_total_amount(self):
        self.ensure_one()
        estimated_total = self._get_reservation_confirmation_data()['total_stay_amount']
        operational_total = self.sale_order_id.amount_total if self.sale_order_id else 0.0
        if self.folio_type in ['desk', 'group_master'] and operational_total:
            return operational_total
        return max(estimated_total, operational_total)

    @api.model
    def _get_or_create_accommodation_product(self):
        setup = self.env['hotel.config.setup'].sudo()
        configured_product = (
            setup._get_config_record(self.env.company, 'hotel_accommodation_product_id', 'product.product')
            or setup._get_config_record(self.env.company, 'hotel_room_charge_product_id', 'product.product')
        )
        if configured_product:
            return configured_product
        product = self.env['product.product'].search([
            ('name', 'in', ['Accommodation / Room Charge', 'Accommodation'])
        ], limit=1)
        if not product:
            product = self.env['product.product'].create({
                'name': 'Accommodation / Room Charge',
                'type': 'service',
            })
        return product

    def _get_night_audit_target_order(self):
        self.ensure_one()
        if self.is_desk_folio:
            return self.env['sale.order']

        if not self.sale_order_id:
            self.action_create_folio()

        target_order = self.sale_order_id
        if self.group_id and self.billing_routing in ['master_room', 'master_all']:
            paymaster = self.search([
                ('is_desk_folio', '=', True),
                ('group_id', '=', self.group_id.id)
            ], limit=1)
            if paymaster:
                if not paymaster.sale_order_id:
                    paymaster.action_create_folio()
                target_order = paymaster.sale_order_id

        if target_order:
            target_order = self._ensure_folio_order_ready(target_order)

        return target_order

    def _find_existing_night_audit_charge_line(self, business_date, product, target_order):
        self.ensure_one()
        return self.env['sale.order.line'].search([
            ('order_id', '=', target_order.id),
            ('hotel_business_date', '=', business_date),
            ('hotel_reservation_id', '=', self.id),
            ('is_night_audit_charge', '=', True),
        ], limit=1)

    def _post_night_audit_room_charge(self, business_date, post_message=False):
        self.ensure_one()
        business_date = fields.Date.to_date(business_date)
        room_name = self.room_id.name if self.room_id else 'Unassigned'

        if business_date < self.checkin_date:
            return {
                'status': 'skipped',
                'reservation': self,
                'room_name': room_name,
                'message': f"Audit date {business_date} is before check-in date {self.checkin_date}.",
            }

        if business_date >= self.checkout_date:
            return {
                'status': 'skipped',
                'reservation': self,
                'room_name': room_name,
                'message': f"Audit date {business_date} is on/after checkout date {self.checkout_date}.",
            }

        if self.is_desk_folio:
            return {
                'status': 'bypassed',
                'reservation': self,
                'room_name': room_name,
                'message': "Desk Folios do not receive room charges.",
            }

        target_order = self._get_night_audit_target_order()
        if not target_order:
            return {
                'status': 'skipped',
                'reservation': self,
                'room_name': room_name,
                'message': "No target folio is available for room-charge posting.",
            }

        product = self._get_or_create_accommodation_product()
        existing = self._find_existing_night_audit_charge_line(business_date, product, target_order)
        daily_line = self._get_daily_transaction_line(business_date, create_if_missing=True)
        if existing:
            if daily_line and daily_line.posted_sale_line_id != existing:
                daily_line.with_context(skip_hotel_daily_rate_audit=True).write({
                    'description': existing.name or daily_line.description,
                    'revenue': existing.price_unit * existing.product_uom_qty,
                    'posted_sale_line_id': existing.id,
                })
            return {
                'status': 'already_posted',
                'reservation': self,
                'room_name': room_name,
                'message': f"Room charge already exists on folio {target_order.name or target_order.id}.",
                'amount': existing.price_unit * existing.product_uom_qty,
                'target_order': target_order,
            }

        amount = self._get_night_audit_room_charge_amount(business_date)
        if amount <= 0:
            if post_message:
                self.message_post(body="Night Audit skipped: No room rate found for this business date.")
            return {
                'status': 'skipped',
                'reservation': self,
                'room_name': room_name,
                'message': "No room rate was found for this business date.",
            }

        new_line = self.env['sale.order.line'].with_context(skip_procurement=True).create({
            'order_id': target_order.id,
            'product_id': product.id,
            'name': daily_line.description if daily_line else self._get_night_audit_charge_line_name(business_date),
            'product_uom_qty': 1,
            'price_unit': amount,
            'hotel_business_date': business_date,
            'hotel_reservation_id': self.id,
            'is_night_audit_charge': True,
        })
        new_line.write({'price_unit': amount})
        if daily_line:
            daily_line.with_context(skip_hotel_daily_rate_audit=True).write({
                'description': new_line.name,
                'revenue': amount,
                'posted_sale_line_id': new_line.id,
            })

        if post_message:
            self.message_post(body=f"Night Audit posted room charge: {amount:.2f} for {business_date}")

        return {
            'status': 'posted',
            'reservation': self,
            'room_name': room_name,
            'message': f"Charged {(self.currency_id.symbol or '$')}{amount}",
            'amount': amount,
            'target_order': target_order,
            'sale_line': new_line,
        }

    @api.model
    def _run_night_audit_room_charge_batch(self, business_date=None, reservation_domain=None, post_messages=False, raise_on_error=True):
        business_date = fields.Date.to_date(business_date or self.env.company.hotel_business_date or fields.Date.context_today(self))
        reservation_domain = reservation_domain or [
            ('state', 'in', ['checkin', 'checkout_hold']),
            ('checkin_date', '<=', business_date),
        ]
        reservations = self.search(reservation_domain)
        results = []

        for reservation in reservations:
            try:
                results.append(reservation._post_night_audit_room_charge(business_date, post_message=post_messages))
            except Exception as exc:
                if raise_on_error:
                    raise
                _logger.exception("Night Audit room-charge posting failed for reservation %s", reservation.name)
                results.append({
                    'status': 'error',
                    'reservation': reservation,
                    'room_name': reservation.room_id.name if reservation.room_id else 'Unassigned',
                    'message': str(exc),
                })

        return results

    @api.model
    def _move_due_out_guests_to_checkout_hold(self, business_date=None, enforce_time_gate=False):
        business_date = fields.Date.to_date(business_date or self.env.company.hotel_business_date or fields.Date.context_today(self))
        hold_time_limit = self.env.company.hotel_checkout_hold_time or 12.0

        if enforce_time_gate:
            import pytz
            from datetime import datetime

            tz_name = self.env.company.partner_id.tz or self.env.user.tz or 'UTC'
            hotel_tz = pytz.timezone(tz_name)
            now_local = datetime.now(hotel_tz)
            current_time_float = now_local.hour + (now_local.minute / 60.0)
            if current_time_float < hold_time_limit:
                return self.browse()

        overdue_guests = self.search([
            ('state', '=', 'checkin'),
            ('checkout_date', '<=', business_date),
            ('is_desk_folio', '=', False),
        ])

        for reservation in overdue_guests:
            reservation.write({'state': 'checkout_hold'})
            reservation.message_post(
                body=f"Automation: Guest missed the {hold_time_limit} check-out time. Status securely locked to Checkout Hold."
            )

        return overdue_guests

    @api.model
    def cron_daily_room_charge(self):
        biz_date = self.env.company.hotel_business_date or fields.Date.context_today(self)
        self._run_night_audit_room_charge_batch(
            business_date=biz_date,
            reservation_domain=[
                ('state', 'in', ['checkin', 'checkout_hold']),
                ('checkin_date', '<=', biz_date),
            ],
            post_messages=True,
            raise_on_error=False,
        )

    @api.model
    def _cron_send_pre_arrival_emails(self):
        return self.cron_send_pre_arrival_links()

    # NEW: Pre-Arrival Fields
    passport_image = fields.Image("Passport/ID Photo", max_width=1920, max_height=1920)
    pre_arrival_sent = fields.Boolean("Pre-Arrival Sent", default=False, copy=False)
    access_token = fields.Char('Security Token', copy=False)

    def _generate_access_token(self):
        for res in self:
            if not res.access_token:
                res.access_token = str(uuid.uuid4())

    def _is_inside_pre_arrival_automation_window(self):
        self.ensure_one()
        if not self.checkin_date:
            return False
        days = max(self.company_id.pre_arrival_days or self.env.company.pre_arrival_days or 0, 0)
        today = fields.Date.to_date(
            self.company_id.hotel_business_date
            or self.env.company.hotel_business_date
            or fields.Date.context_today(self)
        )
        target_date = today + timedelta(days=days)
        checkin_date = fields.Date.to_date(self.checkin_date)
        return bool(checkin_date and today <= checkin_date <= target_date)

    def _has_existing_pre_arrival_communication(self):
        self.ensure_one()
        audit = self.env['hotel.email.audit'].sudo().search_count([
            ('reservation_id', '=', self.id),
            ('audit_type', '=', 'pre_arrival'),
            ('status', 'in', ['queued', 'sent', 'failed']),
        ])
        if audit:
            return True
        queued_mail = self.env['mail.mail'].sudo().search_count([
            ('model', '=', 'hotel.reservation'),
            ('res_id', '=', self.id),
            ('state', 'in', ['outgoing', 'sent', 'exception']),
            ('subject', 'ilike', 'Pre-Arrival'),
        ])
        return bool(queued_mail)

    def action_send_pre_arrival_link(self):
        self.ensure_one()
        if self._has_existing_pre_arrival_communication():
            self.message_post(
                body=_("Pre-arrival email was not queued again because one already exists for this reservation."),
                subtype_xmlid='mail.mt_note',
            )
            return False
        self._generate_access_token()
        link = self._get_pre_arrival_absolute_url()
        guest_email = (self.partner_email or self.partner_id.email or '').strip()
        if not guest_email:
            message = _("Guest email is required before sending pre-arrival link.")
            self.message_post(
                body=_("Pre-arrival email not sent: %s") % message,
                subtype_xmlid='mail.mt_note',
            )
            raise UserError(message)

        template = self.env.ref('hotel_management.email_template_pre_arrival', raise_if_not_found=False)
        if not template:
            message = _("Pre-arrival email template was not found.")
            self.message_post(
                body=_("Pre-arrival email not sent to %(email)s: %(reason)s")
                % {'email': guest_email, 'reason': message},
                subtype_xmlid='mail.mt_note',
            )
            raise UserError(message)
        
        try:
            mail_id = template.send_mail(self.id, force_send=False)
        except Exception as error:
            self._create_email_audit(
                'pre_arrival',
                guest_email,
                'failed',
                _("Pre-Arrival Registration - %s") % (self.name or ''),
                failure_reason=str(error),
            )
            self.message_post(
                body=_("Pre-arrival email failed for %(email)s: %(reason)s")
                % {'email': guest_email, 'reason': str(error)},
                subtype_xmlid='mail.mt_note',
            )
            raise

        self._create_email_audit(
            'pre_arrival',
            guest_email,
            'queued',
            template._render_field('subject', [self.id])[self.id],
            mail=self.env['mail.mail'].sudo().browse(mail_id).exists(),
        )
        safe_message = Markup(
            "<b>Pre-arrival email queued to guest: %s.</b><br/>"
            "Link: <a href='%s' target='_blank'>Click Here</a>"
        ) % (guest_email, link)
        self.message_post(body=safe_message, subtype_xmlid='mail.mt_note')
        self.pre_arrival_sent = True

    @api.model
    def cron_send_pre_arrival_links(self):
        days = self.env.company.pre_arrival_days or 3
        today = fields.Date.context_today(self)
        target_date = today + timedelta(days=days)
        
        reservations = self.search([
            ('state', 'in', ['draft', 'confirm']), 
            ('checkin_date', '>=', today),
            ('checkin_date', '<=', target_date),
            ('pre_arrival_sent', '=', False),
            ('partner_id.email', '!=', False) # Safely ensure the guest has an email
        ])
        
        for res in reservations:
            if res._has_existing_pre_arrival_communication():
                continue
            res.action_send_pre_arrival_link()

    @api.model
    def cron_send_queued_pre_arrival_emails(self, limit=50):
        deleted_mail_audits = self.env['hotel.email.audit'].sudo().search([
            ('audit_type', '=', 'pre_arrival'),
            ('status', '=', 'failed'),
            ('failure_reason', 'ilike', 'mail.mail'),
            ('failure_reason', 'ilike', 'deleted'),
        ], limit=limit)
        deleted_mail_audits.write({
            'status': 'sent',
            'mail_id': False,
            'failure_reason': False,
        })
        sent_audits = self.env['hotel.email.audit'].sudo().search([
            ('audit_type', '=', 'pre_arrival'),
            ('status', 'in', ['queued', 'failed']),
            ('mail_id', '!=', False),
            ('mail_id.state', '=', 'sent'),
        ], limit=limit)
        sent_audits.write({
            'status': 'sent',
            'failure_reason': False,
        })
        audits = self.env['hotel.email.audit'].sudo().search([
            ('audit_type', '=', 'pre_arrival'),
            ('status', '=', 'queued'),
        ], order='create_date asc, id asc', limit=limit)
        template = self.env.ref('hotel_management.email_template_pre_arrival', raise_if_not_found=False)
        for audit in audits:
            reservation = audit.reservation_id.exists()
            try:
                if not reservation:
                    raise UserError(_("Reservation is missing."))
                if not template and not audit.mail_id:
                    raise UserError(_("Pre-arrival email template was not found."))

                reservation._generate_access_token()
                recipient = (audit.recipient or reservation.partner_email or reservation.partner_id.email or '').strip()
                if not recipient or recipient == '-':
                    raise UserError(_("Guest email is required before sending pre-arrival link."))

                try:
                    mail = audit.mail_id.sudo().exists()
                except MissingError:
                    audit.write({
                        'status': 'sent',
                        'mail_id': False,
                        'failure_reason': False,
                    })
                    reservation.message_post(
                        body=_("Pre-arrival email sent to guest: %s") % recipient,
                        subtype_xmlid='mail.mt_note',
                    )
                    continue
                if mail and mail.state != 'sent':
                    mail.send()
                    mail.invalidate_recordset()
                elif not mail:
                    mail_id = template.send_mail(reservation.id, force_send=True)
                    mail = self.env['mail.mail'].sudo().browse(mail_id).exists()

                if mail and mail.state == 'exception':
                    raise UserError(mail.failure_reason or _("Mail delivery failed."))

                audit.write({
                    'status': 'sent',
                    'mail_id': mail.id if mail else False,
                    'failure_reason': False,
                })
                reservation.message_post(
                    body=_("Pre-arrival email sent to guest: %s") % recipient,
                    subtype_xmlid='mail.mt_note',
                )
            except Exception as error:
                sent_mail = audit.mail_id.sudo().exists()
                if sent_mail:
                    sent_mail.invalidate_recordset()
                if sent_mail and sent_mail.state == 'sent':
                    audit.write({
                        'status': 'sent',
                        'failure_reason': False,
                    })
                    if reservation:
                        reservation.message_post(
                            body=_("Pre-arrival email sent to guest: %s") % (audit.recipient or reservation.partner_email or reservation.partner_id.email or ''),
                            subtype_xmlid='mail.mt_note',
                        )
                    continue
                _logger.exception(
                    "Queued pre-arrival email failed for audit_id=%s reservation_id=%s",
                    audit.id,
                    reservation.id if reservation else False,
                )
                audit.write({
                    'status': 'failed',
                    'failure_reason': str(error),
                })
                if reservation:
                    reservation.message_post(
                        body=_("Pre-arrival email failed: %s") % str(error),
                        subtype_xmlid='mail.mt_note',
                    )
        return True

class HotelRoomMoveWizard(models.TransientModel):
    _name = 'hotel.room.move.wizard'
    _description = 'Move Room Wizard'

    reservation_id = fields.Many2one('hotel.reservation', string="Reservation", required=True)
    current_room_id = fields.Many2one('hotel.room', related='reservation_id.room_id', string="Current Room")
    new_room_type_id = fields.Many2one('hotel.room.type', string="New Room Type", required=True)
    new_room_id = fields.Many2one('hotel.room', string="New Room", required=True)
    reason = fields.Char(string="Reason for Move", required=True)

    def action_confirm_move(self):
        self.ensure_one()
        self.reservation_id._perform_room_move(self.new_room_id, self.reason)
        return {'type': 'ir.actions.act_window_close'}


class HotelArrivalReportWizard(models.TransientModel):
    _name = 'hotel.arrival.report.wizard'
    _description = 'Arrival Report Wizard'

    start_date = fields.Date(string="From Date", required=True, default=fields.Date.context_today)
    end_date = fields.Date(string="To Date", required=True, default=fields.Date.context_today)

    def action_view_report(self):
        self.ensure_one()
        domain = [('state', 'in', ['draft', 'confirm']), ('checkin_date', '>=', self.start_date), ('checkin_date', '<=', self.end_date)]
        tree_view_id = self.env.ref('hotel_management.view_hotel_front_desk_report_tree').id
        return {
            'name': _('Expected Arrivals (%s to %s)') % (self.start_date.strftime('%b %d'), self.end_date.strftime('%b %d')),
            'type': 'ir.actions.act_window',
            'res_model': 'hotel.reservation',
            'view_mode': 'list,form',
            'views': [(tree_view_id, 'list'), (False, 'form')], 
            'domain': domain,
            'target': 'current',
        }

    def action_print_report(self):
        self.ensure_one()
        domain = [('state', 'in', ['draft', 'confirm']), ('checkin_date', '>=', self.start_date), ('checkin_date', '<=', self.end_date)]
        reservations = self.env['hotel.reservation'].search(domain)
        if not reservations:
            raise UserError(_("No arrivals found for these dates!"))
        return self.env.ref('hotel_management.action_report_hotel_reservation_list').report_action(reservations)

class HotelDepartureReportWizard(models.TransientModel):
    _name = 'hotel.departure.report.wizard'
    _description = 'Departure Report Wizard'

    start_date = fields.Date(string="From Date", required=True, default=fields.Date.context_today)
    end_date = fields.Date(string="To Date", required=True, default=fields.Date.context_today)

    def action_view_report(self):
        self.ensure_one()
        domain = [('state', 'in', ['checkin', 'checkout_hold']), ('checkout_date', '>=', self.start_date), ('checkout_date', '<=', self.end_date)]
        tree_view_id = self.env.ref('hotel_management.view_hotel_front_desk_report_tree').id
        return {
            'name': _('Expected Departures (%s to %s)') % (self.start_date.strftime('%b %d'), self.end_date.strftime('%b %d')),
            'type': 'ir.actions.act_window',
            'res_model': 'hotel.reservation',
            'view_mode': 'list,form',
            'views': [(tree_view_id, 'list'), (False, 'form')], 
            'domain': domain,
            'target': 'current',
        }
    
    def action_print_report(self):
        self.ensure_one()
        domain = [('state', 'in', ['checkin', 'checkout_hold']), ('checkout_date', '>=', self.start_date), ('checkout_date', '<=', self.end_date)]
        reservations = self.env['hotel.reservation'].search(domain)
        if not reservations:
            raise UserError(_("No departures found for these dates!"))
        return self.env.ref('hotel_management.action_report_hotel_reservation_list').report_action(reservations)

class HotelNightAuditWizard(models.TransientModel):
    _name = 'hotel.night.audit.wizard'
    _description = 'Night Audit Processing Wizard'
    
    company_id = fields.Many2one('res.company', default=lambda self: self.env.company)
    audit_date = fields.Date(string="Business Date to Close", related='company_id.hotel_business_date', readonly=True)
    system_date = fields.Date(string="Physical System Date", default=fields.Date.context_today, readonly=True)
    state = fields.Selection([('draft', 'Draft'), ('done', 'Done')], default='draft')
    result_log = fields.Html(string="Audit Results", readonly=True)

    def action_run_audit(self):
        import os
        import odoo
        from datetime import datetime, timedelta
        
        audit_date = self.audit_date
        
        # =================================================================
        # Front desk protections.
        # =================================================================
        
        pending_arrivals = self.env['hotel.reservation'].search([
            ('state', '=', 'confirm'),
            ('checkin_date', '<=', audit_date)
        ])
        if pending_arrivals:
            raise UserError(f"CANNOT RUN NIGHT AUDIT!\n\nThere are {len(pending_arrivals)} Pending Arrivals for today. The Front Desk must Check them In, Cancel them, or mark them as No-Show before you can close the day.")

        checkout_hold_records = self.env['hotel.reservation'].cron_auto_checkout_hold(
            business_date=audit_date,
            enforce_time_gate=False,
        )
        # Manual night audit uses the same official checkout-hold flow as the scheduler.
        if False:
            pass
            raise UserError(f"CANNOT RUN NIGHT AUDIT!\n\nThere are {len(pending_departures)} Pending Departures for today. The Front Desk must Check them Out or Extend their stay before you can close the day.")

        # =================================================================
        # Proceed with audit and backups.
        # =================================================================
        
        audit_date_str = audit_date.strftime('%Y-%m-%d')
        db_name = self.env.cr.dbname
        timestamp = datetime.now().strftime('%Y%m%d_%H%M%S')
        
        # Keep night-audit backups with the active Odoo data directory after upgrades.
        backup_root = os.path.join(odoo.tools.config['data_dir'], 'hotel_night_audit_backups')
        before_dir = os.path.join(backup_root, 'before')
        after_dir = os.path.join(backup_root, 'after')
        
        os.makedirs(before_dir, exist_ok=True)
        os.makedirs(after_dir, exist_ok=True)
        
        before_filepath = os.path.join(before_dir, f"{db_name}_Before_Audit_{timestamp}.zip")
        after_filepath = os.path.join(after_dir, f"{db_name}_After_Audit_{timestamp}.zip")

        # --- STEP 1: BACKUP BEFORE AUDIT ---
        try:
            with open(before_filepath, 'wb') as f:
                odoo.service.db.dump_db(db_name, f, backup_format='zip')
            backup_1_status = f"<span style='color: #28a745;'>Success: {before_filepath}</span>"
        except Exception as e:
            backup_1_status = f"<span style='color: #dc3545;'>Failed: {str(e)}</span>"

        # --- STEP 2: RUN NIGHT AUDIT CHARGES ---
        results = self.env['hotel.reservation']._run_night_audit_room_charge_batch(
            business_date=audit_date,
            reservation_domain=[('state', 'in', ['checkin', 'checkout_hold'])],
            post_messages=False,
            raise_on_error=True,
        )
        log_lines = []
        posted_count = 0
        skipped_count = 0

        status_labels = {
            'posted': ('POSTED', '#28a745'),
            'already_posted': ('ALREADY POSTED', '#856404'),
            'bypassed': ('BYPASSED', '#6c757d'),
            'skipped': ('SKIPPED', '#dc3545'),
            'error': ('ERROR', '#dc3545'),
        }

        for result in results:
            reservation = result['reservation']
            room_name = result.get('room_name') or 'Unassigned'
            status = result.get('status', 'skipped')
            label, color = status_labels.get(status, ('INFO', '#0056b3'))
            log_lines.append(
                f"<li style='margin-bottom: 5px;'><span style='color: {color}; font-weight: bold;'>{label}:</span> "
                f"<b>{reservation.name}</b> (Room {room_name}) - {result.get('message', '')}</li>"
            )
            if status == 'posted':
                posted_count += 1
            else:
                skipped_count += 1
                        
        next_day = audit_date + timedelta(days=1)
        self._roll_hotel_business_date(next_day)

        self.env.cr.commit()

        # --- STEP 3: BACKUP AFTER AUDIT ---
        try:
            with open(after_filepath, 'wb') as f:
                odoo.service.db.dump_db(db_name, f, backup_format='zip')
            backup_2_status = f"<span style='color: #28a745;'>Success: {after_filepath}</span>"
        except Exception as e:
            backup_2_status = f"<span style='color: #dc3545;'>Failed: {str(e)}</span>"

        # --- STEP 4: RENDER UI RESULTS ---
        html = f"""
            <div style='background-color: #e9ecef; padding: 15px; border-radius: 5px; border: 1px solid #ddd; margin-bottom: 15px;'>
                <h4 style='margin-top: 0; color: #333;'><i class='fa fa-hdd-o'></i> Automated Database Backups</h4>
                <p style='margin: 5px 0; font-size: 13px;'><b>Before Audit:</b> {backup_1_status}</p>
                <p style='margin: 5px 0; font-size: 13px;'><b>After Audit:</b> {backup_2_status}</p>
            </div>
            <div style='background-color: #f8f9fa; padding: 15px; border-radius: 5px; border: 1px solid #ddd; margin-bottom: 20px;'>
                <h3 style='margin-top: 0; color: #333;'>Night Audit Complete for {audit_date_str}</h3>
                <div style='font-size: 16px;'>
                    <p style='margin: 5px 0;'><b>Moved to Checkout Hold:</b> {len(checkout_hold_records)} guests</p>
                    <p style='margin: 5px 0;'><b>Successfully Posted:</b> {posted_count} rooms</p>
                    <p style='margin: 5px 0;'><b>Skipped:</b> {skipped_count} rooms</p>
                    <hr/>
                    <p style='margin: 5px 0; color: #0056b3; font-weight: bold;'>The Hotel Business Date has successfully moved forward to: {next_day.strftime('%Y-%m-%d')}</p>
                </div>
            </div>
            <h4 style='border-bottom: 2px solid #eee; padding-bottom: 5px;'>Detailed Room Log:</h4>
            <ul style='list-style-type: none; padding-left: 0; font-size: 14px;'>
                {''.join(log_lines) if log_lines else '<li>No in-house guests found for processing.</li>'}
            </ul>
        """
        self.write({'result_log': html, 'state': 'done'})
        return {'type': 'ir.actions.act_window', 'res_model': 'hotel.night.audit.wizard', 'res_id': self.id, 'view_mode': 'form', 'target': 'new'}

    def _roll_hotel_business_date(self, next_day):
        self.ensure_one()
        if not (
            self.env.su
            or self.env.user.has_group('hotel_management.group_hotel_night_auditor')
            or self.env.user.has_group('hotel_management.group_hotel_manager')
            or self.env.user.has_group('base.group_system')
        ):
            raise AccessError(_("Only Night Auditor, Hotel Manager, or Administrator can roll the hotel business date."))

        company = self.company_id
        old_date = company.hotel_business_date
        company.sudo().write({'hotel_business_date': next_day})
        _logger.info(
            "Night Audit rolled hotel_business_date for company_id=%s from %s to %s by user_id=%s (%s)",
            company.id,
            old_date,
            next_day,
            self.env.user.id,
            self.env.user.login,
        )
        return True
    
class HotelDepositWizard(models.TransientModel):
    _name = 'hotel.deposit.wizard'
    _description = 'Advance Deposit Wizard'

    reservation_id = fields.Many2one('hotel.reservation', string="Reservation", required=True)
    amount = fields.Float(string="Deposit Amount", required=True)
    currency_id = fields.Many2one(related='reservation_id.currency_id')
    deposit_required = fields.Boolean(related='reservation_id.hotel_deposit_policy_required', readonly=True)
    required_deposit_amount = fields.Monetary(
        string="Required Deposit Amount",
        related='reservation_id.hotel_required_deposit_amount',
        readonly=True,
        currency_field='currency_id',
    )
    deposit_received_amount = fields.Monetary(
        string="Deposit Received",
        related='reservation_id.hotel_deposit_received_amount',
        readonly=True,
        currency_field='currency_id',
    )
    remaining_deposit_required = fields.Monetary(
        string="Remaining Deposit Required",
        related='reservation_id.hotel_remaining_deposit_required',
        readonly=True,
        currency_field='currency_id',
    )
    business_date = fields.Date(
        string="Business Date",
        default=lambda self: self.env.company.hotel_business_date or fields.Date.context_today(self),
        required=True,
        readonly=True,
    )
    payment_date = fields.Date(
        string="Payment Date",
        default=fields.Date.context_today,
        required=True,
        readonly=True,
    )
    processed = fields.Boolean(string="Processed", default=False, readonly=True)
    journal_id = fields.Many2one(
        'account.journal',
        string="Payment Method",
        domain=[('active', '=', True), ('type', 'in', ['bank', 'cash'])],
        required=True,
    )

    def _find_duplicate_deposit_registration(self):
        self.ensure_one()
        reservation = self.reservation_id
        amount = self.amount or 0.0
        rounding = reservation.currency_id.rounding or 0.01
        business_date = fields.Date.to_date(self.business_date or self.env.company.hotel_business_date or fields.Date.context_today(self))
        duplicate_window_start = fields.Datetime.now() - timedelta(seconds=60)
        duplicate_payment = self.env['account.payment'].search([
            ('is_advance_deposit', '=', True),
            ('state', 'in', ('in_process', 'paid')),
            ('payment_type', '=', 'inbound'),
            ('hotel_reservation_id', '=', reservation.id),
            ('journal_id', '=', self.journal_id.id),
            ('create_uid', '=', self.env.user.id),
            ('create_date', '>=', duplicate_window_start),
            ('hotel_business_date', '=', business_date),
        ], order='create_date desc, id desc', limit=20).filtered(
            lambda pay: (
                abs((pay.amount or 0.0) - amount) <= rounding
                and not pay.advance_deposit_void_payment_ids.filtered(lambda void: void.state != 'cancel')
            )
        )[:1]
        return duplicate_payment

    def _format_deposit_currency(self, amount):
        self.ensure_one()
        currency = self.currency_id or self.reservation_id.currency_id or self.env.company.currency_id
        return "%s%.2f" % (currency.symbol or '', amount or 0.0)

    def _validate_required_deposit_policy(self):
        self.ensure_one()
        reservation = self.reservation_id
        if not reservation.company_id.hotel_deposit_required:
            return

        currency = reservation.currency_id or reservation.company_id.currency_id
        rounding = currency.rounding or 0.01
        required_amount = reservation._get_required_deposit_amount()
        existing_amount = reservation._get_posted_advance_deposit_amount()
        cumulative_amount = existing_amount + (self.amount or 0.0)

        if required_amount - cumulative_amount > rounding:
            raise UserError(
                _("Deposit amount is less than the required deposit amount of %s.")
                % self._format_deposit_currency(required_amount)
            )

    def action_confirm_deposit(self):
        self.ensure_one()
        duplicate_error = _("This deposit appears to have just been submitted. Please wait a moment before trying again.")
        if self.processed:
            raise UserError(duplicate_error)
        if self.amount <= 0:
            raise UserError(_("Deposit amount must be greater than zero."))

        res = self.reservation_id
        is_group_deposit = bool(
            self.env.context.get('group_deposit')
            and res.is_desk_folio
            and res.group_id
        )

        if (res.is_desk_folio or res.folio_type in ['desk', 'group_master']) and not is_group_deposit:
            raise UserError(_("Advance deposits are only available for future room reservations."))

        rounding = res.currency_id.rounding or 0.01
        # Allow any deposit amount — hotels commonly collect larger deposits
        # to cover incidentals, security, or advance payment for multiple stays.
        # Only block if reservation already has a credit balance (already overpaid).
        if not is_group_deposit and res.guest_balance_due <= rounding and res.guest_credit_balance > rounding:
            raise UserError(_("This reservation already has a credit balance of %.2f. Please use Deposit Settlement to refund or transfer it first.") % res.guest_credit_balance)

        if not is_group_deposit:
            self._validate_required_deposit_policy()

        if self._find_duplicate_deposit_registration():
            raise UserError(duplicate_error)
            
        deposit_account = res._get_advance_deposit_liability_account()
        if not deposit_account:
            raise UserError(_("Please configure the Advance Deposit Liability Account in Hotel Settings before registering deposits."))
            
        payment_method_line = self.journal_id.inbound_payment_method_line_ids[:1]
        if not payment_method_line:
            raise UserError(_("The selected payment journal does not have an inbound payment method configured."))
            
        self.write({'processed': True})

        # =========================================================
        # DEPOSIT RECEIPT ONLY MODE (V1)
        # No customer invoice is created for advance deposits. Deposit tax
        # invoice mode is deferred to Version 2.
        # =========================================================

        payment_memo = res.name
        payment_reference = _("Advance Deposit - %s") % res.name
        posting_description = _("Advance Deposit Received (%s)") % self.journal_id.name

        if is_group_deposit:
            # Keep memo as the Paymaster reservation number, e.g. RES/2026/0023.
            # The PMS uses this to link the payment back to the reservation.
            payment_memo = res.name
            payment_reference = _("Group Advance Deposit - %s") % (res.group_id.name or res.name)
            posting_description = _("Group Advance Deposit Received (%s)") % self.journal_id.name

        payment = self.env['account.payment'].create({
            'payment_type': 'inbound',
            'partner_type': 'customer',
            'partner_id': res.partner_id.id,
            'amount': self.amount,
            'date': self.payment_date,
            'journal_id': self.journal_id.id,
            'payment_method_line_id': payment_method_line.id,
            'memo': payment_memo,
            'payment_reference': payment_reference,
            'hotel_business_date': self.business_date,
            'is_advance_deposit': True,
            'hotel_reservation_id': res.id,
            'destination_account_id': deposit_account.id,
        })
        payment.write({'destination_account_id': deposit_account.id})
        payment.sudo().action_post()

        if hasattr(payment, '_compute_hotel_info'):
            payment._compute_hotel_info()
        if hasattr(payment, '_compute_hotel_payment_activity_type'):
            payment._compute_hotel_payment_activity_type()
        if hasattr(res, '_compute_folio_status'):
            res._compute_folio_status()
        if hasattr(res, '_refresh_operational_folio_status'):
            res._refresh_operational_folio_status()

        existing_entry = self.env['hotel.posting.journal'].search([
            ('reservation_id', '=', res.id),
            ('source_payment_id', 'in', payment.ids),
            ('journal_type', '=', 'payment'),
        ], limit=1)
        deposit_entry_vals = {
            'reservation_id': res.id,
            'journal_type': 'payment',
            'description': posting_description,
            'amount': -payment.amount,
            'business_date': self.business_date,
            'date': payment.create_date or fields.Datetime.now(),
            'source_order_id': res.sale_order_id.id if res.sale_order_id else False,
            'source_move_id': False,
            'source_payment_id': payment.id,
            'folio_billing_target': 'guest',
        }
        if existing_entry:
            existing_entry.write(deposit_entry_vals)
        else:
            self.env['hotel.posting.journal'].create(deposit_entry_vals)
        if hasattr(res, '_refresh_operational_folio_status'):
            res._refresh_operational_folio_status()
            
        res._log_exchange_event(
            _("Advance Deposit Receipt"),
            '',
            _("%s%.2f via %s") % ((res.currency_id.symbol or ''), payment.amount, payment.journal_id.display_name),
            change_type='action',
            source_document=payment,
        )

        action = self.env.ref('hotel_management.action_report_advance_deposit_receipt').report_action(payment)
        action['close_on_report_download'] = True
        return action


class HotelDepositVoidWizard(models.TransientModel):
    _name = 'hotel.deposit.void.wizard'
    _description = 'Deposit Settlement Wizard'

    reservation_id = fields.Many2one('hotel.reservation', string="Reservation", required=True)
    currency_id = fields.Many2one(related='reservation_id.currency_id')
    business_date = fields.Date(
        string="Business Date",
        default=lambda self: self.env.company.hotel_business_date or fields.Date.context_today(self),
        required=True,
        readonly=True,
    )
    deposit_source_type = fields.Selection(
        [('payment', 'Payment Deposit'), ('invoice', 'Legacy Deposit Invoice')],
        string="Deposit Source",
        default='payment',
        required=True,
    )
    settlement_action = fields.Selection(
        [
            ('refund', 'Refund Deposit'),
            ('transfer', 'Transfer Deposit'),
            ('apply', 'Apply Deposit to Charge / Fee'),
            ('void', 'Void Wrong Entry / Correction'),
        ],
        string="Settlement Action",
        default='refund',
        required=True,
    )
    target_reservation_id = fields.Many2one(
        'hotel.reservation',
        string="Transfer To Reservation",
        domain="[('id', '!=', reservation_id), ('state', 'not in', ['checkout', 'cancel'])]",
    )

    transfer_amount = fields.Monetary(
        string="Transfer Amount",
        currency_field='currency_id',
    )
    available_invoice_ids = fields.Many2many('account.move', compute='_compute_available_deposit_docs')
    available_payment_ids = fields.Many2many('account.payment', compute='_compute_available_deposit_docs')
    deposit_invoice_id = fields.Many2one(
        'account.move',
        string="Legacy Deposit Invoice",
        domain="[('id', 'in', available_invoice_ids)]",
    )
    deposit_payment_id = fields.Many2one(
        'account.payment',
        string="Deposit Payment",
        domain="[('id', 'in', available_payment_ids)]",
    )
    deposit_payment_ids = fields.Many2many(
        'account.payment',
        string="Related Payment(s)",
        compute='_compute_available_deposit_docs',
    )
    amount = fields.Monetary(string="Deposit Amount", compute='_compute_available_deposit_docs')
    document_state = fields.Selection(
    [
        ('draft', 'Draft'),
        ('posted', 'Posted'),
        ('in_process', 'In Process'),
        ('paid', 'Paid'),
        ('cancel', 'Cancelled'),
    ],
        string="Status",
        compute='_compute_available_deposit_docs',
    )
    payment_journal_names = fields.Char(string="Payment Journal(s)", compute='_compute_available_deposit_docs')

    settlement_amount = fields.Monetary(
        string="Settlement Amount",
        currency_field='currency_id',
        help="Amount to refund or void. Leave at full amount or enter a partial amount.",
    )
    available_credit = fields.Monetary(
        string="Available Credit",
        currency_field='currency_id',
        compute='_compute_available_credit',
    )

    @api.depends('reservation_id', 'deposit_payment_id', 'deposit_invoice_id', 'deposit_source_type')
    def _compute_available_credit(self):
        for wizard in self:
            if wizard.reservation_id:
                wizard.available_credit = wizard.reservation_id.guest_credit_balance
            else:
                wizard.available_credit = 0.0

    settlement_amount = fields.Monetary(
        string="Settlement Amount",
        currency_field='currency_id',
        help="Amount to refund or void. Defaults to the available credit. You can type a smaller amount for partial settlement.",
    )
    available_credit = fields.Monetary(
        string="Available Credit to Settle",
        currency_field='currency_id',
        compute='_compute_available_credit',
    )

    @api.depends('reservation_id')
    def _compute_available_credit(self):
        for wizard in self:
            if wizard.reservation_id:
                wizard.available_credit = wizard.reservation_id.guest_credit_balance
            else:
                wizard.available_credit = 0.0
    
    reason = fields.Text(string="Settlement Reason", required=True)

    @api.onchange('settlement_action', 'amount', 'deposit_payment_id')
    def _onchange_settlement_action_amount(self):
        credit = self.reservation_id.guest_credit_balance if self.reservation_id else 0.0
        if self.settlement_action == 'transfer':
            self.transfer_amount = self.amount
            self.settlement_amount = 0.0
        elif self.settlement_action in ('refund', 'void'):
            self.target_reservation_id = False
            self.transfer_amount = 0.0
            self.settlement_amount = round(credit, 2) if credit > 0 else round(self.amount, 2)
        else:
            self.target_reservation_id = False
            self.transfer_amount = 0.0
            self.settlement_amount = 0.0

    @api.model
    def default_get(self, fields_list):
        values = super().default_get(fields_list)
        reservation_id = values.get('reservation_id') or self.env.context.get('default_reservation_id')
        if reservation_id:
            reservation = self.env['hotel.reservation'].browse(reservation_id)
            payment = reservation._get_voidable_advance_deposit_payments()[:1]
            invoice = reservation._get_voidable_deposit_invoices()[:1]
            if payment:
                values['deposit_source_type'] = 'payment'
                if 'deposit_payment_id' in fields_list:
                    values['deposit_payment_id'] = payment.id
            elif invoice:
                values['deposit_source_type'] = 'invoice'
                if 'deposit_invoice_id' in fields_list:
                    values['deposit_invoice_id'] = invoice.id
        return values

    @api.onchange('reservation_id', 'deposit_source_type')
    def _onchange_reservation_or_source(self):
        if not self.reservation_id:
            self.deposit_invoice_id = False
            self.deposit_payment_id = False
            return

        if self.deposit_source_type == 'payment':
            self.deposit_invoice_id = False
            if not self.deposit_payment_id:
                self.deposit_payment_id = self.reservation_id._get_voidable_advance_deposit_payments()[:1]
        else:
            self.deposit_payment_id = False
            if not self.deposit_invoice_id:
                self.deposit_invoice_id = self.reservation_id._get_voidable_deposit_invoices()[:1]

    @api.onchange('deposit_invoice_id')
    def _onchange_deposit_invoice_id(self):
        if self.deposit_invoice_id:
            self.deposit_source_type = 'invoice'
            self.deposit_payment_id = False

    @api.onchange('deposit_payment_id')
    def _onchange_deposit_payment_id(self):
        if self.deposit_payment_id:
            self.deposit_source_type = 'payment'
            self.deposit_invoice_id = False

    @api.depends('reservation_id', 'deposit_source_type', 'deposit_invoice_id', 'deposit_payment_id', 'settlement_action')
    def _compute_available_deposit_docs(self):
        for wizard in self:
            invoices = wizard.reservation_id._get_voidable_deposit_invoices() if wizard.reservation_id else self.env['account.move']
            payment_records = wizard.reservation_id._get_voidable_advance_deposit_payments() if wizard.reservation_id else self.env['account.payment']
            wizard.available_invoice_ids = invoices
            wizard.available_payment_ids = payment_records

            selected_payments = self.env['account.payment']
            amount = 0.0
            state = False
            journal_names = ""

            if wizard.deposit_source_type == 'payment' and wizard.deposit_payment_id:
                selected_payments = wizard.deposit_payment_id
                amount = wizard.deposit_payment_id.amount
                state = wizard.deposit_payment_id.state
                journal_names = wizard.deposit_payment_id.journal_id.name or ""
            elif wizard.deposit_invoice_id:
                selected_payments = wizard.deposit_invoice_id._get_reconciled_payments().filtered(
                    lambda pay: pay.state in ('in_process', 'paid')
                )
                amount = wizard.deposit_invoice_id.amount_total
                state = wizard.deposit_invoice_id.state
                journal_names = ", ".join(selected_payments.mapped('journal_id.name')) or wizard.deposit_invoice_id.journal_id.name or ""
            elif wizard.settlement_action == 'transfer' and wizard.reservation_id:
                amount = wizard.reservation_id._get_operational_advance_deposit_credit_amount()

            wizard.deposit_payment_ids = selected_payments
            wizard.amount = amount
            wizard.document_state = state
            wizard.payment_journal_names = journal_names

    def _reverse_deposit_invoice(self, invoice):
        self.ensure_one()
        reversal = self.env['account.move.reversal'].with_context(
            active_model='account.move',
            active_ids=invoice.ids,
        ).create({
            'move_ids': [(6, 0, invoice.ids)],
            'date': self.business_date,
            'reason': self.reason,
            'journal_id': invoice.journal_id.id,
        })
        reversal.reverse_moves()
        refund_move = reversal.new_move_ids[:1]
        if not refund_move:
            raise UserError(_("The system could not create a credit note for this deposit."))
        refund_move.write({'hotel_business_date': self.business_date})
        if refund_move.state == 'draft':
            refund_move.action_post()
        return refund_move

    def _mirror_deposit_refund_payments(self, refund_move, source_payments):
        self.ensure_one()
        refunds = self.env['account.payment']
        rounding = self.reservation_id.currency_id.rounding or 0.01
        remaining = refund_move.amount_residual
        for payment in source_payments.sorted(lambda pay: (pay.date or fields.Date.context_today(self), pay.id)):
            if remaining <= rounding:
                break
            amount = min(payment.amount, remaining)
            if amount <= rounding:
                continue
            register = self.env['account.payment.register'].with_context(
                active_model='account.move',
                active_ids=refund_move.ids,
            ).create({
                'journal_id': payment.journal_id.id,
                'amount': amount,
                'payment_date': self.business_date,
            })
            refunds |= register._create_payments()
            refund_move.invalidate_recordset(['amount_residual', 'payment_state'])
            remaining = refund_move.amount_residual
        return refunds

    def _reconcile_deposit_void_moves(self, invoice, refund_move):
        self.ensure_one()
        lines_to_reconcile = (invoice.line_ids | refund_move.line_ids).filtered(
            lambda line: line.account_id.account_type == 'asset_receivable' and not line.reconciled
        )
        if lines_to_reconcile:
            lines_to_reconcile.reconcile()

    def _create_advance_deposit_void_payment(self, payment):
        self.ensure_one()
        reservation = self.reservation_id
        if payment.advance_deposit_void_payment_ids.filtered(lambda void: void.state != 'cancel'):
            raise UserError(_("This advance deposit payment has already been refunded or corrected."))
        applied = reservation._get_advance_deposit_payment_application_map(
            include_draft_applications=True
        ).get(payment.id, 0.0)
        rounding = reservation.currency_id.rounding or 0.01
        if applied >= (payment.amount - rounding) and applied > rounding:
            raise UserError(_("This advance deposit is fully consumed by an invoice. Please reset the invoice to Draft first, then refund."))

        if payment.state == 'draft':
            payment.unlink()
            return self.env['account.payment']

        if payment.state == 'draft':
            payment.unlink()
            return self.env['account.payment']

        if payment.state not in ('in_process', 'paid'):
            raise UserError(_("Only draft or processed advance deposit payments can be refunded or corrected."))

        payment_method_line = payment.journal_id.outbound_payment_method_line_ids[:1]
        if not payment_method_line:
            raise UserError(_("The selected payment journal does not have an outbound payment method configured for reversing this deposit."))

        reference_label = (
            _("Void Wrong Deposit Entry")
            if self.settlement_action == 'void'
            else _("Refund Advance Deposit")
        )
        void_payment = self.env['account.payment'].create({
            'payment_type': 'outbound',
            'partner_type': 'customer',
            'partner_id': payment.partner_id.id,
            'amount': self.settlement_amount if self.settlement_amount and self.settlement_amount > 0 else payment.amount,
            'date': self.business_date,
            'journal_id': payment.journal_id.id,
            'payment_method_line_id': payment_method_line.id,
            'memo': reservation.name,
            'payment_reference': _("%(label)s - %(reservation)s") % {
                'label': reference_label,
                'reservation': reservation.name,
            },
            'hotel_business_date': self.business_date,
            'is_advance_deposit': True,
            'destination_account_id': payment.destination_account_id.id,
            'voids_advance_deposit_payment_id': payment.id,
        })
        void_payment.action_post()
        self._reconcile_advance_deposit_void_payments(payment, void_payment)
        return void_payment

    def _reconcile_advance_deposit_void_payments(self, source_payment, void_payment):
        self.ensure_one()
        account = source_payment.destination_account_id
        if not account or not account.reconcile:
            return

        lines_to_reconcile = (source_payment.move_id.line_ids | void_payment.move_id.line_ids).filtered(
            lambda line: (
                line.account_id == account
                and not line.reconciled
            )
        )
        if lines_to_reconcile:
            lines_to_reconcile.reconcile()

    def _build_void_note_body(self, reservation, amount, journal_names, reason, extra_lines=None, title=False):
        self.ensure_one()
        safe_reason = Markup.escape(reason or "")
        safe_user = Markup.escape(self.env.user.name or "")
        safe_journal = Markup.escape(journal_names or _("N/A"))
        safe_date = Markup.escape(fields.Date.to_string(self.business_date) or "")
        safe_title = Markup.escape(title or _("Deposit Settlement Processed"))
        note_parts = [
            "<p><strong>%s</strong></p>" % safe_title,
            "<p>Amount: <strong>%s%.2f</strong></p>" % ((reservation.currency_id.symbol or ''), amount),
            "<p>Journal: <strong>%s</strong></p>" % safe_journal,
            "<p>Date: <strong>%s</strong></p>" % safe_date,
            "<p>User: <strong>%s</strong></p>" % safe_user,
            "<p>Reason: %s</p>" % safe_reason,
        ]
        for extra_line in extra_lines or []:
            note_parts.append("<p>%s</p>" % extra_line)
        return Markup("".join(note_parts))

    def action_confirm_void(self):
        self.ensure_one()
        reservation = self.reservation_id
        reservation._check_deposit_void_access()

        # Validate settlement amount for refund/void
        if self.settlement_action in ('refund', 'void') and self.settlement_amount:
            available = reservation.guest_credit_balance
            rounding = reservation.currency_id.rounding or 0.01
            if self.settlement_amount <= 0:
                raise UserError(_("Settlement amount must be greater than zero."))
            if self.settlement_amount - available > rounding:
                raise UserError(_(
                    "Settlement amount ($%.2f) cannot exceed the available credit balance ($%.2f)."
                ) % (self.settlement_amount, available))

        if self.settlement_action == 'transfer':
            if not self.target_reservation_id:
                raise UserError(_("Please select the target reservation to transfer this deposit."))

            if self.target_reservation_id == reservation:
                raise UserError(_("You cannot transfer a deposit to the same reservation."))

            amount = self.transfer_amount or self.amount
            if amount <= 0:
                raise UserError(_("Transfer amount must be greater than zero."))

            available_credit = reservation._get_operational_advance_deposit_credit_amount()
            if amount - available_credit > (reservation.currency_id.rounding or 0.01):
                raise UserError(_("Transfer amount cannot be greater than the available deposit amount."))

            business_date = self.business_date
            source_desc = _("Deposit Transfer Out to %s") % (self.target_reservation_id.name or '')
            target_desc = _("Deposit Transfer In from %s") % (reservation.name or '')

            reservation._ensure_posting_journal_entry(
                'payment',
                source_desc,
                amount,
                business_date,
                entry_datetime=fields.Datetime.now(),
                folio_billing_target='guest',
            )

            self.target_reservation_id._ensure_posting_journal_entry(
                'payment',
                target_desc,
                -amount,
                business_date,
                entry_datetime=fields.Datetime.now(),
                folio_billing_target='guest',
            )

            note_body = Markup(
                "<b>Deposit Transferred:</b> %s%s transferred from <b>%s</b> to <b>%s</b>.<br/>"
                "<b>Reason:</b> %s"
            ) % (
                Markup.escape(reservation.currency_id.symbol or ''),
                Markup.escape("%.2f" % amount),
                Markup.escape(reservation.name or ''),
                Markup.escape(self.target_reservation_id.name or ''),
                Markup.escape(self.reason or ''),
            )

            reservation.message_post(body=note_body, subtype_xmlid='mail.mt_note')
            self.target_reservation_id.message_post(body=note_body, subtype_xmlid='mail.mt_note')

            reservation._log_exchange_event(
                _("Deposit Transfer Out"),
                _("%s%.2f") % ((reservation.currency_id.symbol or ''), amount),
                _("Transferred to %s on %s") % (
                    self.target_reservation_id.name or '',
                    fields.Date.to_string(business_date),
                ),
                change_type='action',
                reason=self.reason,
                source_document=self.target_reservation_id,
            )

            self.target_reservation_id._log_exchange_event(
                _("Deposit Transfer In"),
                _("%s%.2f") % ((reservation.currency_id.symbol or ''), amount),
                _("Transferred from %s on %s") % (
                    reservation.name or '',
                    fields.Date.to_string(business_date),
                ),
                change_type='action',
                reason=self.reason,
                source_document=reservation,
            )

            (reservation | self.target_reservation_id)._refresh_operational_folio_status()

            return {'type': 'ir.actions.act_window_close'}

        if self.settlement_action == 'apply':
            raise UserError(_(
                "Apply Deposit to Charge / Fee is intentionally blocked in Version 1. "
                "A dedicated auditable fee/charge model is required before this action can safely create cancellation, no-show, early-departure, or manual fee entries."
            ))

        if self.settlement_action not in ('refund', 'void'):
            raise UserError(_(
                "This settlement action is not implemented yet. "
                "For now, please use Refund Deposit or Transfer Deposit only."
            ))

        refund_move = self.env['account.move']
        refund_payments = self.env['account.payment']
        note_body = Markup("")

        if self.deposit_source_type == 'payment':
            payment = self.deposit_payment_id
            if payment not in reservation._get_voidable_advance_deposit_payments():
                raise UserError(_("Please select a valid active deposit payment to refund or correct."))
            original_state = payment.state
            original_name = payment.name or payment.payment_reference or _("Draft Payment")
            journal_names = payment.journal_id.name or ""
            refund_payments = self._create_advance_deposit_void_payment(payment)

            extra_lines = [
                "Deposit Payment: <strong>%s</strong>" % Markup.escape(original_name),
            ]
            if original_state == 'draft':
                extra_lines.append("Draft deposit payment deleted before posting.")
            elif refund_payments:
                extra_lines.append(
                    "Reversing Payment: <strong>%s</strong>" % Markup.escape(
                        ", ".join(refund_payments.mapped('name')) or _("Draft Reversal")
                    )
                )
            note_body = self._build_void_note_body(
                reservation,
                payment.amount,
                journal_names,
                self.reason,
                extra_lines=extra_lines,
                title=_("Deposit Void / Correction") if self.settlement_action == 'void' else _("Advance Deposit Refunded"),
            )
        else:
            invoice = self.deposit_invoice_id
            if invoice not in reservation._get_voidable_deposit_invoices():
                raise UserError(_("Please select a valid active legacy deposit invoice to refund or correct."))

            source_payments = invoice._get_reconciled_payments().filtered(lambda pay: pay.state in ('in_process', 'paid'))

            if invoice.state == 'draft':
                reservation.write({'deposit_invoice_ids': [(3, invoice.id)]})
                invoice.unlink()
            elif invoice.state == 'posted':
                refund_move = self._reverse_deposit_invoice(invoice)
                if source_payments:
                    refund_payments = self._mirror_deposit_refund_payments(refund_move, source_payments)
                self._reconcile_deposit_void_moves(invoice, refund_move)
            else:
                raise UserError(_("Only draft or posted deposit invoices can be voided."))

            reservation._neutralize_deposit_order_lines(invoice, self.reason)

            journal_names = ", ".join(source_payments.mapped('journal_id.name')) or invoice.journal_id.name or ""
            extra_lines = [
                "Deposit Invoice: <strong>%s</strong>" % Markup.escape(invoice.name or _("Draft Invoice")),
            ]
            if refund_move:
                extra_lines.append(
                    "Credit Note: <strong>%s</strong>" % Markup.escape(refund_move.name or _("Draft Credit Note"))
                )
            if refund_payments:
                extra_lines.append(
                    "Refund Payment(s): <strong>%s</strong>" % Markup.escape(", ".join(refund_payments.mapped('name')))
                )
            note_body = self._build_void_note_body(
                reservation,
                invoice.amount_total,
                journal_names,
                self.reason,
                extra_lines=extra_lines,
                title=_("Deposit Void / Correction") if self.settlement_action == 'void' else _("Advance Deposit Refunded"),
            )

        reservation.message_post(body=note_body, subtype_xmlid='mail.mt_note')
        if reservation.sale_order_id:
            reservation.sale_order_id.message_post(body=note_body, subtype_xmlid='mail.mt_note')
        void_amount = self.deposit_payment_id.amount if self.deposit_source_type == 'payment' and self.deposit_payment_id else self.amount
        source_doc = (
            refund_payments[:1]
            or refund_move[:1]
            or self.deposit_payment_id
            or self.deposit_invoice_id
            or reservation
        )
        reservation._log_exchange_event(
            _("Advance Deposit Refunded"),
            _("%s%.2f") % ((reservation.currency_id.symbol or ''), void_amount),
            _("Refunded on %s") % fields.Date.to_string(self.business_date),
            change_type='action',
            reason=self.reason,
            source_document=source_doc,
        )
        reservation._refresh_operational_folio_status()

        return {'type': 'ir.actions.act_window_close'}

class HotelAccountingReportWizard(models.TransientModel):
    _name = 'hotel.accounting.report.wizard'
    _description = 'Accounting Report Wizard'

    start_date = fields.Date(string="From Date", required=True, default=fields.Date.context_today)
    end_date = fields.Date(string="To Date", required=True, default=fields.Date.context_today)
    
    invoice_ids = fields.Many2many('account.move')
    payment_ids = fields.Many2many('account.payment')

    def print_invoices(self):
        self.ensure_one()
        domain = [
            ('move_type', '=', 'out_invoice'),
            ('state', 'in', ('in_process', 'paid')),
            ('invoice_date', '>=', self.start_date),
            ('invoice_date', '<=', self.end_date)
        ]
        records = self.env['account.move'].search(domain, order='name asc')
        if not records:
            raise UserError(_("No Posted Invoices found for these dates!"))
            
        self.invoice_ids = records.ids
        return self.env.ref('hotel_management.action_report_hotel_invoice_list').report_action(self)

    def print_receipts(self):
        self.ensure_one()
        domain = [
            ('payment_type', '=', 'inbound'),
            ('state', 'in', ('in_process', 'paid')),
            ('date', '>=', self.start_date),
            ('date', '<=', self.end_date)
        ]
        records = self.env['account.payment'].search(domain, order='name asc')
        if not records:
            raise UserError(_("No Receipts found for these dates!"))
            
        self.payment_ids = records.ids
        return self.env.ref('hotel_management.action_report_hotel_receipt_list').report_action(self)        

# =========================================================
#  HOTEL MASTER POSTING JOURNAL (AUDIT TRAIL)
# =========================================================
class HotelPostingJournal(models.Model):
    _name = 'hotel.posting.journal'
    _description = 'Hotel Posting Journal'
    # THE FIX: Force the database to sort by Business Date first, physical date second!
    _order = 'business_date desc, date desc'

    reservation_id = fields.Many2one('hotel.reservation', string='Reservation', required=True, ondelete='cascade')
    partner_id = fields.Many2one(related='reservation_id.partner_id', string='Guest', store=True)
    room_id = fields.Many2one(related='reservation_id.room_id', string='Room', store=True)
    
    date = fields.Datetime(string='Date/Time', default=fields.Datetime.now, required=True, readonly=True)
    
    # THE FIX: Added Business Date Column directly to the journal
    business_date = fields.Date(string='Business Date', default=lambda self: self.env.company.hotel_business_date or fields.Date.context_today(self), required=True, readonly=True)
    
    user_id = fields.Many2one('res.users', string='Posted By', default=lambda self: self.env.user, readonly=True)
    
    journal_type = fields.Selection([
        ('charge', 'Manual / POS Charge'),
        ('payment', 'Payment / Deposit'),
        ('system', 'Night Audit / System')
    ], string='Type', required=True, readonly=True)
    
    description = fields.Char(string='Description', required=True, readonly=True)
    amount = fields.Monetary(string='Amount', required=True, readonly=True)
    currency_id = fields.Many2one('res.currency', related='reservation_id.currency_id')
    untaxed_amount = fields.Monetary(
        string='Untaxed Amount',
        compute='_compute_amount_breakdown',
        store=True,
        readonly=True,
    )
    tax_amount = fields.Monetary(
        string='Tax',
        compute='_compute_amount_breakdown',
        store=True,
        readonly=True,
    )
    total_amount = fields.Monetary(
        string='Total Amount',
        compute='_compute_amount_breakdown',
        store=True,
        readonly=True,
    )
    folio_billing_target = fields.Selection(
        [('guest', 'Guest'), ('company', 'Company')],
        string='Billing Target',
        default='guest',
        readonly=True,
        index=True,
    )
    source_order_id = fields.Many2one('sale.order', string='Source Folio', readonly=True, ondelete='set null')
    source_move_id = fields.Many2one('account.move', string='Source Invoice', readonly=True, ondelete='set null')
    source_payment_id = fields.Many2one('account.payment', string='Source Payment', readonly=True, ondelete='set null')
    source_sale_line_id = fields.Many2one('sale.order.line', string='Source Folio Line', readonly=True, ondelete='set null')
    folio_entry_type = fields.Selection(
        [
            ('deposit', 'Deposit'),
            ('room_charge', 'Room Charge'),
            ('pos_charge', 'POS Charge'),
            ('charge', 'Charge'),
            ('invoice', 'Invoice'),
            ('payment', 'Payment'),
            ('deposit_application', 'Invoice Application'),
            ('refund', 'Deposit Refund'),
            ('deposit_transfer_out', 'Deposit Transfer Out'),
            ('deposit_transfer_in', 'Deposit Transfer In'),
            ('correction', 'Void / Correction'),
        ],
        string='Folio Type',
        compute='_compute_folio_entry_metadata',
        store=True,
        readonly=True,
    )
    source_status = fields.Char(
        string='Posted/Invoice Status',
        compute='_compute_folio_entry_metadata',
        store=True,
        readonly=True,
    )
    source_document_name = fields.Char(
        string='Source Document Name',
        compute='_compute_source_document_link',
        readonly=True,
    )
    source_document_ref = fields.Reference(
        selection=[
            ('sale.order', 'Folio'),
            ('account.move', 'Invoice'),
            ('account.payment', 'Payment'),
        ],
        string='Source Document',
        compute='_compute_source_document_link',
        readonly=True,
    )
    entry_side = fields.Selection(
        [('debit', 'Debit Charge'), ('credit', 'Credit Deposit/Payment'), ('info', 'Informational')],
        string='Side',
        compute='_compute_financial_presentation',
        store=True,
        readonly=True,
    )
    debit_amount = fields.Monetary(
        string='Debit Charges',
        compute='_compute_financial_presentation',
        store=True,
        readonly=True,
    )
    credit_amount = fields.Monetary(
        string='Credit Deposits/Payments',
        compute='_compute_financial_presentation',
        store=True,
        readonly=True,
    )
    net_position = fields.Monetary(
        string='Net Position',
        compute='_compute_financial_presentation',
        store=True,
        readonly=True,
    )
    running_balance = fields.Monetary(
        string='Running Balance',
        compute='_compute_running_balance',
        readonly=True,
    )

    @api.depends('source_order_id', 'source_move_id', 'source_payment_id')
    def _compute_source_document_link(self):
        for rec in self:
            source_ref = False
            source_name = False
            if rec.source_move_id:
                source_ref = f'account.move,{rec.source_move_id.id}'
                source_name = rec.source_move_id.display_name
            elif rec.source_payment_id:
                source_ref = f'account.payment,{rec.source_payment_id.id}'
                source_name = rec.source_payment_id.display_name
            elif rec.source_order_id:
                source_ref = f'sale.order,{rec.source_order_id.id}'
                source_name = rec.source_order_id.display_name
            rec.source_document_ref = source_ref
            rec.source_document_name = source_name or rec.description

    @api.depends(
        'amount',
        'source_move_id',
        'source_sale_line_id.price_subtotal',
        'source_sale_line_id.price_total',
        'source_payment_id.amount',
        'folio_entry_type',
    )
    def _compute_amount_breakdown(self):
        for rec in self:
            untaxed = 0.0
            tax = 0.0
            total = abs(rec.amount or 0.0)

            if rec.source_sale_line_id:
                untaxed = abs(rec.source_sale_line_id.price_subtotal or 0.0)
                total = abs(rec.source_sale_line_id.price_total or 0.0)
                tax = max(total - untaxed, 0.0)
            elif rec.folio_entry_type in (
                'deposit',
                'payment',
                'deposit_application',
                'refund',
                'deposit_transfer_out',
                'deposit_transfer_in',
                'correction',
            ):
                total = abs(rec.amount or 0.0)
            elif rec.folio_entry_type == 'invoice':
                total = 0.0

            rec.untaxed_amount = untaxed
            rec.tax_amount = tax
            rec.total_amount = total

    @api.depends(
        'description',
        'source_move_id.state',
        'source_move_id.payment_state',
        'source_payment_id.state',
        'source_payment_id.payment_type',
        'source_payment_id.is_advance_deposit',
        'source_sale_line_id.invoice_status',
        'source_sale_line_id.is_night_audit_charge',
        'source_sale_line_id.name',
        'source_sale_line_id.product_id',
        'source_sale_line_id.product_id.categ_id',
    )
    def _compute_folio_entry_metadata(self):
        invoice_state_labels = self.env['account.move']._fields['state']._description_selection(self.env)
        payment_state_labels = self.env['account.move']._fields['payment_state']._description_selection(self.env)
        payment_record_state_labels = self.env['account.payment']._fields['state']._description_selection(self.env)
        sale_invoice_status_labels = self.env['sale.order.line']._fields['invoice_status']._description_selection(self.env)
        invoice_state_map = dict(invoice_state_labels)
        payment_state_map = dict(payment_state_labels)
        payment_record_state_map = dict(payment_record_state_labels)
        sale_invoice_status_map = dict(sale_invoice_status_labels)
        for rec in self:
            description = (rec.description or '').lower()
            if rec.source_payment_id:
                if rec.source_payment_id.is_advance_deposit:
                    rec.folio_entry_type = 'refund' if rec.source_payment_id.payment_type == 'outbound' else 'deposit'
                else:
                    rec.folio_entry_type = 'payment'
                rec.source_status = payment_record_state_map.get(rec.source_payment_id.state, rec.source_payment_id.state or '')
                continue

            if rec.source_move_id:
                if 'advance deposit applied' in description:
                    rec.folio_entry_type = 'deposit_application'
                else:
                    rec.folio_entry_type = 'invoice'
                move_state = invoice_state_map.get(rec.source_move_id.state, rec.source_move_id.state or '')
                payment_state = payment_state_map.get(rec.source_move_id.payment_state, rec.source_move_id.payment_state or '')
                rec.source_status = f"{move_state} / {payment_state}" if payment_state else move_state
                continue

            if 'deleted charge' in description:
                rec.folio_entry_type = 'correction'
                rec.source_status = _('Deleted')
                continue

            if description.startswith('deposit transfer out'):
                rec.folio_entry_type = 'deposit_transfer_out'
                rec.source_status = _('Transferred')
                continue

            if description.startswith('deposit transfer in'):
                rec.folio_entry_type = 'deposit_transfer_in'
                rec.source_status = _('Transferred')
                continue

            if rec.source_sale_line_id:
                sale_line_name = rec.source_sale_line_id.name or ''
                product_name = rec.source_sale_line_id.product_id.display_name if rec.source_sale_line_id.product_id else ''
                category_name = rec.source_sale_line_id.product_id.categ_id.complete_name if rec.source_sale_line_id.product_id and rec.source_sale_line_id.product_id.categ_id else ''
                line_haystack = " ".join(filter(None, [sale_line_name, product_name, category_name, rec.description or ''])).lower()
                if rec.source_sale_line_id.is_night_audit_charge or any(keyword in line_haystack for keyword in ('room charge', 'accommodation', 'lodging')):
                    rec.folio_entry_type = 'room_charge'
                elif any(keyword in line_haystack for keyword in ('restaurant bill', 'restaurant charge', 'pos charge', 'point of sale', 'pos order')):
                    rec.folio_entry_type = 'pos_charge'
                else:
                    rec.folio_entry_type = 'charge'
                rec.source_status = sale_invoice_status_map.get(
                    rec.source_sale_line_id.invoice_status,
                    rec.source_sale_line_id.invoice_status or '',
                )
                continue

            rec.folio_entry_type = 'charge'
            rec.source_status = ''

    @api.depends('folio_entry_type', 'description', 'amount', 'total_amount')
    def _compute_financial_presentation(self):
        for rec in self:
            amount = abs(rec.total_amount or rec.amount or 0.0)

            # Audit trail presentation:
            # charges increase the guest position (debit),
            # deposits, payments, and applications reduce it (credit),
            # while invoice document events stay visible but do not affect balance.
            if rec.folio_entry_type == 'invoice':
                side = 'info'
            elif rec.folio_entry_type in ('deposit', 'payment', 'deposit_transfer_in'):
                side = 'credit'
            elif rec.folio_entry_type == 'deposit_application':
                # Show deposit application visibly in the credit column for PMS-style
                # folio review, but keep it memo-only in the running balance so the
                # original advance-deposit receipt is not double-counted.
                side = 'credit'
            elif rec.folio_entry_type in ('refund', 'deposit_transfer_out'):
                side = 'debit'
            elif rec.folio_entry_type == 'correction':
                side = 'credit' if rec.amount <= 0 else 'debit'
            else:
                side = 'debit' if rec.amount >= 0 else 'credit'

            rec.entry_side = side
            rec.debit_amount = amount if side == 'debit' else 0.0
            rec.credit_amount = amount if side == 'credit' else 0.0
            if rec.folio_entry_type == 'deposit_application':
                rec.net_position = 0.0
            else:
                rec.net_position = amount if side == 'debit' else (-amount if side == 'credit' else 0.0)

    def _compute_running_balance(self):
        grouped = {}
        for rec in self:
            scope = rec.folio_billing_target or 'guest'
            grouped.setdefault((rec.reservation_id.id, scope), self.env['hotel.posting.journal'])
            grouped[(rec.reservation_id.id, scope)] |= rec

        balance_map = {}
        for (reservation_id, scope), _records in grouped.items():
            domain = [('reservation_id', '=', reservation_id)]
            if scope == 'company':
                domain.append(('folio_billing_target', '=', 'company'))
            else:
                domain.extend(['|', ('folio_billing_target', '=', 'guest'), ('folio_billing_target', '=', False)])
            all_entries = self.search(domain, order='business_date asc, date asc, id asc')
            running = 0.0
            for entry in all_entries:
                running += entry.net_position
                balance_map[entry.id] = running

        for rec in self:
            rec.running_balance = balance_map.get(rec.id, 0.0)

    def action_open_source_document(self):
        self.ensure_one()
        source = self.source_move_id or self.source_payment_id or self.source_order_id
        if not source:
            return False
        return {
            'type': 'ir.actions.act_window',
            'name': source.display_name,
            'res_model': source._name,
            'res_id': source.id,
            'view_mode': 'form',
            'target': 'current',
        }


# =========================================================
#  ACCOUNTING INTEGRATION (BUSINESS DATE TRACKING)
# =========================================================
class AccountMoveHotelAudit(models.Model):
    _inherit = 'account.move'

    hotel_group_master_id = fields.Many2one(
        'hotel.group.master',
        string='Hotel Group Master',
        copy=False,
        index=True,
    )

    hotel_business_date = fields.Date(string="Business Date", default=lambda self: self.env.company.hotel_business_date or fields.Date.context_today(self), index=True)
    hotel_folio_id = fields.Many2one('sale.order', string="Folio No.", compute="_compute_hotel_folio", store=True)
    hotel_guest_name = fields.Char(string="Guest Name", compute="_compute_hotel_folio", store=True)
    hotel_billing_target = fields.Selection(
        [('guest', 'Guest'), ('company', 'Company')],
        string="Billing Target",
        readonly=True,
        copy=False,
    )

    def _is_hotel_checkout_invoice_user(self):
        user = self.env.user
        return bool(
            self.env.su
            or user.has_group('hotel_management.group_hotel_front_office')
            or user.has_group('hotel_management.group_hotel_front_office_manager')
            or user.has_group('hotel_management.group_hotel_manager')
            or user.has_group('hotel_management.group_hotel_night_auditor')
            or user.has_group('account.group_account_manager')
            or user.has_group('base.group_system')
        )

    def _is_hotel_full_invoice_user(self):
        user = self.env.user
        return bool(
            self.env.su
            or user.has_group('hotel_management.group_hotel_manager')
            or user.has_group('account.group_account_manager')
            or user.has_group('base.group_system')
        )

    def _is_hotel_operational_customer_invoice(self):
        self.ensure_one()
        if self.move_type not in ('out_invoice', 'out_refund'):
            return False
        if self.hotel_folio_id and (
            self.hotel_folio_id.hotel_reservation_ids or self.hotel_folio_id.hotel_group_master_ids
        ):
            return True
        invoice_lines = self.invoice_line_ids
        if invoice_lines.filtered('hotel_reservation_id'):
            return True
        sale_lines = invoice_lines.mapped('sale_line_ids')
        return bool(
            sale_lines.filtered('hotel_reservation_id')
            or sale_lines.mapped('order_id').filtered(
                lambda order: order.hotel_reservation_ids or order.hotel_group_master_ids
            )
        )

    def _check_hotel_operational_invoice_access(self):
        if not self._is_hotel_checkout_invoice_user():
            raise AccessError(_("Only hotel checkout roles can operate hotel customer invoices."))
        invalid_invoices = self.filtered(lambda move: not move._is_hotel_operational_customer_invoice())
        if invalid_invoices:
            raise AccessError(_("Only hotel-linked customer invoices can be operated from Hotel Management."))

    def _get_hotel_invoice_primary_reservation(self):
        self.ensure_one()
        reservations = self.hotel_folio_id.hotel_reservation_ids.filtered(lambda res: res.state != 'cancel')
        if not reservations:
            reservations = self.invoice_line_ids.mapped('hotel_reservation_id').filtered(lambda res: res.state != 'cancel')
        if not reservations:
            reservations = self.invoice_line_ids.mapped('sale_line_ids.hotel_reservation_id').filtered(lambda res: res.state != 'cancel')
        if not reservations:
            reservations = self.invoice_line_ids.mapped('sale_line_ids.order_id.hotel_reservation_ids').filtered(lambda res: res.state != 'cancel')
        return reservations[:1]

    def _action_open_hotel_safe_invoice_view(self, name=None):
        invoices = self.exists()
        tree_view = self.env.ref('hotel_management.view_hotel_invoice_tree')
        form_view = self.env.ref('hotel_management.view_hotel_customer_invoice_form')
        action = self.env['ir.actions.actions']._for_xml_id('hotel_management.action_hotel_customer_invoices')
        action.update({
            'name': name or _('Customer Invoices'),
            'domain': [('id', 'in', invoices.ids or [0])],
            'context': {
                'create': False,
                'edit': True,
                'delete': False,
                'default_move_type': 'out_invoice',
            },
            'target': 'current',
        })
        if len(invoices) == 1:
            action.update({
                'res_id': invoices.id,
                'view_mode': 'form',
                'views': [(form_view.id, 'form')],
                'view_id': form_view.id,
            })
        else:
            action.update({
                'view_mode': 'list,form',
                'views': [(tree_view.id, 'list'), (form_view.id, 'form')],
                'view_id': tree_view.id,
            })
        return action

    def action_hotel_post_invoice(self):
        self._check_hotel_operational_invoice_access()
        draft_invoices = self.filtered(lambda move: move.state == 'draft')
        if not draft_invoices:
            raise UserError(_("Only draft hotel customer invoices can be confirmed."))
        draft_invoices.sudo().with_context(disable_abnormal_invoice_detection=True).action_post()
        return draft_invoices._action_open_hotel_safe_invoice_view(name=_("Customer Invoice"))

    def action_hotel_print_invoice(self):
        self._check_hotel_operational_invoice_access()
        report = self.env.ref('account.account_invoices')
        return report.report_action(self)

    def action_hotel_register_payment(self):
        self.ensure_one()
        self._check_hotel_operational_invoice_access()
        if self.state != 'posted':
            raise UserError(_("Please confirm/post the invoice before registering payment."))
        if self.payment_state in ('paid', 'in_payment') or self.amount_residual <= 0:
            raise UserError(_("This invoice does not have an open amount to pay."))
        return {
            'name': _('Register Hotel Payment'),
            'type': 'ir.actions.act_window',
            'res_model': 'hotel.invoice.payment.wizard',
            'view_mode': 'form',
            'target': 'new',
            'context': {'default_invoice_id': self.id},
        }

    def action_post(self):
        # Auto-sync: if staff adds a product line directly to a hotel invoice
        # that does not exist in the folio, automatically create the folio
        # charge line so both are always in sync. No error — seamless for staff.
        for move in self:
            if not move._is_hotel_operational_customer_invoice():
                continue
            if move.move_type != 'out_invoice':
                continue
            folio = move.hotel_folio_id
            if not folio:
                continue
            reservations = self.env['hotel.reservation'].search([
                ('sale_order_id', '=', folio.id)
            ], limit=1)
            if not reservations:
                continue
            reservation = reservations[0]
            folio_line_products = set(
                sol.product_id.id
                for sol in move.invoice_line_ids.mapped('sale_line_ids')
                if not sol.display_type and sol.product_id
            )
            orphan_lines = [
                line for line in move.invoice_line_ids
                if not line.display_type
                and line.product_id
                and line.product_id.id not in folio_line_products
            ]
            for inv_line in orphan_lines:
                biz_date = (
                    self.env.company.hotel_business_date
                    or fields.Date.context_today(self)
                )
                new_sol = self.env['sale.order.line'].create({
                    'order_id': folio.id,
                    'product_id': inv_line.product_id.id,
                    'name': inv_line.name or inv_line.product_id.name,
                    'product_uom_qty': inv_line.quantity,
                    'price_unit': inv_line.price_unit,
                    'tax_id': [(6, 0, inv_line.tax_ids.ids)],
                    'hotel_business_date': biz_date,
                    'hotel_reservation_id': reservation.id,
                    'billing_target': 'guest',
                    'is_night_audit_charge': False,
                })
                inv_line.sale_line_ids = [(4, new_sol.id)]

        if (
            not self.env.su
            and not self._is_hotel_full_invoice_user()
            and self._is_hotel_checkout_invoice_user()
            and self
            and all(move._is_hotel_operational_customer_invoice() for move in self)
        ):
            return self.action_hotel_post_invoice()
        return super().action_post()

    @api.depends('invoice_line_ids.sale_line_ids.order_id')
    def _compute_hotel_folio(self):
        for move in self:
            folios = move.mapped('invoice_line_ids.sale_line_ids.order_id')
            if folios:
                folio = folios[0]
                move.hotel_folio_id = folio.id

                reservations = self.env['hotel.reservation'].search([('sale_order_id', '=', folio.id)])
                desk_folios = reservations.filtered(lambda r: r.is_desk_folio)

                if desk_folios:
                    move.hotel_guest_name = desk_folios[0].partner_id.name or folio.partner_id.name
                elif reservations:
                    move.hotel_guest_name = reservations[0].partner_id.name
                else:
                    move.hotel_guest_name = folio.partner_id.name
            else:
                move.hotel_folio_id = False
                move.hotel_guest_name = False

    @api.model_create_multi
    def create(self, vals_list):
        for vals in vals_list:
            if vals.get('hotel_billing_target'):
                continue

            sale_line_ids = set()
            for command in vals.get('invoice_line_ids') or []:
                if command[0] != Command.CREATE or not command[2]:
                    continue
                for relation in command[2].get('sale_line_ids') or []:
                    if relation[0] == Command.LINK:
                        sale_line_ids.add(relation[1])
                    elif relation[0] == Command.SET:
                        sale_line_ids.update(relation[2])

            if not sale_line_ids:
                continue

            sale_lines = self.env['sale.order.line'].browse(list(sale_line_ids)).filtered(lambda line: not line.display_type)
            targets = {line.billing_target or line._get_resolved_billing_target() for line in sale_lines}
            if len(targets) == 1:
                vals['hotel_billing_target'] = targets.pop()

        return super().create(vals_list)

    def write(self, vals):
        if (
            not self.env.su
            and self._is_hotel_checkout_invoice_user()
            and not self._is_hotel_full_invoice_user()
        ):
            self._check_hotel_operational_invoice_access()
            if any(move.state != 'draft' for move in self):
                raise AccessError(_("Only draft hotel customer invoices can be edited from Hotel Management."))
        if 'state' in vals:
            for move in self:
                orders = move.invoice_line_ids.mapped('sale_line_ids.order_id')
                for order in orders:
                    reservation = self.env['hotel.reservation'].search([('sale_order_id', '=', order.id)], limit=1)
                    if reservation and move.state != vals['state']:
                        state_dict = dict(self._fields['state'].selection)
                        old_state = state_dict.get(move.state, move.state)
                        new_state = state_dict.get(vals['state'], vals['state'])
                        reservation._log_exchange_event(
                            f"Invoice Status ({move.name or 'Draft Invoice'})",
                            str(old_state),
                            str(new_state),
                            source_document=move,
                        )

        return super().write(vals)

class AccountMoveLineHotelAudit(models.Model):
    _inherit = 'account.move.line'

    hotel_reservation_id = fields.Many2one('hotel.reservation', string="Hotel Reservation", index=True, copy=False)
    is_advance_deposit_application = fields.Boolean(string="Advance Deposit Application", default=False, index=True, copy=False)

    def _check_hotel_invoice_line_operation(self):
        moves = self.mapped('move_id')
        if not moves:
            return
        if (
            not self.env.su
            and moves._is_hotel_checkout_invoice_user()
            and not moves._is_hotel_full_invoice_user()
        ):
            moves._check_hotel_operational_invoice_access()
            if any(move.state != 'draft' for move in moves):
                raise AccessError(_("Only draft hotel invoice lines can be edited from Hotel Management."))

    @api.model_create_multi
    def create(self, vals_list):
        if not self.env.su:
            move_ids = [
                vals.get('move_id') or self.env.context.get('default_move_id')
                for vals in vals_list
                if vals.get('move_id') or self.env.context.get('default_move_id')
            ]
            moves = self.env['account.move'].browse(move_ids).exists()
            if (
                moves
                and moves._is_hotel_checkout_invoice_user()
                and not moves._is_hotel_full_invoice_user()
            ):
                moves._check_hotel_operational_invoice_access()
                if any(move.state != 'draft' for move in moves):
                    raise AccessError(_("Only draft hotel invoice lines can be created from Hotel Management."))
        return super().create(vals_list)

    def write(self, vals):
        self._check_hotel_invoice_line_operation()
        return super().write(vals)


class HotelInvoicePaymentWizard(models.TransientModel):
    _name = 'hotel.invoice.payment.wizard'
    _description = 'Register Hotel Invoice Payment'

    invoice_id = fields.Many2one('account.move', string="Invoice", required=True, readonly=True)
    partner_id = fields.Many2one(related='invoice_id.partner_id', readonly=True)
    company_id = fields.Many2one(related='invoice_id.company_id', readonly=True)
    currency_id = fields.Many2one(related='invoice_id.currency_id', readonly=True)
    amount_residual = fields.Monetary(related='invoice_id.amount_residual', currency_field='currency_id', readonly=True)
    amount = fields.Monetary(string="Payment Amount", currency_field='currency_id', required=True)
    payment_date = fields.Date(
        string="Payment Date",
        required=True,
        default=lambda self: self.env.company.hotel_business_date or fields.Date.context_today(self),
    )
    journal_id = fields.Many2one(
        'account.journal',
        string="Payment Journal",
        required=True,
        domain="[('type', 'in', ['bank', 'cash']), ('company_id', '=', company_id)]",
    )
    available_payment_method_line_ids = fields.Many2many(
        'account.payment.method.line',
        compute='_compute_available_payment_method_line_ids',
    )
    payment_method_line_id = fields.Many2one(
        'account.payment.method.line',
        string="Payment Method",
        required=True,
        domain="[('id', 'in', available_payment_method_line_ids)]",
    )
    hotel_receipt_number = fields.Char(string="Hotel Receipt No.")

    @api.model
    def default_get(self, fields_list):
        values = super().default_get(fields_list)
        invoice_id = values.get('invoice_id') or self.env.context.get('default_invoice_id')
        invoice = self.env['account.move'].browse(invoice_id).exists() if invoice_id else self.env['account.move']
        if invoice:
            invoice._check_hotel_operational_invoice_access()
            values.setdefault('invoice_id', invoice.id)
            values.setdefault('amount', invoice.amount_residual)
            values.setdefault('payment_date', invoice.hotel_business_date or self.env.company.hotel_business_date or fields.Date.context_today(self))
            payment_line_field = 'outbound_payment_method_line_ids' if invoice.move_type == 'out_refund' else 'inbound_payment_method_line_ids'
            journal = self.env['account.journal'].search([
                ('type', 'in', ['bank', 'cash']),
                ('company_id', '=', invoice.company_id.id),
                (payment_line_field, '!=', False),
            ], limit=1)
            if journal:
                values.setdefault('journal_id', journal.id)
                values.setdefault('payment_method_line_id', journal[payment_line_field][:1].id)
        return values

    @api.depends('journal_id', 'invoice_id.move_type')
    def _compute_available_payment_method_line_ids(self):
        for wizard in self:
            if not wizard.journal_id:
                wizard.available_payment_method_line_ids = self.env['account.payment.method.line']
                continue
            if wizard.invoice_id.move_type == 'out_refund':
                wizard.available_payment_method_line_ids = wizard.journal_id.outbound_payment_method_line_ids
            else:
                wizard.available_payment_method_line_ids = wizard.journal_id.inbound_payment_method_line_ids

    @api.onchange('journal_id', 'invoice_id')
    def _onchange_journal_id(self):
        method_lines = self.available_payment_method_line_ids
        if self.payment_method_line_id not in method_lines:
            self.payment_method_line_id = method_lines[:1]

    def action_register_payment(self):
        self.ensure_one()
        invoice = self.invoice_id.exists()
        invoice._check_hotel_operational_invoice_access()
        if invoice.state != 'posted':
            raise UserError(_("Please confirm/post the invoice before registering payment."))
        if invoice.payment_state in ('paid', 'in_payment') or invoice.amount_residual <= 0:
            raise UserError(_("This invoice does not have an open amount to pay."))
        if self.amount <= 0:
            raise UserError(_("Payment amount must be greater than zero."))
        if self.amount - invoice.amount_residual > (invoice.currency_id.rounding or 0.01):
            raise UserError(_("Payment amount cannot exceed the invoice amount due."))
        if self.journal_id.type not in ('bank', 'cash'):
            raise UserError(_("Only cash or bank journals can be used for hotel invoice payment."))
        if self.payment_method_line_id not in self.available_payment_method_line_ids:
            raise UserError(_("Please select a payment method configured on the selected journal."))

        reservation = invoice._get_hotel_invoice_primary_reservation()
        payment_register = self.env['account.payment.register'].sudo().with_context(
            active_model='account.move',
            active_ids=invoice.ids,
        ).create({
            'journal_id': self.journal_id.id,
            'payment_method_line_id': self.payment_method_line_id.id,
            'amount': self.amount,
            'payment_date': self.payment_date,
            'hotel_receipt_number': self.hotel_receipt_number,
            'hotel_reservation_id': reservation.id if reservation else False,
            'folio_id': invoice.hotel_folio_id.id if invoice.hotel_folio_id else False,
            'hotel_business_date': self.payment_date,
        })
        payments = payment_register._create_payments()
        payments = payments.sudo()
        if hasattr(payments, '_compute_hotel_info'):
            payments._compute_hotel_info()
        if hasattr(payments, '_compute_invoice_ref'):
            payments._compute_invoice_ref()
        if hasattr(payments, '_compute_hotel_payment_activity_type'):
            payments._compute_hotel_payment_activity_type()

        for payment in payments:
            if self.hotel_receipt_number:
                payment.hotel_receipt_number = self.hotel_receipt_number
            if reservation:
                payment.message_post(
                    body=_("Hotel invoice payment registered from invoice %s by %s.")
                         % (invoice.name or invoice.display_name, self.env.user.name),
                    subtype_xmlid='mail.mt_note',
                )
                reservation.message_post(
                    body=_("Payment of %s%.2f registered for invoice %s by %s.")
                         % (invoice.currency_id.symbol or '', self.amount, invoice.name or invoice.display_name, self.env.user.name),
                    subtype_xmlid='mail.mt_note',
                )
        return invoice._action_open_hotel_safe_invoice_view(name=_("Customer Invoice"))

class AccountPaymentHotelAudit(models.Model):
    _inherit = 'account.payment'
    hotel_business_date = fields.Date(string="Business Date", default=lambda self: self.env.company.hotel_business_date or fields.Date.context_today(self), index=True)
    is_advance_deposit = fields.Boolean(string="Advance Deposit", default=False, copy=False, index=True)
    voids_advance_deposit_payment_id = fields.Many2one(
        'account.payment',
        string="Voids Advance Deposit Payment",
        copy=False,
        index=True,
        readonly=True,
    )
    advance_deposit_void_payment_ids = fields.One2many(
        'account.payment',
        'voids_advance_deposit_payment_id',
        string="Advance Deposit Void Payments",
        readonly=True,
    )
    destination_account_id = fields.Many2one(
        comodel_name='account.account',
        string='Destination Account',
        store=True,
        readonly=False,
        compute='_compute_destination_account_id',
        domain="[('account_type', 'in', ('asset_receivable', 'liability_payable', 'liability_current', 'liability_non_current')), ('deprecated', '=', False)]",
        check_company=True,
    )

    @api.depends('journal_id', 'partner_id', 'partner_type', 'is_advance_deposit', 'hotel_reservation_id')
    def _compute_destination_account_id(self):
        super()._compute_destination_account_id()
        for pay in self.filtered(lambda payment: payment.is_advance_deposit and payment.hotel_reservation_id):
            deposit_account = pay.hotel_reservation_id.company_id.hotel_advance_deposit_account_id
            if deposit_account:
                pay.destination_account_id = deposit_account

    @api.model_create_multi
    def create(self, vals_list):
        # THE FIX: Empty super() is bulletproof in Python 3!
        payments = super().create(vals_list)
        for pay in payments:
            active_ids = self._context.get('active_ids')
            active_model = self._context.get('active_model')
            if active_model == 'account.move' and active_ids:
                invoices = self.env['account.move'].browse(active_ids)
                for inv in invoices:
                    if inv.invoice_origin:
                        res = self.env['hotel.reservation'].search([('name', '=', inv.invoice_origin)], limit=1)
                        if res:
                            self.env['hotel.posting.journal'].create({
                                'reservation_id': res.id,
                                'journal_type': 'payment',
                                'description': f"Payment Received ({pay.journal_id.name})",
                                'amount': -pay.amount if pay.payment_type == 'inbound' else pay.amount,
                                'business_date': pay.hotel_business_date,
                                'date': pay.create_date or fields.Datetime.now(),
                                'source_order_id': res.sale_order_id.id if res.sale_order_id else False,
                                'source_move_id': inv.id,
                                'source_payment_id': pay.id,
                                'folio_billing_target': inv.hotel_billing_target or 'guest',
                            })
        return payments

    def action_post(self):
        result = super().action_post()
        for pay in self.filtered(lambda payment: payment.is_advance_deposit and payment.hotel_reservation_id):
            amount = -pay.amount if pay.payment_type == 'inbound' else pay.amount
            description = (
                f"Advance Deposit Refunded ({pay.journal_id.name})"
                if pay.payment_type == 'outbound'
                else f"Advance Deposit Received ({pay.journal_id.name})"
            )
            existing_entry = self.env['hotel.posting.journal'].search([
                ('reservation_id', '=', pay.hotel_reservation_id.id),
                ('journal_type', '=', 'payment'),
                ('source_payment_id', '=', pay.id),
            ], limit=1)
            if not existing_entry:
                self.env['hotel.posting.journal'].create({
                    'reservation_id': pay.hotel_reservation_id.id,
                    'journal_type': 'payment',
                    'description': description,
                    'amount': amount,
                    'business_date': pay.hotel_business_date,
                    'date': pay.create_date or fields.Datetime.now(),
                    'source_order_id': pay.hotel_reservation_id.sale_order_id.id if pay.hotel_reservation_id.sale_order_id else False,
                    'source_payment_id': pay.id,
                    'folio_billing_target': 'guest',
                })
            if pay.payment_type == 'inbound':
                pay._send_advance_deposit_receipt_email_safely()
        for pay in self.filtered(lambda payment: payment.state in ('in_process', 'paid') and not payment.is_advance_deposit):
            linked_reservations = self.env['hotel.reservation']
            linked_invoices = pay.reconciled_invoice_ids.filtered(lambda move: move.hotel_folio_id)
            for invoice in linked_invoices:
                linked_reservations |= self.env['hotel.reservation'].search(
                    [('sale_order_id', '=', invoice.hotel_folio_id.id)]
                )
            action_label = _("Payment Registered") if pay.payment_type == 'inbound' else _("Payment Refunded")
            for reservation in linked_reservations:
                reservation._log_exchange_event(
                    action_label,
                    '',
                    _("%s%.2f via %s") % ((reservation.currency_id.symbol or ''), pay.amount, pay.journal_id.display_name),
                    change_type='action',
                    source_document=pay,
                )
        return result

class SaleAdvancePaymentInvHotel(models.TransientModel):
    _inherit = 'sale.advance.payment.inv'

    def create_invoices(self):
        #if self.sale_order_ids.filtered('is_hotel_folio'):
        #    raise UserError(_("Hotel folios must be invoiced from the reservation using the hotel billing workflow."))
        return super().create_invoices()

    def _prepare_down_payment_invoice_line_values(self, order, so_line, account):
        values = super()._prepare_down_payment_invoice_line_values(order, so_line, account)
        if not order.is_hotel_folio or not order.company_id.hotel_deposit_tax_proportional or so_line.tax_ids:
            return values

        reservation = order.hotel_reservation_ids.filtered(
            lambda rec: not rec.is_desk_folio and rec.folio_type == 'guest'
        )[:1]
        if not reservation:
            return values

        taxes = reservation._get_advance_deposit_taxes()
        if taxes:
            values.update({
                'tax_ids': [Command.set(taxes.ids)],
                'price_unit': reservation._get_tax_inclusive_deposit_price_unit(values['price_unit'], taxes),
            })
        return values

class SaleOrderLineHotelAudit(models.Model):
    _inherit = 'sale.order.line'
    hotel_business_date = fields.Date(string="Business Date", default=lambda self: self.env.company.hotel_business_date or fields.Date.context_today(self))
    hotel_reservation_id = fields.Many2one('hotel.reservation', string="Hotel Reservation", index=True, copy=False)
    deposit_invoice_id = fields.Many2one('account.move', string="Advance Deposit Invoice", index=True, copy=False, readonly=True)
    source_payment_id = fields.Many2one('account.payment', string="Source Deposit Payment", index=True, copy=False, readonly=True)
    is_night_audit_charge = fields.Boolean(string="Night Audit Charge", default=False, index=True, copy=False)
    billing_target = fields.Selection(
        [('guest', 'Guest'), ('company', 'Company')],
        string="Billing Target",
        default='guest',
        copy=True,
        help="Controls whether this folio line invoices the guest directly or routes to the City Ledger company.",
    )
    billing_target_display = fields.Char(
        string="Bill To",
        compute='_compute_billing_target_display',
        readonly=True,
    )

    def _is_hotel_operational_folio_line(self):
        self.ensure_one()
        order = self.order_id
        return bool(
            self.hotel_reservation_id
            or order.is_hotel_folio
            or order.hotel_reservation_ids
            or order.hotel_group_master_ids
        )

    def _action_launch_stock_rule(self, *, previous_product_uom_qty=False):
        hotel_lines = self.filtered(lambda line: line._is_hotel_operational_folio_line())
        regular_lines = self - hotel_lines
        if regular_lines:
            return super(SaleOrderLineHotelAudit, regular_lines)._action_launch_stock_rule(
                previous_product_uom_qty=previous_product_uom_qty,
            )
        return True

    @api.depends(
        'billing_target',
        'hotel_reservation_id.city_ledger_id',
        'hotel_reservation_id.city_ledger_id.name',
        'order_id.hotel_reservation_ids.city_ledger_id',
        'order_id.hotel_reservation_ids.city_ledger_id.name',
        'order_id.hotel_group_master_ids.city_ledger_id',
        'order_id.hotel_group_master_ids.city_ledger_id.name',
    )
    def _compute_billing_target_display(self):
        for line in self:
            if line.billing_target != 'company':
                line.billing_target_display = _('Guest')
                continue

            reservation = line._get_hotel_billing_reservation()
            company = reservation.city_ledger_id if reservation else self.env['res.partner']
            if not company and line.order_id.hotel_group_master_ids:
                company = line.order_id.hotel_group_master_ids[:1].city_ledger_id
            if not company and line.order_id.hotel_reservation_ids:
                company = line.order_id.hotel_reservation_ids.filtered('city_ledger_id')[:1].city_ledger_id

            line.billing_target_display = company.name if company else _('Company')

    def _get_hotel_billing_reservation(self):
        self.ensure_one()
        if self.hotel_reservation_id:
            return self.hotel_reservation_id

        reservations = self.order_id.hotel_reservation_ids.filtered(lambda res: res.state != 'cancel')
        if len(reservations) == 1:
            return reservations

        non_desk_reservations = reservations.filtered(lambda res: not res.is_desk_folio)
        if len(non_desk_reservations) == 1:
            return non_desk_reservations

        return reservations[:1]

    def _get_resolved_billing_target(self):
        self.ensure_one()
        if self.billing_target:
            return self.billing_target

        reservation = self._get_hotel_billing_reservation()
        if reservation:
            return reservation._compute_default_billing_target(self)
        return 'guest'

    def _hotel_is_new_invoiceable_transaction(self):
        self.ensure_one()
        # 1. Trust standard Odoo: If there is no qty left to invoice, block it.
        if self.display_type or self.qty_to_invoice <= 0:
            return False
        if self.is_downpayment or getattr(self, 'deposit_invoice_id', False):
            return False
        
        # 2. ALLOW REVERSALS: Only block new invoices if there is an active DRAFT pending.
        # If the invoice was Reversed, qty_to_invoice > 0 will allow it to proceed naturally.
        pending_drafts = self._get_invoice_lines().filtered(
            lambda inv_line: inv_line.move_id.state == 'draft'
            and inv_line.move_id.move_type in ('out_invoice', 'out_refund')
        )
        return not bool(pending_drafts)

    def _hotel_assign_missing_billing_targets(self):
        for line in self.filtered(lambda l: not l.display_type and not l.billing_target):
            line.with_context(skip_hotel_billing_audit=True).write({
                'billing_target': line._get_resolved_billing_target(),
            })
        return True

    @api.model_create_multi
    def create(self, vals_list):
        for vals in vals_list:
            if vals.get('display_type') or not vals.get('product_id'):
                continue

            product = self.env['product.product'].browse(vals['product_id'])
            if not product.exists():
                continue

            if vals.get('order_id') and not vals.get('hotel_reservation_id'):
                reservations = self.env['hotel.reservation'].search([
                    ('sale_order_id', '=', vals['order_id']),
                    ('is_desk_folio', '=', False),
                    ('state', '!=', 'cancel'),
                ], limit=2)
                if len(reservations) == 1:
                    vals['hotel_reservation_id'] = reservations.id

            vals.setdefault('product_uom_id', product.uom_id.id)
            vals.setdefault('product_template_id', product.product_tmpl_id.id)
            vals.setdefault('name', product.get_product_multiline_description_sale() or product.display_name)

            if not vals.get('billing_target'):
                reservation = self.env['hotel.reservation'].browse(vals.get('hotel_reservation_id'))
                if not reservation and vals.get('order_id'):
                    order = self.env['sale.order'].browse(vals['order_id'])
                    reservations = order.hotel_reservation_ids.filtered(lambda res: res.state != 'cancel')
                    if len(reservations) == 1:
                        reservation = reservations
                    else:
                        non_desk_reservations = reservations.filtered(lambda res: not res.is_desk_folio)
                        reservation = non_desk_reservations[:1] or reservations[:1]
                vals['billing_target'] = reservation._compute_default_billing_target(vals) if reservation else 'guest'

        lines = super().create(vals_list)
        for line in lines:
            res = line.hotel_reservation_id
            if not res and line.order_id:
                reservations = self.env['hotel.reservation'].search([('sale_order_id', '=', line.order_id.id)], limit=2)
                if len(reservations) == 1:
                    res = reservations

            if res and line.price_unit > 0:
                j_type = 'system' if line.is_night_audit_charge or 'Room Charge' in (line.name or '') else 'charge'
                safe_amount = line.price_total
                
                self.env['hotel.posting.journal'].create({
                    'reservation_id': res.id,
                    'journal_type': j_type,
                    'description': f"Added Charge: {line.name}",
                    'amount': safe_amount,
                    'business_date': line.hotel_business_date,
                    'date': line.create_date or fields.Datetime.now(),
                    'source_order_id': line.order_id.id,
                    'source_sale_line_id': line.id,
                    'folio_billing_target': line.billing_target or line._get_resolved_billing_target(),
                })
        return lines

    def unlink(self):
        for line in self:
            res = self.env['hotel.reservation'].search([('sale_order_id', '=', line.order_id.id)], limit=1)
            if res and line.price_unit > 0:
                self.env['hotel.posting.journal'].create({
                    'reservation_id': res.id,
                    'journal_type': 'system',
                    'description': f"Deleted Charge: {line.name}",
                    'amount': -line.price_total,
                    'business_date': self.env.company.hotel_business_date or fields.Date.context_today(self),
                    'date': fields.Datetime.now(),
                    'source_order_id': line.order_id.id,
                    'folio_billing_target': line.billing_target or line._get_resolved_billing_target(),
                })
        return super().unlink()

    # ==========================================
    # ADD THE SCISSORS TRIGGER HERE
    # ==========================================
    def action_open_split_wizard(self):
        self.ensure_one()
        
        # 1. Build the VIP List right here, before the popup opens!
        partners = self.order_id.partner_id
        reservations = self.env['hotel.reservation'].search([('sale_order_id', '=', self.order_id.id), ('state', '!=', 'cancel')])
        for res in reservations:
            if hasattr(res, 'accompanying_guest_ids') and res.accompanying_guest_ids:
                partners |= res.accompanying_guest_ids
            if hasattr(res, 'city_ledger_id') and res.city_ledger_id:
                partners |= res.city_ledger_id
                
        # 2. Open the wizard and hand it the EXACT price and the EXACT guest list
        return {
            'name': 'Split Charge',
            'type': 'ir.actions.act_window',
            'res_model': 'hotel.split.line.wizard',
            'view_mode': 'form',
            'target': 'new',
            'context': {
                'default_line_id': self.id,
                'default_original_total': self.price_total, # Forces the real total
                'allowed_split_partner_ids': partners.ids,  # Forces the VIP list
            }
        }
    # =========================================================
#  POS INTEGRATION (SHOW ROOM NUMBER ON GUEST PROFILE)
# =========================================================
class ResPartnerHotel(models.Model):
    _inherit = 'res.partner'

    hotel_room_name = fields.Char(string="Current Room", compute="_compute_hotel_room_name", store=False)

    @api.model
    def _load_pos_data_fields(self, config):
        fields_to_load = super()._load_pos_data_fields(config)
        return [*fields_to_load, 'hotel_room_name']

    def _compute_hotel_room_name(self):
        for partner in self:
            res = self.env['hotel.reservation'].search([
                ('partner_id', '=', partner.id),
                ('state', 'in', ['checkin', 'checkout_hold'])
            ], limit=1)
            if res and res.room_id:
                partner.hotel_room_name = f"Room {res.room_id.name}"
            else:
                partner.hotel_room_name = False

# =========================================================
#  PHASE 2: GROUP MASTER BOOKING ENGINE 
# =========================================================
class HotelGroupMaster(models.Model):
    _name = 'hotel.group.master'
    _description = 'Group Master Block'
    _inherit = ['mail.thread', 'mail.activity.mixin']
    _order = 'arrival_date desc'

    name = fields.Char(string='Group Code / Name', required=True, copy=False, default=lambda self: _('New Group'))
    partner_id = fields.Many2one('res.partner', string='Company / Agent', required=True, tracking=True)
    city_ledger_id = fields.Many2one('res.partner', string="Company (City Ledger)", domain="[('is_company', '=', True)]")
    arrival_date = fields.Date(string='Arrival', required=True, tracking=True)
    departure_date = fields.Date(string='Departure', required=True, tracking=True)
    rate_plan_id = fields.Many2one('hotel.rate.plan', string='Master Rate Plan', required=True)
    override_rates = fields.Boolean(string="Lock Group Rates", default=True, tracking=True)
    
    state = fields.Selection([
        ('draft', 'Draft'),
        ('generated', 'Rooms Generated'),
        ('confirm', 'Confirmed'),
        ('assigned', 'Rooms Assigned'),
        ('checkin', 'In-House'),
        ('done', 'Checked Out'),
        ('cancel', 'Cancelled')
    ], string='Status', default='draft', tracking=True)

    room_line_ids = fields.One2many('hotel.group.room.line', 'group_id', string='Room Blocks')
    # 1. This domain strictly hides the PM from the "Generated Reservations" tab!
    reservation_ids = fields.One2many('hotel.reservation', 'group_id', string='Generated Reservations', domain="[('is_desk_folio', '=', False)]")
    checkout_guest_total = fields.Integer(string="Rooms in Group", compute='_compute_checkout_progress')
    checkout_guest_completed = fields.Integer(string="Checked Out", compute='_compute_checkout_progress')
    checkout_guest_pending = fields.Integer(string="Pending Checkout", compute='_compute_checkout_progress')
    checkout_progress = fields.Float(string="Checkout Progress", compute='_compute_checkout_progress')
    
    # 2. This gives the PM its own dedicated shortcut link
    paymaster_id = fields.Many2one('hotel.reservation', string='Group Paymaster (PM)', compute='_compute_paymaster')

    company_id = fields.Many2one(
        'res.company',
        string='Company',
        default=lambda self: self.env.company,
    )
    currency_id = fields.Many2one(
        'res.currency',
        related='company_id.currency_id',
        readonly=True,
    )

    group_deposit_received = fields.Monetary(
        string="Group Deposit Received",
        compute="_compute_group_financial_summary",
        currency_field="currency_id",
    )
    group_deposit_remaining = fields.Monetary(
        string="Group Deposit Remaining",
        compute="_compute_group_financial_summary",
        currency_field="currency_id",
    )
    group_total_charges = fields.Monetary(
        string="Group Total Charges",
        compute="_compute_group_financial_summary",
        currency_field="currency_id",
    )
    group_balance_due = fields.Monetary(
        string="Group Balance Due",
        compute="_compute_group_financial_summary",
        currency_field="currency_id",
    )
    group_credit_balance = fields.Monetary(
        string="Group Credit Balance",
        compute="_compute_group_financial_summary",
        currency_field="currency_id",
    )

    def _compute_group_financial_summary(self):
        AccountMove = self.env['account.move'].sudo()

        for group in self:
            paymaster = group.paymaster_id or self.env['hotel.reservation'].sudo().search([
                ('group_id', '=', group.id),
                ('is_desk_folio', '=', True),
            ], limit=1)

            reservations = (group.reservation_ids | paymaster).exists()

            deposit_received = 0.0
            deposit_remaining = 0.0
            total_charges = 0.0
            balance_due = 0.0
            credit_balance = 0.0

            for reservation in reservations:
                deposit_received += reservation.sudo()._get_posted_advance_deposit_amount()

            # Find invoice by reservation numbers inside invoice lines.
            # Example invoice lines contain: RES/2026/0020, RES/2026/0021, RES/2026/0022.
            child_reservations = group.reservation_ids.sudo().filtered(lambda r: not r.is_desk_folio)
            reservation_names = [name for name in child_reservations.mapped('name') if name]

            if paymaster and paymaster.name:
                reservation_names.append(paymaster.name)

            invoices = AccountMove.browse()

            # Directly linked invoices, if the custom field exists.
            if 'hotel_group_master_id' in AccountMove._fields:
                invoices |= AccountMove.search([
                    ('hotel_group_master_id', '=', group.id),
                    ('move_type', '=', 'out_invoice'),
                    ('state', '!=', 'cancel'),
                ])

            # Fallback: search recent invoices and match invoice line text.
            candidate_invoices = AccountMove.search([
                ('move_type', '=', 'out_invoice'),
                ('state', '!=', 'cancel'),
            ], order='id desc', limit=300)

            for invoice in candidate_invoices:
                invoice_text = " ".join(invoice.invoice_line_ids.mapped('name') or [])
                if any(res_name in invoice_text for res_name in reservation_names):
                    invoices |= invoice

            if invoices:
                deposit_applied_total = 0.0

                for invoice in invoices:
                    deposit_lines = invoice.invoice_line_ids.filtered(
                        lambda line: getattr(line, 'is_advance_deposit_application', False)
                    )

                    if not deposit_lines and paymaster:
                        deposit_account = paymaster._get_advance_deposit_liability_account()
                        if deposit_account:
                            deposit_lines = invoice.invoice_line_ids.filtered(
                                lambda line: line.account_id == deposit_account and line.price_total < 0
                            )

                    deposit_applied = abs(sum(deposit_lines.mapped('price_total')))
                    deposit_applied_total += deposit_applied

                    # invoice.amount_total already includes the negative deposit line.
                    # Add deposit back to show the real gross group charge.
                    total_charges += invoice.amount_total + deposit_applied

                    # Draft invoice: amount_total is remaining due after deposit line.
                    # Posted invoice: amount_residual is safer.
                    if invoice.state == 'posted':
                        balance_due += invoice.amount_residual
                    else:
                        balance_due += invoice.amount_total

                deposit_remaining = max(deposit_received - deposit_applied_total, 0.0)
                credit_balance = max(deposit_remaining - balance_due, 0.0)

            else:
                # Before invoice exists, use operational folio values.
                for reservation in reservations:
                    calc_reservation = reservation.sudo()
                    deposit_remaining += calc_reservation._get_deposit_balance_amount()
                    total_charges += calc_reservation.guest_total_charges or 0.0
                    balance_due += calc_reservation.guest_balance_due or 0.0
                    credit_balance += calc_reservation.guest_credit_balance or 0.0

            group.group_deposit_received = deposit_received
            group.group_deposit_remaining = deposit_remaining
            group.group_total_charges = total_charges
            group.group_balance_due = balance_due
            group.group_credit_balance = credit_balance

    def _compute_paymaster(self):
        for group in self:
            pm = self.env['hotel.reservation'].search([
                ('group_id', '=', group.id), 
                ('is_desk_folio', '=', True)
            ], limit=1)
            group.paymaster_id = pm.id if pm else False

    @api.depends('reservation_ids.state', 'reservation_ids.is_desk_folio')
    def _compute_checkout_progress(self):
        for group in self:
            reservations = group.reservation_ids.filtered(
                lambda reservation: not reservation.is_desk_folio
                and reservation.state not in ['cancel', 'noshow', 'blocked']
            )
            completed = reservations.filtered(lambda reservation: reservation.state == 'checkout')
            pending = reservations.filtered(lambda reservation: reservation.state in ['checkin', 'checkout_hold'])
            group.checkout_guest_total = len(reservations)
            group.checkout_guest_completed = len(completed)
            group.checkout_guest_pending = len(pending)
            group.checkout_progress = (100.0 * len(completed) / len(reservations)) if reservations else 0.0

    folio_id = fields.Many2one('sale.order', string="Master Folio", readonly=True)
    
    # Drag-and-Drop Rooming List Fields
    rooming_list_ids = fields.One2many('hotel.group.rooming.list', 'group_id', string='Guest Pool')
    import_names_text = fields.Text(string="Quick Import (Paste Names)")

    @api.model_create_multi
    def create(self, vals_list):
        for vals in vals_list:
            if vals.get('name', _('New Group')) == _('New Group'): 
                vals['name'] = self.env['ir.sequence'].next_by_code('hotel.group.master') or 'GRP-' + str(fields.Date.today().year)
        return super().create(vals_list)

    def action_load_availability_grid(self):
        for group in self:
            if group.state != 'draft':
                continue
            group.room_line_ids = [(5, 0, 0)]
            lines = []
            room_types = self.env['hotel.room.type'].search([])
            
            for rtype in room_types:
                current_rate = 0.0
                if group.rate_plan_id:
                    domain = [
                        ('plan_id', '=', group.rate_plan_id.id),
                        ('room_type_id', '=', rtype.id),
                        '|', ('date_start', '=', False), ('date_start', '<=', group.arrival_date)
                    ]
                    rule = self.env['hotel.rate.plan.line'].search(domain, order='date_start desc', limit=1)
                    current_rate = rule.price if rule else 0.0
                    
                total_rooms = self.env['hotel.room'].search_count([('room_type_id', '=', rtype.id)])
                booked_rooms = self.env['hotel.reservation'].search_count([
                    ('room_type_id', '=', rtype.id),
                    ('state', 'in', ['draft', 'confirm', 'checkin', 'checkout_hold']),
                    ('checkin_date', '<', group.departure_date),
                    ('checkout_date', '>', group.arrival_date)
                ])
                
                other_blocks = self.env['hotel.group.room.line'].search([
                    ('room_type_id', '=', rtype.id),
                    ('group_id.state', 'in', ['draft', 'confirm']),
                    ('group_id.arrival_date', '<', group.departure_date),
                    ('group_id.departure_date', '>', group.arrival_date),
                    ('group_id', '!=', group.id)
                ])
                total_blocked = sum(other_blocks.mapped('qty_blocked'))
                
                available_qty = max(0, total_rooms - booked_rooms - total_blocked)
                
                lines.append((0, 0, {
                    'room_type_id': rtype.id,
                    'current_rate': current_rate,
                    'available_qty': available_qty,
                    'qty_blocked': 0
                }))
                
            group.room_line_ids = lines

    def _ensure_group_paymaster(self):
        self.ensure_one()

        pm = self.env['hotel.reservation'].search([
            ('group_id', '=', self.id),
            ('is_desk_folio', '=', True),
        ], limit=1)

        if pm:
            return pm

        desk_type = self.env['hotel.reservation']._get_or_create_desk_folio_room_type()

        checkin_date = self.arrival_date or fields.Date.context_today(self)
        checkout_date = self.departure_date or (checkin_date + timedelta(days=1))
        if checkout_date <= checkin_date:
            checkout_date = checkin_date + timedelta(days=1)

        pm = self.env['hotel.reservation'].create({
            'is_desk_folio': True,
            'group_id': self.id,
            'partner_id': self.partner_id.id,
            'city_ledger_id': self.city_ledger_id.id if self.city_ledger_id else False,
            'billing_routing': self.billing_routing,
            'room_type_id': desk_type.id,
            'checkin_date': checkin_date,
            'checkout_date': checkout_date,
            'adults': 0,
            'is_manual_rate': True,
            'manual_rate': 0.0,
            'state': 'draft',
        })

        return pm

    def _ensure_group_paymaster(self):
        self.ensure_one()

        paymaster = self.env['hotel.reservation'].search([
            ('group_id', '=', self.id),
            ('is_desk_folio', '=', True),
        ], limit=1)

        if paymaster:
            return paymaster

        desk_type = self.env['hotel.reservation']._get_or_create_desk_folio_room_type()

        checkin_date = self.arrival_date or fields.Date.context_today(self)
        checkout_date = self.departure_date or (checkin_date + timedelta(days=1))
        if checkout_date <= checkin_date:
            checkout_date = checkin_date + timedelta(days=1)

        paymaster = self.env['hotel.reservation'].create({
            'is_desk_folio': True,
            'group_id': self.id,
            'partner_id': self.partner_id.id,
            'city_ledger_id': self.city_ledger_id.id if self.city_ledger_id else False,
            'billing_routing': self.billing_routing,
            'room_type_id': desk_type.id,
            'checkin_date': checkin_date,
            'checkout_date': checkout_date,
            'adults': 0,
            'is_manual_rate': True,
            'manual_rate': 0.0,
            'state': 'draft',
        })

        return paymaster

    def action_create_group_deposit(self):
        self.ensure_one()

        if self.state == 'draft':
            raise UserError(_("Please confirm and generate group rooms before receiving a group deposit."))

        paymaster = self._ensure_group_paymaster()

        if not paymaster.partner_id:
            raise UserError(_("The Group Paymaster has no customer/partner. Please check Company / Agent."))

        if not paymaster._get_advance_deposit_liability_account():
            raise UserError(_("Please configure the Advance Deposit Liability Account in Hotel Settings before registering group deposits."))

        return {
            'name': _('Register Group Deposit'),
            'type': 'ir.actions.act_window',
            'res_model': 'hotel.deposit.wizard',
            'view_mode': 'form',
            'target': 'new',
            'context': {
                'active_model': 'hotel.reservation',
                'active_id': paymaster.id,
                'active_ids': [paymaster.id],
                'default_reservation_id': paymaster.id,
                'default_business_date': self.env.company.hotel_business_date or fields.Date.context_today(self),
                'group_deposit': True,
            },
        }       

    def action_confirm_and_generate(self):
        for group in self:
            if group.state != 'draft': continue
            
            rooms_to_book = group.room_line_ids.filtered(lambda l: l.qty_blocked > 0)
            if not rooms_to_book:
                raise ValidationError("You must enter a quantity in the grid to block at least one room!")

            if not group.folio_id:
                folio = self.env['sale.order'].create({
                    'partner_id': group.partner_id.id, 
                    'reference': f"Group Master: {group.name}", 
                    'date_order': fields.Datetime.now()
                })
                group.folio_id = folio.id
                folio._ensure_hotel_folio_confirmed()

            for line in rooms_to_book:
                for _ in range(line.qty_blocked):
                    # 1. Build the base reservation
                    new_res = self.env['hotel.reservation'].create({
                        'group_id': group.id,
                        'partner_id': group.partner_id.id,  
                        'room_type_id': line.room_type_id.id,
                        'checkin_date': group.arrival_date,
                        'checkout_date': group.departure_date,
                        'rate_plan_id': group.rate_plan_id.id,
                        'state': 'draft', 
                        'adults': 2, 
                    })
                    
                    # 2. Force custom rate
                    if group.override_rates:
                        new_res.write({
                            'is_manual_rate': True, 
                            'manual_rate': line.current_rate
                        })
            
            # === PIPELINE UPDATE: Move to Generated Stage ===
            group.state = 'generated'
            
    def action_auto_assign_rooms(self):
        for group in self:
            assigned_rooms = []
            unassigned_reservations = group.reservation_ids.filtered(lambda r: not r.room_id)
            if not unassigned_reservations:
                raise ValidationError("All reservations already have a room assigned!")

            for res in unassigned_reservations:
                taken_reservations = self.env['hotel.reservation'].search([
                    ('state', 'in', ['draft', 'confirm', 'checkin', 'checkout_hold']),
                    ('checkin_date', '<', res.checkout_date),
                    ('checkout_date', '>', res.checkin_date),
                    ('room_id', '!=', False),
                    ('id', '!=', res.id) 
                ])
                taken_room_ids = taken_reservations.mapped('room_id.id') + assigned_rooms
                
                domain = [('room_type_id', '=', res.room_type_id.id)]
                if taken_room_ids:
                    domain.append(('id', 'not in', taken_room_ids))
                    
                available_room = self.env['hotel.room'].search(domain, limit=1)
                if available_room:
                    res.room_id = available_room.id
                    assigned_rooms.append(available_room.id)
            
            # === PIPELINE UPDATE: Move to Assigned Stage ===
            group.state = 'assigned'

    def action_confirm_reservations(self):
        for group in self:
            for res in group.reservation_ids:
                if res.state == 'draft':
                    res.state = 'confirm'
            
            # === PIPELINE UPDATE: Move to Confirm Stage ===
            group.state = 'confirm'

    def action_cancel_group(self):
        for group in self:
            # 1. Loop through all reservations and cancel them
            for res in group.reservation_ids:
                if res.state in ['draft', 'confirm']: 
                    if hasattr(res, 'action_cancel'):
                        res.action_cancel()
                    else:
                        res.state = 'cancel'
            
            # 2. Cancel the Group Master itself
            group.state = 'cancel'
            
    def action_import_names(self):
        for group in self:
            if not group.import_names_text:
                continue
            names = group.import_names_text.split('\n')
            for name in names:
                if name.strip():
                    partner = self.env['res.partner'].create({'name': name.strip()})
                    self.env['hotel.group.rooming.list'].create({
                        'group_id': group.id,
                        'partner_id': partner.id,
                        'reservation_id': False 
                    })
            group.import_names_text = ""

    # === NEW: GROUP ROUTING & CHECK-IN ===
    billing_routing = fields.Selection([
        ('guest', 'Guest Pays All'),
        ('master_room', 'Master Pays Room, Guest Pays Incidentals'),
        ('master_all', 'Master Pays All')
    ], string="Billing Routing", default='master_room', tracking=True)

    
    def action_mass_group_checkin(self):
        for group in self:
            # Find all rooms that belong to this group that are NOT checked in or cancelled
            reservations = self.env['hotel.reservation'].search([
                ('group_id', '=', group.id),
                ('is_desk_folio', '=', False),
                ('state', 'not in', ['checkin', 'checkout_hold', 'checkout', 'noshow', 'cancel', 'blocked'])
            ])

            if not reservations:
                raise UserError("There are no pending reservations to check in for this group.")

            # AUTOMATIC PAYMASTER (DESK FOLIO) CREATION WITH SAFETY LOCK
            existing_pm = self.env['hotel.reservation'].search([
                ('is_desk_folio', '=', True),
                ('group_id', '=', group.id) 
            ], limit=1)
            
            if not existing_pm:
                desk_type = self.env['hotel.reservation']._get_or_create_desk_folio_room_type()

                pm_vals = {
                    'is_desk_folio': True,
                    'group_id': group.id,
                    'partner_id': group.partner_id.id if hasattr(group, 'partner_id') else False,
                    'city_ledger_id': group.city_ledger_id.id if hasattr(group, 'city_ledger_id') and group.city_ledger_id else False,
                    'billing_routing': group.billing_routing,
                    'room_type_id': desk_type.id,  # This will never be False/Null now!
                    'checkin_date': fields.Date.context_today(self),
                    'checkout_date': fields.Date.context_today(self) + timedelta(days=365),
                    'adults': 0,
                    'is_manual_rate': True,
                    'manual_rate': 0.0,
                    'state': 'draft'
                }
                self.env['hotel.reservation'].create(pm_vals)

            for res in reservations:
                res.write({'billing_routing': group.billing_routing})
                if hasattr(res, 'action_checkin'):
                    res.action_checkin()
                else:
                    res.write({'state': 'checkin'})
            
            # === PIPELINE UPDATE: Move to In-House Stage ===
            group.state = 'checkin'

    def _get_active_checkout_reservations(self):
        self.ensure_one()
        return self.env['hotel.reservation'].search([
            ('group_id', '=', self.id),
            ('is_desk_folio', '=', False),
            ('state', 'in', ['checkin', 'checkout_hold']),
        ], order='room_id, name')

    def _validate_group_checkout_balances(self, guest_reservations):
        self.ensure_one()
        reservations_to_validate = guest_reservations | self.paymaster_id
        for reservation in reservations_to_validate:
            outstanding_balance = reservation._get_checkout_outstanding_balance()
            if outstanding_balance <= 0.01:
                continue
            if reservation.is_desk_folio:
                if reservation.city_ledger_id:
                    raise UserError(
                        _("Cannot check out group: the master folio still has guest-routed charges of %.2f. "
                          "Please review folio routing before checkout.") % outstanding_balance
                    )
                raise UserError(
                    _("Cannot check out group: the master folio has an unpaid balance of %.2f. "
                      "Please settle the master folio first.") % outstanding_balance
                )
            room_name = reservation.room_id.name if reservation.room_id else _('Unassigned')
            raise UserError(
                _("Cannot check out group: guest %s (Room %s) has an unpaid incidental balance of %.2f. "
                  "Please settle the personal folio first.")
                % (reservation.partner_id.name, room_name, outstanding_balance)
            )

    def _post_group_checkout_activity(self, reservation):
        self.ensure_one()
        self.message_post(
            body=Markup("<b>Checkout Progress:</b> Room %s - %s has been checked out.")
            % (
                Markup.escape(reservation.room_id.name if reservation.room_id else _("Unassigned")),
                Markup.escape(reservation.partner_id.name or ""),
            ),
            subtype_xmlid='mail.mt_note',
        )

    def _finish_group_checkout_if_complete(self):
        self.ensure_one()
        if not self._get_active_checkout_reservations():
            self.state = 'done'
            self.message_post(
                body=_("Group checkout completed. All active guest rooms were released and checkout balances were validated."),
                subtype_xmlid='mail.mt_note',
            )

    def action_checkout_next_room(self):
        self.ensure_one()
        active_reservations = self._get_active_checkout_reservations()
        if not active_reservations:
            raise UserError(_("There are no active reservations to check out for this group."))

        next_reservation = active_reservations[:1]
        self._validate_group_checkout_balances(next_reservation)
        next_reservation.action_checkout()
        self._post_group_checkout_activity(next_reservation)
        self._finish_group_checkout_if_complete()
        return {'type': 'ir.actions.client', 'tag': 'reload'}

    def _get_required_group_paymaster(self):
        self.ensure_one()
        paymaster = self.paymaster_id or self.env['hotel.reservation'].search([
            ('group_id', '=', self.id),
            ('is_desk_folio', '=', True),
        ], limit=1)

        if not paymaster:
            raise UserError(_("No Group Paymaster / Desk Folio found. Please register a group deposit or check in the group first."))

        return paymaster

    def action_open_group_paymaster(self):
        self.ensure_one()
        paymaster = self._get_required_group_paymaster()
        return {
            'name': _('Group Paymaster'),
            'type': 'ir.actions.act_window',
            'res_model': 'hotel.reservation',
            'res_id': paymaster.id,
            'view_mode': 'form',
            'target': 'current',
        }

    def action_create_group_invoice(self):
        self.ensure_one()

        if self.state != 'checkin':
            raise UserError(_("Group invoice can be created only after the group is checked in."))

        paymaster = self._get_required_group_paymaster()

        if not paymaster.sale_order_id:
            paymaster.action_create_folio()

        existing_invoices = paymaster._get_folio_customer_invoices()

        action = paymaster.action_create_invoice_from_reservation()

        new_invoices = paymaster._get_folio_customer_invoices() - existing_invoices

        # If the action directly opens an invoice, capture it.
        if action and action.get('res_model') == 'account.move' and action.get('res_id'):
            new_invoices |= self.env['account.move'].browse(action['res_id'])

        # Fallback: find newest draft invoice for this paymaster sale order.
        if not new_invoices and paymaster.sale_order_id:
            new_invoices = self.env['account.move'].search([
                ('move_type', '=', 'out_invoice'),
                ('state', '!=', 'cancel'),
                '|',
                ('invoice_origin', '=', paymaster.sale_order_id.name),
                ('invoice_line_ids.sale_line_ids.order_id', '=', paymaster.sale_order_id.id),
            ], order='id desc', limit=1)

        # Tag invoice to this group so Group Summary can find it directly.
        if new_invoices:
            new_invoices.sudo().write({'hotel_group_master_id': self.id})

        draft_invoices = new_invoices.filtered(lambda inv: inv.state == 'draft')

        if draft_invoices and paymaster._get_deposit_balance_amount() > 0:
            paymaster._apply_advance_deposit_to_invoices(draft_invoices)

        if hasattr(paymaster, '_refresh_operational_folio_status'):
            paymaster._refresh_operational_folio_status()
        if hasattr(paymaster, '_compute_folio_status'):
            paymaster._compute_folio_status()

        return action

    def action_sync_group_invoice_financials(self):
        AccountMove = self.env['account.move'].sudo()

        for group in self:
            paymaster = group.paymaster_id or self.env['hotel.reservation'].sudo().search([
                ('group_id', '=', group.id),
                ('is_desk_folio', '=', True),
            ], limit=1)

            child_names = group.reservation_ids.sudo().filtered(
                lambda r: not r.is_desk_folio
            ).mapped('name')

            invoices = AccountMove.browse()

            # 1) Invoices from paymaster folio
            if paymaster:
                invoices |= paymaster._get_folio_customer_invoices().sudo()

            # 2) Invoices from paymaster sale order
            if paymaster and paymaster.sale_order_id:
                invoices |= paymaster.sale_order_id.invoice_ids.sudo()

            # 3) Invoices that contain child reservation numbers in invoice line text
            for res_name in child_names:
                invoices |= AccountMove.search([
                    ('move_type', '=', 'out_invoice'),
                    ('state', '!=', 'cancel'),
                    ('invoice_line_ids.name', 'ilike', res_name),
                ])

            invoices = invoices.filtered(
                lambda inv: inv.move_type == 'out_invoice' and inv.state != 'cancel'
            )

            if not invoices:
                raise UserError(_("No invoice found for this group. Please create the group invoice first."))

            if 'hotel_group_master_id' in AccountMove._fields:
                invoices.write({'hotel_group_master_id': group.id})

            if paymaster:
                if hasattr(paymaster, '_refresh_operational_folio_status'):
                    paymaster._refresh_operational_folio_status()
                if hasattr(paymaster, '_compute_folio_status'):
                    paymaster._compute_folio_status()

        return {
            'type': 'ir.actions.client',
            'tag': 'display_notification',
            'params': {
                'title': _('Group Invoice Synced'),
                'message': _('Existing group invoice has been linked to this group. Please refresh the group screen.'),
                'type': 'success',
                'sticky': False,
            }
        }


    def action_mass_group_checkout(self):
        for group in self:
            active_reservations = group._get_active_checkout_reservations()
            if not active_reservations:
                raise UserError(_("There are no active reservations to check out for this group."))

            # Check the paymaster as well as every active guest before making any state change.
            group._validate_group_checkout_balances(active_reservations)
            for reservation in active_reservations:
                reservation.action_checkout()
                group._post_group_checkout_activity(reservation)
            group._finish_group_checkout_if_complete()



class HotelGroupRoomLine(models.Model):
    _name = 'hotel.group.room.line'
    _description = 'Group Room Block Line'

    group_id = fields.Many2one('hotel.group.master', string="Group Master", ondelete='cascade')
    room_type_id = fields.Many2one('hotel.room.type', string="Room Type", required=True)
    current_rate = fields.Float(string="Current Rate")
    available_qty = fields.Integer(string="Available")
    qty_blocked = fields.Integer(string="Qty to Block", default=0)
    
    @api.constrains('qty_blocked', 'available_qty')
    def _check_qty(self):
        for line in self:
            if line.qty_blocked > line.available_qty:
                raise ValidationError(f"Overbooking Alert! You cannot block {line.qty_blocked} {line.room_type_id.name}s. Only {line.available_qty} are available.")


class HotelGroupRoomingList(models.Model):
    _name = 'hotel.group.rooming.list'
    _description = 'Group Rooming List'

    group_id = fields.Many2one('hotel.group.master', string="Group Master", ondelete='cascade')
    partner_id = fields.Many2one('res.partner', string="Guest Name", required=True)
    reservation_id = fields.Many2one('hotel.reservation', string="Assigned Room", domain="[('group_id', '=', group_id)]", group_expand='_read_group_reservation_id')

    group_folio_role = fields.Selection(
        related='reservation_id.group_folio_role',
        readonly=True,
    )

    rooming_board_label = fields.Char(
        related='reservation_id.rooming_board_label',
        readonly=True,
    )

    is_desk_folio = fields.Boolean(
        related='reservation_id.is_desk_folio',
        readonly=True,
    )

    group_id = fields.Many2one(
        related='reservation_id.group_id',
        readonly=True,
    )

    @api.model
    def _read_group_reservation_id(self, reservations, domain, order=None):
        group_id = self._context.get('default_group_id')

        if group_id:
            return self.env['hotel.reservation'].search([
                ('group_id', '=', group_id),
                ('is_desk_folio', '=', False),
            ], order=order or 'name asc')

        return reservations.filtered(lambda reservation: not reservation.is_desk_folio)

    def write(self, vals):
        # 1. Capture the rooms before the drag-and-drop happens
        old_reservations = self.mapped('reservation_id')
        
        # 2. Let Odoo perform the actual drag-and-drop save
        res = super().write(vals)
        
        # 3. Safely update the physical reservations
        if 'reservation_id' in vals:
            all_reservations = old_reservations | self.mapped('reservation_id')
            for room in all_reservations:
                if room and room.id:
                    # Find who is left in the room
                    guests = self.env['hotel.group.rooming.list'].search([('reservation_id', '=', room.id)]).mapped('partner_id')
                    
                    if guests:
                        # SAFELY write the new primary guest using dictionaries
                        room.write({
                            'partner_id': guests[0].id,
                            'accompanying_guest_ids': [(6, 0, guests[1:].ids)] if len(guests) > 1 else [(5, 0, 0)]
                        })
                    else:
                        # Room is empty! Triple-layer failsafe to find a fallback name
                        fallback_partner = room.group_id.partner_id or self.env.user.company_id.partner_id or self.env.company.partner_id
                        
                        if fallback_partner:
                            room.write({
                                'partner_id': fallback_partner.id,
                                'accompanying_guest_ids': [(5, 0, 0)]
                            })
        return res
    
# =========================================================
#  PHASE 3: ADVANCED VISUALS FOR GROUP BOARD
# =========================================================
from odoo import models, fields, api

# 1. UPGRADE RESERVATION DISPLAY (For Header)
class HotelReservationExtension(models.Model):
    _inherit = 'hotel.reservation'

    def name_get(self):
        """ Overriding display name to provide multiline headers on board """
        result = []
        for record in self:
            name = record.name
            if record.room_id:
                # \n Room... creates the second line in CSS pre-wrap
                name += f"\nRoom {record.room_id.name}"
            result.append((record.id, name))
        return result


# 2. UPGRADE ROOMING LIST (For Card Colors & Header Columns)
class HotelGroupRoomingListExtension(models.Model):
    _inherit = 'hotel.group.rooming.list'

    # --- NEW FIELDS FOR VISUALS ---
    state_color_class = fields.Char(string="State Color Class", compute='_compute_state_color')

    @api.depends('reservation_id.state')
    def _compute_state_color(self):
        """ Maps reservation states to specific color classes """
        state_color_map = {
            'draft': 'muted',      # Grey
            'confirm': 'primary',  # Cyan/Blue
            'checkin': 'success',  # Green
            'checkout': 'warning', # Yellow
            'cancel': 'danger',    # Red
            # Odoo maps: danger=red, success=green, primary=blue, warning=yellow, muted=grey
        }
        for record in self:
            res_state = record.reservation_id.state if record.reservation_id else 'draft'
            record.state_color_class = state_color_map.get(res_state, 'muted')

class HotelPaymentFilterWizard(models.TransientModel):
    _name = 'hotel.payment.filter.wizard'
    _description = 'Payment Date Filter Wizard'

    # 1. This creates the Calendar field and defaults to your Hotel's Business Date!
    target_date = fields.Date(
        string="Select Business Date",
        default=lambda self: self.env.company.hotel_business_date or fields.Date.context_today(self),
        required=True
    )

    def action_open_payments(self):
        self.ensure_one()
        # 2. This opens the list view, strictly filtered to the date they picked on the calendar
        return {
            'name': f'Payments & Receipts ({self.target_date})',
            'type': 'ir.actions.act_window',
            'res_model': 'account.payment',
            'view_mode': 'list,form',
            'domain': [('hotel_business_date', '=', self.target_date)],
            'target': 'current',
        }    
    

# =========================================================
#  THE DESK FOLIO FLAG & AUTO-FILL MAGIC
# =========================================================
class SaleOrderHotelAudit(models.Model):
    _inherit = 'sale.order'

    hotel_reservation_ids = fields.One2many('hotel.reservation', 'sale_order_id', string="Hotel Reservations", readonly=True)
    hotel_group_master_ids = fields.One2many('hotel.group.master', 'folio_id', string="Hotel Group Masters", readonly=True)
    is_hotel_folio = fields.Boolean(string="Is Hotel Folio", compute="_compute_is_hotel_folio")
    hotel_invoice_numbers = fields.Char(string="Invoice Numbers", compute="_compute_hotel_audit_docs")
    hotel_receipt_numbers = fields.Char(string="Receipt Numbers", compute="_compute_hotel_audit_docs")
    hotel_payment_journals = fields.Char(string="Payment Method", compute="_compute_hotel_audit_docs")
    hotel_payment_dates = fields.Char(string="Payment Date", compute="_compute_hotel_audit_docs")

    # --- NEW: SEPARATE GUEST AND COMPANY COLUMNS ---
    hotel_guest_names = fields.Char(string="Guest Name", compute="_compute_hotel_audit_guests")
    hotel_city_ledger_names = fields.Char(string="Company (City Ledger)", compute="_compute_hotel_audit_guests")
    hotel_total_folio_charges = fields.Monetary(string="Total Folio Charges", compute='_compute_hotel_guest_financial_snapshot')
    hotel_guest_total_charges = fields.Monetary(string="Total Charges", compute='_compute_hotel_guest_financial_snapshot')
    hotel_advance_deposit_credit = fields.Monetary(string="Advance Deposit Credit", compute='_compute_hotel_guest_financial_snapshot')
    hotel_invoice_payments = fields.Monetary(string="Invoice Payments", compute='_compute_hotel_guest_financial_snapshot')
    hotel_deposit_paid_total = fields.Monetary(string="Deposit / Paid", compute='_compute_hotel_guest_financial_snapshot')
    hotel_guest_net_position = fields.Monetary(string="Guest Net Position", compute='_compute_hotel_guest_financial_snapshot')
    hotel_guest_balance_due = fields.Monetary(string="Guest Balance Due", compute='_compute_hotel_guest_financial_snapshot')
    hotel_guest_credit_balance = fields.Monetary(string="Guest Credit Balance", compute='_compute_hotel_guest_financial_snapshot')
    hotel_all_payment_ids = fields.Many2many(
        'account.payment',
        string="Payments & Deposits",
        compute='_compute_hotel_all_payment_ids',
    )

    @api.depends(
        'hotel_reservation_ids.advance_deposit_payment_ids',
        'hotel_reservation_ids.advance_deposit_payment_ids.state',
        'invoice_ids.payment_ids',
        'invoice_ids.state',
    )
    def _compute_hotel_all_payment_ids(self):
        for order in self:
            payments = self.env['account.payment']
            for res in order.hotel_reservation_ids:
                payments |= res._get_registered_payment_records()
            order.hotel_all_payment_ids = payments

    @api.depends('hotel_reservation_ids', 'hotel_group_master_ids')
    def _compute_is_hotel_folio(self):
        for order in self:
            order.is_hotel_folio = bool(order.hotel_reservation_ids or order.hotel_group_master_ids)

    @api.depends(
        'hotel_reservation_ids.state',
        'order_line.price_total',
        'order_line.display_type',
        'order_line.is_downpayment',
        'order_line.name',
        'hotel_reservation_ids.guest_total_charges',
        'hotel_reservation_ids.advance_deposit_credit',
        'hotel_reservation_ids.guest_invoice_payments',
        'hotel_reservation_ids.guest_deposit_paid_total',
        'hotel_reservation_ids.guest_net_position',
        'hotel_reservation_ids.guest_balance_due',
        'hotel_reservation_ids.guest_credit_balance',
    )
    def _compute_hotel_guest_financial_snapshot(self):
        for order in self:
            reservations = order.hotel_reservation_ids.filtered(lambda res: res.state != 'cancel')
            charge_lines = order.order_line.filtered(
                lambda line: (
                    not line.display_type
                    and not getattr(line, 'is_downpayment', False)
                    and 'Deposit' not in (line.name or '')
                )
            )
            order.hotel_total_folio_charges = sum(charge_lines.mapped('price_total'))
            order.hotel_guest_total_charges = sum(reservations.mapped('guest_total_charges'))
            order.hotel_advance_deposit_credit = sum(reservations.mapped('advance_deposit_credit'))
            order.hotel_invoice_payments = sum(reservations.mapped('guest_invoice_payments'))
            order.hotel_deposit_paid_total = sum(reservations.mapped('guest_deposit_paid_total'))
            order.hotel_guest_net_position = sum(reservations.mapped('guest_net_position'))
            order.hotel_guest_balance_due = sum(reservations.mapped('guest_balance_due'))
            order.hotel_guest_credit_balance = sum(reservations.mapped('guest_credit_balance'))

    def action_view_hotel_operational_folio(self):
        self.ensure_one()
        
        # 1. FOOLPROOF DATABASE SEARCH:
        # Ignore broken relational fields and query the database directly to find the Desk Folio.
        reservations = self.env['hotel.reservation'].search([('sale_order_id', '=', self.id)])
        
        # 2. FORCE THE SYNC:
        # This guarantees the Posting Journal updates with the newly transferred charges.
        if reservations:
            reservations._sync_guest_financial_activity_journal()
            
        is_desk_folio = any(res.is_desk_folio for res in reservations)
        
        # 3. BULLETPROOF DOMAIN:
        # Strictly look for lines attached to this exact Folio (Sale Order).
        domain = [
            ('source_order_id', '=', self.id),
            ('entry_side', '!=', 'info')
        ]
        
        # If it is a normal guest, hide company charges. If it is a Desk Folio, show everything!
        if not is_desk_folio:
            domain.append(('folio_billing_target', '!=', 'company'))

        action = self.env['ir.actions.actions']._for_xml_id('hotel_management.action_hotel_posting_journal')
        action.update({
            'name': _('Operational Folio') if is_desk_folio else _('Operational Guest Folio'),
            'domain': domain,
            'target': 'current',
            'views': [
                (self.env.ref('hotel_management.view_hotel_guest_folio_tree').id, 'list'),
                (False, 'form'),
            ],
        })
        return action

    def _ensure_hotel_folio_confirmed(self):
        for order in self:
            if not order.is_hotel_folio:
                continue
            if order.state == 'cancel':
                raise UserError(_("Hotel folio %s cannot stay cancelled. Cancel the reservation instead of the folio.") % (order.name or order.id))
            if order.state in ['draft', 'sent']:
                order.action_confirm()
        return self

    @api.model_create_multi
    def create(self, vals_list):
        orders = super().create(vals_list)
        orders.filtered(lambda order: order.is_hotel_folio and order.state in ['draft', 'sent'])._ensure_hotel_folio_confirmed()
        return orders

    def write(self, vals):
        res = super().write(vals)
        self.filtered(lambda order: order.is_hotel_folio and order.state in ['draft', 'sent'])._ensure_hotel_folio_confirmed()
        return res

    def action_cancel(self):
        hotel_orders = self.filtered(lambda order: order.is_hotel_folio)
        if hotel_orders:
            raise UserError(_("Hotel folios must remain confirmed. Cancel the reservation instead of cancelling folio(s): %s") % ", ".join(hotel_orders.mapped('name')))
        return super().action_cancel()

    def _get_hotel_new_invoiceable_lines(self, final=False):
        self.ensure_one()
        invoiceable_lines = self._get_invoiceable_lines(final)
        hotel_invoiceable_lines = self.env['sale.order.line']
        pending_display_lines = self.env['sale.order.line']

        for line in invoiceable_lines:
            if line.display_type:
                pending_display_lines |= line
                continue

            if not line._hotel_is_new_invoiceable_transaction():
                continue

            if pending_display_lines:
                hotel_invoiceable_lines |= pending_display_lines
                pending_display_lines = self.env['sale.order.line']
            hotel_invoiceable_lines |= line

        return hotel_invoiceable_lines

    def _get_hotel_billing_partner(self, billing_target, lines):
        self.ensure_one()
        lines = lines.filtered(lambda line: not line.display_type)
        reservations = lines.mapped('hotel_reservation_id').filtered(lambda res: res.state != 'cancel')
        folio_reservations = reservations or self.hotel_reservation_ids

        if billing_target == 'company':
            partners = reservations.mapped('city_ledger_id').filtered(lambda partner: partner)
            if not partners:
                partners = self.hotel_reservation_ids.mapped('city_ledger_id').filtered(lambda partner: partner)
            if not partners and self.hotel_group_master_ids:
                partners = self.hotel_group_master_ids.mapped('city_ledger_id').filtered(lambda partner: partner)
            if len(partners) > 1:
                raise UserError(
                    _("This folio routes company charges to multiple City Ledger accounts. Please split the charges before invoicing.")
                )
            if not partners:
                raise UserError(
                    _("Some folio lines are routed to Company, but no City Ledger / Bill To company is configured on this folio.")
                )
            return partners[:1]

        partners = reservations.filtered(lambda res: not res.is_desk_folio).mapped('partner_id').filtered(lambda partner: partner)
        if not partners:
            partners = self.hotel_reservation_ids.filtered(lambda res: not res.is_desk_folio).mapped('partner_id').filtered(lambda partner: partner)
        if len(partners) > 1:
            raise UserError(
                _("This folio contains guest-routed charges for multiple guests. Please transfer or split the charges before invoicing.")
            )
        if partners:
            return partners[:1]
        if (
            self.partner_id
            and folio_reservations
            and all(res.folio_type in ['desk', 'group_master'] for res in folio_reservations)
        ):
            return self.partner_id
        if self.partner_id and not self.partner_id.is_company:
            return self.partner_id
        raise UserError(
            _("Guest-routed folio lines do not have a clear guest / account partner. Please review the Bill To routing before invoicing.")
        )

    def _prepare_hotel_routed_invoice_vals(self, partner, billing_target, date=None):
        self.ensure_one()
        invoice_vals = self._prepare_invoice()
        invoice_partner_id = partner.address_get(['invoice']).get('invoice') if partner else False
        shipping_partner_id = partner.address_get(['delivery']).get('delivery') if partner else False
        invoice_partner = self.env['res.partner'].browse(invoice_partner_id) if invoice_partner_id else partner
        shipping_partner = self.env['res.partner'].browse(shipping_partner_id) if shipping_partner_id else partner
        fiscal_position = self.fiscal_position_id or self.fiscal_position_id._get_fiscal_position(invoice_partner)

        invoice_vals.update({
            'partner_id': invoice_partner.id,
            'partner_shipping_id': shipping_partner.id if shipping_partner else False,
            'fiscal_position_id': fiscal_position.id,
            'invoice_payment_term_id': partner.property_payment_term_id.id or self.payment_term_id.id,
            'invoice_line_ids': [],
            'hotel_billing_target': billing_target,
        })
        if date:
            invoice_vals['invoice_date'] = date
        return invoice_vals

    def _get_hotel_invoiceable_lines_by_target(self, final=False):
        self.ensure_one()
        routed_lines = {
            'guest': self.env['sale.order.line'],
            'company': self.env['sale.order.line'],
        }
        pending_display_lines = self.env['sale.order.line']

        for line in self._get_hotel_new_invoiceable_lines(final=final):
            if line.display_type:
                pending_display_lines |= line
                continue

            billing_target = line._get_resolved_billing_target()
            if pending_display_lines:
                routed_lines[billing_target] |= pending_display_lines
                pending_display_lines = self.env['sale.order.line']
            routed_lines[billing_target] |= line

        return routed_lines

    def _log_hotel_routed_invoice_results(self, plan_entries):
        selection_labels = dict(self.env['account.move']._fields['hotel_billing_target'].selection)
        plans_by_order = {}
        for entry in plan_entries:
            plans_by_order.setdefault(entry['order'].id, []).append(entry)

        for order in self:
            entries = plans_by_order.get(order.id, [])
            if not entries:
                continue

            routed_summary = []
            invoice_summary = []
            for entry in entries:
                label = selection_labels.get(entry['target'], entry['target'])
                routed_lines = entry['lines'].filtered(lambda line: not line.display_type)
                routed_total = sum(routed_lines.mapped('price_total'))
                routed_summary.append(
                    f"{label}: {len(routed_lines)} line(s), {(order.currency_id.symbol or '')}{routed_total:.2f}"
                )
                invoice_name = entry['move'].name if entry['move'].name and entry['move'].name != '/' else _("Draft Invoice")
                invoice_summary.append(
                    f"{label}: {invoice_name}, {(entry['move'].currency_id.symbol or '')}{entry['move'].amount_total:.2f}"
                )

            body = Markup(
                "<p><strong>Billing routing applied:</strong><br/>%s</p>"
                "<p><strong>Invoice split result:</strong><br/>%s</p>"
                % ("<br/>".join(routed_summary), "<br/>".join(invoice_summary))
            )
            order.message_post(body=body, subtype_xmlid='mail.mt_note')
            for reservation in order.hotel_reservation_ids:
                reservation.message_post(body=body, subtype_xmlid='mail.mt_note')
                for entry in entries:
                    label = selection_labels.get(entry['target'], entry['target'])
                    move = entry['move']
                    invoice_name = move.name if move.name and move.name != '/' else _("Draft Invoice")
                    reservation._log_exchange_event(
                        _("Invoice Created"),
                        '',
                        _("%s invoice %s for %s%.2f") % (
                            label,
                            invoice_name,
                            move.currency_id.symbol or '',
                            move.amount_total,
                        ),
                        change_type='action',
                        source_document=move,
                    )

    def _create_hotel_routed_invoices(self, final=False, date=None):
        invoice_vals_list = []
        invoice_plan = []

        for order in self:
            if order.partner_invoice_id.lang:
                order = order.with_context(lang=order.partner_invoice_id.lang)
            order = order.with_company(order.company_id)
            order.order_line.filtered(lambda line: not line.display_type and not line.billing_target)._hotel_assign_missing_billing_targets()
            routed_lines = order._get_hotel_invoiceable_lines_by_target(final=final)

            for billing_target in ('company', 'guest'):
                target_lines = routed_lines[billing_target]
                if not any(not line.display_type for line in target_lines):
                    continue

                partner = order._get_hotel_billing_partner(billing_target, target_lines)
                invoice_vals = order._prepare_hotel_routed_invoice_vals(partner, billing_target, date=date)
                invoice_line_vals = []
                sequence = 1
                down_payment_section_added = False

                for line in target_lines:
                    if not down_payment_section_added and line.is_downpayment:
                        invoice_line_vals.append(
                            Command.create(order._prepare_down_payment_section_line(sequence=sequence))
                        )
                        down_payment_section_added = True
                        sequence += 1
                    invoice_line_vals.append(
                        Command.create(line._prepare_invoice_line(sequence=sequence))
                    )
                    sequence += 1

                invoice_vals['invoice_line_ids'] = invoice_line_vals
                invoice_vals_list.append(invoice_vals)
                invoice_plan.append({
                    'order': order,
                    'target': billing_target,
                    'lines': target_lines,
                })

        if not invoice_vals_list and self._context.get('raise_if_nothing_to_invoice', True):
            raise UserError(_("All folio transactions are already invoiced."))

        moves = self._create_account_invoices(invoice_vals_list, final)

        if final and (moves_to_switch := moves.sudo().filtered(lambda move: move.amount_total < 0)):
            with self.env.protecting([moves._fields['team_id']], moves_to_switch):
                moves_to_switch.action_switch_move_type()
                self.invoice_ids._set_reversed_entry(moves_to_switch)

        for move in moves:
            move.message_post_with_source(
                'mail.message_origin_link',
                render_values={'self': move, 'origin': move.line_ids.sale_line_ids.order_id},
                subtype_xmlid='mail.mt_note',
            )

        for move, entry in zip(moves, invoice_plan):
            entry['move'] = move
        for order in self:
            order_moves = self.env['account.move']
            for entry in invoice_plan:
                if entry['order'] == order:
                    order_moves |= entry['move']

            deposit_reservations = self.env['hotel.reservation']

            # Normal guest reservation deposits
            deposit_reservations |= order.hotel_reservation_ids.filtered(
                lambda res: not res.is_desk_folio
                and res.folio_type == 'guest'
                and res._get_deposit_balance_amount() > 0
            )

            # Group Paymaster / Desk Folio deposits
            for group in order.hotel_group_master_ids:
                paymaster = group.paymaster_id or self.env['hotel.reservation'].search([
                    ('group_id', '=', group.id),
                    ('is_desk_folio', '=', True),
                ], limit=1)
                if paymaster and paymaster._get_deposit_balance_amount() > 0:
                    deposit_reservations |= paymaster

            for reservation in deposit_reservations:
                reservation._apply_advance_deposit_to_invoices(order_moves)
        self._log_hotel_routed_invoice_results(invoice_plan)
        return moves

    def _create_invoices(self, grouped=False, final=False, date=None):
        hotel_orders = self.filtered(lambda order: bool(order.hotel_reservation_ids or order.hotel_group_master_ids))
        regular_orders = self - hotel_orders
        invoices = self.env['account.move']

        if regular_orders:
            invoices |= super(SaleOrderHotelAudit, regular_orders)._create_invoices(
                grouped=grouped,
                final=final,
                date=date,
            )
        if hotel_orders:
            invoices |= hotel_orders._create_hotel_routed_invoices(final=final, date=date)
        return invoices

    def _is_hotel_invoice_linked_to_order(self, invoice):
        self.ensure_one()
        invoice = invoice.sudo()
        if invoice.move_type not in ('out_invoice', 'out_refund'):
            return False
        if invoice.hotel_folio_id and invoice.hotel_folio_id.id == self.id:
            return True
        return bool(
            invoice.invoice_line_ids.mapped('sale_line_ids.order_id').filtered(
                lambda order: order.id == self.id
            )
        )

    def _compute_hotel_audit_docs(self):
        for order in self:
            if not (order.hotel_reservation_ids or order.hotel_group_master_ids):
                order.hotel_invoice_numbers = ""
                order.hotel_receipt_numbers = ""
                order.hotel_payment_journals = ""
                order.hotel_payment_dates = ""
                continue

            invoices = order.sudo().invoice_ids.filtered(
                lambda i: i.state == 'posted'
                and i.move_type == 'out_invoice'
                and order._is_hotel_invoice_linked_to_order(i)
            )
            order.hotel_invoice_numbers = ", ".join(invoices.mapped('name')) if invoices else ""
            
            payments = self.env['account.payment'].sudo()
            for inv in invoices:
                payments |= inv.sudo()._get_reconciled_payments().sudo()
            
            order.hotel_receipt_numbers = ", ".join(payments.mapped('name')) if payments else ""
            order.hotel_payment_journals = ", ".join(set(payments.mapped('journal_id.name'))) if payments else ""
            order.hotel_payment_dates = ", ".join(set([p.date.strftime('%Y-%m-%d') for p in payments if p.date])) if payments else ""

    def _compute_hotel_audit_guests(self):
        for order in self:
            # Look backwards to find all reservations linked to this Folio
            reservations = self.env['hotel.reservation'].search([('sale_order_id', '=', order.id)])
            
            # Check if this Folio contains a Desk Folio (Group Master / House Account)
            desk_folios = reservations.filtered(lambda r: r.is_desk_folio)
            
            if desk_folios:
                # It's a Group Master! Just use the main Group Account Name.
                order.hotel_guest_names = desk_folios[0].partner_id.name or order.partner_id.name
            elif reservations:
                # It's a normal booking! Grab ONLY the primary guest of the first room.
                order.hotel_guest_names = reservations[0].partner_id.name
            else:
                # Fallback just in case
                order.hotel_guest_names = order.partner_id.name
            
            # City Ledger / Company (Keep this the same)
            companies = [c for c in reservations.mapped('city_ledger_id.name') if c]
            order.hotel_city_ledger_names = ", ".join(set(companies)) if companies else ""

class HotelRoutingWizard(models.TransientModel):
    _name = 'hotel.routing.wizard'
    _description = 'Transfer Charges Wizard'

    source_order_id = fields.Many2one('sale.order', string="Current Folio", readonly=True)
    
    # We remove the domain here so it doesn't crash the Python backend
    destination_reservation_id = fields.Many2one(
        'hotel.reservation', 
        string="Move to Room / Desk Folio", 
        required=True
    )
    
    line_ids = fields.Many2many(
        'sale.order.line', 
        string="Select Charges to Move", 
        required=True,
        domain="[('order_id', '=', source_order_id)]"
    )

    def action_transfer(self):
        if not self.destination_reservation_id.sale_order_id:
            self.destination_reservation_id.action_create_folio()
            
        dest_order = self.destination_reservation_id.sale_order_id
        
        if not dest_order:
            raise UserError(_("The system could not generate a folio for the destination."))
            
        # 1. Get the Source Reservation
        source_reservation = self.env['hotel.reservation'].search([('sale_order_id', '=', self.source_order_id.id)], limit=1)
        
        for line in self.line_ids:
            original_taxes = line.tax_ids.ids
            line_desc = f"{line.product_id.name} | Qty {line.product_uom_qty} | Total {line.price_total}"
            
            # 2. Move the line financially
            line.write({
                'order_id': dest_order.id,
                'tax_ids': [(6, 0, original_taxes)],
                'hotel_reservation_id': self.destination_reservation_id.id,
            })
            
            # 3. WRITE TO SOURCE EXCHANGE JOURNAL (Transferred OUT)
            if source_reservation:
                # Using your custom built-in logger!
                self.env['hotel.change.log'].log_reservation_event(
                    reservation=source_reservation,
                    field_name='Charge Transferred OUT',
                    old_value='',
                    new_value=f"Moved to {self.destination_reservation_id.name}",
                    reason=line_desc,
                    change_type='action',
                    source_document=line
                )
                source_reservation.message_post(body=f"<b>Charge Transferred OUT:</b> {line_desc} <br/><b>Moved to:</b> {self.destination_reservation_id.name}")

            # 4. WRITE TO DESTINATION EXCHANGE JOURNAL (Transferred IN)
            source_name = source_reservation.name if source_reservation else 'Another Folio'
            self.env['hotel.change.log'].log_reservation_event(
                reservation=self.destination_reservation_id,
                field_name='Charge Transferred IN',
                old_value='',
                new_value=f"Received from {source_name}",
                reason=line_desc,
                change_type='action',
                source_document=line
            )
            self.destination_reservation_id.message_post(body=f"<b>Charge Transferred IN:</b> {line_desc} <br/><b>Received from:</b> {source_name}")

        # 5. FORCE RESYNC OF OPERATIONAL GUEST FOLIOS
        if source_reservation:
            source_reservation._sync_guest_financial_activity_journal()
        self.destination_reservation_id._sync_guest_financial_activity_journal()
        
        return {'type': 'ir.actions.act_window_close'}
    
class ResPartnerExtended(models.Model):
    _inherit = 'res.partner'

    passport_number = fields.Char(string="Passport / National ID", copy=False, tracking=True)
    
    passport_image = fields.Image(
        string="Passport/ID Image", 
        max_width=1024, 
        max_height=1024
    )
    
    @api.constrains('passport_number')
    def _check_unique_passport(self):
        for record in self:
            if record.passport_number:
                duplicate = self.search([
                    ('passport_number', '=', record.passport_number),
                    ('id', '!=', record.id)
                ])
                if duplicate:
                    raise ValidationError(f"Stop! A guest with Passport/ID '{record.passport_number}' already exists in the system.")     

class ResCompany(models.Model):
    _inherit = 'res.company'
    
    hotel_checkout_hold_time = fields.Float(string="Checkout Hold Time", default=12.0)
    # NEW: The True/False switch for Passport validation (Defaults to True for safety)
    hotel_require_id_checkin = fields.Boolean(string="Require ID on Check-In", default=True)
    require_all_guest_profiles_before_checkin = fields.Boolean(
        string="Require All Guest Profiles Before Check-In",
        default=False,
    )

class ResConfigSettings(models.TransientModel):
    _inherit = 'res.config.settings'
    
    hotel_checkout_hold_time = fields.Float(related='company_id.hotel_checkout_hold_time', readonly=False)
    # NEW: The bridge to the settings menu
    hotel_require_id_checkin = fields.Boolean(related='company_id.hotel_require_id_checkin', readonly=False)
    require_all_guest_profiles_before_checkin = fields.Boolean(
        related='company_id.require_all_guest_profiles_before_checkin',
        readonly=False,
    )
    hotel_advance_deposit_account_id = fields.Many2one(related='company_id.hotel_advance_deposit_account_id', readonly=False)
    hotel_deposit_required = fields.Boolean(related='company_id.hotel_deposit_required', readonly=False)
    hotel_confirmation_deposit_percent = fields.Float(related='company_id.hotel_confirmation_deposit_percent', readonly=False)
    hotel_deposit_tax_proportional = fields.Boolean(related='company_id.hotel_deposit_tax_proportional', readonly=False)
    hotel_auto_email_deposit_receipt = fields.Boolean(related='company_id.hotel_auto_email_deposit_receipt', readonly=False)
    hotel_attach_confirmation_pdf_to_booking_email = fields.Boolean(
        related='company_id.hotel_attach_confirmation_pdf_to_booking_email',
        readonly=False,
    )
    hotel_online_payment_link_enabled = fields.Boolean(related='company_id.hotel_online_payment_link_enabled', readonly=False)
    hotel_online_payment_instruction = fields.Html(related='company_id.hotel_online_payment_instruction', readonly=False)
    hotel_cancellation_policy = fields.Html(related='company_id.hotel_cancellation_policy', readonly=False)
    hotel_payment_instructions = fields.Html(related='company_id.hotel_payment_instructions', readonly=False)
    hotel_business_date = fields.Date(
    related='company_id.hotel_business_date',
    readonly=False
    )
    hotel_auto_noshow_enabled = fields.Boolean(related='company_id.hotel_auto_noshow_enabled', readonly=False)
    hotel_auto_noshow_cutoff_time = fields.Float(related='company_id.hotel_auto_noshow_cutoff_time', readonly=False)
    hotel_auto_noshow_grace_hours = fields.Float(related='company_id.hotel_auto_noshow_grace_hours', readonly=False)
    hotel_auto_noshow_apply_to = fields.Selection(related='company_id.hotel_auto_noshow_apply_to', readonly=False)
    hotel_auto_noshow_exclude_deposit = fields.Boolean(related='company_id.hotel_auto_noshow_exclude_deposit', readonly=False)
    hotel_req_reservation_nationality = fields.Boolean(config_parameter='hotel_management.guest_profile_required_reservation_nationality')
    hotel_req_checkin_nationality = fields.Boolean(config_parameter='hotel_management.guest_profile_required_checkin_nationality')
    hotel_req_reservation_country = fields.Boolean(config_parameter='hotel_management.guest_profile_required_reservation_country')
    hotel_req_checkin_country = fields.Boolean(config_parameter='hotel_management.guest_profile_required_checkin_country')
    hotel_req_reservation_passport_id = fields.Boolean(config_parameter='hotel_management.guest_profile_required_reservation_passport_id')
    hotel_req_checkin_passport_id = fields.Boolean(config_parameter='hotel_management.guest_profile_required_checkin_passport_id')
    hotel_req_reservation_date_of_birth = fields.Boolean(config_parameter='hotel_management.guest_profile_required_reservation_date_of_birth')
    hotel_req_checkin_date_of_birth = fields.Boolean(config_parameter='hotel_management.guest_profile_required_checkin_date_of_birth')
    hotel_req_reservation_gender = fields.Boolean(config_parameter='hotel_management.guest_profile_required_reservation_gender')
    hotel_req_checkin_gender = fields.Boolean(config_parameter='hotel_management.guest_profile_required_checkin_gender')
    hotel_req_reservation_email = fields.Boolean(config_parameter='hotel_management.guest_profile_required_reservation_email')
    hotel_req_checkin_email = fields.Boolean(config_parameter='hotel_management.guest_profile_required_checkin_email')
    hotel_req_reservation_phone = fields.Boolean(config_parameter='hotel_management.guest_profile_required_reservation_phone')
    hotel_req_checkin_phone = fields.Boolean(config_parameter='hotel_management.guest_profile_required_checkin_phone')
    hotel_req_reservation_source_category = fields.Boolean(config_parameter='hotel_management.guest_profile_required_reservation_source_category')
    hotel_req_checkin_source_category = fields.Boolean(config_parameter='hotel_management.guest_profile_required_checkin_source_category')
    hotel_req_reservation_sub_source = fields.Boolean(config_parameter='hotel_management.guest_profile_required_reservation_sub_source')
    hotel_req_checkin_sub_source = fields.Boolean(config_parameter='hotel_management.guest_profile_required_checkin_sub_source')
    hotel_req_reservation_market_segment = fields.Boolean(config_parameter='hotel_management.guest_profile_required_reservation_market_segment')
    hotel_req_checkin_market_segment = fields.Boolean(config_parameter='hotel_management.guest_profile_required_checkin_market_segment')
    hotel_req_reservation_guest_class = fields.Boolean(config_parameter='hotel_management.guest_profile_required_reservation_guest_class')
    hotel_req_checkin_guest_class = fields.Boolean(config_parameter='hotel_management.guest_profile_required_checkin_guest_class')
    hotel_req_reservation_guest_classification = fields.Boolean(config_parameter='hotel_management.guest_profile_required_reservation_guest_classification')
    hotel_req_checkin_guest_classification = fields.Boolean(config_parameter='hotel_management.guest_profile_required_checkin_guest_classification')
    hotel_req_checkin_all_stay_guest_profiles = fields.Boolean(
        string="Require All Stay Guest Profiles at Check-In",
        config_parameter='hotel_management.guest_profile_required_checkin_all_stay_guest_profiles',
    )
    hotel_req_checkin_all_stay_guest_passport = fields.Boolean(
        string="Require Passport/ID for All Stay Guests at Check-In",
        config_parameter='hotel_management.guest_profile_required_checkin_all_stay_guest_passport',
    )
    hotel_req_checkin_all_stay_guest_nationality = fields.Boolean(
        string="Require Nationality for All Stay Guests at Check-In",
        config_parameter='hotel_management.guest_profile_required_checkin_all_stay_guest_nationality',
    )
    hotel_req_reservation_udf_1 = fields.Boolean(config_parameter='hotel_management.guest_profile_required_reservation_udf_1')
    hotel_req_checkin_udf_1 = fields.Boolean(config_parameter='hotel_management.guest_profile_required_checkin_udf_1')
    hotel_req_reservation_udf_2 = fields.Boolean(config_parameter='hotel_management.guest_profile_required_reservation_udf_2')
    hotel_req_checkin_udf_2 = fields.Boolean(config_parameter='hotel_management.guest_profile_required_checkin_udf_2')
    hotel_req_reservation_udf_3 = fields.Boolean(config_parameter='hotel_management.guest_profile_required_reservation_udf_3')
    hotel_req_checkin_udf_3 = fields.Boolean(config_parameter='hotel_management.guest_profile_required_checkin_udf_3')
    hotel_req_reservation_udf_4 = fields.Boolean(config_parameter='hotel_management.guest_profile_required_reservation_udf_4')
    hotel_req_checkin_udf_4 = fields.Boolean(config_parameter='hotel_management.guest_profile_required_checkin_udf_4')
    hotel_req_reservation_udf_5 = fields.Boolean(config_parameter='hotel_management.guest_profile_required_reservation_udf_5')
    hotel_req_checkin_udf_5 = fields.Boolean(config_parameter='hotel_management.guest_profile_required_checkin_udf_5')
    hotel_req_reservation_udf_6 = fields.Boolean(config_parameter='hotel_management.guest_profile_required_reservation_udf_6')
    hotel_req_checkin_udf_6 = fields.Boolean(config_parameter='hotel_management.guest_profile_required_checkin_udf_6')
    hotel_req_reservation_udf_7 = fields.Boolean(config_parameter='hotel_management.guest_profile_required_reservation_udf_7')
    hotel_req_checkin_udf_7 = fields.Boolean(config_parameter='hotel_management.guest_profile_required_checkin_udf_7')
    hotel_req_reservation_udf_8 = fields.Boolean(config_parameter='hotel_management.guest_profile_required_reservation_udf_8')
    hotel_req_checkin_udf_8 = fields.Boolean(config_parameter='hotel_management.guest_profile_required_checkin_udf_8')
    hotel_req_reservation_udf_9 = fields.Boolean(config_parameter='hotel_management.guest_profile_required_reservation_udf_9')
    hotel_req_checkin_udf_9 = fields.Boolean(config_parameter='hotel_management.guest_profile_required_checkin_udf_9')
    hotel_req_reservation_udf_10 = fields.Boolean(config_parameter='hotel_management.guest_profile_required_reservation_udf_10')
    hotel_req_checkin_udf_10 = fields.Boolean(config_parameter='hotel_management.guest_profile_required_checkin_udf_10')
    hotel_udf_label_1 = fields.Char(related='company_id.hotel_udf_label_1', readonly=True)
    hotel_udf_label_2 = fields.Char(related='company_id.hotel_udf_label_2', readonly=True)
    hotel_udf_label_3 = fields.Char(related='company_id.hotel_udf_label_3', readonly=True)
    hotel_udf_label_4 = fields.Char(related='company_id.hotel_udf_label_4', readonly=True)
    hotel_udf_label_5 = fields.Char(related='company_id.hotel_udf_label_5', readonly=True)
    hotel_udf_label_6 = fields.Char(related='company_id.hotel_udf_label_6', readonly=True)
    hotel_udf_label_7 = fields.Char(related='company_id.hotel_udf_label_7', readonly=True)
    hotel_udf_label_8 = fields.Char(related='company_id.hotel_udf_label_8', readonly=True)
    hotel_udf_label_9 = fields.Char(related='company_id.hotel_udf_label_9', readonly=True)
    hotel_udf_label_10 = fields.Char(related='company_id.hotel_udf_label_10', readonly=True)

class HotelExpressCheckinWizard(models.TransientModel):
    _name = 'hotel.express.checkin.wizard'
    _description = 'Express QR Scanner & E-Sign'

    access_token = fields.Char(string="Scan QR Code Here")
    reservation_id = fields.Many2one('hotel.reservation', string="Found Reservation", readonly=True)
    partner_id = fields.Many2one('res.partner', related="reservation_id.partner_id", string="Guest Name")
    room_id = fields.Many2one('hotel.room', related="reservation_id.room_id", string="Assigned Room")
    guest_signature = fields.Binary(string="Guest E-Signature")

    def action_find_guest(self):
        self.ensure_one()
        # 1. Search for the reservation when the button is clicked
        if self.access_token:
            reservation = self.env['hotel.reservation'].search([('access_token', '=', self.access_token)], limit=1)
            if reservation:
                self.reservation_id = reservation.id
            else:
                return {'warning': {'title': 'Not Found', 'message': 'No reservation matches this code.'}}
        
        # 2. Refresh the pop-up window to show the found guest
        return {
            'type': 'ir.actions.act_window',
            'res_model': 'hotel.express.checkin.wizard',
            'res_id': self.id,
            'view_mode': 'form',
            'target': 'new',
        }

    def action_confirm_checkin(self):
        self.ensure_one()
        if not self.reservation_id:
            return {'warning': {'title': 'Error', 'message': 'No reservation found!'}}
            
        # 3. Force the Signature to save to the database immediately
        if self.guest_signature:
            self.reservation_id.write({
                'guest_signature': self.guest_signature,
            })
            
            self.reservation_id.message_post(
                body="Express Check-In Signature Captured at Front Desk.",
                attachments=[('guest_signature.png', self.guest_signature)]
            )
            self.reservation_id.action_checkin()

        # 4. Teleport the user to the Main Reservation Screen
        return {
            'type': 'ir.actions.act_window',
            'res_model': 'hotel.reservation',
            'res_id': self.reservation_id.id,
            'view_mode': 'form',
            'target': 'main',
        }
