from odoo import models, fields, api, _
from odoo.exceptions import AccessError, UserError, ValidationError
from datetime import timedelta
import base64

class HotelRoomType(models.Model):
    _name = 'hotel.room.type'
    _description = 'Hotel Room Type'
    name = fields.Char(required=True)
    code = fields.Char(string='Short Code')
    sequence = fields.Integer(default=10)
    zone_ids = fields.Many2many('hotel.zone', string="Allowed Buildings")

class HotelRoomAmenity(models.Model):
    _name = 'hotel.room.amenity'
    _description = 'Room Amenity'
    name = fields.Char(required=True)
    icon = fields.Char(string="Icon", help="FontAwesome Icon class (e.g. fa-wifi)")

class HotelZone(models.Model):
    _name = 'hotel.zone'
    _description = 'Hotel Zone / Building'
    _order = 'sequence, name'

    name = fields.Char(string="Building Name", required=True)
    color = fields.Integer(string="Color Index")
    sequence = fields.Integer(default=10)
    background_image = fields.Binary(string="Building Map Overview", attachment=True)
    pos_x = fields.Float(string="Campus X (%)", default=50.0)
    pos_y = fields.Float(string="Campus Y (%)", default=50.0)

    @api.model
    def save_campus_background(self, image_base64):
        Attachment = self.env['ir.attachment']
        existing = Attachment.search([('name', '=', 'hotel_campus_map_bg.png')], limit=1)
        if existing: existing.write({'datas': image_base64})
        else: Attachment.create({'name': 'hotel_campus_map_bg.png', 'type': 'binary', 'datas': image_base64, 'public': True, 'mimetype': 'image/png'})
        return True

    @api.model
    def get_campus_background(self):
        existing = self.env['ir.attachment'].search([('name', '=', 'hotel_campus_map_bg.png')], limit=1)
        if existing: return '/web/content/%s?unique=%s' % (existing.id, fields.Datetime.now())
        return False

class HotelFloor(models.Model):
    _name = 'hotel.floor'
    _description = 'Hotel Floor'
    _order = 'zone_id, sequence, name'
    _rec_name = 'display_name'

    name = fields.Char(required=True)
    sequence = fields.Integer(default=10)
    zone_id = fields.Many2one('hotel.zone', string="Zone / Building", required=True)
    background_image = fields.Binary(string="Floor Map Image", attachment=True)
    display_name = fields.Char(compute='_compute_display_name', store=True)

    @api.depends('name', 'zone_id.name')
    def _compute_display_name(self):
        for rec in self:
            if rec.zone_id:
                rec.display_name = f"{rec.zone_id.name} - {rec.name}"
            else:
                rec.display_name = rec.name

class HotelRoom(models.Model):
    _name = 'hotel.room'
    _description = 'Hotel Room'
    _inherit = ['mail.thread', 'mail.activity.mixin']
    _order = 'zone_id, floor_id, name'

    hk_board_stage = fields.Selection([
        ('clean', 'Clean'),
        ('dirty', 'Dirty'),
        ('inspected', 'Inspected'),
        ('occupied', 'Occupied'),
    ], string='Housekeeping Board Stage', compute='_compute_hk_board_stage', store=True, index=True)

    hk_reclean_required = fields.Boolean(
        string="Failed / Reclean",
        compute="_compute_hk_reclean_info",
        compute_sudo=True,
    )
    hk_reclean_reason = fields.Char(
        string="Reclean Reason",
        compute="_compute_hk_reclean_info",
        compute_sudo=True,
    )
    hk_reclean_photo_count = fields.Integer(
        string="Evidence Photos",
        compute="_compute_hk_reclean_info",
        compute_sudo=True,
    )
    @api.depends('occupancy_status', 'housekeeping_status')
    def _compute_hk_board_stage(self):
        for room in self:
            if room.occupancy_status == 'occupied':
                room.hk_board_stage = 'occupied'
            elif room.housekeeping_status == 'dirty':
                room.hk_board_stage = 'dirty'
            elif room.housekeeping_status == 'inspected':
                room.hk_board_stage = 'inspected'
            else:
                room.hk_board_stage = 'clean'

    def _compute_hk_reclean_info(self):
        try:
            Task = self.env['hotel.housekeeping'].sudo()
        except KeyError:
            Task = False

        for room in self:
            room.hk_reclean_required = False
            room.hk_reclean_reason = False
            room.hk_reclean_photo_count = 0

            if not Task:
                continue

            task = Task.search([
                ('room_id', '=', room.id),
                ('inspection_state', '=', 'failed'),
            ], order='inspected_datetime desc, write_date desc, id desc', limit=1)

            is_reclean = bool(
                task
                and room.housekeeping_status == 'dirty'
                and not room.release_ready
            )

            if (
                is_reclean
                and room.cleaned_at
                and task.inspected_datetime
                and room.cleaned_at > task.inspected_datetime
            ):
                is_reclean = False

            room.hk_reclean_required = is_reclean
            room.hk_reclean_reason = task.failure_reason if is_reclean else False
            room.hk_reclean_photo_count = len(task.inspection_attachment_ids) if is_reclean else 0

    name = fields.Char(string='Room Number', required=True, tracking=True)
    zone_id = fields.Many2one('hotel.zone', string="Building / Zone", required=True, tracking=True)
    floor_id = fields.Many2one('hotel.floor', string='Floor', required=True, tracking=True)
    room_type_id = fields.Many2one('hotel.room.type', string='Room Type', required=True)
    amenity_ids = fields.Many2many('hotel.room.amenity', string="Amenities")
    
    capacity = fields.Integer(string='Capacity', default=2)
    ooo_until = fields.Date(string="OOO Until")
    clean_priority = fields.Boolean(string="Clean Priority", default=False)
    housekeeping_release_policy = fields.Selection([
        ('inspection_required', 'Supervisor Inspection Required'),
        ('clean_only', 'Clean Only'),
    ], string="Release Policy", default='inspection_required', tracking=True)
    assigned_housekeeper_id = fields.Many2one('res.users', string="Assigned Housekeeper", tracking=True)
    assigned_inspector_id = fields.Many2one('res.users', string="Assigned Inspector", tracking=True)
    cleaned_by_id = fields.Many2one('res.users', string="Last Cleaned By", readonly=True)
    cleaned_at = fields.Datetime(string="Last Cleaned At", readonly=True)
    inspected_by_id = fields.Many2one('res.users', string="Last Inspected By", readonly=True)
    inspected_at = fields.Datetime(string="Last Inspected At", readonly=True)
    release_ready = fields.Boolean(string="Release Ready", tracking=True)
    service_workflow = fields.Selection([
        ('arrival_priority', 'Arrival Priority'),
        ('departure_clean', 'Departure Clean'),
        ('inspection_pending', 'Inspection Pending'),
        ('stayover_service', 'Stayover Service'),
        ('vacant_ready', 'Vacant Ready'),
        ('out_of_order', 'Out of Order'),
    ], string="Service Workflow", tracking=True)
    arrival_priority_level = fields.Selection([
        ('none', 'No Arrival Pressure'),
        ('arrival_today', 'Arrival Today'),
        ('rush_arrival', 'Rush Arrival'),
    ], string="Arrival Priority", default='none', compute='_compute_arrival_priority_level', store=True, tracking=True)
    departure_clean_required = fields.Boolean(string="Departure Clean Required", tracking=True)
    do_not_disturb = fields.Boolean(string="Do Not Disturb", tracking=True)
    turndown_required = fields.Boolean(string="Turndown Required", tracking=True)
    turndown_completed = fields.Boolean(string="Turndown Completed", tracking=True)
    minibar_check_required = fields.Boolean(string="Minibar Check Required", tracking=True)
    minibar_checked = fields.Boolean(string="Minibar Checked", tracking=True)
    linen_change_required = fields.Boolean(string="Linen Change Required", tracking=True)
    linen_changed = fields.Boolean(string="Linen Changed", tracking=True)
    room_note = fields.Text(string="Room Note")

    pos_x = fields.Float(string="Position X (%)", default=10.0)
    pos_y = fields.Float(string="Position Y (%)", default=10.0)
    shape = fields.Selection([('square', 'Standard Room'), ('wide', 'Suite'), ('tall', 'Vertical')], default='square')

    state = fields.Selection([
        ('vacant_clean', 'Vacant Clean'), ('vacant_dirty', 'Vacant Dirty'),
        ('occupied_clean', 'Occupied Clean'), ('occupied_dirty', 'Occupied Dirty'),
        ('blocked', 'Out of Order'), ('available', 'Available (Legacy)'),
    ], string='Status', default='vacant_clean', tracking=True)
    occupancy_status = fields.Selection([
        ('vacant', 'Vacant'),
        ('occupied', 'Occupied'),
    ], string='Occupancy', tracking=True)
    housekeeping_status = fields.Selection([
        ('dirty', 'Dirty'),
        ('clean', 'Clean'),
        ('inspected', 'Inspected'),
    ], string='Housekeeping', tracking=True)
    availability_status = fields.Selection([
        ('available', 'Available'),
        ('out_of_order', 'Out of Order'),
    ], string='Availability', tracking=True)

    # --- LIVE STATUS LINKS (IN-HOUSE, ARRIVAL, BLOCK) ---
    reservation_ids = fields.One2many('hotel.reservation', 'room_id', string='Reservations')
    
    is_arrival_today = fields.Boolean(compute='_compute_live_status')
    arrival_reservation_id = fields.Many2one('hotel.reservation', compute='_compute_live_status')
    
    is_occupied = fields.Boolean(compute='_compute_live_status')
    inhouse_reservation_id = fields.Many2one('hotel.reservation', compute='_compute_live_status')
    
    is_blocked_today = fields.Boolean(compute='_compute_live_status')
    block_id = fields.Many2one('hotel.reservation', compute='_compute_live_status')
    room_block_id = fields.Many2one('hotel.room.block', compute='_compute_live_status')

    # --- CONNECTING ROOMS LOGIC ---
    physical_connecting_room_ids = fields.Many2many(
        'hotel.room', 'room_physical_rel', 'room1_id', 'room2_id', 
        string="Physical Connecting Doors",
        help="Rooms that physically share a door."
    )
    active_connecting_room_ids = fields.Many2many(
        'hotel.room', 'room_active_rel', 'room1_id', 'room2_id', 
        string="Currently Connected (Open)",
        help="Check this when selling the rooms together as a suite."
    )

    @api.model
    def _housekeeping_room_write_fields(self):
        return {
            'housekeeping_status',
            'assigned_housekeeper_id',
            'assigned_inspector_id',
            'do_not_disturb',
            'turndown_required',
            'turndown_completed',
            'minibar_check_required',
            'minibar_checked',
            'linen_change_required',
            'linen_changed',
            'clean_priority',
            'room_note',
            'message_follower_ids',
            'message_partner_ids',
            'message_main_attachment_id',
        }

    @api.model
    def _front_office_room_write_fields(self):
        return {
            'message_follower_ids',
            'message_partner_ids',
            'message_main_attachment_id',
        }

    @api.model
    def _reservation_workflow_room_write_fields(self):
        return {
            'occupancy_status',
            'housekeeping_status',
            'availability_status',
            'do_not_disturb',
            'turndown_required',
            'turndown_completed',
            'minibar_check_required',
            'minibar_checked',
            'linen_change_required',
            'linen_changed',
        }

    @api.model
    def _is_reservation_workflow_room_write(self, vals):
        field_names = set(vals)
        if not field_names or field_names - self._reservation_workflow_room_write_fields():
            return False
        if vals.get('housekeeping_status') not in (None, 'dirty'):
            return False
        if vals.get('occupancy_status') not in (None, 'occupied', 'vacant'):
            return False
        if vals.get('availability_status') not in (None, 'available', 'out_of_order'):
            return False
        boolean_fields = {
            'do_not_disturb',
            'turndown_required',
            'turndown_completed',
            'minibar_check_required',
            'minibar_checked',
            'linen_change_required',
            'linen_changed',
        }
        return all(isinstance(vals[field], bool) for field in boolean_fields if field in vals)

    @api.model
    def _user_has_group_if_exists(self, xmlid):
        return bool(self.env.ref(xmlid, raise_if_not_found=False)) and self.env.user.has_group(xmlid)

    @api.model
    def _can_update_housekeeping_room_status(self):
        allowed_groups = (
            'hotel_management.group_hotel_housekeeper',
            'hotel_housekeeping_app.group_housekeeping_user',
            'hotel_housekeeping_app.group_housekeeping_supervisor',
            'hotel_housekeeping_app.group_housekeeping_manager',
            'hotel_management.group_hotel_manager',
            'base.group_system',
        )
        return (
            self.env.su
            or self.env.context.get('install_mode')
            or any(self._user_has_group_if_exists(group) for group in allowed_groups)
        )

    def _check_housekeeping_room_status_access(self):
        if self._can_update_housekeeping_room_status():
            return
        raise AccessError(_("Only Housekeeping, Hotel Manager, or System users can update housekeeping room status."))

    @api.model
    def _can_manage_ooo(self):
        return (
            self.env.su
            or self.env.context.get('install_mode')
            or self.env.context.get('hotel_room_security_bypass')
            or self.env.user.has_group('hotel_management.group_hotel_front_office')
        )
    
    def _can_supervise_housekeeping_room(self):
        user = self.env.user

        if self.env.su:
            return True

        allowed_xmlids = [
            'hotel_housekeeping_app.group_housekeeping_supervisor',
            'hotel_housekeeping_app.group_housekeeping_manager',
            'hotel_management.group_hotel_manager',
            'base.group_system',
        ]

        for xmlid in allowed_xmlids:
            group = self.env.ref(xmlid, raise_if_not_found=False)
            if group and user.has_group(xmlid):
                return True

        return False

    @api.model
    def _check_room_write_access(self, vals):
        if (
            not vals
            or self.env.su
            or self.env.context.get('install_mode')
            or self.env.context.get('hotel_room_security_bypass')
            or self.env.user.has_group('hotel_management.group_hotel_manager')
        ):
            return
        if (
            self.env.context.get('hotel_reservation_room_workflow')
            and self._is_reservation_workflow_room_write(vals)
        ):
            return

        field_names = set(vals)

        housekeeping_inspection_fields = {
            'inspected_at',
            'inspected_by',
            'inspected_by_id',
            'release_ready',
            'service_type',
            'service_workflow',
            'inspection_state',
            'last_inspection_id',
        }

        if self.env.user.has_group('hotel_management.group_hotel_front_office'):
            allowed_fields = self._front_office_room_write_fields()

        elif self._can_supervise_housekeeping_room():
            # Supervisor/Manager can update normal housekeeping fields
            # plus inspection/release fields only.
            allowed_fields = (
                self._housekeeping_room_write_fields()
                | housekeeping_inspection_fields
            )

        elif self.env.user.has_group('hotel_management.group_hotel_housekeeper'):
            # Normal housekeeper can clean/update room status,
            # but cannot pass/fail/release inspection.
            allowed_fields = self._housekeeping_room_write_fields()

        else:
            raise AccessError(_("You are not allowed to modify hotel room operational data."))

        restricted_fields = sorted(field_names - allowed_fields)
        if restricted_fields:
            raise AccessError(
                _("You are not allowed to modify these room fields: %s") % ", ".join(restricted_fields)
            )

    @api.model
    def _check_ooo_management_access(self):
        if self._can_manage_ooo():
            return
        raise AccessError(_("Only Front Office can mark rooms unavailable or release OOO blocks."))

    @api.model
    def _operational_axes_from_state(self, state):
        state = state or 'vacant_clean'
        if state == 'blocked':
            return {
                'occupancy_status': 'vacant',
                'housekeeping_status': 'dirty',
                'availability_status': 'out_of_order',
            }
        if state == 'occupied_dirty':
            return {
                'occupancy_status': 'occupied',
                'housekeeping_status': 'dirty',
                'availability_status': 'available',
            }
        if state == 'occupied_clean':
            return {
                'occupancy_status': 'occupied',
                'housekeeping_status': 'clean',
                'availability_status': 'available',
            }
        if state == 'vacant_dirty':
            return {
                'occupancy_status': 'vacant',
                'housekeeping_status': 'dirty',
                'availability_status': 'available',
            }
        return {
            'occupancy_status': 'vacant',
            'housekeeping_status': 'clean',
            'availability_status': 'available',
        }

    @api.model
    def _legacy_state_from_axes(self, occupancy_status, housekeeping_status, availability_status):
        occupancy_status = occupancy_status or 'vacant'
        housekeeping_status = housekeeping_status or 'clean'
        availability_status = availability_status or 'available'

        if availability_status == 'out_of_order':
            return 'blocked'
        if occupancy_status == 'occupied':
            return 'occupied_dirty' if housekeeping_status == 'dirty' else 'occupied_clean'
        return 'vacant_dirty' if housekeeping_status == 'dirty' else 'vacant_clean'

    def _current_operational_axes(self):
        self.ensure_one()
        derived = self._operational_axes_from_state(self.state)
        return {
            'occupancy_status': self.occupancy_status or derived['occupancy_status'],
            'housekeeping_status': self.housekeeping_status or derived['housekeeping_status'],
            'availability_status': self.availability_status or derived['availability_status'],
        }

    def _effective_release_policy(self):
        self.ensure_one()
        return self.housekeeping_release_policy or 'inspection_required'

    def _get_housekeeping_workflow_values(self, occupancy_status, housekeeping_status, availability_status, arrival_today=False):
        self.ensure_one()
        release_policy = self._effective_release_policy()
        release_ready = (
            availability_status == 'available'
            and occupancy_status == 'vacant'
            and (
                housekeeping_status == 'inspected'
                or (
                    release_policy == 'clean_only'
                    and housekeeping_status in ['clean', 'inspected']
                )
            )
        )
        departure_clean_required = (
            availability_status == 'available'
            and occupancy_status == 'vacant'
            and housekeeping_status == 'dirty'
        )

        if availability_status == 'out_of_order':
            service_workflow = 'out_of_order'
        elif arrival_today and not release_ready:
            service_workflow = 'arrival_priority'
        elif departure_clean_required:
            service_workflow = 'departure_clean'
        elif occupancy_status == 'vacant' and housekeeping_status == 'clean' and release_policy == 'inspection_required':
            service_workflow = 'inspection_pending'
        elif occupancy_status == 'occupied' and availability_status == 'available':
            service_workflow = 'stayover_service'
        else:
            service_workflow = 'vacant_ready'

        arrival_priority_level = 'none'
        if arrival_today and release_ready:
            arrival_priority_level = 'arrival_today'
        elif arrival_today and not release_ready:
            arrival_priority_level = 'rush_arrival'

        return {
            'release_ready': release_ready,
            'departure_clean_required': departure_clean_required,
            'service_workflow': service_workflow,
            'arrival_priority_level': arrival_priority_level,
        }

    def _synchronize_operational_values(self, vals):
        vals = dict(vals)
        axes_fields = ['occupancy_status', 'housekeeping_status', 'availability_status']
        has_axes = any(field in vals for field in axes_fields)

        if 'state' in vals and not has_axes:
            vals.update(self._operational_axes_from_state(vals['state']))
            return vals

        if self:
            current = self._current_operational_axes()
        else:
            current = self._operational_axes_from_state(vals.get('state') or 'vacant_clean')

        occupancy_status = vals.get('occupancy_status', current['occupancy_status'])
        housekeeping_status = vals.get('housekeeping_status', current['housekeeping_status'])
        availability_status = vals.get('availability_status', current['availability_status'])

        vals['occupancy_status'] = occupancy_status
        vals['housekeeping_status'] = housekeeping_status
        vals['availability_status'] = availability_status
        vals['state'] = self._legacy_state_from_axes(
            occupancy_status,
            housekeeping_status,
            availability_status,
        )
        return vals

    def _ensure_operational_axes(self):
        for room in self:
            if room.occupancy_status and room.housekeeping_status and room.availability_status:
                continue
            derived = room._operational_axes_from_state(room.state)
            room.with_context(
                skip_hotel_room_reconcile=True,
                tracking_disable=True,
                mail_notrack=True,
            ).sudo().write(derived)

    def _reconcile_operational_status(self):
        if not self or self.env.context.get('skip_hotel_room_reconcile'):
            return

        rooms = self.with_context(skip_hotel_room_reconcile=True)
        rooms._ensure_operational_axes()

        biz_date = self.env.company.hotel_business_date or fields.Date.context_today(self)
        Reservation = self.env['hotel.reservation'].with_context(skip_hotel_room_reconcile=True)
        RoomBlock = self.env['hotel.room.block'].sudo()

        occupied_room_ids = set(Reservation.search([
            ('room_id', 'in', rooms.ids),
            # A room stays occupied until the guest is actually checked out.
            ('state', 'in', ['checkin', 'checkout_hold']),
            ('checkin_date', '<=', biz_date),
        ]).mapped('room_id').ids)

        legacy_blocked_room_ids = set(Reservation.search([
            ('room_id', 'in', rooms.ids),
            ('state', '=', 'blocked'),
            ('checkin_date', '<=', biz_date),
            ('checkout_date', '>', biz_date),
        ]).mapped('room_id').ids)
        room_blocked_room_ids = set(RoomBlock.search([
            ('room_id', 'in', rooms.ids),
            ('state', '=', 'active'),
            ('date_from', '<=', biz_date),
            ('date_to', '>', biz_date),
        ]).mapped('room_id').ids)
        blocked_room_ids = legacy_blocked_room_ids | room_blocked_room_ids

        arrival_room_ids = set(Reservation.search([
            ('room_id', 'in', rooms.ids),
            ('state', '=', 'confirm'),
            ('checkin_date', '=', biz_date),
        ]).mapped('room_id').ids)

        for room in rooms:
            current = room._current_operational_axes()
            target_vals = {
                'occupancy_status': 'occupied' if room.id in occupied_room_ids else 'vacant',
                'housekeeping_status': current['housekeeping_status'],
                'availability_status': 'out_of_order' if room.id in blocked_room_ids else 'available',
            }
            synced_vals = room._synchronize_operational_values(target_vals)
            synced_vals.update(
                room._get_housekeeping_workflow_values(
                    synced_vals['occupancy_status'],
                    synced_vals['housekeeping_status'],
                    synced_vals['availability_status'],
                    arrival_today=room.id in arrival_room_ids,
                )
            )
            if any(room[field] != synced_vals[field] for field in [
                'state', 'occupancy_status', 'housekeeping_status', 'availability_status',
                'release_ready', 'departure_clean_required', 'service_workflow', 'arrival_priority_level',
            ]):
                room.with_context(
                    skip_hotel_room_reconcile=True,
                    tracking_disable=True,
                    mail_notrack=True,
                ).sudo().write(synced_vals)

    def _sync_housekeeping_task_records(self):
        biz_date = self.env.company.hotel_business_date or fields.Date.context_today(self)
        Task = self.env['hotel.housekeeping'].sudo()

        for room in self:
            active_task = Task.search([
                ('room_id', '=', room.id),
                ('business_date', '=', biz_date),
                ('state', '!=', 'done'),
            ], order='id desc', limit=1)

            reservation = room.inhouse_reservation_id or room.arrival_reservation_id or room.block_id
            needs_task = any([
                room.housekeeping_status == 'dirty',
                room.service_workflow in ['arrival_priority', 'departure_clean', 'inspection_pending', 'stayover_service'],
                room.do_not_disturb,
                room.turndown_required,
                room.minibar_check_required,
                room.linen_change_required,
                room.assigned_housekeeper_id,
                room.assigned_inspector_id,
            ])

            task_state = 'done'
            if room.service_workflow == 'inspection_pending':
                task_state = 'inspection'
            elif room.housekeeping_status == 'dirty' or room.service_workflow in ['arrival_priority', 'departure_clean', 'stayover_service']:
                task_state = 'dirty'
            elif room.housekeeping_status == 'clean':
                task_state = 'clean'

            task_vals = {
                'name': f"HK {biz_date} / Room {room.name}",
                'room_id': room.id,
                'reservation_id': reservation.id if reservation else False,
                'maid_id': room.assigned_housekeeper_id.id,
                'inspector_id': room.assigned_inspector_id.id,
                'business_date': biz_date,
                'service_type': room.service_workflow,
                'arrival_priority_level': room.arrival_priority_level,
                'departure_clean_required': room.departure_clean_required,
                'release_policy': room._effective_release_policy(),
                'room_ready': room.release_ready,
                'do_not_disturb': room.do_not_disturb,
                'turndown_required': room.turndown_required,
                'turndown_completed': room.turndown_completed,
                'minibar_check_required': room.minibar_check_required,
                'minibar_checked': room.minibar_checked,
                'linen_change_required': room.linen_change_required,
                'linen_changed': room.linen_changed,
                'state': task_state,
            }

            if needs_task:
                if active_task:
                    active_task.write(task_vals)
                else:
                    Task.create(task_vals)
            elif active_task:
                active_task.write(dict(task_vals, state='done'))

    @api.depends(
        'reservation_ids.state',
        'reservation_ids.checkin_date',
        'reservation_ids.checkout_date',
        'release_ready',
        'housekeeping_status',
        'availability_status',
        'occupancy_status',
        'housekeeping_release_policy',
    )
    def _compute_arrival_priority_level(self):
        biz_date = self.env.company.hotel_business_date or fields.Date.context_today(self)
        arrival_room_ids = set(self.env['hotel.reservation'].sudo().search([
            ('room_id', 'in', self.ids),
            ('checkin_date', '=', biz_date),
            ('state', '=', 'confirm'),
        ]).mapped('room_id').ids)

        for room in self:
            if room.id not in arrival_room_ids:
                room.arrival_priority_level = 'none'
            elif room.release_ready:
                room.arrival_priority_level = 'arrival_today'
            else:
                room.arrival_priority_level = 'rush_arrival'            

    @api.depends('reservation_ids.state', 'reservation_ids.checkin_date', 'reservation_ids.checkout_date')
    def _compute_live_status(self):
        biz_date = self.env.company.hotel_business_date or fields.Date.context_today(self)
        for rec in self:
            # 1. In-House Guest
            inhouse = self.env['hotel.reservation'].search([
                ('room_id', '=', rec.id),
                # Due-out guests still occupy the room until checkout is completed.
                ('state', 'in', ['checkin', 'checkout_hold']),
                ('checkin_date', '<=', biz_date),
            ], limit=1)
            
            # 2. Arrival Today
            arrival = self.env['hotel.reservation'].search([
                ('room_id', '=', rec.id),
                ('checkin_date', '=', biz_date),
                ('state', '=', 'confirm')
            ], limit=1)
            
            # 3. Maintenance / OOO Block
            block = self.env['hotel.reservation'].search([
                ('room_id', '=', rec.id),
                ('state', '=', 'blocked'),
                ('checkin_date', '<=', biz_date),
                ('checkout_date', '>', biz_date)
            ], limit=1)
            room_block = self.env['hotel.room.block'].sudo().search([
                ('room_id', '=', rec.id),
                ('state', '=', 'active'),
                ('date_from', '<=', biz_date),
                ('date_to', '>', biz_date),
            ], limit=1)

            # --- ASSIGNMENTS ---
            rec.inhouse_reservation_id = inhouse.id
            rec.is_occupied = bool(inhouse)
            
            rec.arrival_reservation_id = arrival.id
            rec.is_arrival_today = bool(arrival)
            
            rec.block_id = block.id
            rec.room_block_id = room_block.id
            rec.is_blocked_today = bool(block or room_block)
            
            

    @api.constrains('zone_id', 'floor_id')
    def _check_location_consistency(self):
        for rec in self:
            if rec.floor_id and rec.zone_id and rec.floor_id.zone_id != rec.zone_id:
                raise ValidationError(f"Room {rec.name} cannot be on Floor '{rec.floor_id.name}' because that floor belongs to '{rec.floor_id.zone_id.name}', not '{rec.zone_id.name}'.")

    @api.onchange('zone_id')
    def _onchange_zone_id(self):
        if self.zone_id:
            if self.floor_id and self.floor_id.zone_id != self.zone_id: self.floor_id = False
            if self.room_type_id and self.zone_id.id not in self.room_type_id.zone_ids.ids: self.room_type_id = False

    @api.onchange('floor_id')
    def _onchange_floor_id(self):
        if self.floor_id and self.floor_id.zone_id: self.zone_id = self.floor_id.zone_id

    @api.model_create_multi
    def create(self, vals_list):
        prepared_vals_list = []
        for vals in vals_list:
            room_vals = dict(vals)
            if 'state' not in room_vals and not any(
                field in room_vals for field in ['occupancy_status', 'housekeeping_status', 'availability_status']
            ):
                room_vals['state'] = 'vacant_clean'
            prepared_vals_list.append(self._synchronize_operational_values(room_vals))

        rooms = super().create(prepared_vals_list)
        rooms._ensure_operational_axes()
        rooms._reconcile_operational_status()
        rooms._sync_housekeeping_task_records()
        return rooms

    def write(self, vals):
        self._check_room_write_access(vals)
        housekeeping_program_fields = [
            'housekeeping_release_policy',
            'assigned_housekeeper_id',
            'assigned_inspector_id',
            'cleaned_by_id',
            'cleaned_at',
            'inspected_by_id',
            'inspected_at',
            'release_ready',
            'do_not_disturb',
            'turndown_required',
            'turndown_completed',
            'minibar_check_required',
            'minibar_checked',
            'linen_change_required',
            'linen_changed',
            'clean_priority',
        ]
        sync_status_fields = [
            'state',
            'occupancy_status',
            'housekeeping_status',
            'availability_status',
            'release_ready',
            'service_workflow',
            'cleaned_by_id',
            'cleaned_at',
            'inspected_by_id',
            'inspected_at',
        ]

        if any(field in vals for field in sync_status_fields):
            for room in self:
                room_vals = room._synchronize_operational_values(vals)
                super(HotelRoom, room).write(room_vals)
            if not self.env.context.get('skip_hotel_room_reconcile'):
                self._reconcile_operational_status()
                self._sync_housekeeping_task_records()
            return True
        res = super().write(vals)
        if any(field in vals for field in housekeeping_program_fields) and not self.env.context.get('skip_hotel_room_reconcile'):
            self._reconcile_operational_status()
            self._sync_housekeeping_task_records()
        return res

    def action_set_clean(self):
        self._check_housekeeping_room_status_access()
        biz_date = self.env.company.hotel_business_date or fields.Date.today()
        for rec in self:
            if rec.availability_status == 'out_of_order':
                raise UserError(_("Room %s is Out of Order. Release OOO before changing housekeeping status.") % rec.name)
            has_active_block = self.env['hotel.reservation'].search_count([
                ('room_id', '=', rec.id),
                ('state', '=', 'blocked'),
                ('checkin_date', '<=', biz_date),
                ('checkout_date', '>', biz_date),
            ])
            rec.with_context(hotel_room_security_bypass=True).write({
                'housekeeping_status': 'clean',
                'availability_status': 'out_of_order' if has_active_block else 'available',
                'cleaned_by_id': self.env.user.id,
                'cleaned_at': fields.Datetime.now(),
                'inspected_by_id': False,
                'inspected_at': False,
            })
            if not has_active_block:
                rec.with_context(hotel_room_security_bypass=True).write({'ooo_until': False})
            rec._sync_housekeeping_task_records()

    def action_set_dirty(self):
        self._check_housekeeping_room_status_access()
        biz_date = self.env.company.hotel_business_date or fields.Date.today()
        for rec in self:
            if rec.availability_status == 'out_of_order':
                raise UserError(_("Room %s is Out of Order. Release OOO before changing housekeeping status.") % rec.name)
            has_active_block = self.env['hotel.reservation'].search_count([
                ('room_id', '=', rec.id),
                ('state', '=', 'blocked'),
                ('checkin_date', '<=', biz_date),
                ('checkout_date', '>', biz_date),
            ])
            rec.with_context(hotel_room_security_bypass=True).write({
                'housekeeping_status': 'dirty',
                'availability_status': 'out_of_order' if has_active_block else 'available',
                'cleaned_by_id': False,
                'cleaned_at': False,
                'inspected_by_id': False,
                'inspected_at': False,
                'turndown_completed': False,
                'minibar_checked': False,
                'linen_changed': False,
            })
            if not has_active_block:
                rec.with_context(hotel_room_security_bypass=True).write({'ooo_until': False})
            rec._sync_housekeeping_task_records()

    def action_set_inspected(self):
        self._check_housekeeping_room_status_access()
        now = fields.Datetime.now()

        for room in self:
            room.with_context(skip_hotel_room_reconcile=True).write({
                'housekeeping_status': 'inspected',
                'release_ready': True,
                'inspected_by_id': self.env.user.id,
                'inspected_at': now,
                'service_workflow': 'vacant_ready',
            })

        # Sync to housekeeping inspection/task records when the housekeeping model exists.
        inspection_model_name = False
        for model_name in [
            #'hotel.housekeeping.inspection',
            'housekeeping.inspection',
            'hotel.housekeeping.task',
        ]:
            if model_name in self.env.registry.models:
                inspection_model_name = model_name
                break

        if not inspection_model_name:
            return True

        Inspection = self.env[inspection_model_name].sudo()

        for room in self:
            task = Inspection.search([
                ('room_id', '=', room.id),
                ('state', '!=', 'done'),
            ], order='create_date desc', limit=1)

            if not task:
                task = Inspection.search([
                    ('room_id', '=', room.id),
                ], order='create_date desc', limit=1)

            vals = {}

            if 'state' in Inspection._fields:
                vals['state'] = 'done'
            if 'inspection_state' in Inspection._fields:
                vals['inspection_state'] = 'passed'
            if 'failure_reason' in Inspection._fields:
                vals['failure_reason'] = False
            if 'inspected_by' in Inspection._fields:
                vals['inspected_by'] = self.env.user.id
            if 'inspected_by_id' in Inspection._fields:
                vals['inspected_by_id'] = self.env.user.id
            if 'inspected_datetime' in Inspection._fields:
                vals['inspected_datetime'] = now
            if 'inspected_at' in Inspection._fields:
                vals['inspected_at'] = now
            if 'room_ready' in Inspection._fields:
                vals['room_ready'] = True

            if task:
                if 'cleaning_completed_by_id' in Inspection._fields and not task.cleaning_completed_by_id:
                    vals['cleaning_completed_by_id'] = self.env.user.id
                if 'cleaning_completed_datetime' in Inspection._fields and not task.cleaning_completed_datetime:
                    vals['cleaning_completed_datetime'] = now
                task.write(vals)
            else:
                vals['room_id'] = room.id
                Inspection.create(vals)
        # Sync Hotel Management Inspect action to Housekeeping Passed Today counter
        if 'hotel.housekeeping' in self.env.registry.models:
            Task = self.env['hotel.housekeeping'].sudo()
            now = fields.Datetime.now()
            today_start = fields.Datetime.to_datetime(fields.Date.context_today(self))
            biz_date = self.env.company.hotel_business_date or fields.Date.context_today(self)

            for room in self:
                task = Task.search([
                    ('room_id', '=', room.id),
                    ('state', '!=', 'done'),
                ], order='write_date desc, create_date desc, id desc', limit=1)

                if not task:
                    task = Task.search([
                        ('room_id', '=', room.id),
                        ('inspection_state', '=', 'passed'),
                        ('inspected_datetime', '>=', today_start),
                    ], order='write_date desc, create_date desc, id desc', limit=1)

                vals = {
                    'inspection_state': 'passed',
                    'inspected_by': self.env.user.id,
                    'inspected_datetime': now,
                    'failure_reason': False,
                    'state': 'done',
                    'room_ready': True,
                }

                if 'business_date' in Task._fields:
                    vals['business_date'] = biz_date

                if 'cleaning_completed_by_id' in Task._fields and task and not task.cleaning_completed_by_id:
                    vals['cleaning_completed_by_id'] = self.env.user.id

                if 'cleaning_completed_datetime' in Task._fields and task and not task.cleaning_completed_datetime:
                    vals['cleaning_completed_datetime'] = now

                if task:
                    task.write(vals)
                else:
                    create_vals = dict(vals)
                    create_vals.update({
                        'name': "Inspection Passed / Room %s" % (room.name or room.display_name),
                        'room_id': room.id,
                    })
                    Task.with_context(skip_housekeeping_duplicate_guard=True).create(create_vals)
        return True

    def action_set_blocked(self):
        self._check_ooo_management_access()
        for room in self:
            if room.occupancy_status == 'occupied' or room.is_occupied:
                raise UserError(_("You cannot mark an occupied room as unavailable!"))

            biz_date = self.env.company.hotel_business_date or fields.Date.today()
            existing_block = self.env['hotel.room.block'].sudo().search([
                ('room_id', '=', room.id),
                ('state', '=', 'active'),
                ('source', '=', 'manual'),
                ('date_from', '<=', biz_date),
                ('date_to', '>', biz_date),
            ], limit=1)

            if not existing_block:
                self.env['hotel.room.block'].sudo().create({
                    'name': _("OOO: %s") % room.name,
                    'room_id': room.id,
                    'date_from': biz_date,
                    'date_to': biz_date + timedelta(days=1),
                    'state': 'active',
                    'source': 'manual',
                    'reason': 'Unavailable / OOO',
                })

            room.with_context(hotel_room_security_bypass=True).write({'availability_status': 'out_of_order'})
            room._sync_housekeeping_task_records()

        return True

    def action_release_ooo(self):
        self._check_ooo_management_access()
        biz_date = self.env.company.hotel_business_date or fields.Date.today()
        for room in self:
            self.env['hotel.room.block'].sudo().search([
                ('room_id', '=', room.id),
                ('state', '=', 'active'),
                ('source', '=', 'manual'),
                ('date_from', '<=', biz_date),
                ('date_to', '>', biz_date),
            ]).action_release()
            has_active_legacy_block = self.env['hotel.reservation'].search_count([
                ('room_id', '=', room.id),
                ('state', '=', 'blocked'),
                ('checkin_date', '<=', biz_date),
                ('checkout_date', '>', biz_date),
            ])
            has_active_room_block = self.env['hotel.room.block'].sudo().search_count([
                ('room_id', '=', room.id),
                ('state', '=', 'active'),
                ('date_from', '<=', biz_date),
                ('date_to', '>', biz_date),
            ])
            has_active_block = bool(has_active_legacy_block or has_active_room_block)
            room.with_context(hotel_room_security_bypass=True).write({
                'availability_status': 'out_of_order' if has_active_block else 'available'
            })
            if not has_active_block:
                room.ooo_until = False
            room._sync_housekeeping_task_records()

    def action_assign_housekeeper_me(self):
        self.with_context(hotel_room_security_bypass=True).write({'assigned_housekeeper_id': self.env.user.id})

    def action_assign_inspector_me(self):
        self.with_context(hotel_room_security_bypass=True).write({'assigned_inspector_id': self.env.user.id})

    def action_toggle_dnd(self):
        for room in self:
            room.with_context(hotel_room_security_bypass=True).write({'do_not_disturb': not room.do_not_disturb})

    def action_mark_turndown_done(self):
        self.with_context(hotel_room_security_bypass=True).write({'turndown_completed': True})

    def action_mark_minibar_checked(self):
        self.with_context(hotel_room_security_bypass=True).write({
            'minibar_checked': True,
            'minibar_check_required': False,
        })

    def action_mark_linen_changed(self):
        self.with_context(hotel_room_security_bypass=True).write({
            'linen_changed': True,
            'linen_change_required': False,
        })
    
    def action_make_clean(self): return self.action_set_clean()
    @api.model
    def save_floor_plan_background(self, image_base64): return True 
    @api.model
    def get_floor_plan_background(self): return False

    # NEW: Dynamic CSS color class for the Floor Plan Kanban
    floor_plan_color = fields.Char(compute='_compute_floor_plan_color')

    @api.depends('state', 'occupancy_status', 'housekeeping_status', 'availability_status')
    def _compute_floor_plan_color(self):
        for room in self:
            axes = room._current_operational_axes()
            if axes['availability_status'] == 'out_of_order':
                room.floor_plan_color = '#6C757D'
            elif axes['occupancy_status'] == 'occupied' and axes['housekeeping_status'] == 'dirty':
                room.floor_plan_color = '#FF4D4D'
            elif axes['occupancy_status'] == 'vacant' and axes['housekeeping_status'] == 'dirty':
                room.floor_plan_color = '#FFB366'
            elif axes['housekeeping_status'] == 'inspected':
                room.floor_plan_color = '#1DBF73'
            elif axes['occupancy_status'] == 'occupied':
                room.floor_plan_color = '#B266FF'
            else:
                room.floor_plan_color = '#00FFFF'

    def action_mark_room_clean(self):
        """Triggered by the mobile Housekeeping app to clean a room."""
        self._check_housekeeping_room_status_access()
        self.action_set_clean()

        # Optional: If you want to track who cleaned it, you could add:
        # room.last_cleaned_by = self.env.user.id
        # room.last_cleaned_time = fields.Datetime.now()

class HotelRoomRate(models.Model):
    _name = 'hotel.room.rate'
    _description = 'Room Rate'
    name = fields.Char(required=True)
    room_type_id = fields.Many2one('hotel.room.type', required=True)
    unit_price = fields.Monetary(required=True)
    currency_id = fields.Many2one('res.currency', default=lambda self: self.env.company.currency_id)

class HotelFloorElement(models.Model):
    _name = 'hotel.floor.element'
    _description = 'Floor Plan Object'
    name = fields.Char(string="Name", default="New Object")
    floor_id = fields.Many2one('hotel.floor', string="Floor", required=True, ondelete='cascade')
    element_type = fields.Selection([('wall', 'Wall'), ('area', 'Area'), ('icon', 'Icon'), ('label', 'Label')], default='wall', required=True)
    pos_x = fields.Float(default=50.0)
    pos_y = fields.Float(default=50.0)
    width = fields.Float(default=100.0)
    height = fields.Float(default=10.0)
    color = fields.Char(default="#333333")
    icon_class = fields.Char(default="fa-tree")
    font_size = fields.Integer(default=14)
    z_index = fields.Integer(default=1)
