import base64

from markupsafe import Markup
from odoo import http, _
from odoo.exceptions import AccessError, UserError, ValidationError
from odoo.http import request
from urllib.parse import quote


class HousekeepingInspectionController(http.Controller):

    def _create_inspection_photo_attachments(self, task):
        files = request.httprequest.files.getlist('inspection_photos')
        files = [upload for upload in files if upload and upload.filename]
        if not files:
            raise ValidationError(_("Please upload at least one evidence photo for failed inspection."))

        Attachment = request.env['ir.attachment'].sudo()
        attachments = request.env['ir.attachment'].sudo().browse()
        for upload in files:
            mimetype = upload.mimetype or ''
            if not mimetype.startswith('image/'):
                raise ValidationError(_("Only image evidence photos can be uploaded."))
            attachments |= Attachment.create({
                'name': upload.filename,
                'type': 'binary',
                'datas': base64.b64encode(upload.read()).decode(),
                'res_model': 'hotel.housekeeping',
                'res_id': task.id,
                'mimetype': mimetype,
            })
        task.sudo().write({'inspection_attachment_ids': [(4, attachment.id) for attachment in attachments]})
        task.message_post(
            body=Markup("<b>Failed Inspection Evidence:</b> %s photo(s) uploaded.") % len(attachments),
            attachment_ids=attachments.ids,
            subtype_xmlid='mail.mt_note',
        )

        # Also show the failed inspection photo in the Hotel Room chatter
        if task.room_id:
            task.room_id.sudo().message_post(
                body=Markup(
                    "<b>Inspection Failed Evidence:</b> Room %s requires reclean.<br/>"
                    "<b>Reason:</b> %s<br/>"
                    "%s photo(s) uploaded."
                ) % (
                    task.room_id.display_name,
                    task.failure_reason or "-",
                    len(attachments),
                ),
                attachment_ids=attachments.ids,
                subtype_xmlid='mail.mt_note',
            )

        return attachments

    def _unique_latest_by_room(self, tasks):
        seen_room_ids = set()
        unique_tasks = request.env['hotel.housekeeping'].sudo().browse()
        for task in tasks:
            if task.room_id.id in seen_room_ids:
                continue
            seen_room_ids.add(task.room_id.id)
            unique_tasks |= task
        return unique_tasks

    def _check_supervisor(self):
        user = request.env.user
        if not (
            user.has_group('hotel_housekeeping_app.group_housekeeping_supervisor')
            or user.has_group('hotel_housekeeping_app.group_housekeeping_manager')
            or user.has_group('hotel_management.group_hotel_manager')
            or user.has_group('base.group_system')
        ):
            raise AccessError(_("Only Housekeeping Supervisors or Managers can inspect rooms."))

    def _get_task(self, task_id):
        self._check_supervisor()
        return request.env['hotel.housekeeping'].sudo().browse(task_id).exists()

    @http.route('/housekeeping/supervisor/inspection', type='http', auth='user', website=True)
    def supervisor_inspection(self, **kw):
        self._check_supervisor()

        Task = request.env['hotel.housekeeping'].sudo()
        Task._deduplicate_active_tasks()

        # READY FOR INSPECTION:
        # Keep old task logic, but only show tasks where the current room is really clean and not released.
        tasks = Task.search([
            ('is_ready_for_inspection', '=', True),
            ('state', '!=', 'done'),
            ('inspection_state', '=', 'ready'),
            ('room_id.housekeeping_status', '=', 'clean'),
            ('room_id.release_ready', '=', False),
            ('room_id.occupancy_status', '=', 'vacant'),
        ], order='floor_id, room_id, cleaning_completed_datetime desc, id desc')

        tasks = self._unique_latest_by_room(tasks)

        # FAILED / RECLEAN:
        # Keep old failed task records because evidence photos and failure reason are linked to this task.
        failed_tasks = Task.search([
            ('inspection_state', '=', 'failed'),
            ('state', '=', 'dirty'),
            ('room_id.housekeeping_status', '=', 'dirty'),
            ('room_id.occupancy_status', '=', 'vacant'),
        ], order='inspected_datetime desc, write_date desc, id desc', limit=20)

        failed_tasks = self._unique_latest_by_room(failed_tasks)

        return request.render('hotel_housekeeping_app.supervisor_inspection_page', {
            'tasks': tasks,
            'failed_tasks': failed_tasks,
            'error': kw.get('error'),
            'success': kw.get('success'),
        })

    @http.route('/housekeeping/inspection/pass/<int:task_id>', type='http', auth='user', methods=['POST'], website=True)
    def inspection_pass(self, task_id, **post):
        task = self._get_task(task_id)
        if not task:
            return request.redirect('/housekeeping/supervisor/inspection?error=Task not found')
        try:
            if post.get('supervisor_note'):
                task.write({'supervisor_note': post['supervisor_note'].strip()})
            task.action_inspection_passed()
        except (AccessError, UserError, ValidationError) as exc:
            return request.redirect('/housekeeping/supervisor/inspection?error=%s' % quote(str(exc)))
        return request.redirect('/housekeeping/supervisor/inspection?success=Inspection passed')

    @http.route('/housekeeping/inspection/fail/<int:task_id>', type='http', auth='user', methods=['POST'], website=True)
    def inspection_fail(self, task_id, **post):
        task = self._get_task(task_id)
        if not task:
            return request.redirect('/housekeeping/supervisor/inspection?error=Task not found')

        try:
            task.write({
                'failure_reason': (post.get('failure_reason') or '').strip(),
                'supervisor_note': (post.get('supervisor_note') or '').strip(),
            })

            attachments = self._create_inspection_photo_attachments(task)

            task.action_inspection_failed()

            # Keep failed evidence linked after room is returned to dirty/reclean.
            task.sudo().write({
                'inspection_state': 'failed',
                'state': 'dirty',
                'room_ready': False,
                'inspection_attachment_ids': [(4, attachment.id) for attachment in attachments],
            })

        except (AccessError, UserError, ValidationError) as exc:
            return request.redirect('/housekeeping/supervisor/inspection?error=%s' % quote(str(exc)))

        return request.redirect('/housekeeping/supervisor/inspection?success=Room returned for reclean')
