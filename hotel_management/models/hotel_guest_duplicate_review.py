from collections import defaultdict

from odoo import fields, models, _


class HotelGuestDuplicateReviewWizard(models.TransientModel):
    _name = 'hotel.guest.duplicate.review.wizard'
    _description = 'Review Possible Duplicate Guest Profiles'

    duplicate_partner_ids = fields.Many2many(
        'res.partner',
        string='Possible Duplicate Guests',
        compute='_compute_duplicate_partner_ids',
    )
    duplicate_count = fields.Integer(
        string='Possible Duplicate Count',
        compute='_compute_duplicate_partner_ids',
    )

    def _normalize(self, value):
        return (value or '').strip().casefold()

    def _get_duplicate_partner_ids(self):
        Partner = self.env['res.partner'].sudo()
        partners = Partner.search([])
        grouped = defaultdict(list)

        for partner in partners:
            name = self._normalize(partner.name)
            email = self._normalize(partner.email)
            phone = self._normalize(partner.phone)

            if email:
                grouped[('email', email)].append(partner.id)
            if name and email:
                grouped[('name_email', name, email)].append(partner.id)
            if name and phone:
                grouped[('name_phone', name, phone)].append(partner.id)

            for field_name in ('passport_number', 'hotel_passport_number', 'national_id'):
                if field_name in Partner._fields:
                    passport = self._normalize(partner[field_name])
                    if passport:
                        grouped[(field_name, passport)].append(partner.id)

        duplicate_ids = set()
        for partner_ids in grouped.values():
            if len(partner_ids) > 1:
                duplicate_ids.update(partner_ids)
        return list(duplicate_ids)

    def _compute_duplicate_partner_ids(self):
        duplicate_ids = self._get_duplicate_partner_ids()
        for wizard in self:
            wizard.duplicate_partner_ids = [(6, 0, duplicate_ids)]
            wizard.duplicate_count = len(duplicate_ids)

    def action_open_duplicate_guests(self):
        duplicate_ids = self._get_duplicate_partner_ids()
        return {
            'type': 'ir.actions.act_window',
            'name': _('Possible Duplicate Guests'),
            'res_model': 'res.partner',
            'view_mode': 'list,form',
            'domain': [('id', 'in', duplicate_ids)],
        }
