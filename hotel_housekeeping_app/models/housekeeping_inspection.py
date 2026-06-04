from odoo import api, fields, models, _
from odoo.exceptions import AccessError, UserError, ValidationError
from markupsafe import Markup


class HotelHousekeepingInspection(models.Model):
    _inherit = 'hotel.housekeeping'

    inspection_state = fields.Selection([
        ('pending', 'Pending'),
        ('ready', 'Ready for Inspection'),
        ('passed', 'Passed'),
        ('failed', 'Failed / Reclean'),
    ], string='Inspection Status', default='pending', tracking=True, index=True)
    inspected_by = fields.Many2one('res.users', string='Inspected By', readonly=True, copy=False)
    inspected_datetime = fields.Datetime(string='Inspected At', readonly=True, copy=False)
    failure_reason = fields.Text(string='Failure Reason', tracking=True)
    supervisor_note = fields.Text(string='Supervisor Note', tracking=True)
    cleaning_completed_by_id = fields.Many2one(
        'res.users',
        string='Cleaning Completed By',
        readonly=True,
        copy=False,
    )
    cleaning_completed_datetime = fields.Datetime(
        string='Cleaning Completed At',
        readonly=True,
        copy=False,
    )
    is_ready_for_inspection = fields.Boolean(
        string='Ready for Inspection',
        compute='_compute_is_ready_for_inspection',
        store=True,
        index=True,
    )
    floor_id = fields.Many2one('hotel.floor', related='room_id.floor_id', string='Floor', store=True)
    room_type_id = fields.Many2one('hotel.room.type', related='room_id.room_type_id', string='Room Type', store=True)
    room_housekeeping_status = fields.Selection(
        related='room_id.housekeeping_status',
        string='Room Housekeeping',
        store=True,
    )
    room_occupancy_status = fields.Selection(
        related='room_id.occupancy_status',
        string='Room Occupancy',
        store=True,
    )
    last_guest_id = fields.Many2one(
        'res.partner',
        string='Last Guest',
        compute='_compute_last_guest',
        store=False,
    )
    inspection_attachment_ids = fields.Many2many(
        'ir.attachment',
        'hotel_housekeeping_inspection_attachment_rel',
        'housekeeping_id',
        'attachment_id',
        string='Inspection Evidence Photos',
        copy=False,
    )

    def init(self):
        """Keep only the latest open task per room before enforcing the guard index."""
        self.env.cr.execute("""
            WITH ranked AS (
                SELECT
                    id,
                    ROW_NUMBER() OVER (
                        PARTITION BY room_id
                        ORDER BY COALESCE(write_date, create_date) DESC, id DESC
                    ) AS row_number
                FROM hotel_housekeeping
                WHERE room_id IS NOT NULL
                  AND state != 'done'
            )
            UPDATE hotel_housekeeping
               SET state = 'done',
                   room_ready = false,
                   write_date = NOW()
             WHERE id IN (
                SELECT id
                  FROM ranked
                 WHERE row_number > 1
             )
        """)
        self.env.cr.execute("""
            CREATE UNIQUE INDEX IF NOT EXISTS hotel_housekeeping_one_open_task_per_room_idx
                ON hotel_housekeeping (room_id)
             WHERE room_id IS NOT NULL
               AND state != 'done'
        """)

    @api.model
    def _open_task_domain(self, room_id=False):
        domain = [('state', '!=', 'done')]
        if room_id:
            domain.append(('room_id', '=', room_id))
        return domain

    @api.model
    def _get_open_task_for_room(self, room):
        room_id = room.id if hasattr(room, 'id') else room
        return self.search(
            self._open_task_domain(room_id),
            order='write_date desc, create_date desc, id desc',
            limit=1,
        )

    @api.model
    def _deduplicate_active_tasks(self, room_ids=False):
        domain = self._open_task_domain()
        if room_ids:
            domain.append(('room_id', 'in', room_ids))
        tasks = self.search(domain, order='room_id, write_date desc, create_date desc, id desc')
        seen_room_ids = set()
        duplicate_tasks = self.browse()
        for task in tasks:
            if task.room_id.id in seen_room_ids:
                duplicate_tasks |= task
            else:
                seen_room_ids.add(task.room_id.id)
        if duplicate_tasks:
            duplicate_tasks.write({'state': 'done', 'room_ready': False})
            for duplicate_task in duplicate_tasks:
                duplicate_task.message_post(
                    body=_("Closed automatically because a newer active housekeeping task exists for this room."),
                    subtype_xmlid='mail.mt_note',
                )
        return True

    @api.model_create_multi
    def create(self, vals_list):
        if self.env.context.get('skip_housekeeping_duplicate_guard'):
            return super().create(vals_list)

        records = self.browse()
        for vals in vals_list:
            room_id = vals.get('room_id')
            if room_id:
                existing_task = self.sudo()._get_open_task_for_room(room_id)
                if existing_task:
                    update_vals = dict(vals)
                    if update_vals.get('name') == _('New'):
                        update_vals.pop('name')
                    existing_task.write(update_vals)
                    records |= existing_task
                    continue
            records |= super(HotelHousekeepingInspection, self).create([vals])
        return records

    @api.depends('inspection_state', 'state', 'service_type')
    def _compute_is_ready_for_inspection(self):
        for task in self:
            task.is_ready_for_inspection = (
                task.inspection_state == 'ready'
                or task.state == 'inspection'
                or task.service_type == 'inspection_pending'
            ) and task.inspection_state != 'passed'

    def _compute_last_guest(self):
        Reservation = self.env['hotel.reservation'].sudo()
        for task in self:
            reservation = task.reservation_id
            if not reservation and task.room_id:
                reservation = Reservation.search([
                    ('room_id', '=', task.room_id.id),
                    ('state', 'in', ['checkout', 'checkin', 'checkout_hold']),
                ], order='checkout_date desc, checkin_date desc, id desc', limit=1)
            task.last_guest_id = reservation.partner_id if reservation else False

    @api.model
    def _can_supervise_inspection(self):
        return (
            self.env.su
            or self.env.user.has_group('hotel_housekeeping_app.group_housekeeping_supervisor')
            or self.env.user.has_group('hotel_housekeeping_app.group_housekeeping_manager')
            or self.env.user.has_group('hotel_management.group_hotel_manager')
            or self.env.user.has_group('base.group_system')
        )

    def _check_supervisor_access(self):
        if not self._can_supervise_inspection():
            raise AccessError(_("Only Housekeeping Supervisors or Managers can inspect rooms."))

    def _check_can_inspect(self):
        for task in self:
            ready_for_inspection = (
                task.inspection_state == 'ready'
                or task.state == 'inspection'
                or task.service_type == 'inspection_pending'
            )
            if not ready_for_inspection:
                raise UserError(_("Room %s is not waiting for inspection.") % task.room_id.name)
            if task.room_id.occupancy_status == 'occupied':
                raise UserError(_("Room %s is occupied and cannot be inspection-passed for sale.") % task.room_id.name)

    def _post_inspection_log(self, body):
        for task in self:
            task.message_post(body=body, subtype_xmlid='mail.mt_note')
            if task.room_id:
                task.room_id.message_post(body=body, subtype_xmlid='mail.mt_note')

    def action_ready_for_inspection(self):
        now = fields.Datetime.now()
        for task in self:
            if task.state == 'done':
                raise UserError(_("Completed housekeeping tasks cannot be sent for inspection."))
            if not task.room_id:
                raise UserError(_("A room is required before requesting inspection."))
            task.room_id.action_set_clean()
            vals = {
                'state': 'inspection',
                'inspection_state': 'ready',
                'failure_reason': False,
                'cleaning_completed_by_id': self.env.user.id,
                'cleaning_completed_datetime': now,
                'room_ready': task.room_id.release_ready,
            }
            task.write(vals)
            task._post_inspection_log(Markup(
                "<b>Cleaning Done:</b> Room %s is ready for supervisor inspection by %s."
            ) % (task.room_id.display_name, self.env.user.display_name))
        return True

    def action_inspection_passed(self):
        self._check_supervisor_access()
        self._check_can_inspect()
        now = fields.Datetime.now()
        for task in self:
            task.room_id.action_set_inspected()
            task.write({
                'inspection_state': 'passed',
                'inspected_by': self.env.user.id,
                'inspected_datetime': now,
                'failure_reason': False,
                'state': 'done',
                'room_ready': task.room_id.release_ready,
            })
            task._post_inspection_log(Markup(
                "<b>Inspection Passed:</b> Room %s was approved by %s at %s."
            ) % (task.room_id.display_name, self.env.user.display_name, fields.Datetime.to_string(now)))
        return True

    def action_inspection_failed(self):
        self._check_supervisor_access()
        self._check_can_inspect()
        for task in self:
            if not (task.failure_reason or '').strip():
                raise ValidationError(_("Failure Reason is required before marking inspection failed."))
            task.action_reclean_required()
        return True

    def action_reclean_required(self):
        self._check_supervisor_access()
        self._check_can_inspect()
        now = fields.Datetime.now()
        for task in self:
            if not task.inspection_attachment_ids:
                raise ValidationError(_("Please upload at least one evidence photo for failed inspection."))
            task.room_id.action_set_dirty()
            task.write({
                'inspection_state': 'failed',
                'inspected_by': self.env.user.id,
                'inspected_datetime': now,
                'state': 'dirty',
                'room_ready': False,
            })
            task._post_inspection_log(Markup(
                "<b>Inspection Failed:</b> Room %s requires reclean. <br/><b>Reason:</b> %s"
            ) % (task.room_id.display_name, task.failure_reason or _('No reason provided')))
        return True

    def action_open_mobile_inspection(self):
        return {
            'type': 'ir.actions.act_url',
            'url': '/housekeeping/supervisor/inspection',
            'target': 'self',
        }


class HotelRoomInspectionMobile(models.Model):
    _inherit = 'hotel.room'

    def _sync_housekeeping_task_records(self):
        biz_date = self.env.company.hotel_business_date or fields.Date.context_today(self)
        Task = self.env['hotel.housekeeping'].sudo()

        Task._deduplicate_active_tasks(self.ids)
        for room in self:
            active_task = Task._get_open_task_for_room(room)
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
            inspection_state = 'pending'
            if room.service_workflow == 'inspection_pending':
                task_state = 'inspection'
                inspection_state = 'ready'
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
            if inspection_state == 'ready' and (not active_task or active_task.inspection_state != 'failed'):
                task_vals['inspection_state'] = inspection_state

            if needs_task:
                if active_task:
                    active_task.write(task_vals)
                else:
                    Task.with_context(skip_housekeeping_duplicate_guard=True).create(task_vals)
            elif active_task:
                active_task.write(dict(task_vals, state='done'))

    def action_mark_room_clean(self):
        result = super().action_mark_room_clean()
        tasks = self.env['hotel.housekeeping'].sudo().search([
            ('room_id', 'in', self.ids),
            ('state', '!=', 'done'),
        ])
        for task in tasks:
            if task.release_policy == 'inspection_required' or task.room_id.service_workflow == 'inspection_pending':
                task.with_user(self.env.user).action_ready_for_inspection()
        return result


class HotelDashboardInspection(models.Model):
    _inherit = 'hotel.dashboard'

    rooms_ready_for_inspection = fields.Integer(
        string='Rooms Ready for Inspection',
        compute='_compute_inspection_counts',
    )
    failed_inspection_reclean = fields.Integer(
        string='Failed Inspection / Reclean',
        compute='_compute_inspection_counts',
    )
    passed_inspection_today = fields.Integer(
        string='Passed Today',
        compute='_compute_inspection_counts',
    )

    def _compute_inspection_counts(self):
        Task = self.env['hotel.housekeeping'].sudo()
        today_start = fields.Datetime.to_datetime(fields.Date.context_today(self))
        for dashboard in self:
            dashboard.rooms_ready_for_inspection = Task.search_count([
                ('is_ready_for_inspection', '=', True),
                ('state', '!=', 'done'),
            ])
            dashboard.failed_inspection_reclean = Task.search_count([
                ('inspection_state', '=', 'failed'),
                ('state', '=', 'dirty'),
            ])
            dashboard.passed_inspection_today = Task.search_count([
                ('inspection_state', '=', 'passed'),
                ('inspected_datetime', '>=', today_start),
            ])

    def action_view_rooms_ready_for_inspection(self):
        return {
            'name': _('Rooms Ready for Inspection'),
            'type': 'ir.actions.act_window',
            'res_model': 'hotel.housekeeping',
            'view_mode': 'list,form',
            'domain': [('is_ready_for_inspection', '=', True), ('state', '!=', 'done')],
            'context': {'search_default_ready': 1},
        }

    def action_view_failed_inspection_reclean(self):
        return {
            'name': _('Failed Inspection / Reclean'),
            'type': 'ir.actions.act_window',
            'res_model': 'hotel.housekeeping',
            'view_mode': 'list,form',
            'domain': [('inspection_state', '=', 'failed'), ('state', '=', 'dirty')],
            'context': {'search_default_failed': 1},
        }

    def action_view_passed_inspection_today(self):
        today_start = fields.Datetime.to_datetime(fields.Date.context_today(self))
        return {
            'name': _('Passed Inspection Today'),
            'type': 'ir.actions.act_window',
            'res_model': 'hotel.housekeeping',
            'view_mode': 'list,form',
            'domain': [('inspection_state', '=', 'passed'), ('inspected_datetime', '>=', today_start)],
            'context': {'search_default_passed_today': 1},
        }
