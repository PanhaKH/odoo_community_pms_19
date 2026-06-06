from odoo import models, fields, api, _
from datetime import timedelta

class ResCompanyHotel(models.Model):
    _inherit = 'res.company'
    
    hotel_business_date = fields.Date(
        string="Hotel Business Date", 
        default=fields.Date.context_today,
        required=True
    )

class HotelDashboard(models.Model):
    _name = 'hotel.dashboard'
    _description = 'Hotel Dashboard'

    name = fields.Char(default="Hotel Overview")
    
    company_id = fields.Many2one('res.company', string='Company', default=lambda self: self.env.company)
    business_date = fields.Date(related='company_id.hotel_business_date', string="Business Date")
    system_date = fields.Date(compute='_compute_dates', string="System Date")
    audit_warning = fields.Boolean(compute='_compute_dates')

    # --- PERFORMANCE METRICS ---
    total_rooms = fields.Integer(string="Total Rooms", readonly=True)
    rooms_available = fields.Integer(string="Available (Clean)", readonly=True)
    rooms_dirty = fields.Integer(string="Vacant Dirty", readonly=True)
    rooms_occupied = fields.Integer(string="Occupied", readonly=True)
    rooms_blocked = fields.Integer(string="Out of Order", readonly=True)
    
    occupancy_rate = fields.Float(string="Occupancy %", readonly=True)
    occupancy_tomorrow = fields.Float(string="Occupancy Tomorrow %", readonly=True)

    adr = fields.Float(string="ADR", readonly=True)
    revpar = fields.Float(string="RevPAR", readonly=True)
    total_revenue = fields.Float(string="Room Revenue", readonly=True)
    
    # --- 7-DAY FORECAST METRICS ---
    label_day_1 = fields.Char(readonly=True)
    occ_day_1 = fields.Float(readonly=True)
    label_day_2 = fields.Char(readonly=True)
    occ_day_2 = fields.Float(readonly=True)
    label_day_3 = fields.Char(readonly=True)
    occ_day_3 = fields.Float(readonly=True)
    label_day_4 = fields.Char(readonly=True)
    occ_day_4 = fields.Float(readonly=True)
    label_day_5 = fields.Char(readonly=True)
    occ_day_5 = fields.Float(readonly=True)
    label_day_6 = fields.Char(readonly=True)
    occ_day_6 = fields.Float(readonly=True)
    label_day_7 = fields.Char(readonly=True)
    occ_day_7 = fields.Float(readonly=True)

    # --- FLOW COUNTS ---
    arrivals_display = fields.Char(string="Arrivals", readonly=True)
    departures_display = fields.Char(string="Departures", readonly=True)
    stayovers_display = fields.Char(string="Stayovers", readonly=True)

    # --- FINANCIAL LEDGERS ---
    #deposit_ledger = fields.Float(string="Deposit Ledger", readonly=True)
    #guest_ledger = fields.Float(string="Guest Ledger", readonly=True)
    #city_ledger = fields.Float(string="City Ledger (A/R)", readonly=True)
    deposit_ledger = fields.Float(string="Deposit Ledger", readonly=True)
    guest_ledger = fields.Float(string="Guest Ledger", readonly=True)
    guest_ledger_display_amount = fields.Float(string="Guest Ledger Display Amount", readonly=True)
    guest_ledger_display_label = fields.Char(string="Guest Ledger Display Label", readonly=True)
    guest_pending_billing = fields.Float(string="Guest Pending Billing", readonly=True)
    guest_pending_charges = fields.Float(string="Guest Pending Charges", readonly=True)
    guest_draft_invoices = fields.Float(string="Guest Draft Invoices", readonly=True)
    guest_posted_unpaid = fields.Float(string="Guest Posted Unpaid", readonly=True)
    guest_collected = fields.Float(string="Guest Collected", readonly=True)
    guest_advance_deposit_credit = fields.Float(string="Advance Deposits / Guest Credit", readonly=True)
    guest_room_ledger = fields.Float(string="Guest Room Ledger", readonly=True)
    desk_folio_ledger = fields.Float(string="Desk Folio Ledger", readonly=True)
    company_pending_billing = fields.Float(string="Company Pending Billing", readonly=True)
    city_ledger = fields.Float(string="City Ledger (A/R)", readonly=True)

    inhouse_total = fields.Float(string="In-House Total Charges", readonly=True)
    inhouse_collected = fields.Float(string="In-House Collected (Paid)", readonly=True)
    
    today_invoiced = fields.Float(string="Today's Invoices (Issued)", readonly=True)
    today_collected = fields.Float(string="Today's Receipts (Collected)", readonly=True)

    # --- GUEST SERVICE ALERTS ---
    req_upcoming = fields.Integer(string="Upcoming Alerts", readonly=True)
    req_inhouse = fields.Integer(string="In-House Alerts", readonly=True)
    req_history = fields.Integer(string="Past Alerts", readonly=True)

    repeat_guest_count = fields.Integer(string="Repeat Guests Total", compute="_compute_repeat_guests")
    repeat_guest_today_count = fields.Integer(string="Repeat Arrivals Today", compute="_compute_repeat_guests")
    repeat_arriving_today_count = fields.Integer(string="Repeat Arriving Today", compute="_compute_repeat_guests")
    repeat_inhouse_count = fields.Integer(string="Repeat In-House Stay", compute="_compute_repeat_guests")
    repeat_future_booking_count = fields.Integer(string="Repeat Future Booking", compute="_compute_repeat_guests")
    vip_arriving_today_count = fields.Integer(string="VIP/VVIP Arriving Today", compute="_compute_vip_guests")
    vip_inhouse_count = fields.Integer(string="VIP/VVIP In-House Stay", compute="_compute_vip_guests")
    vip_future_booking_count = fields.Integer(string="VIP/VVIP Future Booking", compute="_compute_vip_guests")

    @api.model
    def get_guest_chat_alert_status(self):
        model = self.env['ir.model'].sudo().search([
            ('model', '=', 'hotel.guest.message'),
        ], limit=1)
        if not model:
            return {'count': 0, 'latest_message_id': False, 'has_unread': False}
        return self.env['hotel.guest.message'].get_unread_status()

    def _compute_repeat_guests(self):
        for rec in self:
            arriving = rec._get_repeat_reservations('arriving_today')
            inhouse = rec._get_repeat_reservations('inhouse')
            future = rec._get_repeat_reservations('future_booking')
            rec.repeat_arriving_today_count = len(arriving)
            rec.repeat_inhouse_count = len(inhouse)
            rec.repeat_future_booking_count = len(future)
            rec.repeat_guest_today_count = rec.repeat_arriving_today_count
            rec.repeat_guest_count = rec.repeat_arriving_today_count + rec.repeat_inhouse_count + rec.repeat_future_booking_count

    def _get_repeat_base_domain(self, bucket):
        self.ensure_one()
        biz_date = self.business_date or fields.Date.context_today(self)
        domain = [
            ('partner_id', '!=', False),
            ('is_desk_folio', '=', False),
        ]
        if bucket == 'arriving_today':
            return domain + [
                ('checkin_date', '=', biz_date),
                ('state', 'in', ['confirm', 'guaranteed']),
            ]
        if bucket == 'inhouse':
            return domain + [
                ('state', 'in', ['checkin', 'checkout_hold']),
            ]
        if bucket == 'future_booking':
            return domain + [
                ('checkin_date', '>', biz_date),
                ('state', 'in', ['confirm', 'guaranteed']),
            ]
        return domain + [
            ('state', 'in', ['confirm', 'guaranteed', 'checkin', 'checkout_hold']),
        ]

    def _is_repeat_reservation(self, reservation):
        return reservation._has_any_repeat_stay_guest()

    def _get_repeat_reservations(self, bucket):
        self.ensure_one()
        reservations = self.env['hotel.reservation'].search(self._get_repeat_base_domain(bucket))
        return reservations.filtered(lambda reservation: self._is_repeat_reservation(reservation))

    def _get_repeat_guest_action(self, title, bucket):
        self.ensure_one()
        repeat_ids = self._get_repeat_reservations(bucket).ids
        return {
            'name': title,
            'type': 'ir.actions.act_window',
            'res_model': 'hotel.reservation',
            'view_mode': 'list,form',
            'domain': [('id', 'in', repeat_ids or [0])],
            'context': {'create': False},
        }

    def _compute_vip_guests(self):
        for rec in self:
            rec.vip_arriving_today_count = len(rec._get_vip_reservations('arriving_today'))
            rec.vip_inhouse_count = len(rec._get_vip_reservations('inhouse'))
            rec.vip_future_booking_count = len(rec._get_vip_reservations('future_booking'))

    def _get_vip_reservations(self, bucket):
        self.ensure_one()
        reservations = self.env['hotel.reservation'].search(self._get_repeat_base_domain(bucket))
        return reservations.filtered(
            lambda reservation: any(
                partner.vip_level in ('vip', 'vvip')
                for partner in (
                    reservation.partner_id
                    | reservation.accompanying_guest_ids
                    | reservation.stay_guest_ids.mapped('partner_id')
                )
            )
        )

    def _get_vip_guest_action(self, title, bucket):
        self.ensure_one()
        reservation_ids = self._get_vip_reservations(bucket).ids
        return {
            'name': title,
            'type': 'ir.actions.act_window',
            'res_model': 'hotel.reservation',
            'view_mode': 'list,form',
            'domain': [('id', 'in', reservation_ids or [0])],
            'context': {'create': False},
        }

    def action_view_repeat_arriving_today(self):
        biz_date = self.business_date or fields.Date.context_today(self)
        return self._get_repeat_guest_action(_("Repeat Guests Arriving Today (%s)") % biz_date, 'arriving_today')

    def action_view_repeat_inhouse(self):
        return self._get_repeat_guest_action(_("Repeat Guests In-House"), 'inhouse')

    def action_view_repeat_future_booking(self):
        return self._get_repeat_guest_action(_("Repeat Guests Future Bookings"), 'future_booking')

    def action_view_vip_arriving_today(self):
        biz_date = self.business_date or fields.Date.context_today(self)
        return self._get_vip_guest_action(_("VIP / VVIP Guests Arriving Today (%s)") % biz_date, 'arriving_today')

    def action_view_vip_inhouse(self):
        return self._get_vip_guest_action(_("VIP / VVIP Guests In-House"), 'inhouse')

    def action_view_vip_future_booking(self):
        return self._get_vip_guest_action(_("VIP / VVIP Guests Future Bookings"), 'future_booking')

    def action_process_noshow_review(self):
        return self.env['hotel.reservation'].action_process_noshow_review()

    def action_open_repeat_guests(self):
        return self._get_repeat_guest_action(_("Active Repeat Guests"), 'all_active')

    def action_open_repeat_guests_today(self):
        return self.action_view_repeat_arriving_today()

    def _compute_dates(self):
        for rec in self:
            rec.system_date = fields.Date.context_today(self)
            if rec.business_date:
                rec.audit_warning = (rec.system_date != rec.business_date)
            else:
                rec.audit_warning = False

    @api.model
    def get_main_dashboard(self):
        dashboard = self.search([], limit=1)
        if not dashboard:
            dashboard = self.create({'name': 'Hotel Overview'})
        dashboard.action_refresh() 
        return dashboard.id

    def _get_hotel_posted_receivable_invoice_domain(self, partner_ids, billing_target):
        domain = [
            ('move_type', '=', 'out_invoice'),
            ('state', '=', 'posted'),
            ('amount_residual', '>', 0),
            ('hotel_folio_id', '!=', False),
            ('partner_id', 'in', partner_ids or [0]),
            ('hotel_billing_target', '=', billing_target),
        ]
        return domain

    def _get_active_desk_folios(self):
        Reservation = self.env['hotel.reservation'].sudo()
        # Desk folios are operational non-stay folios, so they stay active
        # without entering the room-stay check-in / check-out lifecycle.
        return Reservation.search([
            ('is_desk_folio', '=', True),
            ('desk_folio_status', '!=', 'paid'),
            ('state', 'not in', ['cancel', 'blocked', 'noshow', 'checkout']),
        ])

    def _get_city_ledger_invoice_domain(self):
        Reservation = self.env['hotel.reservation'].sudo()
        city_ledger_partner_ids = Reservation.search([
            ('city_ledger_id', '!=', False),
        ]).mapped('city_ledger_id').ids
        return self._get_hotel_posted_receivable_invoice_domain(city_ledger_partner_ids, 'company')

    def _get_deposit_ledger_reservations(self):
        Reservation = self.env['hotel.reservation'].sudo()
        # Deposit Ledger = advance deposits for future/unarrived room reservations only.
        # Desk folios and group-master folios are operational billing accounts, not deposits.
        return Reservation.search([
            ('state', 'in', ['draft', 'confirm']),
            ('is_desk_folio', '=', False),
            ('folio_type', '=', 'guest'),
        ])

    def _get_guest_ledger_bookings(self):
        Reservation = self.env['hotel.reservation'].sudo()
        room_guest_bookings = Reservation.search([
            ('state', 'in', ['checkin', 'checkout_hold']),
            ('is_desk_folio', '=', False),
        ])
        desk_folios = self._get_active_desk_folios()
        return room_guest_bookings, desk_folios, room_guest_bookings + desk_folios

    def _get_guest_ledger_breakdown(self):
        self.ensure_one()
        room_guest_bookings, desk_folios, all_guest_ledger_bookings = self._get_guest_ledger_bookings()

        positions = {
            reservation.id: reservation._get_operational_folio_position()
            for reservation in all_guest_ledger_bookings
        }

        guest_pending_charges = sum(
            reservation._get_guest_pending_charges_amount()
            for reservation in all_guest_ledger_bookings
        )
        guest_draft_invoices = sum(
            reservation._get_guest_draft_invoices_amount()
            for reservation in all_guest_ledger_bookings
        )
        guest_posted_unpaid = sum(
            reservation._get_guest_posted_unpaid_amount()
            for reservation in all_guest_ledger_bookings
        )
        guest_collected = sum(position['payments_received'] for position in positions.values())
        guest_advance_deposit_credit = sum(
            positions[reservation.id]['deposit_credit']
            for reservation in room_guest_bookings
            if reservation.id in positions
        )
        guest_room_balance = sum(
            positions[reservation.id]['operational_balance']
            for reservation in room_guest_bookings
            if reservation.id in positions
        )
        desk_folio_balance = sum(
            positions[reservation.id]['operational_balance']
            for reservation in desk_folios
            if reservation.id in positions
        )
        guest_net_balance = sum(position['operational_balance'] for position in positions.values())

        return {
            'room_guest_bookings': room_guest_bookings,
            'desk_folios': desk_folios,
            'all_guest_ledger_bookings': all_guest_ledger_bookings,
            'guest_pending_charges': guest_pending_charges,
            'guest_draft_invoices': guest_draft_invoices,
            'guest_posted_unpaid': guest_posted_unpaid,
            'guest_collected': guest_collected,
            'guest_advance_deposit_credit': guest_advance_deposit_credit,
            'guest_pending_billing': guest_pending_charges + guest_draft_invoices,
            'guest_room_ledger': guest_room_balance,
            'desk_folio_ledger': desk_folio_balance,
            'guest_ledger': guest_net_balance,
        }

    def _get_guest_pending_lines(self):
        lines = self.env['sale.order.line']
        _, _, all_guest_ledger_bookings = self._get_guest_ledger_bookings()
        for reservation in all_guest_ledger_bookings:
            lines |= reservation._get_routed_folio_lines('guest', invoiceable_only=True)
        return lines

    def _get_guest_draft_invoices(self):
        invoices = self.env['account.move']
        _, _, all_guest_ledger_bookings = self._get_guest_ledger_bookings()
        for reservation in all_guest_ledger_bookings:
            invoices |= reservation._get_routed_folio_invoices('guest').filtered(
                lambda inv: inv.move_type == 'out_invoice' and inv.state == 'draft'
            )
        return invoices

    def _get_guest_posted_unpaid_invoices(self):
        invoices = self.env['account.move']
        _, _, all_guest_ledger_bookings = self._get_guest_ledger_bookings()
        for reservation in all_guest_ledger_bookings:
            invoices |= reservation._get_routed_folio_invoices('guest').filtered(
                lambda inv: (
                    inv.move_type == 'out_invoice'
                    and inv.state == 'posted'
                    and inv.amount_residual > 0.01
                )
            )
        return invoices

    def _get_guest_collected_payments(self):
        payments = self.env['account.payment']
        guest_invoices = self._get_guest_posted_unpaid_invoices()
        _, _, all_guest_ledger_bookings = self._get_guest_ledger_bookings()
        for reservation in all_guest_ledger_bookings:
            guest_invoices |= reservation._get_routed_folio_invoices('guest').filtered(
                lambda inv: inv.move_type == 'out_invoice' and inv.state == 'posted'
            )

        for invoice in guest_invoices:
            payments |= invoice._get_reconciled_payments().filtered(
                lambda pay: (
                    pay.state in ('in_process', 'paid')
                    and pay.payment_type == 'inbound'
                    and not pay.is_advance_deposit
                )
            )
        return payments

    def _get_guest_advance_deposit_credit_payments(self):
        payments = self.env['account.payment']
        room_guest_bookings, _, _ = self._get_guest_ledger_bookings()
        for reservation in room_guest_bookings.filtered(
            lambda res: res._get_operational_folio_position()['deposit_credit'] > 0.01
        ):
            payments |= reservation._get_advance_deposit_payments(posted_only=True, inbound_only=True)
        return payments

    def _get_guest_pending_line_domain(self):
        line_ids = self._get_guest_pending_lines().ids
        return [('id', 'in', line_ids or [0])]

    def _get_guest_draft_invoice_domain(self):
        invoice_ids = self._get_guest_draft_invoices().ids
        return [('id', 'in', invoice_ids or [0])]

    def _get_guest_posted_unpaid_domain(self):
        invoice_ids = self._get_guest_posted_unpaid_invoices().ids
        return [('id', 'in', invoice_ids or [0])]

    def _get_guest_collected_payment_domain(self):
        payment_ids = self._get_guest_collected_payments().ids
        return [('id', 'in', payment_ids or [0])]

    def _get_guest_advance_deposit_credit_domain(self):
        payment_ids = self._get_guest_advance_deposit_credit_payments().ids
        return [('id', 'in', payment_ids or [0])]

    def action_refresh(self):
        company = self.env.company
        biz_date = company.hotel_business_date or fields.Date.context_today(self)
        RevenueReport = self.env['hotel.revenue.report'].sudo()
        
        for rec in self:
            rec.business_date = biz_date
            
            # 1. Total Rooms
            total_rooms_count = self.env['hotel.room'].search_count([])
            rec.total_rooms = total_rooms_count

            # 2. Live Physical Room Status
            rec.rooms_available = self.env['hotel.room'].search_count([('state', '=', 'vacant_clean')])
            rec.rooms_dirty = self.env['hotel.room'].search_count([('state', '=', 'vacant_dirty')])
            rec.rooms_occupied = self.env['hotel.room'].search_count([('state', 'in', ['occupied_clean', 'occupied_dirty'])])
            rec.rooms_blocked = self.env['hotel.room'].search_count([('state', '=', 'blocked')])

            # 3. Financials & Occupancy from the reconciled daily revenue report
            actual_rows = RevenueReport.search([
                ('date', '=', biz_date),
                ('revenue_type', '=', 'actual'),
            ])
            occupied_count = sum(actual_rows.mapped('occupied_count'))
            daily_revenue = sum(actual_rows.mapped('folio_total'))
            rec.total_revenue = daily_revenue

            if total_rooms_count > 0:
                rec.occupancy_rate = occupied_count / total_rooms_count
                rec.revpar = daily_revenue / total_rooms_count
            else:
                rec.occupancy_rate = 0.0
                rec.revpar = 0.0

            if occupied_count > 0:
                rec.adr = daily_revenue / occupied_count
            else:
                rec.adr = 0.0

            # 4. Forecast 
            forecast_labels = []
            forecast_rates = []
            for i in range(1, 8):
                target_date = biz_date + timedelta(days=i)
                date_label = target_date.strftime('%a, %b %d')
                occ_count = sum(RevenueReport.search([
                    ('date', '=', target_date),
                    ('revenue_type', '=', 'forecast'),
                ]).mapped('occupied_count'))
                rate = (occ_count / total_rooms_count) if total_rooms_count > 0 else 0.0
                forecast_labels.append(date_label)
                forecast_rates.append(rate)

            rec.label_day_1, rec.occ_day_1 = forecast_labels[0], forecast_rates[0]
            rec.label_day_2, rec.occ_day_2 = forecast_labels[1], forecast_rates[1]
            rec.label_day_3, rec.occ_day_3 = forecast_labels[2], forecast_rates[2]
            rec.label_day_4, rec.occ_day_4 = forecast_labels[3], forecast_rates[3]
            rec.label_day_5, rec.occ_day_5 = forecast_labels[4], forecast_rates[4]
            rec.label_day_6, rec.occ_day_6 = forecast_labels[5], forecast_rates[5]
            rec.label_day_7, rec.occ_day_7 = forecast_labels[6], forecast_rates[6]

            # 5. Flow counts 
            # (Added the Desk Folio shield to all of these!)
            arr_total = self.env['hotel.reservation'].search_count([('checkin_date', '=', biz_date), ('state', 'in', ['confirm', 'checkin']), ('is_desk_folio', '=', False)])
            arr_pending = self.env['hotel.reservation'].search_count([('checkin_date', '=', biz_date), ('state', '=', 'confirm'), ('is_desk_folio', '=', False)])
            rec.arrivals_display = f"{arr_pending}/{arr_total}"

            # Fixed the Total to include 'checkout_hold' so the math perfectly matches!
            dep_total = self.env['hotel.reservation'].search_count([('checkout_date', '=', biz_date), ('state', 'in', ['checkin', 'checkout_hold', 'checkout']), ('is_desk_folio', '=', False)])
            dep_pending = self.env['hotel.reservation'].search_count([('checkout_date', '=', biz_date), ('state', 'in', ['checkin', 'checkout_hold']), ('is_desk_folio', '=', False)])
            rec.departures_display = f"{dep_pending}/{dep_total}"
            stay_total = self.env['hotel.reservation'].search_count([('checkin_date', '<=', biz_date), ('checkout_date', '>', biz_date), ('state', 'in', ['checkin', 'confirm']), ('is_desk_folio', '=', False)])
            rec.stayovers_display = str(stay_total)

            # 6. Ledgers

            # Deposit Ledger = advance money collected from future/unarrived bookings
            future_bookings = rec._get_deposit_ledger_reservations()
            rec.deposit_ledger = sum(future_bookings.mapped('deposit_balance'))

            guest_breakdown = rec._get_guest_ledger_breakdown()
            room_guest_bookings = guest_breakdown['room_guest_bookings']
            desk_folios = guest_breakdown['desk_folios']
            all_guest_ledger_bookings = guest_breakdown['all_guest_ledger_bookings']

            rec.inhouse_total = sum(
                res._get_operational_folio_position()['folio_total_debit']
                for res in all_guest_ledger_bookings
            )
            rec.inhouse_collected = sum(
                res._get_operational_folio_position()['payments_received']
                for res in all_guest_ledger_bookings
            )

            rec.guest_pending_charges = guest_breakdown['guest_pending_charges']
            rec.guest_draft_invoices = guest_breakdown['guest_draft_invoices']
            rec.guest_posted_unpaid = guest_breakdown['guest_posted_unpaid']
            rec.guest_collected = guest_breakdown['guest_collected']
            rec.guest_advance_deposit_credit = guest_breakdown['guest_advance_deposit_credit']
            rec.guest_pending_billing = guest_breakdown['guest_pending_billing']
            rec.guest_room_ledger = guest_breakdown['guest_room_ledger']
            rec.desk_folio_ledger = guest_breakdown['desk_folio_ledger']
            rec.guest_ledger = guest_breakdown['guest_ledger']
            if rec.guest_ledger > 0.01:
                rec.guest_ledger_display_amount = rec.guest_ledger
                rec.guest_ledger_display_label = _('Guest Balance Due')
            elif rec.guest_ledger < -0.01:
                rec.guest_ledger_display_amount = abs(rec.guest_ledger)
                rec.guest_ledger_display_label = _('Guest Credit Balance')
            else:
                rec.guest_ledger_display_amount = 0.0
                rec.guest_ledger_display_label = _('Settled')

            routed_company_reservations = self.env['hotel.reservation'].search([
                ('sale_order_id', '!=', False),
                ('state', '!=', 'cancel'),
                ('city_ledger_id', '!=', False),
            ])

            # Company Pending Billing = company-routed charges not yet posted.
            rec.company_pending_billing = sum(
                res._get_company_pending_billing_amount() for res in routed_company_reservations
            )

            # City Ledger = posted unpaid company receivables only.
            rec.city_ledger = sum(res._get_company_outstanding_amount() for res in routed_company_reservations)

            # 7. NEW FIX: Querying the new Business Date column on Accounting!
            invoices_today = self.env['account.move'].search([('move_type', '=', 'out_invoice'), ('state', '=', 'posted'), ('hotel_business_date', '=', biz_date)])
            rec.today_invoiced = sum(invoices_today.mapped('amount_total'))

            payments_today = self.env['account.payment'].search([('hotel_business_date', '=', biz_date), ('state', 'in', ('in_process', 'paid')), ('payment_type', '=', 'inbound')])
            rec.today_collected = sum(payments_today.mapped('amount'))

            # 8. GUEST PORTAL ALERTS
            rec.req_upcoming = self.env['hotel.service.request'].search_count([('reservation_id.state', '=', 'confirm'), ('state', 'in', ['new', 'progress'])])
            rec.req_inhouse = self.env['hotel.service.request'].search_count([('reservation_id.state', 'in', ['checkin', 'checkout_hold']), ('state', 'in', ['new', 'progress'])])
            rec.req_history = self.env['hotel.service.request'].search_count([('reservation_id.state', '=', 'checkout'), ('state', 'in', ['new', 'progress'])])

    def _get_biz_date(self):
        return self.env.company.hotel_business_date or fields.Date.context_today(self)

    def action_view_arrivals(self): return self._get_action('Remaining Arrivals', 'hotel.reservation', [('checkin_date', '=', self._get_biz_date()), ('state', '=', 'confirm'), ('is_desk_folio', '=', False)])
    def action_view_departures(self): return self._get_action('Departures Today', 'hotel.reservation', [('checkout_date', '=', self._get_biz_date()), ('state', 'in', ['checkin', 'checkout_hold', 'checkout']), ('is_desk_folio', '=', False)])
    def action_view_stayovers(self): return self._get_action('Guests Staying Tonight', 'hotel.reservation', [('checkin_date', '<=', self._get_biz_date()), ('checkout_date', '>', self._get_biz_date()), ('state', 'in', ['checkin', 'confirm']), ('is_desk_folio', '=', False)])

    def action_walk_in_checkin(self):
        self.ensure_one()
        biz_date = self._get_biz_date()
        walk_in_source = self.env.ref('hotel_management.source_walk_in', raise_if_not_found=False)
        return {
            'name': _('Walk-In Check-In'),
            'type': 'ir.actions.act_window',
            'res_model': 'hotel.reservation',
            'views': [(self.env.ref('hotel_management.view_hotel_reservation_form').id, 'form')],
            'target': 'current',
            'context': {
                'default_checkin_date': biz_date,
                'default_checkout_date': biz_date + timedelta(days=1),
                'default_source_id': walk_in_source.id if walk_in_source else False,
                'default_booking_source_category_id': walk_in_source.category_id.id if walk_in_source else False,
                'default_booking_sub_source_id': walk_in_source.id if walk_in_source else False,
            },
        }

    def action_view_vacant_clean(self): return self._get_action('Ready Rooms', 'hotel.room', [('state', '=', 'vacant_clean')])
    def action_view_dirty_rooms(self): return self._get_action('Rooms to Clean', 'hotel.room', [('state', '=', 'vacant_dirty')])
    def action_view_occupied_rooms(self): return self._get_action('In-House Rooms', 'hotel.room', [('state', 'in', ['occupied_clean', 'occupied_dirty'])])
    def action_view_maintenance_rooms(self): return self._get_action('Blocked / Maintenance', 'hotel.room', [('state', '=', 'blocked')])

    def action_view_deposit_ledger(self): return self._get_action('Deposit Ledger', 'hotel.reservation', [('state', 'in', ['draft', 'confirm']), ('is_desk_folio', '=', False), ('folio_type', '=', 'guest'), ('deposit_balance', '>', 0)])
    def action_view_guest_ledger(self):
        _, _, all_guest_ledger_bookings = self._get_guest_ledger_bookings()
        reservation_ids = all_guest_ledger_bookings.filtered(
            lambda res: (
                abs(res._get_operational_folio_position()['operational_balance']) > 0.01
                or res._get_operational_folio_position()['credit_balance'] > 0.01
            )
        ).ids
        return self._get_action('Guest Ledger Detail', 'hotel.reservation', [('id', 'in', reservation_ids or [0])])

    def action_view_guest_pending_billing(self):
        _, _, all_guest_ledger_bookings = self._get_guest_ledger_bookings()
        reservation_ids = all_guest_ledger_bookings.filtered(
            lambda res: res._get_guest_pending_billing_amount() > 0.01
        ).ids
        return self._get_action('Guest Pending Billing', 'hotel.reservation', [('id', 'in', reservation_ids or [0])])

    def action_view_guest_pending_charges(self):
        return self._get_action('Guest Pending Charges', 'sale.order.line', self._get_guest_pending_line_domain())

    def action_view_guest_draft_invoices(self):
        action = self.env['ir.actions.actions']._for_xml_id('account.action_move_out_invoice_type')
        action['domain'] = self._get_guest_draft_invoice_domain()
        action['context'] = {'default_move_type': 'out_invoice'}
        return action

    def action_view_guest_posted_unpaid(self):
        action = self.env['ir.actions.actions']._for_xml_id('account.action_move_out_invoice_type')
        action['domain'] = self._get_guest_posted_unpaid_domain()
        action['context'] = {'default_move_type': 'out_invoice'}
        return action

    def action_view_guest_collected(self):
        return self._get_action('Guest Collected Payments', 'account.payment', self._get_guest_collected_payment_domain())

    def action_view_guest_advance_deposit_credit(self):
        return self._get_action(
            'Advance Deposits / Guest Credit',
            'account.payment',
            self._get_guest_advance_deposit_credit_domain(),
        )

    def action_view_guest_room_ledger(self):
        room_guest_bookings, _, _ = self._get_guest_ledger_bookings()
        reservation_ids = room_guest_bookings.filtered(
            lambda res: abs(res._get_operational_folio_position()['operational_balance']) > 0.01
        ).ids
        return self._get_action('Guest Room Net', 'hotel.reservation', [('id', 'in', reservation_ids or [0])])

    def action_view_desk_folio_ledger(self):
        _, desk_folios, _ = self._get_guest_ledger_bookings()
        reservation_ids = desk_folios.filtered(
            lambda res: abs(res._get_operational_folio_position()['operational_balance']) > 0.01
        ).ids
        return self._get_action('Desk Folio Net', 'hotel.reservation', [('id', 'in', reservation_ids or [0])])

    def action_view_company_pending_billing(self):
        return self._get_action(
            'Company Pending Billing',
            'hotel.reservation',
            [('state', '!=', 'cancel'), ('company_pending_billing', '>', 0)],
        )
    def action_view_city_ledger(self):
        action = self.env['ir.actions.actions']._for_xml_id('hotel_management.action_hotel_city_ledger_invoices')
        action['domain'] = self._get_city_ledger_invoice_domain()
        return action
    
    # NEW FIX: The dashboard buttons now filter exactly by the Business Date column!
    def action_view_today_invoices(self): return self._get_action('Today Invoices', 'account.move', [('move_type', '=', 'out_invoice'), ('state', '=', 'posted'), ('hotel_business_date', '=', self._get_biz_date())])
    def action_view_today_receipts(self): 
        self.ensure_one()
        receipt_tree = self.env.ref('hotel_management.view_hotel_receipt_tree', raise_if_not_found=False)
        domain = [
            ('hotel_business_date', '=', self._get_biz_date()),
            ('state', 'in', ['in_process', 'paid']),
            ('payment_type', '=', 'inbound'),
            ('hotel_reservation_id', '!=', False),
            ('voids_advance_deposit_payment_id', '=', False),
            ('advance_deposit_void_payment_ids', '=', False),
        ]
        views = [(receipt_tree.id, 'list'), (False, 'form')] if receipt_tree else [(False, 'list'), (False, 'form')]
        return {
            'name': _("Today's Receipts"),
            'type': 'ir.actions.act_window',
            'res_model': 'account.payment',
            'view_mode': 'list,form',
            'views': views,
            'domain': domain,
            'context': {'create': False},
        }

    def action_view_req_upcoming(self): return self._get_action('Upcoming Guest Alerts', 'hotel.service.request', [('reservation_id.state', '=', 'confirm'), ('state', 'in', ['new', 'progress'])])
    def action_view_req_inhouse(self): return self._get_action('In-House Guest Alerts', 'hotel.service.request', [('reservation_id.state', 'in', ['checkin', 'checkout_hold']), ('state', 'in', ['new', 'progress'])])
    def action_view_req_history(self): return self._get_action('Past Guest Alerts', 'hotel.service.request', [('reservation_id.state', '=', 'checkout'), ('state', 'in', ['new', 'progress'])])

    def _get_action(self, name, res_model, domain):
        return {
            'name': name,
            'type': 'ir.actions.act_window',
            'res_model': res_model,
            'view_mode': 'list,form' if res_model != 'hotel.room' else 'kanban,list,form',
            'domain': domain,
        }
    
    def action_view_chat_logs(self):
        self.ensure_one()
        guest_message_model = self.env['hotel.guest.message']
        guest_message_model._check_staff_access()
        if not guest_message_model._table_is_ready():
            return {
                'type': 'ir.actions.client',
                'tag': 'display_notification',
                'params': {
                    'title': _('Guest Chat Logs Not Ready'),
                    'message': _('Upgrade the Hotel Management module to initialize guest message tracking.'),
                    'type': 'warning',
                    'sticky': True,
                },
            }
        messages = guest_message_model.search([('is_read', '=', False)])
        messages.action_mark_as_read()
        return {
            'name': 'Guest Chat Logs',
            'type': 'ir.actions.act_window',
            'res_model': 'hotel.guest.message',
            'view_mode': 'list,form',
            'domain': [],
            'context': {'create': False},
        }

    @api.model
    def get_monthly_stats(self, start_date_str, end_date_str):
        start_date = fields.Date.from_string(start_date_str)
        end_date = fields.Date.from_string(end_date_str)
        
        total_rooms = self.env['hotel.room'].search_count([])
        if total_rooms == 0:
            return []

        report_rows = self.env['hotel.revenue.report'].sudo().search([
            ('date', '>=', start_date),
            ('date', '<=', end_date),
            ('revenue_type', '=', 'actual'),
        ])

        stats_list = []
        current_date = start_date
        
        while current_date <= end_date:
            date_str = fields.Date.to_string(current_date)
            day_rows = report_rows.filtered(lambda row: row.date == current_date)
            occupied_count = sum(day_rows.mapped('occupied_count'))
            daily_rev = sum(day_rows.mapped('folio_total'))
            
            occ_pc = (occupied_count / total_rooms) * 100.0
            adr = (daily_rev / occupied_count) if occupied_count > 0 else 0.0
            revpar = daily_rev / total_rooms
            
            stats_list.append({
                'date': date_str,
                'occupancy_pc': occ_pc,
                'adr': adr,
                'revpar': revpar,
                'total_revenue': daily_rev
            })
            current_date += timedelta(days=1)
            
        return stats_list

