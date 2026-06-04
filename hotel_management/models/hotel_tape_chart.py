from odoo import models, api

class HotelTapeChart(models.AbstractModel):
    _name = 'hotel.tape.chart'
    _description = 'Tape Chart Data Service'

    @api.model
    def get_tape_chart_data(self, start_date, end_date):
        """ Returns Rooms and Bookings for the JS Grid """
        
        # 1. Get All Rooms
        rooms = self.env['hotel.room'].search_read([], ['id', 'name', 'room_type_id'])
        
        # 2. Get Bookings in Range
        domain = [
            ('checkin_date', '<=', end_date),
            ('checkout_date', '>=', start_date),
            ('state', '!=', 'cancel')
        ]
        bookings = self.env['hotel.reservation'].search_read(domain, ['id', 'room_id', 'partner_id', 'checkin_date', 'checkout_date', 'state', 'name'])
        
        return {
            'rooms': rooms,
            'bookings': bookings
        }
