import json
import uuid
import base64
from datetime import timedelta
from urllib.parse import urlencode

# pyrefly: ignore [missing-import]
from markupsafe import Markup

from odoo import fields, http, _
from odoo.exceptions import ValidationError
from odoo.osv import expression
from odoo.tools import single_email_re
# pyrefly: ignore [missing-import]
from odoo.addons.hotel_management.controllers.main import HotelCustomerPortal
from odoo.http import request

class HotelWebsiteBooking(HotelCustomerPortal):
    ROOM_IMAGES = [
        'https://images.unsplash.com/photo-1566665797739-1674de7a421a?auto=format&fit=crop&w=900&q=80',
        'https://images.unsplash.com/photo-1590490360182-c33d57733427?auto=format&fit=crop&w=900&q=80',
        'https://images.unsplash.com/photo-1598928506311-c55ded91a20c?auto=format&fit=crop&w=900&q=80',
        'https://images.unsplash.com/photo-1611892440504-42a792e24d32?auto=format&fit=crop&w=900&q=80',
    ]

    HERO_IMAGE = 'https://images.unsplash.com/photo-1566073771259-6a8506099945?auto=format&fit=crop&w=1400&q=80'
    LOUNGE_IMAGE = 'https://images.unsplash.com/photo-1600585154340-be6161a56a0c?auto=format&fit=crop&w=900&q=80'
    POOL_IMAGE = 'https://images.unsplash.com/photo-1571896349842-33c89424de2d?auto=format&fit=crop&w=900&q=80'
    RESTAURANT_IMAGE = 'https://images.unsplash.com/photo-1555396273-367ea4eb4db5?auto=format&fit=crop&w=900&q=80'
    SORT_OPTIONS = [
        ('room_type_id, name', 'Featured'),
        ('name', 'Room Type'),
        ('capacity desc, room_type_id, name', 'Capacity'),
    ]

    def _parse_date(self, value, fallback):
        try:
            return fields.Date.from_string(value) if value else fallback
        except Exception:
            return fallback

    def _availability_domain(self, checkin, checkout, room_type_id=False):
        domain = [
            ('availability_status', '!=', 'out_of_order'),
            ('state', '!=', 'blocked'),
        ]
        if room_type_id:
            domain.append(('room_type_id', '=', room_type_id))
        return domain

    def _available_rooms(self, checkin, checkout, room_type_id=False):
        Room = request.env['hotel.room'].sudo()
        rooms = Room.search(self._availability_domain(checkin, checkout, room_type_id), order='room_type_id, name')

        if not checkin or not checkout:
            return rooms

        conflicts = request.env['hotel.reservation'].sudo().search([
            ('room_id', 'in', rooms.ids),
            ('state', 'not in', ['cancel', 'noshow', 'checkout']),
            ('is_desk_folio', '=', False),
            ('checkin_date', '<', checkout),
            ('checkout_date', '>', checkin),
        ])
        rooms = rooms.filtered(lambda room: room.id not in conflicts.mapped('room_id').ids)

        blocks = request.env['hotel.room.block'].sudo().search([
            ('room_id', 'in', rooms.ids),
            ('state', '=', 'active'),
            ('date_from', '<', checkout),
            ('date_to', '>', checkin),
        ])
        return rooms.filtered(lambda room: room.id not in blocks.mapped('room_id').ids)

    def _keep_url(self, **updates):
        params = dict(request.params)
        for key, value in updates.items():
            if value in (None, False, ''):
                params.pop(key, None)
            else:
                params[key] = value
        return '/hotel%s' % (('?' + urlencode(params)) if params else '')

    def _room_pricing(self, room_type, checkin, checkout=False, adults=2):
        if not room_type:
            return {
                'nightly_rate': 0.0,
                'average_nightly_rate': 0.0,
                'total': 0.0,
                'rate_plan': request.env['hotel.rate.plan'].sudo(),
                'rule': request.env['hotel.rate.plan.line'].sudo(),
                'nights': [],
            }
        RateLine = request.env['hotel.rate.plan.line'].sudo()
        return RateLine._get_stay_pricing(room_type, checkin, checkout, adults=adults)

    def _room_price(self, room_type, checkin, checkout=False, adults=2):
        return self._room_pricing(room_type, checkin, checkout, adults=adults)['nightly_rate']

    def _room_type_image(self, room_type, index=1, fallback_index=0):
        field_name = 'website_image_%s' % index
        if room_type and getattr(room_type, field_name, False):
            return {
                'url': '/web/image/hotel.room.type/%s/%s' % (room_type.id, field_name),
                'field': field_name,
                'editable': True,
            }
        return {
            'url': self.ROOM_IMAGES[fallback_index % len(self.ROOM_IMAGES)],
            'field': field_name,
            'editable': bool(room_type),
        }

    def _room_type_gallery(self, room_type):
        gallery_images = room_type.website_gallery_image_ids.sorted(lambda image: (image.sequence, image.id)) if room_type else []
        if gallery_images:
            return [
                {
                    'url': '/web/image/hotel.room.type.website.image/%s/image' % image.id,
                    'field': 'image',
                    'editable': True,
                    'record_model': 'hotel.room.type.website.image',
                    'record_id': image.id,
                    'gallery_image_id': image.id,
                    'expression': 'image.image',
                }
                for image in gallery_images
            ]
        return [
            self._room_type_image(room_type, index=1, fallback_index=room_type.sequence),
            self._room_type_image(room_type, index=2, fallback_index=room_type.sequence + 1),
            self._room_type_image(room_type, index=3, fallback_index=room_type.sequence + 2),
        ]

    def _gallery_editor_enabled(self):
        return bool(
            request.env.user.has_group('base.group_user')
            or request.params.get('enable_editor')
            or request.params.get('edit_translations')
            or request.env.context.get('edit_translations')
        )

    def _ensure_room_type_gallery_records(self, room_type):
        if not room_type or room_type.website_gallery_image_ids:
            return
        GalleryImage = request.env['hotel.room.type.website.image'].sudo()
        for index, field_name in enumerate(('website_image_1', 'website_image_2', 'website_image_3'), start=1):
            image_value = getattr(room_type, field_name, False)
            if image_value:
                GalleryImage.create({
                    'room_type_id': room_type.id,
                    'sequence': index * 10,
                    'name': _('Gallery Image %s') % index,
                    'image': image_value,
                })

    def _gallery_json_response(self, payload, status=200):
        return request.make_json_response(payload, status=status)

    @http.route('/hotel/gallery/image/seed', type='http', auth='user', website=True, methods=['POST'], csrf=False)
    def hotel_gallery_image_seed(self, **post):
        try:
            room_type_id = int(post.get('room_type_id') or 0)
        except (TypeError, ValueError):
            return self._gallery_json_response({'error': 'Invalid room type.'}, status=400)

        room_type = request.env['hotel.room.type'].sudo().browse(room_type_id).exists()
        if not room_type:
            return self._gallery_json_response({'error': 'Room type not found.'}, status=404)
        if room_type.website_gallery_image_ids:
            return self._gallery_json_response({'ok': True, 'created': 0})

        created = 0
        GalleryImage = request.env['hotel.room.type.website.image'].sudo()
        for index, field_name in enumerate(('website_image_1', 'website_image_2', 'website_image_3'), start=1):
            image_value = getattr(room_type, field_name, False)
            if not image_value:
                continue
            GalleryImage.create({
                'room_type_id': room_type.id,
                'sequence': index * 10,
                'name': _('Gallery Image %s') % index,
                'image': image_value,
            })
            created += 1
        return self._gallery_json_response({'ok': True, 'created': created})

    @http.route('/hotel/gallery/image/delete', type='http', auth='user', website=True, methods=['POST'], csrf=False)
    def hotel_gallery_image_delete(self, **post):
        try:
            image_id = int(post.get('image_id') or 0)
        except (TypeError, ValueError):
            return self._gallery_json_response({'error': 'Invalid image.'}, status=400)
        image = request.env['hotel.room.type.website.image'].sudo().browse(image_id).exists()
        if not image:
            return self._gallery_json_response({'error': 'Image not found.'}, status=404)
        image.unlink()
        return self._gallery_json_response({'ok': True})

    @http.route('/hotel/gallery/image/reorder', type='http', auth='user', website=True, methods=['POST'], csrf=False)
    def hotel_gallery_image_reorder(self, **post):
        try:
            ordered_ids = [int(image_id) for image_id in json.loads(post.get('ordered_ids') or '[]')]
        except (TypeError, ValueError, json.JSONDecodeError):
            return self._gallery_json_response({'error': 'Invalid image order.'}, status=400)
        images = request.env['hotel.room.type.website.image'].sudo().browse(ordered_ids).exists()
        if len(images) != len(set(ordered_ids)):
            return self._gallery_json_response({'error': 'Some images were not found.'}, status=404)
        for sequence, image_id in enumerate(ordered_ids, start=1):
            request.env['hotel.room.type.website.image'].sudo().browse(image_id).write({'sequence': sequence * 10})
        return self._gallery_json_response({'ok': True})

    def _room_type_cards(self, rooms, checkin, checkout):
        cards = []
        deposit_policy = self._deposit_policy()
        for index, room_type in enumerate(rooms.mapped('room_type_id').sorted(lambda rec: rec.sequence or 0)):
            type_rooms = rooms.filtered(lambda room: room.room_type_id == room_type)
            sample_room = type_rooms[:1]
            pricing = self._room_pricing(room_type, checkin, checkout)
            price = pricing['nightly_rate']
            cards.append({
                'room_type': room_type,
                'sample_room': sample_room,
                'capacity': sample_room.capacity or 2,
                'available_count': len(type_rooms),
                'image': self._room_type_image(room_type, index=1, fallback_index=index),
                'price': price,
                'pricing': pricing,
                'deposit_required': deposit_policy['required'],
                'deposit_percent': deposit_policy['percent'],
                'deposit_amount': self._deposit_amount(pricing, checkin, checkout),
            })
        return cards

    def _availability_counts(self, checkin, checkout):
        counts = []
        RoomType = request.env['hotel.room.type'].sudo()
        for room_type in RoomType.search([], order='sequence, name'):
            count = len(self._available_rooms(checkin, checkout, room_type.id))
            counts.append({'type': room_type, 'count': count})
        return counts

    def _parse_guest_values(self, values, default_adults=2):
        try:
            adults = max(int(values.get('adults') or default_adults), 1)
        except (TypeError, ValueError):
            adults = default_adults
        try:
            children = max(int(values.get('children') or 0), 0)
        except (TypeError, ValueError):
            children = 0
        return adults, children

    def _stay_nights(self, checkin, checkout):
        if not checkin or not checkout or checkout <= checkin:
            return 1
        return max((checkout - checkin).days, 1)

    def _deposit_policy(self):
        company = self._website_company()
        percent = max(company.hotel_confirmation_deposit_percent or 0.0, 0.0) if company.hotel_deposit_required else 0.0
        return {
            'required': bool(company.hotel_deposit_required and percent > 0.0),
            'percent': percent,
        }

    def _website_company(self):
        website = getattr(request, 'website', False)
        company = website.company_id if website and website.company_id else request.env.company
        return company.sudo()

    def _deposit_amount(self, room_rate, checkin, checkout):
        policy = self._deposit_policy()
        if not policy['required'] or not room_rate:
            return 0.0
        if isinstance(room_rate, dict):
            stay_total = room_rate.get('total') or 0.0
        else:
            stay_total = (room_rate or 0.0) * self._stay_nights(checkin, checkout)
        return round(stay_total * policy['percent'] / 100.0, 2)

    def _payment_status_label(self, status):
        return {
            'none': _('No payment required'),
            'pending_verification': _('Pending Manual Verification'),
            'paid': _('Payment verified'),
            'failed': _('Payment verification failed'),
        }.get(status or 'none', _('No payment required'))

    def _safe_booking_payload(self, values):
        allowed_keys = {
            'room_id',
            'room_type_id',
            'checkin',
            'checkout',
            'adults',
            'children',
            'guest_name',
            'guest_email',
            'guest_phone',
            'special_request',
            'payment_mode',
            'expected_deposit_amount',
        }
        return {
            key: (values.get(key) or '').strip() if isinstance(values.get(key), str) else values.get(key)
            for key in allowed_keys
            if key in values
        }

    def _normalized_email(self, email):
        return (email or '').strip().lower()

    def _website_customer_partner(self):
        if request.env.user._is_public():
            return request.env['res.partner']
        return request.env.user.partner_id.sudo()

    def _website_booking_owner_domain(self, partner=False, emails=False):
        partner = partner or self._website_customer_partner()
        emails = [self._normalized_email(email) for email in (emails or []) if self._normalized_email(email)]
        owner_domains = []
        if partner:
            owner_domains.extend([
                [('website_partner_id', '=', partner.id)],
                [('partner_id', '=', partner.id)],
            ])
        if emails:
            owner_domains.extend([
                [('website_booking_email', 'in', emails)],
                [('partner_id.email', 'in', emails)],
            ])
        if not owner_domains:
            return [('id', '=', 0)]
        return expression.OR(owner_domains)

    def _current_user_booking_domain(self):
        partner = self._website_customer_partner()
        if not partner:
            return [('id', '=', 0)]
        emails = [request.env.user.email, partner.email]
        return expression.AND([
            [('is_desk_folio', '=', False)],
            self._website_booking_owner_domain(partner, emails),
        ])

    def _booking_error_redirect(self, post, error, checkin=False, checkout=False, adults=False, children=False, room_type_id=False):
        params = urlencode({
            'checkin': post.get('checkin') or checkin or '',
            'checkout': post.get('checkout') or checkout or '',
            'adults': post.get('adults') or adults or 1,
            'children': post.get('children') or children or 0,
            'error': error,
        })
        if room_type_id:
            return request.redirect('/hotel/room/%s?%s' % (room_type_id, params))
        return request.redirect('/hotel?%s' % params)

    def _booking_prefill_values(self):
        return {
            'guest_name': '',
            'phone': '',
            'email': '',
            'passport_number': '',
            'nationality_id': False,
            'country_id': False,
            'street': '',
            'city': '',
            'estimated_arrival': 'afternoon',
            'smoking_preference': 'non_smoking',
            'bed_preference': 'any',
            **{'udf_value_%s' % index: False for index in range(1, 11)},
        }

    def _booking_guest_slots(self, adults=2, children=0):
        guest_count = max((adults or 0) + (children or 0), 1)
        return [{
            'index': index,
            'title': _('Main Guest') if index == 0 else _('Accompanying Guest %s') % index,
            'is_primary': index == 0,
            'name': '',
            'phone': '',
            'email': '',
            'passport_number': '',
            'nationality_id': False,
            'country_id': False,
            'date_of_birth': False,
            'gender': False,
        } for index in range(guest_count)]

    def _booking_udf_fields(self, prefill_values):
        attribute_model = request.env['hotel.guest.attribute'].sudo()
        company = request.env.company.sudo()
        udf_fields = []
        for index in range(1, 11):
            options = attribute_model.search([('udf_number', '=', str(index))], order='sequence, name')
            if options:
                label = getattr(company, 'hotel_udf_label_%s' % index, False) or _('Preference %s') % index
                udf_fields.append({
                    'label': label,
                    'name': 'udf_value_%s' % index,
                    'options': options,
                    'value': prefill_values.get('udf_value_%s' % index),
                })
        return udf_fields

    def _room_type_description(self, room_type, rooms):
        if room_type.website_description:
            return False
        sample_room = rooms[:1]
        if sample_room and sample_room.room_note:
            return sample_room.room_note
        return _(
            '%s offers a comfortable stay with live availability, clear pricing, '
            'and a direct booking request workflow for your selected dates.'
        ) % room_type.name

    @http.route(['/hotel', '/hotel/rooms'], type='http', auth='public', website=True)
    def hotel_home(self, **kw):
        today = fields.Date.context_today(request.env.user)
        checkin = self._parse_date(kw.get('checkin'), today)
        checkout = self._parse_date(kw.get('checkout'), checkin + timedelta(days=1))
        if checkout <= checkin:
            checkout = checkin + timedelta(days=1)

        try:
            room_type_id = int(kw.get('room_type_id') or 0)
        except (TypeError, ValueError):
            room_type_id = 0
        room_type = request.env['hotel.room.type'].sudo().browse(room_type_id).exists() if room_type_id else False
        room_type_id = room_type.id if room_type else 0
        adults, children = self._parse_guest_values(kw)
        guests = adults + children
        search = (kw.get('search') or '').strip()
        order = kw.get('order') or self.SORT_OPTIONS[0][0]
        if order not in {option[0] for option in self.SORT_OPTIONS}:
            order = self.SORT_OPTIONS[0][0]
        rooms = self._available_rooms(checkin, checkout, room_type_id or False)
        if guests:
            rooms = rooms.filtered(lambda room: not room.capacity or room.capacity >= guests)
        if search:
            search_l = search.lower()
            rooms = rooms.filtered(lambda room: search_l in (room.room_type_id.name or '').lower())
        rooms = rooms.sorted(lambda room: (room.room_type_id.sequence or 0, room.room_type_id.name or ''))
        if order == 'name':
            rooms = rooms.sorted(lambda room: room.room_type_id.name or '')
        elif order == 'capacity desc, room_type_id, name':
            rooms = rooms.sorted(lambda room: (-(room.capacity or 0), room.room_type_id.name or ''))

        available_counts = self._availability_counts(checkin, checkout)

        values = {
            'checkin': checkin,
            'checkout': checkout,
            'adults': adults,
            'children': children,
            'guests': guests,
            'search': search,
            'order': order,
            'sort_options': self.SORT_OPTIONS,
            'room_type_id': room_type_id,
            'selected_room_type': room_type,
            'room_types': request.env['hotel.room.type'].sudo().search([], order='sequence, name'),
            'available_counts': available_counts,
            'available_type_total': sum(item['count'] for item in available_counts),
            'room_cards': self._room_type_cards(rooms, checkin, checkout),
            'available_total': len(rooms),
            'has_active_filters': bool(room_type_id or search or adults != 2 or children),
            'keep_url': self._keep_url,
            'hero_image': self.HERO_IMAGE,
            'lounge_image': self.LOUNGE_IMAGE,
            'pool_image': self.POOL_IMAGE,
            'restaurant_image': self.RESTAURANT_IMAGE,
            'success': kw.get('success'),
            'payment_pending': kw.get('payment_pending'),
            'reservation_ref': kw.get('reservation_ref'),
            'error': kw.get('error'),
        }
        return request.render('hotel_website_booking.hotel_homepage', values)

    @http.route('/hotel/room/<int:room_type_id>', type='http', auth='public', website=True)
    def hotel_room_detail(self, room_type_id, **kw):
        room_type = request.env['hotel.room.type'].sudo().browse(room_type_id).exists()
        if not room_type:
            return request.not_found()

        today = fields.Date.context_today(request.env.user)
        checkin = self._parse_date(kw.get('checkin'), today)
        checkout = self._parse_date(kw.get('checkout'), checkin + timedelta(days=1))
        invalid_dates = bool(checkout <= checkin)
        availability_checkout = checkout if not invalid_dates else checkin + timedelta(days=1)

        adults, children = self._parse_guest_values(kw)
        guests = adults + children
        rooms = self._available_rooms(checkin, availability_checkout, room_type.id)
        if guests:
            rooms = rooms.filtered(lambda room: not room.capacity or room.capacity >= guests)
        sample_room = rooms[:1]
        gallery_editor_enabled = self._gallery_editor_enabled()
        if gallery_editor_enabled:
            self._ensure_room_type_gallery_records(room_type)
        gallery_images = self._room_type_gallery(room_type)
        pricing = self._room_pricing(room_type, checkin, availability_checkout, adults=adults)
        price = pricing['nightly_rate']
        deposit_policy = self._deposit_policy()
        prefill_values = self._booking_prefill_values()
        values = {
            'room_type': room_type,
            'checkin': checkin,
            'checkout': checkout,
            'adults': adults,
            'children': children,
            'capacity': sample_room.capacity or guests or 2,
            'available_count': len(rooms),
            'price': price,
            'description': self._room_type_description(room_type, rooms),
            'gallery_images': gallery_images,
            'gallery_editor_enabled': gallery_editor_enabled,
            'deposit_required': deposit_policy['required'],
            'deposit_percent': deposit_policy['percent'],
            'pricing': pricing,
            'deposit_amount': self._deposit_amount(pricing, checkin, availability_checkout),
            'deposit_currency': self._website_company().currency_id,
            'date_error': kw.get('error') == 'dates' or invalid_dates,
            'contact_error': kw.get('error') == 'contact',
            'email_error': kw.get('error') == 'email',
            'countries': request.env['res.country'].sudo().search([]),
            'nationalities': request.env['hotel.nationality'].sudo().search([]),
            'prefill_values': prefill_values,
            'guest_slots': self._booking_guest_slots(adults, children),
            'udf_fields': self._booking_udf_fields(prefill_values),
        }
        return request.render('hotel_website_booking.hotel_room_detail', values)

    @http.route('/hotel/book', type='http', auth='public', website=True, methods=['POST'])
    def hotel_book(self, **post):
        today = fields.Date.context_today(request.env.user)
        checkin = self._parse_date(post.get('checkin'), today)
        checkout = self._parse_date(post.get('checkout'), checkin + timedelta(days=1))
        if checkout <= checkin:
            try:
                room_type_id = int(post.get('room_type_id') or 0)
            except (TypeError, ValueError):
                room_type_id = 0
            params = urlencode({
                'checkin': post.get('checkin') or checkin,
                'checkout': post.get('checkout') or checkout,
                'adults': post.get('adults') or 1,
                'children': post.get('children') or 0,
                'error': 'dates',
            })
            if room_type_id:
                return request.redirect('/hotel/room/%s?%s' % (room_type_id, params))
            return request.redirect('/hotel?%s' % params)

        try:
            adults = max(int(post.get('adults') or 0), 1)
            children = max(int(post.get('children') or 0), 0)
        except (TypeError, ValueError):
            adults = 0
            children = 0
        guests = adults + children

        room = request.env['hotel.room'].sudo()
        try:
            room_id = int(post.get('room_id') or 0)
        except (TypeError, ValueError):
            room_id = 0
        try:
            room_type_id = int(post.get('room_type_id') or 0)
        except (TypeError, ValueError):
            room_type_id = 0
        if room_id:
            room = room.browse(room_id).exists()
            available_rooms = self._available_rooms(checkin, checkout, room.room_type_id.id if room else False)
        else:
            available_rooms = self._available_rooms(checkin, checkout, room_type_id or False)
            room = available_rooms[:1]
        if guests:
            available_rooms = available_rooms.filtered(lambda available_room: not available_room.capacity or available_room.capacity >= guests)
            if not room or room not in available_rooms:
                room = available_rooms[:1]
        if not room or room not in available_rooms:
            return request.redirect('/hotel?checkin=%s&checkout=%s&error=unavailable' % (checkin, checkout))

        guest_name = (post.get('guest_name') or post.get('guest_0_name') or '').strip()
        guest_email = (post.get('guest_email') or post.get('guest_0_email') or '').strip()
        guest_phone = (post.get('guest_phone') or post.get('guest_0_phone') or '').strip()
        if not adults or not guest_name or not guest_phone:
            return self._booking_error_redirect(post, 'contact', checkin, checkout, adults, children, room_type_id)
        if guest_email and not single_email_re.match(guest_email):
            return self._booking_error_redirect(post, 'email', checkin, checkout, adults, children, room_type_id)
        partner_name = guest_name or guest_email or _('Website Guest')

        website_partner = self._website_customer_partner()
        Partner = request.env['res.partner'].sudo()
        if website_partner and (
            not guest_email
            or self._normalized_email(guest_email) == self._normalized_email(website_partner.email)
        ):
            partner = website_partner
        elif guest_email:
            partner = Partner.search([('email', '=ilike', guest_email)], limit=1)
        else:
            partner = Partner.search([('name', '=ilike', partner_name), ('phone', '=', guest_phone)], limit=1)
        partner_vals = {
            'name': partner_name,
            'email': guest_email or False,
            'phone': guest_phone,
            'customer_rank': 1,
        }
        if partner:
            if guest_phone and not partner.phone:
                partner.write({'phone': guest_phone})
            if guest_email and not partner.email:
                partner.write({'email': guest_email})
        else:
            partner = Partner.create(partner_vals)

        special_request = (post.get('special_request') or '').strip()
        pricing = self._room_pricing(room.room_type_id, checkin, checkout, adults=adults)
        room_rate = pricing['nightly_rate']
        expected_deposit_amount = self._deposit_amount(pricing, checkin, checkout)
        if self._deposit_policy()['required'] and pricing['total'] <= 0.0:
            return request.redirect('/hotel?checkin=%s&checkout=%s&error=rate' % (checkin, checkout))
        website_source = request.env.ref('hotel_management.source_website', raise_if_not_found=False)
        website_source = website_source.sudo() if website_source else website_source
        wants_deposit_payment = expected_deposit_amount > 0.0

        rate_plan = pricing['rate_plan']

        Reservation = request.env['hotel.reservation'].sudo().with_context(hotel_reservation_security_bypass=True)
        reservation_vals = {
            'partner_id': partner.id,
            'room_type_id': room.room_type_id.id,
            'room_id': room.id,
            'checkin_date': checkin,
            'checkout_date': checkout,
            'adults': adults,
            'children': children,
            'rate_plan_id': rate_plan.id if rate_plan else False,
            'is_manual_rate': not bool(rate_plan),
            'manual_rate': 0.0 if rate_plan else room_rate,
            'guest_note': special_request,
            'reference': _('Website Booking'),
            'website_partner_id': website_partner.id if website_partner else False,
            'website_booking_email': self._normalized_email(guest_email or (website_partner.email if website_partner else '')) or False,
            'website_booking_phone': guest_phone or False,
            'website_booking_payload': json.dumps(self._safe_booking_payload(post), default=str),
            'website_payment_status': 'pending_verification' if wants_deposit_payment else 'none',
            'website_deposit_amount': expected_deposit_amount,
            'state': 'draft',
        }
        for field_name in ('estimated_arrival', 'smoking_preference', 'bed_preference'):
            selection_values = dict(Reservation._fields[field_name].selection)
            if post.get(field_name) in selection_values:
                reservation_vals[field_name] = post[field_name]
        if website_source:
            reservation_vals.update({
                'booking_source_category_id': website_source.category_id.id,
                'booking_sub_source_id': website_source.id,
                'source_id': website_source.id,
            })

        try:
            reservation = Reservation.create(reservation_vals)
        except ValidationError:
            return request.redirect('/hotel?checkin=%s&checkout=%s&error=unavailable' % (checkin, checkout))
        if not reservation.access_token:
            reservation.write({'access_token': str(uuid.uuid4())})
        guest_post = dict(post)
        guest_post.update({
            'guest_0_name': guest_name,
            'guest_0_email': guest_email,
            'guest_0_phone': guest_phone,
        })
        self._save_pre_arrival_guest_slot(reservation, 0, guest_post)
        partner_vals = {}
        for post_name, field_name in (('street', 'street'), ('city', 'city')):
            if post.get(post_name):
                partner_vals[field_name] = post[post_name].strip()
        if partner_vals and reservation.partner_id:
            self._safe_write_partner_values(reservation.partner_id.sudo(), partner_vals)
        udf_vals = {}
        for index in range(1, 11):
            attribute_id = post.get('udf_value_%s' % index)
            if attribute_id and attribute_id.isdigit():
                attribute = request.env['hotel.guest.attribute'].sudo().browse(int(attribute_id)).exists()
                if attribute and attribute.udf_number == str(index):
                    udf_vals['udf_value_%s' % index] = attribute.id
        if udf_vals:
            reservation.write(udf_vals)
        body = Markup(
            '<p><strong>New website booking request</strong></p>'
            '<ul>'
            '<li>Guest: %s</li>'
            '<li>Email: %s</li>'
            '<li>Phone: %s</li>'
            '<li>Room: %s</li>'
            '<li>Stay: %s to %s</li>'
            '<li>Guests: %s adult(s), %s child(ren)</li>'
            '<li>Special request: %s</li>'
            '</ul>'
        ) % (
            guest_name or '-',
            guest_email or '-',
            guest_phone or '-',
            room.display_name,
            checkin,
            checkout,
            adults,
            children,
            special_request or '-',
        )
        reservation.message_post(body=body, message_type='comment', subtype_xmlid='mail.mt_comment')

        notify_user = request.env.ref('base.user_admin', raise_if_not_found=False)
        if notify_user:
            reservation.activity_schedule(
                'mail.mail_activity_data_todo',
                user_id=notify_user.id,
                summary=_('Review website booking request'),
                note=_('A customer submitted a booking request from the hotel website.'),
            )

        return request.redirect('/hotel/confirmation/%s' % reservation.access_token)

    @http.route('/hotel/bookings', type='http', auth='public', website=True)
    def hotel_bookings(self, **kw):
        Reservation = request.env['hotel.reservation'].sudo()
        booking_ids = []
        if not request.env.user._is_public():
            domain = self._current_user_booking_domain()
            if booking_ids:
                domain = expression.AND([
                    [('is_desk_folio', '=', False)],
                    expression.OR([[('id', 'in', booking_ids)], self._website_booking_owner_domain()]),
                ])
            reservations = Reservation.search(domain, order='create_date desc, id desc')
        else:
            domain = [('is_desk_folio', '=', False)]
            domain += [('id', 'in', booking_ids)]
            reservations = Reservation.search(domain)
            reservations = reservations.sorted(lambda r: booking_ids.index(r.id) if r.id in booking_ids else 999)
        return request.render('hotel_website_booking.hotel_booking_basket', {
            'reservations': reservations,
        })

    @http.route('/hotel/payment/submit_receipt/<string:access_token>', type='http', auth='public', website=True, methods=['POST'], csrf=True)
    def hotel_payment_submit_receipt(self, access_token, **kw):
        reservation = request.env['hotel.reservation'].sudo().search([
            ('access_token', '=', access_token),
        ], limit=1)
        if not reservation:
            return request.not_found()

        receipt_file = request.httprequest.files.get('receipt_file')
        if receipt_file and receipt_file.filename:
            attachment = request.env['ir.attachment'].sudo().create({
                'name': receipt_file.filename,
                'datas': base64.b64encode(receipt_file.read()),
                'res_model': 'hotel.reservation',
                'res_id': reservation.id,
            })
            message_body = _(
                "Guest uploaded deposit payment receipt: <b>%s</b>. Please verify the deposit of %s %s in your bank account."
            ) % (
                receipt_file.filename,
                reservation.currency_id.symbol or '',
                f"{reservation.website_deposit_amount or reservation.hotel_required_deposit_amount:.2f}"
            )
            reservation.message_post(
                body=message_body,
                attachment_ids=[attachment.id]
            )

        reservation.write({
            'website_payment_status': 'pending_verification',
        })

        return request.redirect('/hotel/confirmation/%s' % reservation.access_token)

    @http.route('/hotel/confirmation/<string:access_token>', type='http', auth='public', website=True)
    def hotel_booking_confirmation(self, access_token, **kw):
        reservation = request.env['hotel.reservation'].sudo().search([
            ('access_token', '=', access_token),
        ], limit=1)
        if not reservation:
            return request.not_found()
        website_partner = self._website_customer_partner()
        if website_partner and not reservation.website_partner_id:
            emails = [
                reservation.website_booking_email,
                reservation.partner_id.email,
                request.env.user.email,
                website_partner.email,
            ]
            normalized_reservation_emails = {
                self._normalized_email(email)
                for email in emails[:2]
                if self._normalized_email(email)
            }
            normalized_user_emails = {
                self._normalized_email(email)
                for email in emails[2:]
                if self._normalized_email(email)
            }
            if reservation.partner_id == website_partner or normalized_reservation_emails.intersection(normalized_user_emails):
                reservation.write({'website_partner_id': website_partner.id})
        payment_status = self._payment_status_label(reservation.website_payment_status)
        if reservation.website_payment_status == 'none' and reservation.website_deposit_amount:
            payment_status = _('Not collected online')
        values = {
            'reservation': reservation,
            'payment_status': payment_status,
            'deposit_amount': reservation.website_deposit_amount,
            'currency': reservation.currency_id or reservation.company_id.currency_id,
        }
        return request.render('hotel_website_booking.hotel_booking_confirmation', values)
