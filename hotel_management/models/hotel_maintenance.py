from odoo import models, fields, api, _
from datetime import timedelta

class MaintenanceRequest(models.Model):
    _inherit = 'maintenance.request'

    # Link to your Hotel Room
    room_id = fields.Many2one('hotel.room', string="Guest Room")
    
    room_block_id = fields.Many2one('hotel.room.block', string="Room Block", readonly=True)
    reservation_id = fields.Many2one(
        'hotel.reservation',
        string="Legacy Reservation Block",
        readonly=True,
        help="Legacy field kept only so old maintenance-created reservation blocks do not break existing records.",
    )

    @api.model
    def create(self, vals):
        request = super(MaintenanceRequest, self).create(vals)

        stage_name = request.stage_id.name.lower() if request.stage_id else ''

        # Only block room when maintenance is active
        if request.room_id and request._is_room_blocking_stage(stage_name):
            request._create_or_update_room_block()

        return request

    def write(self, vals):
        old_blocks = {req.id: req.room_block_id for req in self}
        res = super(MaintenanceRequest, self).write(vals)

        for req in self:
            stage_name = req.stage_id.name.lower() if req.stage_id else ''

            if 'room_id' in vals and old_blocks.get(req.id) and old_blocks[req.id] != req.room_block_id:
                old_blocks[req.id].action_release()

            # If maintenance is active, create or update the room block
            if req.room_id and req._is_room_blocking_stage(stage_name):
                req._create_or_update_room_block()

            # If maintenance is finished, remove the room block
            elif req._is_room_release_stage(stage_name):
                req._remove_room_block()

        return res

    def _is_room_release_stage(self, stage_name):
        return (stage_name or '').strip().lower() in ['repaired', 'scrap', 'done', 'cancel', 'cancelled', 'closed']

    def _is_room_blocking_stage(self, stage_name):
        return not self._is_room_release_stage(stage_name)

    def _create_or_update_room_block(self):
        self.ensure_one()
        
        # 1. LOGIC: Convert Hourly Maintenance to Nightly Block
        start_dt = self.schedule_date or fields.Datetime.now()
        duration_hours = self.duration or 24.0
        end_dt = start_dt + timedelta(hours=duration_hours)

        # Convert to Dates
        checkin_date = start_dt.date()
        checkout_date = end_dt.date()

        # Force at least one-day block width
        if checkin_date == checkout_date:
            checkout_date = checkin_date + timedelta(days=1)

        # 2. Prepare Data for dedicated hotel.room.block record.
        block_vals = {
            'name': f"MAINTENANCE: {self.name}",
            'room_id': self.room_id.id,
            'date_from': checkin_date,
            'date_to': checkout_date,
            'source': 'maintenance',
            'maintenance_request_id': self.id,
            'state': 'active',
            'reason': self.description or self.name,
        }

        # 3. Create or update the block
        if self.room_block_id:
            self.room_block_id.sudo().write(block_vals)
        else:
            block = self.env['hotel.room.block'].sudo().create(block_vals)
            self.room_block_id = block.id

        self.room_id.with_context(hotel_room_security_bypass=True).write({'availability_status': 'out_of_order'})
        self.room_id._reconcile_operational_status()
        self.room_id._sync_housekeeping_task_records()

    def _remove_room_block(self):
        self.ensure_one()
        room = self.room_id
        if self.room_block_id:
            self.room_block_id.sudo().action_release()
            self.room_block_id = False
        if room:
            room._reconcile_operational_status()
