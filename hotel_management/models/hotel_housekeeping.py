from odoo import models, fields, api, _

class HotelHousekeeping(models.Model):
    _name = 'hotel.housekeeping'
    _description = 'Housekeeping Task'
    _inherit = ['mail.thread', 'mail.activity.mixin']
    _order = 'date_assigned desc, id desc'

    name = fields.Char(string='Task Description', required=True, copy=False, default=lambda self: _('New'))
    room_id = fields.Many2one('hotel.room', string='Room', required=True)
    reservation_id = fields.Many2one('hotel.reservation', string='Source Reservation', readonly=True)
    
    room_state = fields.Selection(related='room_id.state', string="Room Status", readonly=True, store=True)
    business_date = fields.Date(
        string='Business Date',
        default=lambda self: self.env.company.hotel_business_date or fields.Date.context_today(self),
        required=True,
        tracking=True,
    )

    maid_id = fields.Many2one('res.users', string='Assigned Maid', tracking=True)
    inspector_id = fields.Many2one('res.users', string='Assigned Inspector', tracking=True)
    date_assigned = fields.Date(string='Date', default=fields.Date.today)
    service_type = fields.Selection([
        ('arrival_priority', 'Arrival Priority'),
        ('departure_clean', 'Departure Clean'),
        ('inspection_pending', 'Inspection Pending'),
        ('stayover_service', 'Stayover Service'),
        ('vacant_ready', 'Vacant Ready'),
        ('out_of_order', 'Out of Order'),
    ], string='Workflow', tracking=True)
    arrival_priority_level = fields.Selection([
        ('none', 'No Arrival Pressure'),
        ('arrival_today', 'Arrival Today'),
        ('rush_arrival', 'Rush Arrival'),
    ], string='Arrival Priority', default='none', tracking=True)
    release_policy = fields.Selection([
        ('inspection_required', 'Supervisor Inspection Required'),
        ('clean_only', 'Clean Only'),
    ], string='Release Policy', default='inspection_required', tracking=True)
    departure_clean_required = fields.Boolean(string='Departure Clean Required', tracking=True)
    room_ready = fields.Boolean(string='Room Ready', tracking=True)
    do_not_disturb = fields.Boolean(string='Do Not Disturb', tracking=True)
    turndown_required = fields.Boolean(string='Turndown Required', tracking=True)
    turndown_completed = fields.Boolean(string='Turndown Completed', tracking=True)
    minibar_check_required = fields.Boolean(string='Minibar Check Required', tracking=True)
    minibar_checked = fields.Boolean(string='Minibar Checked', tracking=True)
    linen_change_required = fields.Boolean(string='Linen Change Required', tracking=True)
    linen_changed = fields.Boolean(string='Linen Changed', tracking=True)
    
    state = fields.Selection([
        ('dirty', 'Dirty'),
        ('clean', 'Clean'),
        ('inspection', 'Inspection'),
        ('done', 'Done'),
    ], string='Task Status', default='dirty', tracking=True, group_expand='_expand_states')

    def action_done(self):
        for record in self:
            if record.room_id:
                if record.room_id.service_workflow == 'inspection_pending':
                    record.room_id.action_set_inspected()
                elif record.room_id.housekeeping_status == 'dirty':
                    record.room_id.action_set_clean()
                elif not record.room_id.release_ready:
                    record.room_id.action_set_inspected()
            record.state = 'done'

    def action_assign_me(self):
        self.write({'maid_id': self.env.user.id})

    def action_assign_inspector_me(self):
        self.write({'inspector_id': self.env.user.id})

    @api.model_create_multi
    def create(self, vals_list):
        for vals in vals_list:
            if vals.get('name', _('New')) == _('New'):
                vals['name'] = self.env['ir.sequence'].next_by_code('hotel.housekeeping') or _('New')
        return super().create(vals_list)

    @api.model
    def _expand_states(self, states, domain, order):
        return [key for key, val in type(self).state.selection]
