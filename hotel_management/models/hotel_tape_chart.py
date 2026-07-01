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
        room_blocks = self.env['hotel.room.block'].sudo().search_read([
            ('date_from', '<=', end_date),
            ('date_to', '>=', start_date),
            ('state', '=', 'active'),
        ], ['id', 'room_id', 'date_from', 'date_to', 'name'])
        bookings += [{
            'id': 'room_block_%s' % block['id'],
            'room_id': block['room_id'],
            'partner_id': False,
            'checkin_date': block['date_from'],
            'checkout_date': block['date_to'],
            'state': 'blocked',
            'name': block['name'],
            'res_model': 'hotel.room.block',
            'res_id': block['id'],
        } for block in room_blocks]
        
        return {
            'rooms': rooms,
            'bookings': bookings
        }
