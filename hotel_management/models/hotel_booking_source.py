from odoo import models, fields

# 1. THE NEW DYNAMIC CATEGORY TABLE
class HotelBookingSourceCategory(models.Model):
    _name = 'hotel.booking.source.category'
    _description = 'Booking Source Category'

    name = fields.Char(string='Category Name', required=True)
    active = fields.Boolean(default=True)

# 2. YOUR EXISTING SUB-SOURCE TABLE (Updated)
class HotelBookingSource(models.Model):
    _name = 'hotel.booking.source'
    _description = 'Booking Sub-Source'
    _order = 'category_id, name'

    name = fields.Char(required=True)
    category_id = fields.Many2one('hotel.booking.source.category', string="Category", required=True)
    active = fields.Boolean(default=True)
    
    # ==========================================
    # THE MISSING FIELDS (Fixes the install crash!)
    # ==========================================
    commission_percent = fields.Float(string='Default Commission %')
    company_id = fields.Many2one('res.partner', string='Related Partner (Company)')
    notes = fields.Text(string='Notes')

class HotelMarketSegment(models.Model):
    _name = 'hotel.market.segment'
    _description = 'Market Segment'

    name = fields.Char(required=True)
    code = fields.Char(string='Code')
    is_revenue_generating = fields.Boolean(default=True)

class HotelGuestClassification(models.Model):
    _name = 'hotel.guest.classification'
    _description = 'Guest Classification'

    name = fields.Char(required=True)
    active = fields.Boolean(default=True)
    code = fields.Char(index=True)
    priority = fields.Integer(default=1, help="Higher number means higher priority/VIP status")
    discount_allowed = fields.Float(string='Max Discount %')
