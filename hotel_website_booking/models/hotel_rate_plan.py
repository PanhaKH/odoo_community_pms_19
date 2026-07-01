from datetime import timedelta
from odoo import models, fields, api

class HotelRatePlanLine(models.Model):
    _inherit = 'hotel.rate.plan.line'

    @api.model
    def _get_daily_pricing(self, room_type, stay_date, adults=2, rate_plan=False, allow_legacy=True):
        stay_date = fields.Date.to_date(stay_date)
        adults = max(int(adults or 0), 1)
        empty_plan = self.env['hotel.rate.plan']
        empty_rule = self.browse()
        if not room_type or not stay_date:
            return {
                'nightly_rate': 0.0,
                'base_rate': 0.0,
                'extra_person_fee_total': 0.0,
                'rate_plan': empty_plan,
                'rule': empty_rule,
            }

        domain = [
            ('room_type_id', '=', room_type.id),
            '|', ('date_start', '=', False), ('date_start', '<=', stay_date),
            '|', ('date_end', '=', False), ('date_end', '>=', stay_date),
        ]
        if rate_plan:
            domain.append(('plan_id', '=', rate_plan.id))
        else:
            domain.append(('plan_id.active', '=', True))

        rule = self.search(domain, order='date_start desc, id desc', limit=1)
        if rule:
            base_rate = rule.price or 0.0
            extra_fee = 0.0
            if rule.included_guests > 0 and adults > rule.included_guests:
                extra_fee = (adults - rule.included_guests) * (rule.extra_person_fee or 0.0)
            return {
                'nightly_rate': base_rate + extra_fee,
                'base_rate': base_rate,
                'extra_person_fee_total': extra_fee,
                'rate_plan': rule.plan_id,
                'rule': rule,
            }

        if allow_legacy:
            legacy_rate = self.env['hotel.room.rate'].sudo().search([
                ('room_type_id', '=', room_type.id),
            ], order='id desc', limit=1)
            if legacy_rate:
                base_rate = legacy_rate.unit_price or 0.0
                return {
                    'nightly_rate': base_rate,
                    'base_rate': base_rate,
                    'extra_person_fee_total': 0.0,
                    'rate_plan': empty_plan,
                    'rule': empty_rule,
                }

        return {
            'nightly_rate': 0.0,
            'base_rate': 0.0,
            'extra_person_fee_total': 0.0,
            'rate_plan': empty_plan,
            'rule': empty_rule,
        }

    @api.model
    def _get_stay_pricing(self, room_type, checkin, checkout, adults=2, rate_plan=False, allow_legacy=True):
        checkin = fields.Date.to_date(checkin)
        checkout = fields.Date.to_date(checkout)
        if not checkin:
            return {
                'nights': [],
                'nightly_rate': 0.0,
                'average_nightly_rate': 0.0,
                'total': 0.0,
                'rate_plan': self.env['hotel.rate.plan'],
                'rule': self.browse(),
            }
        if not checkout or checkout <= checkin:
            checkout = checkin + timedelta(days=1)

        nights = []
        stay_date = checkin
        while stay_date < checkout:
            pricing = self._get_daily_pricing(
                room_type,
                stay_date,
                adults=adults,
                rate_plan=rate_plan,
                allow_legacy=allow_legacy,
            )
            nights.append({
                'date': stay_date,
                **pricing,
            })
            stay_date += timedelta(days=1)

        total = sum(night['nightly_rate'] for night in nights)
        first_rate_night = next((night for night in nights if night['rule']), nights[0] if nights else False)
        return {
            'nights': nights,
            'nightly_rate': first_rate_night['nightly_rate'] if first_rate_night else 0.0,
            'average_nightly_rate': total / len(nights) if nights else 0.0,
            'total': total,
            'rate_plan': first_rate_night['rate_plan'] if first_rate_night else self.env['hotel.rate.plan'],
            'rule': first_rate_night['rule'] if first_rate_night else self.browse(),
        }
