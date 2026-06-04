from odoo import models, fields, api, _

class HotelLostFound(models.Model):
    _name = 'hotel.lost.found'
    _description = 'Hotel Lost and Found'
    _inherit = ['mail.thread', 'mail.activity.mixin']
    _order = 'date_found desc'

    name = fields.Char(string="Item Name", required=True, tracking=True)
    description = fields.Text(string="Description / Condition")
    
    # --- FINDER DETAILS ---
    date_found = fields.Date(string="Date Found", required=True, default=fields.Date.today)
    finder_id = fields.Many2one('res.users', string="Found By", default=lambda self: self.env.user)
    location_found = fields.Selection([
        ('room', 'Guest Room'),
        ('lobby', 'Lobby / Reception'),
        ('restaurant', 'Restaurant'),
        ('pool', 'Pool / Gym'),
        ('other', 'Other'),
    ], string="Location", default='room', required=True)
    
    room_id = fields.Many2one('hotel.room', string="Room Number", help="If found in a room")
    
    # --- ITEM DETAILS ---
    category = fields.Selection([
        ('electronics', 'Electronics'),
        ('clothing', 'Clothing'),
        ('jewelry', 'Jewelry / Valuables'),
        ('documents', 'Documents / ID'),
        ('misc', 'Miscellaneous'),
    ], string="Category", required=True)
    
    image = fields.Binary(string="Item Photo", attachment=True)
    
    # --- CLAIMANT DETAILS ---
    partner_id = fields.Many2one('res.partner', string="Guest / Owner", help="Who does this belong to?")
    reservation_id = fields.Many2one('hotel.reservation', string="Reservation Link", help="Link to a specific booking if known")
    
    # --- STATUS ---
    state = fields.Selection([
        ('found', 'Found (In Storage)'),
        ('claimed', 'Claimed (Contacted)'),
        ('returned', 'Returned to Owner'),
        ('disposed', 'Disposed / Donated'),
    ], string="Status", default='found', tracking=True)

    return_date = fields.Date(string="Date Returned")
    return_details = fields.Text(string="Return Method")

    @api.onchange('room_id')
    def _onchange_room_id(self):
        """ Auto-detect guest if room is selected and check-out was today """
        if self.room_id:
            # Find who checked out of this room recently
            last_stay = self.env['hotel.reservation'].search([
                ('room_id', '=', self.room_id.id),
                ('state', 'in', ['checkout', 'checkin']),
                ('checkout_date', '>=', self.date_found)
            ], limit=1, order='checkout_date desc')
            
            if last_stay:
                self.reservation_id = last_stay.id
                self.partner_id = last_stay.partner_id.id

    def action_claim(self):
        self.state = 'claimed'

    def action_return(self):
        self.state = 'returned'
        self.return_date = fields.Date.today()

    def action_dispose(self):
        self.state = 'disposed'