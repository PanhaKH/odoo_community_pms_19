from odoo import models, fields, api, _
from datetime import timedelta

class MaintenanceRequest(models.Model):
    _inherit = 'maintenance.request'

    # Link to your Hotel Room
    room_id = fields.Many2one('hotel.room', string="Guest Room")
    
    # Link to the generated Block in the Reservation system
    reservation_id = fields.Many2one('hotel.reservation', string="Room Block", readonly=True)

    @api.model
    def create(self, vals):
        request = super(MaintenanceRequest, self).create(vals)

        stage_name = request.stage_id.name.lower() if request.stage_id else ''

        # Only block room when maintenance is really active
        if request.room_id and request.schedule_date and stage_name == 'in progress':
            request._create_or_update_room_block()

        return request

    def write(self, vals):
        res = super(MaintenanceRequest, self).write(vals)

        for req in self:
            stage_name = req.stage_id.name.lower() if req.stage_id else ''

            # If maintenance is active, create or update the room block
            if req.room_id and req.schedule_date and stage_name == 'in progress':
                req._create_or_update_room_block()

            # If maintenance is finished, remove the room block
            elif stage_name in ['repaired', 'scrap']:
                req._remove_room_block()

        return res

    def _create_or_update_room_block(self):
        self.ensure_one()
        
        # 1. LOGIC: Convert Hourly Maintenance to Nightly Block
        start_dt = self.schedule_date
        duration_hours = self.duration
        end_dt = start_dt + timedelta(hours=duration_hours)

        # Convert to Dates
        checkin_date = start_dt.date()
        checkout_date = end_dt.date()

        # Force at least one-day block width
        if checkin_date == checkout_date:
            checkout_date = checkin_date + timedelta(days=1)

        # 2. Prepare Data for Hotel Reservation block
        block_vals = {
            'name': f"MAINTENANCE: {self.name}",
            'partner_id': False,
            'room_id': self.room_id.id,
            'room_type_id': self.room_id.room_type_id.id,
            'checkin_date': checkin_date,
            'checkout_date': checkout_date,
            'state': 'blocked',
            'block_reason': self.description or self.name,
        }

        # 3. Create or update the block
        if self.reservation_id:
            self.reservation_id.with_context(
                hotel_reservation_security_bypass=True
            ).sudo().write(block_vals)
        else:
            block = self.env['hotel.reservation'].with_context(
                hotel_reservation_security_bypass=True
            ).sudo().create(block_vals)
            self.reservation_id = block.id

    def _remove_room_block(self):
        self.ensure_one()
        if self.reservation_id:
            self.reservation_id.with_context(
                hotel_reservation_security_bypass=True
            ).sudo().unlink()
            self.reservation_id = False
