from odoo import models, fields

class HotelBookingSource(models.Model):
    _name = 'hotel.booking.source'
    _description = 'Booking Source'
    _order = 'name'
    name = fields.Char(string='Source Name', required=True)

class HotelMarketSegment(models.Model):
    _name = 'hotel.market.segment'
    _description = 'Market Segment'
    _order = 'name'
    name = fields.Char(string='Segment Name', required=True)

class HotelGuestClassify(models.Model):
    _name = 'hotel.guest.classify'
    _description = 'Guest Classification'
    _order = 'name'
    name = fields.Char(string='Classification', required=True)
class ResCompany(models.Model):
    _inherit = 'res.company'
    pre_arrival_days = fields.Integer(string="Days before arrival to send link", default=3)

class ResConfigSettings(models.TransientModel):
    _inherit = 'res.config.settings'
    pre_arrival_days = fields.Integer(related='company_id.pre_arrival_days', readonly=False)

class HotelNationality(models.Model):
    _name = 'hotel.nationality'
    _description = 'Guest Nationality'
    _order = 'name'

    name = fields.Char(string='Nationality', required=True, translate=True)
    code = fields.Char(string='Code', help='ISO Code (e.g., KH, CN)')
    
# Then, add this to your Guest/Reservation model (e.g., models/hotel_reservation.py):
# nationality_id = fields.Many2one('hotel.nationality', string='Nationality')
# country_id = fields.Many2one('res.country', string='Country')    
class ResPartner(models.Model):
    _inherit = 'res.partner'

    # This physically adds the Nationality field to Odoo's core Contact/Guest profiles
    nationality_id = fields.Many2one('hotel.nationality', string='Nationality')