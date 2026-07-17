from io import BytesIO
from pathlib import Path
from PIL import Image, ImageDraw
import qrcode

from odoo import _, api, fields, models
from odoo.exceptions import UserError


class HotelRoomServiceRoomToken(models.Model):
    _inherit = "hotel.room.service.room.token"

    POSTER_TEMPLATE_CANDIDATES = (
        "static/src/img/room_service_poster_template.png",
        "static/src/img/room_service_qr_poster.png",
        "static/img/room_service_poster_template.png",
        "static/img/room_service_qr_poster.png",
        "static/description/room_service_poster_template.png",
        "static/description/room_service_qr_poster.png",
    )
    POSTER_REFERENCE_WIDTH = 1054
    POSTER_REFERENCE_HEIGHT = 1492
    POSTER_EXPORT_SCALE = 2

    POSTER_REFERENCE_QR_SIZE = 470
    POSTER_REFERENCE_QR_TOP = 540
    POSTER_REFERENCE_QR_PANEL_PADDING = 35
    POSTER_REFERENCE_QR_PANEL_RADIUS = 32
    POSTER_REFERENCE_QR_PANEL_BORDER = 3

    room_number = fields.Char(
        string="Room Number",
        related="room_id.name",
        store=True,
        readonly=True,
    )
    room_name = fields.Char(
        string="Room Name",
        related="room_id.room_type_id.name",
        store=True,
        readonly=True,
    )
    zone_id = fields.Many2one(
        "hotel.zone",
        string="Building / Zone",
        related="room_id.zone_id",
        store=True,
        readonly=True,
    )
    floor_id = fields.Many2one(
        "hotel.floor",
        string="Floor",
        related="room_id.floor_id",
        store=True,
        readonly=True,
    )
    qr_status = fields.Selection(
        [("active", "Active"), ("inactive", "Inactive")],
        string="Status",
        compute="_compute_qr_status",
    )

    @api.depends("active")
    def _compute_qr_status(self):
        for token in self:
            token.qr_status = "active" if token.active else "inactive"

    def _get_poster_template_path(self):
        module_root = Path(__file__).resolve().parents[1]
        for relative_path in self.POSTER_TEMPLATE_CANDIDATES:
            template_path = module_root / relative_path
            if template_path.is_file():
                return template_path
        raise UserError(_(
            "Room Service poster template PNG was not found. "
            "Please place it inside the module static folder as "
            "'static/src/img/room_service_poster_template.png'."
        ))

    def _get_qr_image(self, size):
        self.ensure_one()

        qr = qrcode.QRCode(version=None, error_correction=qrcode.constants.ERROR_CORRECT_H, box_size=1, border=1)
        qr.add_data(self.qr_url)
        qr.make(fit=True)
        matrix = qr.get_matrix()
        module_count = len(matrix)
        box_size = max(1, size // module_count)
        crisp_size = module_count * box_size
        canvas = Image.new("RGBA", (size, size), (255, 255, 255, 0))
        offset = round((size - crisp_size) / 2)
        draw = ImageDraw.Draw(canvas)
        for row_index, row in enumerate(matrix):
            for column_index, is_dark in enumerate(row):
                if is_dark:
                    x1 = offset + column_index * box_size
                    y1 = offset + row_index * box_size
                    draw.rectangle((x1, y1, x1 + box_size - 1, y1 + box_size - 1), fill=(0, 0, 0, 255))
        return canvas

    def _get_qr_png_bytes(self):
        self.ensure_one()

        poster = Image.open(self._get_poster_template_path()).convert("RGB")
        if self.POSTER_EXPORT_SCALE > 1:
            poster = poster.resize(
                (poster.width * self.POSTER_EXPORT_SCALE, poster.height * self.POSTER_EXPORT_SCALE),
                Image.Resampling.LANCZOS,
            )
        poster_width, poster_height = poster.size
        qr_size = round(self.POSTER_REFERENCE_QR_SIZE * min(
            poster_width / self.POSTER_REFERENCE_WIDTH,
            poster_height / self.POSTER_REFERENCE_HEIGHT,
        ))
        qr_top = round(self.POSTER_REFERENCE_QR_TOP * (poster_height / self.POSTER_REFERENCE_HEIGHT))
        qr_left = round((poster_width - qr_size) / 2)
        design_scale = min(
            poster_width / self.POSTER_REFERENCE_WIDTH,
            poster_height / self.POSTER_REFERENCE_HEIGHT,
        )
        panel_padding = round(self.POSTER_REFERENCE_QR_PANEL_PADDING * design_scale)
        panel_radius = round(self.POSTER_REFERENCE_QR_PANEL_RADIUS * design_scale)
        panel_border = max(1, round(self.POSTER_REFERENCE_QR_PANEL_BORDER * design_scale))
        panel_box = (
            qr_left - panel_padding,
            qr_top - panel_padding,
            qr_left + qr_size + panel_padding,
            qr_top + qr_size + panel_padding,
        )
        draw = ImageDraw.Draw(poster)
        draw.rounded_rectangle(panel_box, radius=panel_radius, fill=(248, 238, 218), outline=(177, 124, 36), width=panel_border)
        inset = round(8 * design_scale)
        inner_box = (
            panel_box[0] + inset,
            panel_box[1] + inset,
            panel_box[2] - inset,
            panel_box[3] - inset,
        )
        draw.rounded_rectangle(inner_box, radius=max(1, panel_radius - inset), outline=(177, 124, 36), width=max(1, panel_border // 2))
        qr_image = self._get_qr_image(qr_size)
        poster.paste(qr_image, (qr_left, qr_top), qr_image)
        buffer = BytesIO()
        poster.save(buffer, format="PNG")
        return buffer.getvalue()

    def _get_qr_filename(self, extension):
        self.ensure_one()
        room = (self.room_number or self.room_id.display_name or str(self.id)).replace("/", "-").replace("\\", "-")
        return "Room_Service_QR_%s.%s" % (room, extension)

    def action_download_png(self):
        self.ensure_one()
        return {
            "type": "ir.actions.act_url",
            "url": "/room-service/qr/%s/download.png" % self.id,
            "target": "self",
        }

    def action_download_pdf(self):
        self.ensure_one()
        return self.env.ref("hotel_room_service_qr.action_print_room_service_qr_cards").report_action(self)

    def action_download_selected_zip(self):
        tokens = self or self.browse(self.env.context.get("active_ids", []))
        if not tokens:
            tokens = self.search([("active", "=", True)])
        return {
            "type": "ir.actions.act_url",
            "url": "/room-service/qr/download.zip?ids=%s" % ",".join(str(token_id) for token_id in tokens.ids),
            "target": "self",
        }

    def action_download_all_zip(self):
        return {
            "type": "ir.actions.act_url",
            "url": "/room-service/qr/download.zip?all=1",
            "target": "self",
        }

    def action_print_selected_pdf(self):
        tokens = self or self.browse(self.env.context.get("active_ids", []))
        if not tokens:
            tokens = self.search([("active", "=", True)])
        return self.env.ref("hotel_room_service_qr.action_print_room_service_qr_cards").report_action(tokens)

    def action_print_all_pdf(self):
        tokens = self.search([("active", "=", True)])
        return self.env.ref("hotel_room_service_qr.action_print_room_service_qr_cards").report_action(tokens)
