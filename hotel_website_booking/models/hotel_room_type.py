from odoo import fields, models
class HotelRoomType(models.Model):
    _inherit = 'hotel.room.type'

    website_image_1 = fields.Image(string='Website Main Image', max_width=1920, max_height=1920)
    website_image_2 = fields.Image(string='Website Gallery Image 2', max_width=1920, max_height=1920)
    website_image_3 = fields.Image(string='Website Gallery Image 3', max_width=1920, max_height=1920)
    website_gallery_image_ids = fields.One2many(
        'hotel.room.type.website.image',
        'room_type_id',
        string='Website Gallery Images',
    )
    website_description = fields.Html(string='Website Description', sanitize=True)
class HotelRoomTypeWebsiteImage(models.Model):
    _name = 'hotel.room.type.website.image'
    _description = 'Hotel Website Room Type Gallery Image'
    _order = 'sequence, id'

    sequence = fields.Integer(default=10)
    name = fields.Char(default='Gallery Image')
    room_type_id = fields.Many2one(
        'hotel.room.type',
        required=True,
        ondelete='cascade',
        index=True,
    )
    image = fields.Image(required=True, max_width=1920, max_height=1920)
