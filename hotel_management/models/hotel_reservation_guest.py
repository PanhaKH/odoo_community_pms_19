import base64

from odoo import api, fields, models, _


class HotelReservationGuest(models.Model):
    _name = 'hotel.reservation.guest'
    _description = 'Hotel Stay Guest'
    _order = 'reservation_id, is_primary desc, id'

    reservation_id = fields.Many2one('hotel.reservation', required=True, ondelete='cascade', index=True)
    partner_id = fields.Many2one('res.partner', string='Guest Profile', index=True)
    name = fields.Char(required=True)
    phone = fields.Char()
    email = fields.Char()
    passport_no = fields.Char(string='Passport / ID Number', index=True)
    nationality_id = fields.Many2one('hotel.nationality', string='Nationality')
    country_id = fields.Many2one('res.country', string='Country')
    date_of_birth = fields.Date()
    gender = fields.Selection([
        ('male', 'Male'),
        ('female', 'Female'),
        ('other', 'Other'),
        ('undisclosed', 'Prefer not to say'),
    ])
    relationship = fields.Char()
    guest_type = fields.Selection([
        ('main', 'Main Guest'),
        ('accompanying', 'Accompanying Guest'),
        ('shared', 'Shared Guest'),
        ('child', 'Child'),
    ], default='accompanying', required=True)
    is_primary = fields.Boolean(default=False)
    id_document_image = fields.Image(string='ID / Passport Image', max_width=1920, max_height=1920)
    signature = fields.Binary(attachment=True)
    visit_count = fields.Integer(compute='_compute_guest_history_flags', string='Visit Count')
    is_repeat_guest = fields.Boolean(compute='_compute_guest_history_flags', string='Repeat Guest')

    def _compute_guest_history_flags(self):
        for rec in self:
            if rec.partner_id and rec.reservation_id:
                rec.visit_count = rec.reservation_id._get_partner_visit_count(rec.partner_id)
                rec.is_repeat_guest = rec.reservation_id._is_repeat_guest_partner(rec.partner_id)
            else:
                rec.visit_count = 0
                rec.is_repeat_guest = False

    @api.onchange('partner_id')
    def _onchange_partner_id(self):
        for rec in self:
            if not rec.partner_id:
                continue
            rec.name = rec.name or rec.partner_id.name
            rec.phone = rec.phone or rec.partner_id.phone
            rec.email = rec.email or rec.partner_id.email
            rec.passport_no = rec.passport_no or rec.partner_id.passport_number
            rec.nationality_id = rec.nationality_id or rec.partner_id.nationality_id
            rec.country_id = rec.country_id or rec.partner_id.country_id
            rec.date_of_birth = rec.date_of_birth or rec.partner_id.hotel_date_of_birth
            rec.gender = rec.gender or rec.partner_id.hotel_gender

    @api.model
    def _find_existing_partner(self, values):
        Partner = self.env['res.partner'].sudo()
        passport_no = (values.get('passport_no') or values.get('passport_number') or '').strip()
        email = (values.get('email') or '').strip()
        phone = (values.get('phone') or '').strip()
        name = (values.get('name') or '').strip()
        nationality_id = values.get('nationality_id')
        date_of_birth = values.get('date_of_birth')

        def empty_partner():
            return Partner.with_context(hotel_identity_match_level=False)

        if passport_no:
            for passport_field in ('passport_number', 'hotel_passport_number', 'national_id'):
                if passport_field in Partner._fields:
                    partner = Partner.search([(passport_field, '=', passport_no)], limit=1)
                    if partner:
                        return partner.with_context(hotel_identity_match_level='passport')
            return empty_partner()

        if email:
            if 'email' in Partner._fields:
                partner = Partner.search([('email', '=ilike', email)], limit=1)
                if partner:
                    return partner.with_context(hotel_identity_match_level='email')
            return empty_partner()

        if phone:
            phone_domains = []
            if 'phone' in Partner._fields:
                phone_domains.append(('phone', '=', phone))
            if 'mobile' in Partner._fields:
                phone_domains.append(('mobile', '=', phone))
            if phone_domains:
                domain = [phone_domains[0]]
                if len(phone_domains) == 2:
                    domain = ['|', phone_domains[0], phone_domains[1]]
                partner = Partner.search(domain, limit=1)
                if partner:
                    return partner.with_context(hotel_identity_match_level='phone')
            return empty_partner()

        weak_domain = []
        if name and 'name' in Partner._fields:
            weak_domain.append(('name', '=ilike', name))
        if nationality_id and 'nationality_id' in Partner._fields:
            weak_domain.append(('nationality_id', '=', nationality_id))
        if date_of_birth and 'hotel_date_of_birth' in Partner._fields:
            weak_domain.append(('hotel_date_of_birth', '=', date_of_birth))
        if len(weak_domain) == 3:
            partners = Partner.search(weak_domain, limit=2)
            if len(partners) == 1:
                return partners.with_context(hotel_identity_match_level='weak')
        return empty_partner()

    @api.model
    def find_or_create_partner(self, values):
        Partner = self.env['res.partner'].sudo()
        partner = self._find_existing_partner(values)
        partner_vals = {
            'name': (values.get('name') or '').strip(),
            'phone': (values.get('phone') or '').strip(),
            'email': (values.get('email') or '').strip(),
            'passport_number': (values.get('passport_no') or values.get('passport_number') or '').strip(),
            'nationality_id': values.get('nationality_id') or False,
            'country_id': values.get('country_id') or False,
            'hotel_date_of_birth': values.get('date_of_birth') or False,
            'hotel_gender': values.get('gender') or False,
        }
        partner_vals = {
            key: value
            for key, value in partner_vals.items()
            if value and key in Partner._fields
        }
        if partner:
            passport = partner_vals.get('passport_number')
            if passport and 'passport_number' in Partner._fields and Partner.search_count([('passport_number', '=', passport), ('id', '!=', partner.id)]):
                partner_vals.pop('passport_number', None)
            write_vals = {
                key: value
                for key, value in partner_vals.items()
                if key in partner._fields and not partner[key]
            }
            if write_vals:
                partner.sudo().write(write_vals)
            return partner

        if not partner_vals.get('name'):
            return Partner

        passport = partner_vals.get('passport_number')
        if passport and 'passport_number' in Partner._fields and Partner.search_count([('passport_number', '=', passport)]):
            partner_vals.pop('passport_number', None)

        return Partner.create(partner_vals)

    @api.model
    def values_from_upload(self, upload):
        if upload and upload.filename:
            return base64.b64encode(upload.read())
        return False


class ResPartnerHotelStayGuest(models.Model):
    _inherit = 'res.partner'

    hotel_date_of_birth = fields.Date(string='Date of Birth')
    hotel_gender = fields.Selection([
        ('male', 'Male'),
        ('female', 'Female'),
        ('other', 'Other'),
        ('undisclosed', 'Prefer not to say'),
    ], string='Gender')
