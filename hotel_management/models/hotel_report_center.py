from odoo import api, fields, models, _
from odoo.exceptions import UserError, ValidationError

import base64
import io
import re
import datetime

try:
    import xlsxwriter
except Exception:
    xlsxwriter = None


class HotelReportCenter(models.TransientModel):
    _name = 'hotel.report.center'
    _description = 'Hotel Report Center'

    report_code = fields.Selection(
        [
            ('arrival', 'Arrival List'),
            ('departure', 'Departure List'),
            ('inhouse', 'In-House Guest List'),
            ('reservation', 'Reservation List'),
            ('payment_history', 'Payment History'),
            ('deposit_ledger', 'Deposit Ledger'),
            ('invoice_issued', 'Invoice Issued'),
            ('night_audit', 'Night Audit Summary'),
        ],
        string='Report',
        default='arrival',
        required=True,
    )

    report_output = fields.Selection(
        [
            ('standard', 'Standard'),
            ('with_company', 'With Company'),
            ('with_booking_source', 'With Booking Source'),
            ('with_market_segment', 'With Market Segment'),
            ('with_guest_class', 'With Guest Class'),
            ('with_rate', 'With Rate'),
            ('with_nationality', 'With Nationality'),
        ],
        string='Report Output',
        default='standard',
        required=True,
    )

    sort_by = fields.Selection(
        [
            ('reference', 'Reference'),
            ('guest_name', 'Guest / Customer'),
            ('room_name', 'Room / Reservation'),
            ('checkin', 'Check-In'),
            ('checkout', 'Check-Out'),
            ('nights', 'Nights'),
            ('rate', 'Rate'),
            ('status', 'Status'),
            ('amount', 'Amount'),

            ('company_name', 'Company'),
            ('booking_source', 'Booking Source'),
            ('market_segment', 'Market Segment'),
            ('guest_class', 'Guest Class'),
            ('nationality', 'Nationality'),
        ],
        string='Sort By',
        default='checkin',
        required=True,
    )

    sort_order = fields.Selection(
        [
            ('asc', 'Ascending'),
            ('desc', 'Descending'),
        ],
        string='Sort Order',
        default='asc',
        required=True,
    )

    currency_id = fields.Many2one(
        'res.currency',
        string='Currency',
        related='company_id.currency_id',
        readonly=True,
    )

    print_style = fields.Selection(
        [
            ('summary', 'Summary'),
            ('detail', 'Detail'),
        ],
        string='Print Style',
        default='summary',
        required=True,
    )

    report_title = fields.Char(
        string='Report Title',
        compute='_compute_report_title',
    )

    company_id = fields.Many2one(
        'res.company',
        string='Company',
        default=lambda self: self.env.company,
        required=True,
    )

    date_from = fields.Date(
        string='Date From',
        default=lambda self: (
            self.env.company.hotel_business_date
            if 'hotel_business_date' in self.env['res.company']._fields
            else fields.Date.context_today(self)
        ),
        required=True,
    )

    date_to = fields.Date(
        string='Date To',
        default=lambda self: (
            self.env.company.hotel_business_date
            if 'hotel_business_date' in self.env['res.company']._fields
            else fields.Date.context_today(self)
        ),
        required=True,
    )

    line_ids = fields.One2many(
        'hotel.report.center.line',
        'wizard_id',
        string='Preview Lines',
        readonly=True,
    )

    total_amount = fields.Float(
        string='Total Amount',
        compute='_compute_total_amount',
    )
    
    def _safe_float(self, value):
        try:
            return float(value or 0.0)
        except Exception:
            return 0.0

    def _sort_lines(self, lines):
        self.ensure_one()

        key_map = {
            'reference': lambda l: (l.get('ref') or '').lower(),
            'guest_name': lambda l: (l.get('guest_name') or '').lower(),
            'room_name': lambda l: (l.get('room_name') or '').lower(),

            'checkin': lambda l: l.get('checkin') or l.get('checkin_date') or l.get('date') or '',
            'checkout': lambda l: l.get('checkout') or l.get('checkout_date') or '',

            'nights': lambda l: int(l.get('nights') or 0),
            'rate': lambda l: self._safe_float(l.get('rate') or l.get('rate_amount')),
            'status': lambda l: (l.get('status') or '').lower(),
            'amount': lambda l: self._safe_float(l.get('amount')),

            'company_name': lambda l: (l.get('company_name') or '').lower(),
            'booking_source': lambda l: (l.get('booking_source') or l.get('source_name') or '').lower(),
            'market_segment': lambda l: (l.get('market_segment') or '').lower(),
            'guest_class': lambda l: (l.get('guest_class') or '').lower(),
            'nationality': lambda l: (l.get('nationality') or '').lower(),
        }

        sort_key = key_map.get(self.sort_by, key_map['checkin'])
        reverse = self.sort_order == 'desc'

        return sorted(lines, key=sort_key, reverse=reverse)

    @api.depends('report_code', 'report_output', 'print_style')
    def _compute_report_title(self):
        report_map = dict(self._fields['report_code'].selection)
        output_map = dict(self._fields['report_output'].selection)
        style_map = dict(self._fields['print_style'].selection)

        for rec in self:
            base_title = report_map.get(rec.report_code, 'Report')
            output_title = output_map.get(rec.report_output, 'Standard')
            style_title = style_map.get(rec.print_style, '')

            title = base_title

            if rec.report_output and rec.report_output != 'standard':
                title = "%s - %s" % (title, output_title)

            if style_title:
                title = "%s (%s)" % (title, style_title)

            rec.report_title = title

    def _get_report_base_filename(self):
        return self.report_title or 'Hotel Report'
    
    @api.depends('line_ids.amount')
    def _compute_total_amount(self):
        for rec in self:
            rec.total_amount = sum(rec.line_ids.mapped('amount'))

    @api.constrains('date_from', 'date_to')
    def _check_date_range(self):
        for rec in self:
            if rec.date_from and rec.date_to and rec.date_to < rec.date_from:
                raise ValidationError(_("Date To cannot be earlier than Date From."))

    # -------------------------------------------------------------------------
    # Helpers
    # -------------------------------------------------------------------------

    def _get_report_titles(self):
        return {
            'arrival': _('Arrival List'),
            'departure': _('Departure List'),
            'inhouse': _('In-House Guest List'),
            'reservation': _('Reservation List'),
            'payment_history': _('Payment History'),
            'deposit_ledger': _('Deposit Ledger'),
            'invoice_issued': _('Invoice Issued'),
            'night_audit': _('Night Audit Summary'),
        }

    def _model_exists(self, model_name):
        return bool(self.env['ir.model'].sudo().search([('model', '=', model_name)], limit=1))

    def _get_model(self, model_name):
        if not self._model_exists(model_name):
            raise UserError(_("Model %s does not exist in this database.") % model_name)
        return self.env[model_name].sudo()

    def _has_field(self, model_name, field_name):
        if not self._model_exists(model_name):
            return False
        return field_name in self.env[model_name]._fields

    def _company_domain(self, model_name):
        if self.company_id and self._has_field(model_name, 'company_id'):
            return [('company_id', '=', self.company_id.id)]
        return []

    def _date_domain(self, model_name, field_name):
        if not self._has_field(model_name, field_name):
            return []

        domain = []
        if self.date_from:
            domain.append((field_name, '>=', self.date_from))
        if self.date_to:
            domain.append((field_name, '<=', self.date_to))
        return domain

    def _get_order(self, model_name, field_names):
        valid_fields = [field for field in field_names if self._has_field(model_name, field)]
        return ', '.join(valid_fields) if valid_fields else 'id'

    def _raw_value(self, record, *field_names):
        for field_name in field_names:
            if field_name == 'display_name':
                return record.display_name

            if field_name in record._fields:
                value = record[field_name]
                if value not in [False, None, '']:
                    return value

        return False

    def _display(self, record, *field_names):
        value = self._raw_value(record, *field_names)

        if not value:
            return ''

        if hasattr(value, 'display_name'):
            return value.display_name

        return str(value)

    def _amount(self, record, *field_names):
        for field_name in field_names:
            if field_name in record._fields:
                return record[field_name] or 0.0
        return 0.0

    def _selection_label(self, record, field_name):
        if field_name not in record._fields:
            return ''

        value = record[field_name]
        if not value:
            return ''

        field = record._fields[field_name]
        selection = field.selection

        if isinstance(selection, list):
            return dict(selection).get(value, value)

        return str(value)

    def _reservation_base_domain(self):
        domain = self._company_domain('hotel.reservation')

        if self._has_field('hotel.reservation', 'is_desk_folio'):
            domain.append(('is_desk_folio', '=', False))

        return domain

    def _reservation_overlap_domain(self):
        domain = self._reservation_base_domain()

        if self._has_field('hotel.reservation', 'checkin_date'):
            domain.append(('checkin_date', '<=', self.date_to))

        if self._has_field('hotel.reservation', 'checkout_date'):
            domain.append(('checkout_date', '>=', self.date_from))

        return domain

    def _date_value(self, record, field_name):
        if field_name in record._fields:
            return record[field_name] or False
        return False

    def _reservation_nights(self, record):
        checkin = self._date_value(record, 'checkin_date')
        checkout = self._date_value(record, 'checkout_date')

        if not checkin or not checkout:
            return 0

        try:
            checkin_date = fields.Date.to_date(checkin)
            checkout_date = fields.Date.to_date(checkout)
            return max((checkout_date - checkin_date).days, 0)
        except Exception:
            return 0

    def _reservation_rate_amount(self, record):
        possible_fields = [
            'daily_rate',
            'room_rate',
            'rate_amount',
            'rate_price',
            'price_unit',
            'rate',
        ]

        for field_name in possible_fields:
            if field_name in record._fields:
                field = record._fields[field_name]
                if field.type in ['float', 'monetary', 'integer']:
                    return record[field_name] or 0.0

        # fallback from reservation / folio lines if available
        possible_line_fields = [
            'reservation_line_ids',
            'folio_line_ids',
            'order_line',
            'sale_order_line_ids',
        ]

        for line_field in possible_line_fields:
            if line_field not in record._fields:
                continue

            for line in record[line_field]:
                line_name = ''
                if 'name' in line._fields:
                    line_name = (line.name or '').lower()

                is_room_line = (
                    'room' in line_name
                    or 'accommodation' in line_name
                    or 'night' in line_name
                )

                if not is_room_line:
                    continue

                for amount_field in ['price_unit', 'rate_amount', 'room_rate', 'amount', 'price_subtotal']:
                    if amount_field in line._fields:
                        field = line._fields[amount_field]
                        if field.type in ['float', 'monetary', 'integer']:
                            return line[amount_field] or 0.0

        return 0.0

    def _room_type_name(self, record):
        value = self._display(record, 'room_type_id')
        if value:
            return value

        if 'room_id' in record._fields and record.room_id:
            room = record.room_id
            if 'room_type_id' in room._fields and room.room_type_id:
                return room.room_type_id.display_name

        return ''

    def _reservation_source_name(self, record):
        return self._display(
            record,
            'booking_source_id',
            'source_id',
            'agent_id',
            'company_partner_id',
            'market_segment_id',
        )

    def _line_vals(self, **kwargs):
        return {
            'source_name': kwargs.get('source_name') or '',
            'date': kwargs.get('date') or '',
            'ref': kwargs.get('ref') or '',
            'guest_name': kwargs.get('guest_name') or '',
            'room_name': kwargs.get('room_name') or '',
            'partner_name': kwargs.get('partner_name') or '',
            'status': kwargs.get('status') or '',
            'payment_method': kwargs.get('payment_method') or '',
            'amount': kwargs.get('amount') or 0.0,
            'note': kwargs.get('note') or '',

            'checkin': kwargs.get('checkin') or '',
            'checkout': kwargs.get('checkout') or '',
            'nights': kwargs.get('nights') or 0,
            'rate': kwargs.get('rate') or 0.0,

            'company_name': kwargs.get('company_name') or '',
            'booking_source': kwargs.get('booking_source') or '',
            'market_segment': kwargs.get('market_segment') or '',
            'guest_class': kwargs.get('guest_class') or '',
            'nationality': kwargs.get('nationality') or '',
        }

    # -------------------------------------------------------------------------
    # Build report data
    # -------------------------------------------------------------------------

    def _reservation_field_display(self, record, known_fields=None, label_keywords=None, comodel_name=None):
        known_fields = known_fields or []
        label_keywords = label_keywords or []

        # 1) Try known technical fields first
        for field_name in known_fields:
            if field_name in record._fields:
                value = record[field_name]
                if value:
                    if hasattr(value, 'display_name'):
                        return value.display_name
                    return str(value)

        # 2) Try to detect by field label/string
        for field_name, field in record._fields.items():
            field_label = (getattr(field, 'string', '') or '').lower()

            if not any(keyword in field_label for keyword in label_keywords):
                continue

            if comodel_name and getattr(field, 'comodel_name', False) != comodel_name:
                continue

            try:
                value = record[field_name]
            except Exception:
                continue

            if value:
                if hasattr(value, 'display_name'):
                    return value.display_name
                return str(value)

        return ''

    def _reservation_company_name(self, record):
        """
        Company shown in Arrival / Reservation reports.
        This is City Ledger / Bill To company, not hotel property company.
        Actual field from reservation form tooltip: city_ledger_id
        """
        return self._reservation_field_display(
            record,
            known_fields=[
                'city_ledger_id',          # correct field from your screenshot
                'city_ledger_partner_id',
                'bill_to_partner_id',
                'billing_partner_id',
                'company_partner_id',
                'corporate_partner_id',
                'partner_company_id',
                'invoice_partner_id',
                'partner_invoice_id',
                'routing_company_id',
                'route_company_partner_id',
            ],
            label_keywords=[
                'city ledger',
                'bill to',
                'billing',
                'invoice partner',
                'company',
            ],
            comodel_name='res.partner',
        )

    def _reservation_booking_source_name(self, record):
        return self._reservation_field_display(
            record,
            known_fields=[
                'booking_source_id',
                'source_id',
                'reservation_source_id',
                'agent_id',
                'ota_id',
                'channel_id',
            ],
            label_keywords=[
                'booking source',
                'source',
                'agent',
                'ota',
                'channel',
            ],
        )

    def _reservation_market_segment_name(self, record):
        return self._reservation_field_display(
            record,
            known_fields=[
                'market_segment_id',
                'segment_id',
                'market_id',
            ],
            label_keywords=[
                'market segment',
                'segment',
            ],
        )

    def _reservation_guest_class_name(self, record):
        return self._reservation_field_display(
            record,
            known_fields=[
                'guest_classification_id',
                'guest_class_id',
                'guest_type_id',
                'vip_status',
            ],
            label_keywords=[
                'guest class',
                'guest classification',
                'guest type',
                'vip',
            ],
        )

    def _reservation_nationality_name(self, record):
        value = self._reservation_field_display(
            record,
            known_fields=[
                'nationality_id',
                'country_id',
            ],
            label_keywords=[
                'nationality',
                'country',
            ],
        )
        if value:
            return value

        if 'partner_id' in record._fields and record.partner_id:
            partner = record.partner_id
            if 'country_id' in partner._fields and partner.country_id:
                return partner.country_id.display_name

        return ''

    def _build_arrival_lines(self):
        Reservation = self._get_model('hotel.reservation')

        domain = self._reservation_base_domain()
        domain += self._date_domain('hotel.reservation', 'checkin_date')

        if self._has_field('hotel.reservation', 'state'):
            domain.append(('state', 'not in', ['cancel', 'cancelled', 'no_show', 'noshow', 'blocked']))

        records = Reservation.search(
            domain,
            order=self._get_order('hotel.reservation', ['checkin_date', 'name'])
        )

        lines = []
        for rec in records:
            lines.append(self._line_vals(
                date=self._display(rec, 'checkin_date'),
                ref=self._display(rec, 'name', 'display_name'),
                guest_name=self._display(rec, 'partner_id', 'guest_id', 'customer_id'),
                room_name=self._display(rec, 'room_id'),
                partner_name=self._reservation_booking_source_name(rec),
                status=self._selection_label(rec, 'state'),
                checkin=self._display(rec, 'checkin_date'),
                checkout=self._display(rec, 'checkout_date'),
                nights=int(getattr(rec, 'duration', 0) or 0),
                rate=float(
                    getattr(rec, 'rate', 0.0)
                    or getattr(rec, 'room_rate', 0.0)
                    or getattr(rec, 'amount_total', 0.0)
                    or 0.0
                ),
                amount=float(getattr(rec, 'amount_total', 0.0) or 0.0),
                note=self._display(rec, 'checkout_date'),
                company_name=self._reservation_company_name(rec),
                booking_source=self._display(rec, 'booking_source_id'),
                market_segment=self._display(rec, 'market_segment_id'),
                guest_class=self._display(rec, 'guest_classification_id'),
                nationality=self._display(rec, 'nationality_id'),
            ))

        return lines

    def _build_departure_lines(self):
        Reservation = self._get_model('hotel.reservation')

        domain = self._reservation_base_domain()
        domain += self._date_domain('hotel.reservation', 'checkout_date')

        if self._has_field('hotel.reservation', 'state'):
            domain.append(('state', 'not in', ['cancel', 'cancelled', 'no_show', 'noshow', 'blocked']))

        records = Reservation.search(
            domain,
            order=self._get_order('hotel.reservation', ['checkout_date', 'name'])
        )

        lines = []
        for rec in records:
            lines.append(self._line_vals(
                date=self._display(rec, 'checkin_date'),
                ref=self._display(rec, 'name', 'display_name'),
                guest_name=self._display(rec, 'partner_id', 'guest_id', 'customer_id'),
                room_name=self._display(rec, 'room_id'),
                partner_name=self._reservation_booking_source_name(rec),
                status=self._selection_label(rec, 'state'),
                checkin=self._display(rec, 'checkin_date'),
                checkout=self._display(rec, 'checkout_date'),
                nights=int(getattr(rec, 'duration', 0) or 0),
                rate=float(
                    getattr(rec, 'rate', 0.0)
                    or getattr(rec, 'room_rate', 0.0)
                    or getattr(rec, 'amount_total', 0.0)
                    or 0.0
                ),
                amount=float(getattr(rec, 'amount_total', 0.0) or 0.0),
                note=self._display(rec, 'checkout_date'),
                company_name=self._reservation_company_name(rec),
                booking_source=self._display(rec, 'booking_source_id'),
                market_segment=self._display(rec, 'market_segment_id'),
                guest_class=self._display(rec, 'guest_classification_id'),
                nationality=self._display(rec, 'nationality_id'),
            ))

        return lines

    def _build_inhouse_lines(self):
        Reservation = self._get_model('hotel.reservation')

        domain = self._reservation_base_domain()

        if self._has_field('hotel.reservation', 'state'):
            domain.append(('state', 'in', ['checkin', 'checkout_hold']))

        records = Reservation.search(
            domain,
            order=self._get_order('hotel.reservation', ['room_id', 'checkout_date', 'name'])
        )

        lines = []
        for rec in records:
            lines.append(self._line_vals(
                date=self._display(rec, 'checkin_date'),
                ref=self._display(rec, 'name', 'display_name'),
                guest_name=self._display(rec, 'partner_id', 'guest_id', 'customer_id'),
                room_name=self._display(rec, 'room_id'),
                partner_name=self._reservation_booking_source_name(rec),
                status=self._selection_label(rec, 'state'),
                checkin=self._display(rec, 'checkin_date'),
                checkout=self._display(rec, 'checkout_date'),
                nights=int(getattr(rec, 'duration', 0) or 0),
                rate=float(
                    getattr(rec, 'rate', 0.0)
                    or getattr(rec, 'room_rate', 0.0)
                    or getattr(rec, 'amount_total', 0.0)
                    or 0.0
                ),
                amount=float(getattr(rec, 'amount_total', 0.0) or 0.0),
                note=self._display(rec, 'checkout_date'),
                company_name=self._reservation_company_name(rec),
                booking_source=self._display(rec, 'booking_source_id'),
                market_segment=self._display(rec, 'market_segment_id'),
                guest_class=self._display(rec, 'guest_classification_id'),
                nationality=self._display(rec, 'nationality_id'),
            ))

        return lines

    def _build_reservation_lines(self):
        Reservation = self._get_model('hotel.reservation')

        domain = self._reservation_overlap_domain()
        records = Reservation.search(
            domain,
            order=self._get_order('hotel.reservation', ['checkin_date', 'name'])
        )

        lines = []
        for rec in records:
            lines.append(self._line_vals(
                date=self._display(rec, 'checkin_date'),
                ref=self._display(rec, 'name', 'display_name'),
                guest_name=self._display(rec, 'partner_id', 'guest_id', 'customer_id'),
                room_name=self._display(rec, 'room_id'),
                partner_name=self._reservation_booking_source_name(rec),
                status=self._selection_label(rec, 'state'),
                checkin=self._display(rec, 'checkin_date'),
                checkout=self._display(rec, 'checkout_date'),
                nights=int(getattr(rec, 'duration', 0) or 0),
                rate=float(
                    getattr(rec, 'rate', 0.0)
                    or getattr(rec, 'room_rate', 0.0)
                    or getattr(rec, 'amount_total', 0.0)
                    or 0.0
                ),
                amount=float(getattr(rec, 'amount_total', 0.0) or 0.0),
                note=self._display(rec, 'checkout_date'),
                company_name=self._reservation_company_name(rec),
                booking_source=self._reservation_booking_source_name(rec),
                market_segment=self._reservation_market_segment_name(rec),
                guest_class=self._reservation_guest_class_name(rec),
                nationality=self._reservation_nationality_name(rec),
            ))

        return lines

    def _build_payment_history_lines(self):
        Payment = self._get_model('account.payment')

        date_field = 'hotel_business_date' if self._has_field('account.payment', 'hotel_business_date') else 'date'

        domain = self._company_domain('account.payment')
        domain += self._date_domain('account.payment', date_field)

        if self._has_field('account.payment', 'state'):
            domain.append(('state', 'not in', ['draft', 'cancel', 'canceled']))

        records = Payment.search(domain, order=self._get_order('account.payment', [date_field, 'name']))

        lines = []
        for rec in records:
            if self._has_field('account.payment', 'hotel_net_receipt_amount'):
                amount = rec.hotel_net_receipt_amount or 0.0
            else:
                amount = rec.amount or 0.0
                if self._has_field('account.payment', 'payment_type') and rec.payment_type == 'outbound':
                    amount = -abs(amount)

            lines.append(self._line_vals(
                date=self._display(rec, date_field),
                ref=self._display(rec, 'name', 'display_name'),
                guest_name=self._display(rec, 'partner_id'),
                partner_name=self._display(rec, 'journal_id'),
                status=self._selection_label(rec, 'state'),
                payment_method=self._display(rec, 'payment_method_line_id'),
                amount=amount,
                note=self._display(rec, 'hotel_payment_activity_type', 'memo', 'ref'),
            ))
        return lines

    def _build_deposit_ledger_lines(self):
        Payment = self._get_model('account.payment')

        date_field = 'hotel_business_date' if self._has_field('account.payment', 'hotel_business_date') else 'date'

        domain = self._company_domain('account.payment')
        domain += self._date_domain('account.payment', date_field)

        if self._has_field('account.payment', 'hotel_payment_activity_type'):
            domain.append(('hotel_payment_activity_type', 'in', ['advance_deposit', 'deposit_void', 'deposit_refund', 'deposit_transfer']))
        elif self._has_field('account.payment', 'hotel_reservation_id'):
            domain.append(('hotel_reservation_id', '!=', False))

        records = Payment.search(domain, order=self._get_order('account.payment', [date_field, 'name']))

        lines = []
        for rec in records:
            if self._has_field('account.payment', 'hotel_net_receipt_amount'):
                amount = rec.hotel_net_receipt_amount or 0.0
            else:
                amount = rec.amount or 0.0
                if self._has_field('account.payment', 'payment_type') and rec.payment_type == 'outbound':
                    amount = -abs(amount)

            lines.append(self._line_vals(
                date=self._display(rec, date_field),
                ref=self._display(rec, 'name', 'display_name'),
                guest_name=self._display(rec, 'partner_id'),
                room_name=self._display(rec, 'hotel_reservation_id'),
                partner_name=self._display(rec, 'journal_id'),
                status=self._selection_label(rec, 'state'),
                payment_method=self._display(rec, 'payment_method_line_id'),
                amount=amount,
                note=self._display(rec, 'hotel_payment_activity_type', 'memo', 'ref'),
            ))
        return lines

    def _build_invoice_issued_lines(self):
        Move = self._get_model('account.move')

        date_field = 'hotel_business_date' if self._has_field('account.move', 'hotel_business_date') else 'invoice_date'

        domain = self._company_domain('account.move')
        domain += self._date_domain('account.move', date_field)

        if self._has_field('account.move', 'move_type'):
            domain.append(('move_type', '=', 'out_invoice'))

        if self._has_field('account.move', 'state'):
            domain.append(('state', '=', 'posted'))

        records = Move.search(domain, order=self._get_order('account.move', [date_field, 'name']))

        lines = []
        for rec in records:
            lines.append(self._line_vals(
                date=self._display(rec, date_field),
                ref=self._display(rec, 'name', 'display_name'),
                guest_name=self._display(rec, 'partner_id'),
                status=self._selection_label(rec, 'payment_state') or self._selection_label(rec, 'state'),
                amount=self._amount(rec, 'amount_total'),
                note='Residual: %.2f' % self._amount(rec, 'amount_residual'),
            ))
        return lines

    def _build_night_audit_lines(self):
        possible_models = [
            'hotel.night.audit',
            'hotel.night.audit.log',
            'hotel.daily.audit',
            'hotel.revenue.report',
        ]

        model_name = False
        for possible_model in possible_models:
            if self._model_exists(possible_model):
                model_name = possible_model
                break

        if not model_name:
            raise UserError(_("No Night Audit report model found yet."))

        Model = self._get_model(model_name)

        date_field = False
        for possible_date_field in ['business_date', 'date', 'hotel_business_date', 'create_date']:
            if self._has_field(model_name, possible_date_field):
                date_field = possible_date_field
                break

        domain = self._company_domain(model_name)
        if date_field:
            domain += self._date_domain(model_name, date_field)

        records = Model.search(domain, order=self._get_order(model_name, [date_field or 'id', 'name']))

        lines = []
        for rec in records:
            lines.append(self._line_vals(
                date=self._display(rec, date_field) if date_field else '',
                ref=self._display(rec, 'name', 'display_name'),
                guest_name=self._display(rec, 'reservation_id', 'partner_id', 'guest_id'),
                room_name=self._display(rec, 'room_id'),
                partner_name=self._display(rec, 'journal_id', 'company_id'),
                status=self._display(rec, 'revenue_type') or self._selection_label(rec, 'state'),
                amount=self._amount(rec, 'folio_total', 'total_revenue', 'room_revenue', 'amount_total', 'amount'),
                note=self._display(rec, 'note', 'description'),
            ))
        return lines
        
    def _build_report_lines(self):
        self.ensure_one()

        builders = {
            'arrival': self._build_arrival_lines,
            'departure': self._build_departure_lines,
            'inhouse': self._build_inhouse_lines,
            'reservation': self._build_reservation_lines,
            'payment_history': self._build_payment_history_lines,
            'deposit_ledger': self._build_deposit_ledger_lines,
            'invoice_issued': self._build_invoice_issued_lines,
            'night_audit': self._build_night_audit_lines,
        }

        builder = builders.get(self.report_code)
        if not builder:
            raise UserError(_("This report is not ready yet."))

        values = builder()
        values = self._sort_lines(values)

        for index, value in enumerate(values, 1):
            value['line_no'] = index

        return values

    def _generate_preview_lines(self):
        self.ensure_one()

        values = self._build_report_lines()

        self.write({
            'line_ids': [(5, 0, 0)] + [(0, 0, value) for value in values],
        })

        return True

    # -------------------------------------------------------------------------
    # Buttons
    # -------------------------------------------------------------------------

    def action_preview(self):
        self.ensure_one()
        self._generate_preview_lines()

        return {
            'type': 'ir.actions.client',
            'tag': 'reload',
        }

    def action_print_pdf(self):
        self.ensure_one()
        self._generate_preview_lines()

        return self.env.ref(
            'hotel_management.action_report_hotel_report_center_pdf'
        ).report_action(self)

    def action_export_excel(self):
        self.ensure_one()
        self._generate_preview_lines()

        if xlsxwriter is None:
            raise UserError(_("Python package xlsxwriter is not installed."))

        output = io.BytesIO()
        workbook = xlsxwriter.Workbook(output, {'in_memory': True})
        sheet = workbook.add_worksheet('Report')

        title_format = workbook.add_format({'bold': True, 'font_size': 14})
        header_format = workbook.add_format({'bold': True, 'border': 1, 'bg_color': '#D9EAF7'})
        normal_format = workbook.add_format({'border': 1})
        amount_format = workbook.add_format({'border': 1, 'num_format': '#,##0.00'})
        total_format = workbook.add_format({'bold': True, 'border': 1, 'num_format': '#,##0.00'})

        sheet.write(0, 0, self.report_title or 'Hotel Report', title_format)
        sheet.write(1, 0, 'Company')
        sheet.write(1, 1, self.company_id.display_name)
        sheet.write(2, 0, 'Date From')
        sheet.write(2, 1, fields.Date.to_string(self.date_from))
        sheet.write(3, 0, 'Date To')
        sheet.write(3, 1, fields.Date.to_string(self.date_to))
        sheet.write(4, 0, 'Printed By')
        sheet.write(4, 1, self.env.user.display_name)

        headers = [
            '#',
            'Date',
            'Reference',
            'Guest / Customer',
            'Room / Reservation',
            'Partner / Journal',
            'Status',
            'Payment Method',
            'Amount',
            'Note',
        ]

        start_row = 6
        for col, header in enumerate(headers):
            sheet.write(start_row, col, header, header_format)

        row = start_row + 1
        for line in self.line_ids:
            sheet.write(row, 0, line.line_no, normal_format)
            sheet.write(row, 1, line.date or '', normal_format)
            sheet.write(row, 2, line.ref or '', normal_format)
            sheet.write(row, 3, line.guest_name or '', normal_format)
            sheet.write(row, 4, line.room_name or '', normal_format)
            sheet.write(row, 5, line.partner_name or '', normal_format)
            sheet.write(row, 6, line.status or '', normal_format)
            sheet.write(row, 7, line.payment_method or '', normal_format)
            sheet.write_number(row, 8, line.amount or 0.0, amount_format)
            sheet.write(row, 9, line.note or '', normal_format)
            row += 1

        sheet.write(row, 7, 'Total', header_format)
        sheet.write_number(row, 8, self.total_amount or 0.0, total_format)

        sheet.set_column(0, 0, 6)
        sheet.set_column(1, 1, 14)
        sheet.set_column(2, 2, 22)
        sheet.set_column(3, 5, 24)
        sheet.set_column(6, 7, 18)
        sheet.set_column(8, 8, 14)
        sheet.set_column(9, 9, 35)

        workbook.close()
        output.seek(0)

        safe_name = re.sub(r'[^A-Za-z0-9_-]+', '_', self.report_code or 'hotel_report')
        filename = '%s_%s_to_%s.xlsx' % (
            safe_name,
            fields.Date.to_string(self.date_from),
            fields.Date.to_string(self.date_to),
        )

        attachment = self.env['ir.attachment'].sudo().create({
            'name': filename,
            'type': 'binary',
            'datas': base64.b64encode(output.read()),
            'res_model': self._name,
            'res_id': self.id,
            'mimetype': 'application/vnd.openxmlformats-officedocument.spreadsheetml.sheet',
        })

        return {
            'type': 'ir.actions.act_url',
            'url': '/web/content/%s?download=true' % attachment.id,
            'target': 'self',
        }


class HotelReportCenterLine(models.TransientModel):
    _name = 'hotel.report.center.line'
    _description = 'Hotel Report Center Line'
    _order = 'line_no, id'

    wizard_id = fields.Many2one(
        'hotel.report.center',
        required=True,
        ondelete='cascade',
    )

    line_no = fields.Integer(string='#')
    date = fields.Char(string='Date')
    ref = fields.Char(string='Reference')
    guest_name = fields.Char(string='Guest / Customer')
    room_name = fields.Char(string='Room / Reservation')
    partner_name = fields.Char(string='Partner / Journal')
    status = fields.Char(string='Status')
    payment_method = fields.Char(string='Payment Method')
    amount = fields.Float(string='Amount')
    note = fields.Char(string='Note')
    checkin_date = fields.Char(string='Check-In')
    checkout_date = fields.Char(string='Check-Out')
    nights = fields.Integer(string='Nights')
    rate_amount = fields.Float(string='Rate')
    room_type_name = fields.Char(string='Room Type')
    source_name = fields.Char(string='Source')
    checkin = fields.Char(string='Check-In')
    checkout = fields.Char(string='Check-Out')
    nights = fields.Integer(string='Nights')
    rate = fields.Float(string='Rate')
    company_name = fields.Char(string='Company')
    booking_source = fields.Char(string='Booking Source')
    market_segment = fields.Char(string='Market Segment')
    guest_class = fields.Char(string='Guest Class')
    nationality = fields.Char(string='Nationality')
    currency_id = fields.Many2one(
        'res.currency',
        related='wizard_id.currency_id',
        string='Currency',
        readonly=True,
    )