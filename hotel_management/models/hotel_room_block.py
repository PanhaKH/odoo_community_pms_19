from odoo import api, fields, models, _
from odoo.exceptions import ValidationError


class HotelRoomBlock(models.Model):
    _name = 'hotel.room.block'
    _description = 'Hotel Room Block / Out of Order'
    _inherit = ['mail.thread', 'mail.activity.mixin']
    _order = 'date_from desc, room_id'

    name = fields.Char(string='Reference', required=True, default=lambda self: _('Room Block'))
    room_id = fields.Many2one('hotel.room', string='Room', required=True, index=True, tracking=True)
    room_type_id = fields.Many2one(related='room_id.room_type_id', string='Room Type', store=True, readonly=True)
    date_from = fields.Date(string='From', required=True, index=True, tracking=True)
    date_to = fields.Date(string='To', required=True, index=True, tracking=True)
    reason = fields.Text(string='Reason')
    source = fields.Selection([
        ('manual', 'Manual'),
        ('maintenance', 'Maintenance'),
    ], string='Source', default='manual', required=True, tracking=True)
    maintenance_request_id = fields.Many2one(
        'maintenance.request',
        string='Maintenance Request',
        ondelete='set null',
        index=True,
    )
    state = fields.Selection([
        ('active', 'Active'),
        ('released', 'Released'),
    ], string='Status', default='active', required=True, tracking=True)
    released_datetime = fields.Datetime(string='Released On', readonly=True)
    released_by_id = fields.Many2one('res.users', string='Released By', readonly=True)

    @api.constrains('date_from', 'date_to')
    def _check_dates(self):
        for block in self:
            if block.date_from and block.date_to and block.date_to <= block.date_from:
                raise ValidationError(_("Room block end date must be after the start date."))

    def action_release(self):
        for block in self.filtered(lambda rec: rec.state == 'active'):
            block.write({
                'state': 'released',
                'released_datetime': fields.Datetime.now(),
                'released_by_id': self.env.user.id,
            })
            block.room_id._reconcile_operational_status()
            block.room_id._sync_housekeeping_task_records()
        return True
