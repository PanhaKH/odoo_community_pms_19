from odoo import http
from odoo.exceptions import UserError, ValidationError
from odoo.http import request
from odoo.addons.portal.controllers.portal import CustomerPortal, pager as portal_pager
from odoo.addons.web.controllers.utils import ensure_db
import base64
import logging

_logger = logging.getLogger(__name__)

class HotelCustomerPortal(CustomerPortal):

    def _get_allowed_request_types(self):
        return {
            key
            for key, _label in request.env['hotel.service.request']._fields['request_type'].selection
        }

    def _get_owned_reservation(self, reservation_id):
        partner = request.env.user.partner_id
        return request.env['hotel.reservation'].sudo().search([
            ('id', '=', reservation_id),
            ('partner_id', '=', partner.id),
        ], limit=1)

    def _get_tokenized_reservation(self, res_id, access_token, allowed_states=None):
        reservation = request.env['hotel.reservation'].sudo().browse(res_id)
        if not reservation.exists() or reservation.access_token != access_token:
            return request.env['hotel.reservation']

        if allowed_states and reservation.state not in allowed_states:
            return request.env['hotel.reservation']

        return reservation

    def _get_pre_arrival_prefill_values(self, reservation):
        """Return reusable guest information after the access token has been checked."""
        partner = reservation.partner_id
        previous = request.env['hotel.reservation']
        if partner:
            previous = request.env['hotel.reservation'].sudo().search([
                ('partner_id', '=', partner.id),
                ('id', '!=', reservation.id),
            ], order='checkin_date desc, checkout_date desc, id desc', limit=1)

        def relation_id(record):
            return record.id if record else False

        prefill_values = {
            'guest_name': partner.name or '',
            'phone': partner.phone or '',
            'email': partner.email or '',
            'passport_number': partner.passport_number or '',
            'nationality_id': relation_id(partner.nationality_id)
                or relation_id(previous.guest_nationality_id),
            'country_id': relation_id(partner.country_id)
                or relation_id(previous.guest_country_id),
            'street': partner.street or '',
            'city': partner.city or '',
            'estimated_arrival': reservation.estimated_arrival
                or previous.estimated_arrival or 'afternoon',
            'smoking_preference': reservation.smoking_preference
                or previous.smoking_preference or 'non_smoking',
            'bed_preference': reservation.bed_preference
                or previous.bed_preference or 'any',
        }
        for index in range(1, 11):
            current_value = reservation[f'udf_value_{index}']
            previous_value = previous[f'udf_value_{index}']
            prefill_values[f'udf_value_{index}'] = relation_id(current_value or previous_value)
        return prefill_values

    def _get_pre_arrival_udf_fields(self, reservation, prefill_values):
        attribute_model = request.env['hotel.guest.attribute'].sudo()
        udf_fields = []
        for index in range(1, 11):
            options = attribute_model.search(
                [('udf_number', '=', str(index))],
                order='sequence, name',
            )
            if options:
                udf_fields.append({
                    'label': reservation[f'udf_label_{index}'],
                    'name': f'udf_value_{index}',
                    'options': options,
                    'value': prefill_values[f'udf_value_{index}'],
                })
        return udf_fields

    def _get_pre_arrival_guest_slots(self, reservation, prefill_values):
        reservation.sudo()._sync_stay_guests_from_reservation_partners()
        expected_count = max((reservation.adults or 0) + (reservation.children or 0), 1)
        slots = []
        existing_guests = reservation.stay_guest_ids.sorted(lambda guest: (0 if guest.is_primary else 1, guest.id))
        for index in range(expected_count):
            stay_guest = existing_guests[index] if index < len(existing_guests) else request.env['hotel.reservation.guest']
            is_primary = index == 0
            partner = reservation.partner_id if is_primary else stay_guest.partner_id
            slots.append({
                'index': index,
                'title': 'Main Guest' if is_primary else 'Accompanying Guest %s' % index,
                'is_primary': is_primary,
                'stay_guest': stay_guest,
                'name': (prefill_values.get('guest_name') if is_primary else stay_guest.name) or (partner.name if partner else ''),
                'phone': (prefill_values.get('phone') if is_primary else stay_guest.phone) or (partner.phone if partner else ''),
                'email': (prefill_values.get('email') if is_primary else stay_guest.email) or (partner.email if partner else ''),
                'passport_number': (prefill_values.get('passport_number') if is_primary else stay_guest.passport_no) or (partner.passport_number if partner else ''),
                'nationality_id': (prefill_values.get('nationality_id') if is_primary else stay_guest.nationality_id.id) or (partner.nationality_id.id if partner and partner.nationality_id else False),
                'country_id': (prefill_values.get('country_id') if is_primary else stay_guest.country_id.id) or (partner.country_id.id if partner and partner.country_id else False),
                'date_of_birth': stay_guest.date_of_birth or (partner.hotel_date_of_birth if partner else False),
                'gender': stay_guest.gender or (partner.hotel_gender if partner else False),
            })
        return slots

    def _get_relation_id_from_post(self, post, field_name, model_name):
        record_id = post.get(field_name)
        if record_id and record_id.isdigit():
            record = request.env[model_name].sudo().browse(int(record_id)).exists()
            if record:
                return record.id
        return False

    def _safe_write_partner_values(self, partner, values, strict_identity=False):
        if not partner:
            return False

        clean_values = {
            key: value
            for key, value in values.items()
            if value and key in partner._fields
        }
        passport_number = clean_values.get('passport_number')
        if passport_number and 'passport_number' in partner._fields:
            duplicate = request.env['res.partner'].sudo().search([
                ('passport_number', '=', passport_number),
                ('id', '!=', partner.id),
            ], limit=1)
            if duplicate:
                message = (
                    "This Passport/ID is already assigned to another guest profile (%s). "
                    "Please contact the Front Desk to review the duplicate guest identity before submitting."
                ) % duplicate.display_name
                if strict_identity:
                    raise UserError(message)
                _logger.info(
                    "Skipping duplicate passport number during pre-arrival partner update. "
                    "partner_id=%s duplicate_partner_id=%s",
                    partner.id, duplicate.id,
                )
                clean_values.pop('passport_number', None)

        write_values = {}
        for key, value in clean_values.items():
            current_value = partner[key]
            if partner._fields[key].type == 'many2one':
                current_value = current_value.id
            if current_value != value:
                write_values[key] = value
        if write_values:
            partner.sudo().write(write_values)
            return True
        return False

    def _save_pre_arrival_guest_slot(self, reservation, index, post):
        prefix = f'guest_{index}_'
        name = (post.get(prefix + 'name') or '').strip()
        if not name:
            return request.env['hotel.reservation.guest']

        values = {
            'name': name,
            'phone': (post.get(prefix + 'phone') or '').strip(),
            'email': (post.get(prefix + 'email') or '').strip(),
            'passport_no': (post.get(prefix + 'passport_number') or '').strip(),
            'nationality_id': self._get_relation_id_from_post(post, prefix + 'nationality_id', 'hotel.nationality'),
            'country_id': self._get_relation_id_from_post(post, prefix + 'country_id', 'res.country'),
            'date_of_birth': post.get(prefix + 'date_of_birth') or False,
            'gender': post.get(prefix + 'gender') if post.get(prefix + 'gender') in ('male', 'female', 'other', 'undisclosed') else False,
        }
        StayGuest = request.env['hotel.reservation.guest'].sudo()
        if index == 0:
            guest_line = reservation.stay_guest_ids.filtered('is_primary')[:1]
            linked_partner = reservation.partner_id or guest_line.partner_id
        else:
            guest_line = reservation.stay_guest_ids.filtered(lambda guest: not guest.is_primary).sorted('id')
            guest_line = guest_line[index - 1:index] if len(guest_line) >= index else request.env['hotel.reservation.guest']
            selected_guests = reservation.accompanying_guest_ids.sorted('id')
            linked_partner = guest_line.partner_id or (
                selected_guests[index - 1] if len(selected_guests) >= index else request.env['res.partner']
            )

        partner_values = {
            'name': values['name'],
            'phone': values['phone'],
            'email': values['email'],
            'passport_number': values['passport_no'],
            'nationality_id': values['nationality_id'],
            'country_id': values['country_id'],
            'hotel_date_of_birth': values['date_of_birth'],
            'hotel_gender': values['gender'],
        }
        partner_updated = False
        if linked_partner:
            partner = linked_partner.sudo()
            partner_updated = self._safe_write_partner_values(
                partner,
                partner_values,
                strict_identity=True,
            )
        else:
            partner = StayGuest.find_or_create_partner(values)

        match_level = partner.env.context.get('hotel_identity_match_level') if partner else False
        if match_level == 'weak':
            reservation.with_context(skip_hotel_guest_message_tracking=True).sudo().message_post(
                body=(
                    "Possible guest match found during pre-arrival registration: "
                    "%s was linked by name, nationality, and date of birth."
                ) % partner.display_name,
                message_type="comment",
                subtype_xmlid="mail.mt_comment",
            )

        upload = request.httprequest.files.get(prefix + 'passport_image')
        upload_filename = upload.filename if upload and upload.filename else ''
        image_data = StayGuest.values_from_upload(upload)
        if image_data:
            values['id_document_image'] = image_data
            if index == 0:
                reservation.sudo().write({'passport_image': image_data})
            try:
                if partner:
                    partner.sudo().write({'passport_image': image_data})
            except Exception:
                _logger.exception("Unable to save pre-arrival guest passport image on partner_id=%s", partner.id)

        values.update({
            'reservation_id': reservation.id,
            'partner_id': partner.id,
            'guest_type': 'main' if index == 0 else 'accompanying',
            'is_primary': index == 0,
        })

        if index == 0:
            if partner and reservation.partner_id != partner:
                reservation.sudo().write({'partner_id': partner.id})

        if guest_line:
            guest_line.sudo().write(values)
        else:
            guest_line = StayGuest.create(values)

        if partner_updated:
            reservation.with_context(skip_hotel_guest_message_tracking=True).sudo().message_post(
                body="Guest profile updated from pre-arrival registration.",
                message_type="comment",
                subtype_xmlid="mail.mt_comment",
            )

        if image_data:
            attachment = request.env['ir.attachment'].sudo().create({
                'name': upload_filename or "Pre-Arrival ID Photo - %s" % guest_line.name,
                'type': 'binary',
                'datas': image_data,
                'res_model': 'hotel.reservation',
                'res_id': reservation.id,
            })
            reservation.with_context(skip_hotel_guest_message_tracking=True).sudo().message_post(
                body="Pre-arrival ID/passport photo uploaded for %s." % guest_line.name,
                attachment_ids=[attachment.id],
                message_type="comment",
                subtype_xmlid="mail.mt_comment",
            )

        if index > 0 and partner not in reservation.accompanying_guest_ids:
            reservation.sudo().write({'accompanying_guest_ids': [(4, partner.id)]})

        return guest_line

    def _create_service_request(self, reservation, request_type, description):
        request_type = request_type if request_type in self._get_allowed_request_types() else 'other'
        description = (description or '').strip()
        if not description:
            return False

        return request.env['hotel.service.request'].sudo().create({
            'reservation_id': reservation.id,
            'request_type': request_type,
            'description': description,
        })

    def _create_guest_message(self, reservation, message_body, source):
        message_body = (message_body or '').strip()
        if not message_body:
            return request.env['hotel.guest.message']
        guest_message_model = request.env['hotel.guest.message'].sudo()
        if not guest_message_model._table_is_ready():
            return guest_message_model
        return guest_message_model.create({
            'reservation_id': reservation.id,
            'partner_id': reservation.partner_id.id,
            'message_body': message_body,
            'source': source,
        })

    def _render_pre_arrival_error(self, reservation=False, message=False, status=200):
        return request.render('hotel_management.portal_pre_arrival_error', {
            'reservation': reservation,
            'message': message or "We could not submit your pre-arrival registration. Please review the form and try again.",
        }, status=status)

    # Adds the count to the portal home box
    def _prepare_home_portal_values(self, counters):
        values = super()._prepare_home_portal_values(counters)
        if 'reservation_count' in counters:
            partner = request.env.user.partner_id
            count = request.env['hotel.reservation'].sudo().search_count([
                ('partner_id', '=', partner.id)
            ])
            values['reservation_count'] = count
        return values

    # List page for reservations
    @http.route(['/my/reservations', '/my/reservations/page/<int:page>'], type='http', auth="user", website=True)
    def portal_my_reservations(self, page=1, **kw):
        values = self._prepare_portal_layout_values()
        partner = request.env.user.partner_id
        HotelReservation = request.env['hotel.reservation'].sudo()

        domain = [('partner_id', '=', partner.id)]
        reservation_count = HotelReservation.search_count(domain)

        pager = portal_pager(
            url="/my/reservations",
            total=reservation_count,
            page=page,
            step=10
        )

        reservations = HotelReservation.search(domain, limit=10, offset=pager['offset'], order='checkin_date desc')

        values.update({
            'reservations': reservations,
            'page_name': 'reservation',
            'pager': pager,
            'default_url': '/my/reservations',
        })
        # Fetch the available countries and nationalities to send to the web page
        countries = request.env['res.country'].sudo().search([])
        nationalities = request.env['hotel.nationality'].sudo().search([])
        
        # Add them to your existing values/qcontext dictionary
        values.update({
            'countries': countries,
            'nationalities': nationalities,
        })

        return request.render("hotel_management.portal_my_reservations", values)

    # Detail page for a single reservation
    @http.route(['/my/reservation/<int:reservation_id>'], type='http', auth="user", website=True)
    def portal_my_reservation_detail(self, reservation_id, access_token=None, **kw):
        reservation = self._get_owned_reservation(reservation_id)
        if not reservation and access_token:
            reservation = self._get_tokenized_reservation(reservation_id, access_token)

        if not reservation:
            return request.redirect('/my')

        values = {
            'reservation': reservation,
            'page_name': 'reservation',
        }
        return request.render("hotel_management.portal_reservation_page", values)

    # POST Route to handle service request form (Logged in users)
    @http.route(['/my/reservation/request/submit'], type='http', auth="user", methods=['POST'], website=True)
    def portal_submit_request(self, **post):
        res_id = int(post.get('reservation_id'))
        reservation = self._get_owned_reservation(res_id)
        if not reservation:
            return request.redirect('/my')

        description = (post.get('description') or '').strip()
        self._create_service_request(
            reservation,
            post.get('request_type'),
            description,
        )
        self._create_guest_message(reservation, description, 'customer_portal')
        return request.redirect('/my/reservation/%s' % res_id)

    # =========================================================
    # MAGIC LINK PORTAL (Passwordless access for Guests) - RESTORED!
    # =========================================================
    @http.route(['/hotel/reservation/<int:res_id>'], type='http', auth="none")
    def portal_magic_link_reservation(self, res_id, access_token=None, db=None, success=None, **kw):
        ensure_db(db=db)
        db_name = request.session.db or db or request.env.cr.dbname
        target = f'/hotel/reservation/view/{res_id}?db={db_name}&access_token={access_token}'
        if success:
            target += '&success=1'
        return request.redirect(target)

    @http.route(['/hotel/reservation/view/<int:res_id>'], type='http', auth="public", website=True)
    def portal_magic_link_reservation_view(self, res_id, access_token=None, **kw):
        reservation = self._get_tokenized_reservation(res_id, access_token)
        if not reservation:
            return request.render('website.404')

        return request.render('hotel_management.hotel_guest_portal_template', {
            'reservation': reservation,
            'page_name': 'reservation_portal',
        })

    # =========================================================
    # FORM SUBMISSION RECEIVER (Creates Alert & Request) - RESTORED!
    # =========================================================
    @http.route(['/hotel/reservation/<int:res_id>/request'], type='http', auth="public", methods=['POST'], website=True)
    def magic_link_submit_request(self, res_id, access_token=None, **post):
        reservation = self._get_tokenized_reservation(res_id, access_token)
        if not reservation:
            return request.render('website.404')

        db_name = request.env.cr.dbname
        request_type = post.get('request_type', 'other')
        description = (post.get('description') or '').strip()
        if not description:
            return request.redirect(
                f'/hotel/reservation/view/{res_id}?db={db_name}&access_token={access_token}'
            )

        self._create_service_request(reservation, request_type, description)
        self._create_guest_message(reservation, description, 'reservation_portal')

        alert_message = f"New guest request ({request_type})<br/>{description}"
        reservation.with_context(skip_hotel_guest_message_tracking=True).sudo().message_post(
            body=alert_message,
            message_type="comment",
            subtype_xmlid="mail.mt_comment"
        )

        return request.redirect(
            f'/hotel/reservation/view/{res_id}?db={db_name}&access_token={access_token}&success=1'
        )

    # =========================================================
    # PRE-ARRIVAL PORTAL (Exact Clone of Working Guest Portal)
    # =========================================================
    @http.route(['/pre-arrival/<int:res_id>'], type='http', auth="none")
    def pre_arrival_entry(self, res_id, access_token=None, db=None, **kw):
        ensure_db(db=db)
        db_name = request.session.db or db or request.env.cr.dbname
        return request.redirect(f'/pre-arrival/view/{res_id}?db={db_name}&access_token={access_token}')

    @http.route(['/pre-arrival/view/<int:res_id>'], type='http', auth="public", website=True)
    def pre_arrival_form(self, res_id, access_token=None, **kw):
        reservation = self._get_tokenized_reservation(res_id, access_token)
        if not reservation:
            return "Unauthorized: The link is invalid, expired, or the security token does not match."

        countries = request.env['res.country'].sudo().search([])
        nationalities = request.env['hotel.nationality'].sudo().search([])
        prefill_values = self._get_pre_arrival_prefill_values(reservation)
        guest_slots = self._get_pre_arrival_guest_slots(reservation, prefill_values)

        return request.render('hotel_management.portal_pre_arrival_form', {
            'reservation': reservation,
            'access_token': access_token,
            'countries': countries,
            'nationalities': nationalities,
            'prefill_values': prefill_values,
            'guest_slots': guest_slots,
            'udf_fields': self._get_pre_arrival_udf_fields(reservation, prefill_values),
        })

    @http.route(['/pre-arrival/submit'], type='http', auth="public", methods=['POST'], website=True, csrf=False)
    def pre_arrival_submit(self, **post):
        res_id = post.get('reservation_id')
        access_token = post.get('access_token')
        reservation = request.env['hotel.reservation']
        try:
            if not res_id or not str(res_id).isdigit():
                return self._render_pre_arrival_error(
                    message="The reservation reference is missing or invalid.",
                    status=400,
                )

            reservation = self._get_tokenized_reservation(int(res_id), access_token)
            if not reservation:
                return self._render_pre_arrival_error(
                    message="The pre-arrival link is invalid or expired.",
                    status=403,
                )

            reservation_vals = {}
            for field_name in ('estimated_arrival', 'smoking_preference', 'bed_preference'):
                selection_values = dict(reservation._fields[field_name].selection)
                if post.get(field_name) in selection_values:
                    reservation_vals[field_name] = post[field_name]
            for index in range(1, 11):
                attribute_id = post.get(f'udf_value_{index}')
                if attribute_id and attribute_id.isdigit():
                    attribute = request.env['hotel.guest.attribute'].sudo().browse(
                        int(attribute_id)
                    ).exists()
                    if attribute and attribute.udf_number == str(index):
                        reservation_vals[f'udf_value_{index}'] = attribute.id
            if reservation_vals:
                reservation.sudo().write(reservation_vals)

            guest_count = max((reservation.adults or 0) + (reservation.children or 0), 1)
            saved_guests = request.env['hotel.reservation.guest']
            for index in range(guest_count):
                saved_guests |= self._save_pre_arrival_guest_slot(reservation, index, post)

            partner_vals = {}
            for post_name, field_name in (
                ('street', 'street'),
                ('city', 'city'),
            ):
                if post.get(post_name):
                    partner_vals[field_name] = post[post_name].strip()
            relation_models = (
                ('country_id', 'country_id', 'res.country'),
                ('nationality_id', 'nationality_id', 'hotel.nationality'),
            )
            for post_name, field_name, model_name in relation_models:
                record_id = post.get(post_name)
                if record_id and record_id.isdigit():
                    record = request.env[model_name].sudo().browse(int(record_id)).exists()
                    if record:
                        partner_vals[field_name] = record.id
            self._safe_write_partner_values(reservation.partner_id, partner_vals)

            if 'passport_image' in request.httprequest.files:
                upload = request.httprequest.files.get('passport_image')
                if upload and upload.filename:
                    image_data = base64.b64encode(upload.read())
                    reservation.sudo().write({'passport_image': image_data})
                    try:
                        reservation.partner_id.sudo().write({'passport_image': image_data})
                    except Exception:
                        _logger.exception(
                            "Unable to save legacy pre-arrival passport image on partner_id=%s",
                            reservation.partner_id.id,
                        )
                    attachment = request.env['ir.attachment'].sudo().create({
                        'name': f"Passport_{reservation.partner_id.name}_{upload.filename}",
                        'type': 'binary',
                        'datas': image_data,
                        'res_model': 'hotel.reservation',
                        'res_id': reservation.id,
                    })

                    self._create_guest_message(
                        reservation,
                        "Guest submitted pre-arrival registration and uploaded an ID document.",
                        'pre_arrival',
                    )
                    reservation.with_context(skip_hotel_guest_message_tracking=True).sudo().message_post(
                        body="Guest successfully uploaded their ID/Passport via Pre-Arrival.",
                        attachment_ids=[attachment.id]
                    )

            if saved_guests:
                self._create_guest_message(
                    reservation,
                    "Guest submitted pre-arrival registration for %s guest profile(s)." % len(saved_guests),
                    'pre_arrival',
                )
                reservation.sudo()._apply_repeat_guest_classification()

            return request.render('hotel_management.portal_pre_arrival_success', {
                'reservation': reservation
            })
        except (UserError, ValidationError) as error:
            _logger.warning(
                "Pre-arrival submit blocked by validation. reservation_id=%s access_token_prefix=%s error=%s",
                res_id,
                (access_token or '')[:8],
                error,
            )
            return self._render_pre_arrival_error(
                reservation=reservation if reservation and reservation.exists() else False,
                message=str(error),
            )
        except Exception:
            _logger.exception(
                "Pre-arrival submit failed. reservation_id=%s access_token_prefix=%s",
                res_id,
                (access_token or '')[:8],
            )
            return self._render_pre_arrival_error(
                reservation=reservation if reservation and reservation.exists() else False,
            )

    @http.route(['/hotel/guest_messages/unread_count'], type='jsonrpc', auth="user")
    def guest_message_unread_count(self, **kw):
        return request.env['hotel.guest.message'].get_unread_status()
