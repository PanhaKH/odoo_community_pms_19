from odoo import models, fields, api, _
from odoo.exceptions import ValidationError

class HotelRatePlan(models.Model):
    _name = 'hotel.rate.plan'
    _description = 'Master Rate Plan'
    
    name = fields.Char(string='Rate Plan Name', required=True, translate=True, help="e.g., Standard Rack Rate, Summer Promo")
    active = fields.Boolean(default=True)
    
    # This links the Parent to all of its internal rules!
    line_ids = fields.One2many('hotel.rate.plan.line', 'plan_id', string='Pricing Rules')

class HotelRatePlanLine(models.Model):
    _name = 'hotel.rate.plan.line'
    _description = 'Rate Plan Pricing Rule'
    _order = 'date_start asc, room_type_id'

    plan_id = fields.Many2one('hotel.rate.plan', string='Rate Plan', ondelete='cascade', required=True)

    included_guests = fields.Integer(
        string="Included Guests (Base)", 
        default=2, 
        help="How many adults are included in the base price before extra fees apply?"
    )
    extra_person_fee = fields.Float(
        string="Extra Person Fee / Night", 
        default=0.0, 
        help="The nightly charge for each adult above the included amount."
    )
    
    # The specific variables for this rule
    room_type_id = fields.Many2one('hotel.room.type', string='Room Type', required=True)
    price = fields.Float(string='Nightly Rate', required=True, digits='Product Price')
    
    # If dates are empty, it means this is the "default" year-round price
    date_start = fields.Date(string='Start Date', help="Leave empty for a year-round default rate.")
    date_end = fields.Date(string='End Date')

    @api.constrains('date_start', 'date_end')
    def _check_dates(self):
        for record in self:
            if record.date_start and record.date_end and record.date_start > record.date_end:
                raise ValidationError(_("The End Date cannot be earlier than the Start Date."))