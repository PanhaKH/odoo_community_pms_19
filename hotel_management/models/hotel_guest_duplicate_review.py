from collections import defaultdict

from odoo import api, fields, models, _


class HotelGuestDuplicateReview(models.Model):
    _name = 'hotel.guest.duplicate.review'
    _description = 'Possible Duplicate Guest Pair'
    _order = 'confidence_sequence, match_reason, partner_a_id, partner_b_id'

    partner_a_id = fields.Many2one('res.partner', string='Guest A', required=True, ondelete='cascade')
    partner_b_id = fields.Many2one('res.partner', string='Guest B', required=True, ondelete='cascade')
    match_reason = fields.Char(required=True)
    confidence_level = fields.Selection([
        ('high', 'High'),
        ('medium', 'Medium'),
        ('low', 'Low'),
    ], required=True)
    confidence_sequence = fields.Integer(default=30)
    passport_display = fields.Char(string='Passport / National ID', compute='_compute_comparison_values')
    email_display = fields.Char(string='Email', compute='_compute_comparison_values')
    phone_display = fields.Char(string='Phone / Mobile', compute='_compute_comparison_values')
    country_display = fields.Char(string='Country', compute='_compute_comparison_values')
    nationality_display = fields.Char(string='Nationality', compute='_compute_comparison_values')
    state = fields.Selection([
        ('pending', 'Pending Review'),
        ('reviewed', 'Reviewed / Ignore'),
    ], default='pending', required=True, index=True)
    reviewed_by = fields.Many2one('res.users', readonly=True)
    reviewed_datetime = fields.Datetime(readonly=True)

    _pair_unique = models.Constraint(
        'UNIQUE(partner_a_id, partner_b_id)',
        'This duplicate guest pair is already registered.',
    )

    @api.depends(
        'partner_a_id.passport_number', 'partner_b_id.passport_number',
        'partner_a_id.email', 'partner_b_id.email',
        'partner_a_id.phone', 'partner_b_id.phone',
        'partner_a_id.country_id', 'partner_b_id.country_id',
        'partner_a_id.nationality_id', 'partner_b_id.nationality_id',
    )
    def _compute_comparison_values(self):
        def compare(left, right):
            left = left or '-'
            right = right or '-'
            return left if left == right else f'{left} | {right}'

        for record in self:
            a = record.partner_a_id
            b = record.partner_b_id
            record.passport_display = compare(a.passport_number, b.passport_number)
            record.email_display = compare(a.email, b.email)
            record.phone_display = compare(
                a.phone or getattr(a, 'mobile', False),
                b.phone or getattr(b, 'mobile', False),
            )
            record.country_display = compare(a.country_id.display_name, b.country_id.display_name)
            record.nationality_display = compare(a.nationality_id.display_name, b.nationality_id.display_name)

    def action_open_contacts(self):
        self.ensure_one()
        return {
            'type': 'ir.actions.act_window',
            'name': _('Compare Possible Duplicate Guests'),
            'res_model': 'res.partner',
            'view_mode': 'list,form',
            'domain': [('id', 'in', [self.partner_a_id.id, self.partner_b_id.id])],
            'context': {'create': False},
        }

    def action_mark_reviewed(self):
        self.write({
            'state': 'reviewed',
            'reviewed_by': self.env.user.id,
            'reviewed_datetime': fields.Datetime.now(),
        })
        return {'type': 'ir.actions.client', 'tag': 'reload'}


class HotelGuestDuplicateReviewWizard(models.TransientModel):
    _name = 'hotel.guest.duplicate.review.wizard'
    _description = 'Review Possible Duplicate Guest Profiles'

    duplicate_review_ids = fields.Many2many(
        'hotel.guest.duplicate.review',
        string='Possible Duplicate Guest Pairs',
        compute='_compute_duplicate_review_ids',
    )
    duplicate_count = fields.Integer(
        string='Pending Duplicate Pairs',
        compute='_compute_duplicate_review_ids',
    )

    @api.model
    def _normalize(self, value):
        return (value or '').strip().casefold()

    @api.model
    def _get_values(self, partner, field_names):
        values = set()
        for field_name in field_names:
            if field_name in partner._fields:
                value = self._normalize(partner[field_name])
                if value:
                    values.add(value)
        return values

    @api.model
    def _get_value(self, partner, field_names):
        return next(iter(self._get_values(partner, field_names)), '')

    @api.model
    def _get_candidate_pairs(self):
        Partner = self.env['res.partner'].sudo()
        partners = Partner.search([])
        grouped = defaultdict(list)

        for partner in partners:
            values = {
                'passports': self._get_values(partner, ('passport_number', 'hotel_passport_number', 'national_id')),
                'email': self._get_value(partner, ('email',)),
                'phones': self._get_values(partner, ('phone', 'mobile')),
                'name': self._get_value(partner, ('name',)),
                'country': partner.country_id.id if 'country_id' in Partner._fields else False,
                'nationality': partner.nationality_id.id if 'nationality_id' in Partner._fields else False,
            }
            for passport in values['passports']:
                grouped[('passport', passport)].append(partner.id)
            if values['email']:
                grouped[('email', values['email'])].append(partner.id)
            for phone in values['phones']:
                grouped[('phone', phone)].append(partner.id)
            if values['name'] and values['country']:
                grouped[('name_country', values['name'], values['country'])].append(partner.id)
            if values['name'] and values['nationality']:
                grouped[('name_nationality', values['name'], values['nationality'])].append(partner.id)
            if values['name']:
                grouped[('name', values['name'])].append(partner.id)

        reason_map = {
            'passport': (_('Same Passport / ID'), 'high', 10),
            'email': (_('Same Email'), 'high', 11),
            'phone': (_('Same Phone'), 'medium', 20),
            'name_country': (_('Same Name + Country'), 'medium', 21),
            'name_nationality': (_('Same Name + Nationality'), 'medium', 22),
            'name': (_('Same Name Only'), 'low', 30),
        }
        pairs = {}
        for key, partner_ids in grouped.items():
            if len(partner_ids) < 2:
                continue
            reason, confidence, sequence = reason_map[key[0]]
            unique_ids = sorted(set(partner_ids))
            for index, partner_a_id in enumerate(unique_ids):
                for partner_b_id in unique_ids[index + 1:]:
                    pair = (partner_a_id, partner_b_id)
                    if pair not in pairs or sequence < pairs[pair]['confidence_sequence']:
                        pairs[pair] = {
                            'partner_a_id': partner_a_id,
                            'partner_b_id': partner_b_id,
                            'match_reason': reason,
                            'confidence_level': confidence,
                            'confidence_sequence': sequence,
                        }
        return pairs

    @api.model
    def _sync_duplicate_reviews(self):
        Review = self.env['hotel.guest.duplicate.review'].sudo()
        for pair, values in self._get_candidate_pairs().items():
            existing = Review.search([
                ('partner_a_id', '=', pair[0]),
                ('partner_b_id', '=', pair[1]),
            ], limit=1)
            if not existing:
                Review.create(values)
            elif existing.state == 'pending':
                existing.write({
                    'match_reason': values['match_reason'],
                    'confidence_level': values['confidence_level'],
                    'confidence_sequence': values['confidence_sequence'],
                })
        return Review.search([('state', '=', 'pending')])

    @api.depends()
    def _compute_duplicate_review_ids(self):
        reviews = self._sync_duplicate_reviews()
        for wizard in self:
            wizard.duplicate_review_ids = [(6, 0, reviews.ids)]
            wizard.duplicate_count = len(reviews)

    def action_open_duplicate_guests(self):
        reviews = self._sync_duplicate_reviews()
        return {
            'type': 'ir.actions.act_window',
            'name': _('Possible Duplicate Guest Pairs'),
            'res_model': 'hotel.guest.duplicate.review',
            'view_mode': 'list,form',
            'domain': [('id', 'in', reviews.ids or [0])],
            'context': {'create': False},
        }
