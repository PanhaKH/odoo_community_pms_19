import re

from markupsafe import Markup, escape

from odoo import _, api, fields, models
from odoo.tools.image import image_data_uri
from odoo.tools.misc import format_amount, format_date


class HotelDocumentTemplate(models.Model):
    _name = 'hotel.document.template'
    _description = 'Hotel Document Template'
    _order = 'document_type, company_id, name'

    name = fields.Char(required=True)
    document_type = fields.Selection([
        ('registration_card', 'Registration Card'),
    ], required=True, default='registration_card', index=True)
    active = fields.Boolean(default=True)
    company_id = fields.Many2one('res.company', default=lambda self: self.env.company)
    html_body = fields.Html(string='HTML Body', sanitize=False)
    show_logo = fields.Boolean(default=True)
    logo_position = fields.Selection([
        ('left', 'Left'),
        ('center', 'Center'),
        ('right', 'Right'),
    ], default='left')
    logo_width = fields.Integer(default=180)
    show_company_name = fields.Boolean(default=True)
    custom_css = fields.Text()
    notes = fields.Text(string='Notes / Help')

    def action_preview_template(self):
        return {
            'type': 'ir.actions.client',
            'tag': 'display_notification',
            'params': {
                'title': _('Template Preview'),
                'message': _('Open a reservation and click Print Registration Card to preview this template with live reservation data.'),
                'type': 'info',
                'sticky': False,
            },
        }

    @api.model
    def _get_registration_card_template(self, company):
        template = self.search([
            ('document_type', '=', 'registration_card'),
            ('active', '=', True),
            ('company_id', '=', company.id),
        ], limit=1)
        if not template:
            template = self.search([
                ('document_type', '=', 'registration_card'),
                ('active', '=', True),
                ('company_id', '=', False),
            ], limit=1)
        return template

    @api.model
    def _default_registration_card_html(self):
        return """
<div class="registration-card">
    <div class="text-center">
        ${company.logo}
        <h2>GUEST REGISTRATION CARD</h2>
        <div><strong>${company.name}</strong></div>
        <div class="text-muted">Reservation No: ${reservation.name} | Date: ${today}</div>
    </div>

    <div class="section">
        <div class="section-title">Guest Identity &amp; Contact</div>
        <table>
            <tr><td class="label">Guest Name</td><td>${reservation.partner_id.name}</td><td class="label">Passport / ID</td><td>${reservation.passport_no}</td></tr>
            <tr><td class="label">Nationality</td><td>${reservation.nationality_id.name}</td><td class="label">Country</td><td>${reservation.country_id.name}</td></tr>
            <tr><td class="label">Phone</td><td>${reservation.phone}</td><td class="label">Email</td><td>${reservation.email}</td></tr>
        </table>
    </div>

    <div class="section">
        <div class="section-title">Stay Details</div>
        <table>
            <tr><td class="label">Arrival</td><td>${reservation.checkin_date}</td><td class="label">Departure</td><td>${reservation.checkout_date}</td></tr>
            <tr><td class="label">Room Number</td><td>${reservation.room_id.name}</td><td class="label">Room Type</td><td>${reservation.room_type_id.name}</td></tr>
            <tr><td class="label">Nights</td><td>${reservation.duration}</td><td class="label">VIP Level</td><td>${reservation.vip_level}</td></tr>
        </table>
    </div>

    <div class="section">
        <div class="section-title">Accompanying Guests</div>
        ${reservation.accompanying_guest_table}
    </div>

    <div class="section">
        <div class="section-title">Estimated Accommodation &amp; Financial Summary</div>
        <table>
            <tr><td>Room Rate / Accommodation Estimate</td><td class="text-end">${reservation.estimated_room_amount}</td></tr>
            <tr><td>Tax / Service Estimate</td><td class="text-end">${reservation.estimated_tax_amount}</td></tr>
            <tr><td><strong>Total Estimated Stay Amount</strong></td><td class="text-end"><strong>${reservation.estimated_total_amount}</strong></td></tr>
            <tr><td>Required Deposit</td><td class="text-end">${reservation.deposit_required_amount}</td></tr>
            <tr><td>Deposit Received</td><td class="text-end">${reservation.deposit_received_amount}</td></tr>
            <tr><td><strong>Estimated Balance</strong></td><td class="text-end"><strong>${reservation.estimated_balance_amount}</strong></td></tr>
        </table>
    </div>

    <div class="section">
        <div class="section-title">Terms and Conditions</div>
        ${reservation.registration_terms}
    </div>

    <div class="row mt-3" style="page-break-inside: avoid;">
        <div class="col-6">
            <div class="section-title">Guest E-Signature</div>
            ${reservation.guest_signature}
        </div>
        <div class="col-6">
            <div class="section-title">Front Desk Verification</div>
            <div class="signature-box"></div>
        </div>
    </div>
</div>
        """

    @api.model
    def _default_registration_card_css(self):
        return """
.registration-card-template {
    font-family: Arial, Helvetica, sans-serif;
    color: #222;
    font-size: 13px;
}
.registration-card-template .registration-card {
    width: 100%;
}
.registration-card-template .section {
    margin-top: 14px;
    page-break-inside: avoid;
}
.registration-card-template .section-title {
    font-weight: 700;
    color: #1f4e79;
    border-bottom: 1px solid #d8dde6;
    padding-bottom: 4px;
    margin-bottom: 6px;
    text-transform: uppercase;
    font-size: 12px;
    letter-spacing: .03em;
}
.registration-card-template table {
    width: 100%;
    border-collapse: collapse;
}
.registration-card-template td,
.registration-card-template th {
    padding: 5px 6px;
    border: 1px solid #e1e5eb;
    vertical-align: top;
}
.registration-card-template .label {
    width: 18%;
    font-weight: 700;
    background: #f7f9fc;
}
.registration-card-template .text-muted {
    color: #6c757d;
}
.registration-card-template .text-center {
    text-align: center;
}
.registration-card-template .text-left {
    text-align: left;
}
.registration-card-template .text-right {
    text-align: right;
}
.registration-card-template .text-end {
    text-align: right;
}
.registration-card-template .signature-box {
    min-height: 90px;
    border: 1px solid #b8c2cc;
    background: #fff;
    padding: 8px;
}
.registration-card-template .signature-box img {
    max-height: 80px;
    max-width: 100%;
}
        """

    def _format_money(self, reservation, amount):
        return format_amount(self.env, amount or 0.0, reservation.currency_id or reservation.company_id.currency_id)

    def _format_date(self, value):
        return format_date(self.env, value) if value else ''

    def _html_text(self, value):
        return Markup('<span style="white-space: pre-line;">%s</span>') % escape(value or '')

    def _selection_label(self, record, field_name):
        field = record._fields.get(field_name)
        value = record[field_name] if field else False
        if not field or not value:
            return ''
        selection = field.selection
        if isinstance(selection, str):
            selection = getattr(record, selection)()
        elif callable(selection):
            try:
                selection = selection(record)
            except TypeError:
                try:
                    selection = selection(record.env)
                except TypeError:
                    selection = selection()
        return dict(selection or []).get(value, value)

    def _logo_html(self, company):
        self.ensure_one()
        if not self.show_logo or not company.logo:
            return Markup('')
        width = max(min(self.logo_width or 180, 600), 40)
        return Markup(
            '<div class="text-%s"><img src="%s" style="max-width:%spx; max-height:120px;" alt="Hotel Logo"/></div>'
        ) % (
            escape(self.logo_position or 'left'),
            escape(image_data_uri(company.logo)),
            width,
        )

    def _signature_html(self, reservation):
        if reservation.guest_signature:
            return Markup(
                '<div class="signature-box"><img src="%s" alt="Guest Signature"/></div>'
            ) % escape(image_data_uri(reservation.guest_signature))
        return Markup('<div class="signature-box"></div>')

    def _accompanying_guest_table(self, guests):
        if not guests:
            return Markup('<div class="text-muted">No accompanying guests registered.</div>')
        rows = []
        for guest in guests:
            rows.append(
                Markup('<tr><td>%s</td><td>%s</td><td>%s</td></tr>')
                % (
                    escape(guest.get('name') or ''),
                    escape(guest.get('passport') or '-'),
                    escape(guest.get('nationality') or '-'),
                )
            )
        return Markup(
            '<table class="table table-sm table-bordered"><thead><tr><th>Name</th><th>Passport / ID</th><th>Nationality</th></tr></thead><tbody>%s</tbody></table>'
        ) % Markup('').join(rows)

    def _placeholder_values(self, reservation):
        self.ensure_one()
        data = reservation._get_registration_card_data()
        company = reservation.company_id
        partner = reservation.partner_id
        today = fields.Date.context_today(reservation)
        terms = data.get('hotel_terms') or ''

        values = {
            'reservation.name': reservation.name or '',
            'reservation.partner_id.name': partner.name or '',
            'reservation.passport_no': reservation.partner_passport or '',
            'reservation.nationality_id.name': reservation.guest_nationality_id.name or '',
            'reservation.country_id.name': reservation.guest_country_id.name or '',
            'reservation.phone': reservation.partner_phone or '',
            'reservation.email': reservation.partner_email or '',
            'reservation.checkin_date': self._format_date(reservation.checkin_date),
            'reservation.checkout_date': self._format_date(reservation.checkout_date),
            'reservation.room_id.name': reservation.room_id.name or '',
            'reservation.room_type_id.name': reservation.room_type_id.name or '',
            'reservation.duration': reservation.duration or '',
            'reservation.adults': reservation.adults or 0,
            'reservation.children': reservation.children or 0,
            'reservation.vip_level': self._selection_label(reservation, 'vip_level'),
            'reservation.guest_classification_id.name': reservation.guest_classification_id.name or '',
            'reservation.estimated_room_amount': self._format_money(reservation, data['untaxed_amount']),
            'reservation.estimated_tax_amount': self._format_money(reservation, data['tax_amount']),
            'reservation.estimated_total_amount': self._format_money(reservation, data['total_amount']),
            'reservation.deposit_required_amount': self._format_money(reservation, data['required_deposit_amount']),
            'reservation.deposit_received_amount': self._format_money(reservation, data['deposit_received']),
            'reservation.estimated_balance_amount': self._format_money(reservation, data['estimated_balance']),
            'reservation.accompanying_guest_table': self._accompanying_guest_table(data['accompanying_guests']),
            'reservation.guest_signature': self._signature_html(reservation),
            'reservation.registration_terms': self._html_text(terms),
            'company.name': company.name or '',
            'company.logo': self._logo_html(company),
            'today': self._format_date(today),
        }
        values.update({
            'guest_signature': values['reservation.guest_signature'],
            'company.logo': values['company.logo'],
        })
        if not self.show_company_name:
            values['company.name'] = ''
        return values

    def _render_for_reservation(self, reservation):
        self.ensure_one()
        body = self.html_body or self._default_registration_card_html()
        values = self._placeholder_values(reservation)

        def replace(match):
            key = match.group(1).strip()
            value = values.get(key, '')
            if isinstance(value, Markup):
                return str(value)
            return str(escape(value))

        rendered_body = re.sub(r'\$\{([^}]+)\}', replace, body)
        css = self.custom_css or ''
        return Markup(
            '<style>%s</style><div class="registration-card-template">%s</div>'
        ) % (Markup(css), Markup(rendered_body))
