import json
import uuid
from datetime import timedelta

from odoo import _, api, fields, models, Command
from odoo.exceptions import UserError, ValidationError


class HotelRoomServiceOutlet(models.Model):
    _name = "hotel.room.service.outlet"
    _description = "Room Service Outlet"
    _order = "sequence, name"

    name = fields.Char(required=True)
    code = fields.Char(index=True)
    active = fields.Boolean(default=True)
    sequence = fields.Integer(default=10)
    pos_config_id = fields.Many2one(
        "pos.config",
        string="POS Outlet",
        help="Optional POS configuration used only when Room Service orders should also create POS orders.",
    )
    auto_create_pos_order = fields.Boolean(
        string="Create Draft POS Order",
        default=False,
        help="Create a draft POS order through the standard POS model. If disabled, Room Service orders stay in the Room Service workflow.",
    )
    notes = fields.Text()
    hide_in_pos = fields.Boolean(
        string="Hide Outlet in POS",
        default=False,
        help="If enabled, this POS configuration will not be visible on the main Point of Sale dashboard.",
    )

    @api.model_create_multi
    def create(self, vals_list):
        records = super().create(vals_list)
        if not self.env.context.get("room_service_installing"):
            records._ensure_pos_self_order_config()
        return records

    def write(self, vals):
        res = super().write(vals)
        if (
            not self.env.context.get("room_service_installing")
            and any(f in vals for f in ['name', 'active', 'pos_config_id', 'hide_in_pos'])
        ):
            self._ensure_pos_self_order_config()
        return res

    @api.model
    def _ensure_default_room_service_setup(self):
        outlet = self.sudo().search([("code", "=", "ROOM")], limit=1)
        if not outlet:
            outlet = self.sudo().search([("name", "=", "Room Service")], limit=1)
        if not outlet:
            outlet = self.sudo().create({
                "name": "Room Service",
                "code": "ROOM",
                "sequence": 1,
                "active": True,
                "auto_create_pos_order": False,
            })
        return outlet

    def _ensure_eh_kds_setup(self):
        """Make Kitchen Display usable without manual KDS configuration.

        Room Service depends on the KDS modules, but a fresh or partially
        configured database can still have no active board, no lanes, no POS
        coverage, or restrictive routing. This setup stays in Room Service and
        only creates/repairs configuration records exposed by the KDS modules.
        """
        if "eh.kds.board" not in self.env.registry.models:
            return False

        Board = self.env["eh.kds.board"].sudo()
        Lane = self.env["eh.kds.lane"].sudo()
        Rule = self.env["eh.kds.route.rule"].sudo()
        PosConfig = self.env["pos.config"].sudo()

        board = Board.search([("name", "=", "Kitchen"), ("active", "=", True)], limit=1)
        if not board:
            board = Board.search([("active", "=", True)], limit=1)
        if not board:
            board = Board.create({
                "name": "Kitchen",
                "layout_mode": "dual",
                "active": True,
            })

        if not board.access_token:
            board.write({"access_token": uuid.uuid4().hex})

        lane_specs = [
            ("In Queue", "#0B88D9", 0),
            ("Cooking", "#FF8A00", 6),
            ("Ready", "#20B85A", 0),
            ("Completed", "#7D8794", 0),
        ]
        if not board.lane_ids:
            Lane.create([
                {
                    "board_id": board.id,
                    "name": name,
                    "color": color,
                    "sla_minutes": sla,
                    "sequence": sequence * 10,
                }
                for sequence, (name, color, sla) in enumerate(lane_specs)
            ])
        elif len(board.lane_ids) < 4:
            existing_names = {name.lower() for name in board.lane_ids.mapped("name")}
            for sequence, (name, color, sla) in enumerate(lane_specs):
                if name.lower() not in existing_names:
                    Lane.create({
                        "board_id": board.id,
                        "name": name,
                        "color": color,
                        "sla_minutes": sla,
                        "sequence": sequence * 10,
                    })

        all_pos_configs = PosConfig.search([("active", "=", True)])
        room_pos_configs = self.sudo().filtered("active").mapped("pos_config_id")
        if self:
            room_pos_configs |= self.sudo().mapped("pos_config_id")
        target_configs = all_pos_configs | room_pos_configs
        if target_configs:
            missing_configs = target_configs - board.pos_config_ids
            if missing_configs:
                board.write({"pos_config_ids": [Command.link(config.id) for config in missing_configs]})

        first_lane = board.lane_ids.sorted("sequence")[:1]
        if first_lane and not Rule.search([
            ("board_id", "=", board.id),
            ("pos_config_id", "=", False),
            ("category_id", "=", False),
            ("attribute_value_id", "=", False),
            ("target_lane_id", "=", first_lane.id),
            ("active", "=", True),
        ], limit=1):
            Rule.create({
                "board_id": board.id,
                "sequence": 9999,
                "target_lane_id": first_lane.id,
                "active": True,
            })

        return board

    def action_configure_pos_outlet(self):
        for outlet in self.filtered(lambda record: record.active):
            outlet._ensure_pos_self_order_config()
        return {
            "type": "ir.actions.client",
            "tag": "display_notification",
            "params": {
                "title": _("Room Service"),
                "message": _("POS outlet configuration has been linked for Room Service."),
                "type": "success",
                "sticky": False,
                "next": {"type": "ir.actions.client", "tag": "reload"},
            },
        }

    def _ensure_pos_self_order_config(self):
        for outlet in self.sudo():
            pos_config = outlet.pos_config_id.sudo() or outlet._get_or_create_room_service_pos_config()
            if not pos_config.has_active_session:
                outlet._configure_room_service_pos_config(pos_config)
            if pos_config.hide_in_pos != outlet.hide_in_pos:
                pos_config.sudo().write({"hide_in_pos": outlet.hide_in_pos})
            if outlet.pos_config_id != pos_config:
                outlet.with_context(room_service_installing=True).write({"pos_config_id": pos_config.id})
            if self.env.registry.ready and not self.env.context.get("room_service_skip_session_open"):
                outlet._ensure_room_service_pos_session(pos_config)
        return True

    def _get_or_create_room_service_pos_config(self):
        self.ensure_one()
        PosConfig = self.env["pos.config"].sudo()
        pos_config = PosConfig.search([("name", "=", self.name)], limit=1)
        if pos_config:
            return pos_config

        rooms_floor = self._get_or_create_rooms_floor()
        payment_methods = self._get_room_service_payment_methods()
        default_user = self._get_room_service_default_pos_user()
        vals = {
            "name": self.name,
            "company_id": self.env.company.id,
            "module_pos_restaurant": True,
            "floor_ids": [Command.link(rooms_floor.id)],
            "self_ordering_mode": "mobile",
            "self_ordering_service_mode": "table",
            "self_ordering_pay_after": "meal",
            "use_presets": False,
            "hide_in_pos": self.hide_in_pos,
        }
        if payment_methods:
            vals["payment_method_ids"] = [Command.set(payment_methods.ids)]
        if default_user:
            vals["self_ordering_default_user_id"] = default_user.id
        return PosConfig.create(vals)

    def _configure_room_service_pos_config(self, pos_config):
        self.ensure_one()
        rooms_floor = self._get_or_create_rooms_floor()
        vals = {
            "active": True,
            "self_ordering_mode": "mobile",
            "self_ordering_service_mode": "table",
            "self_ordering_pay_after": "meal",
            "use_presets": False,
        }
        if not pos_config.module_pos_restaurant:
            vals["module_pos_restaurant"] = True
        if rooms_floor not in pos_config.floor_ids:
            vals["floor_ids"] = [Command.link(rooms_floor.id)]
        if not pos_config.self_ordering_default_user_id:
            default_user = self._get_room_service_default_pos_user()
            if default_user:
                vals["self_ordering_default_user_id"] = default_user.id
        room_charge_methods = self.env["pos.payment.method"].sudo().search([("is_room_charge", "=", True)])
        if room_charge_methods:
            missing_methods = room_charge_methods - pos_config.payment_method_ids
            if missing_methods:
                vals["payment_method_ids"] = [Command.link(pm.id) for pm in missing_methods]
        elif not pos_config.payment_method_ids:
            payment_methods = self._get_room_service_payment_methods()
            if payment_methods:
                vals["payment_method_ids"] = [Command.set(payment_methods.ids)]


        opened_session = pos_config.session_ids.filtered(lambda session: session.state != "closed")
        if opened_session and any(key in vals for key in ("module_pos_restaurant", "payment_method_ids")):
            for key in ("module_pos_restaurant", "payment_method_ids"):
                vals.pop(key, None)
        if vals:
            pos_config.with_context(bypass_payment_method_ids_forbidden_change=True).write(vals)
        if not pos_config.access_token:
            pos_config._update_access_token()
        pos_config.floor_ids.table_ids.filtered(lambda table: not table.identifier)._update_identifier()
        return pos_config

    def _ensure_room_service_pos_session(self, pos_config):
        self.ensure_one()
        if pos_config.has_active_session:
            return pos_config.current_session_id
        session = self.env["pos.session"].sudo().create({
            "user_id": self.env.uid,
            "config_id": pos_config.id,
        })
        session.set_opening_control(0, "")
        return session

    def _get_or_create_rooms_floor(self):
        floor = self.env["restaurant.floor"].sudo().search([("name", "=", "Rooms")], limit=1)
        if not floor:
            floor = self.env["restaurant.floor"].sudo().create({"name": "Rooms"})
        return floor

    def _get_room_service_payment_methods(self):
        methods = self.env["pos.payment.method"].sudo().search([("is_room_charge", "=", True)])
        if methods:
            return methods
        return self.env["pos.config"].sudo()._default_payment_methods()

    def _get_room_service_default_pos_user(self):
        users = self.env["res.users"].sudo().search([
            "|",
            ("company_ids", "in", self.env.company.id),
            ("company_id", "=", False),
        ])
        return users.filtered(lambda user: user.has_group("point_of_sale.group_pos_manager"))[:1] or users.filtered(
            lambda user: user.has_group("point_of_sale.group_pos_user")
        )[:1]

    def _get_pos_menu_products(self):
        self.ensure_one()
        menu_items = self._get_room_service_menu_items()
        if menu_items:
            return menu_items.mapped("product_id")
        Product = self.env["product.product"].sudo()
        domain = [
            ("product_tmpl_id.available_in_pos", "=", True),
            ("sale_ok", "=", True),
            ("active", "=", True),
        ]
        if self.pos_config_id and self.pos_config_id.limit_categories:
            category_ids = self.pos_config_id.iface_available_categ_ids.ids
            if not category_ids:
                return Product
            domain.append(("product_tmpl_id.pos_categ_ids", "in", category_ids))

        products = Product.search(domain, order="name")
        if self.pos_config_id:
            products -= self.pos_config_id._get_special_products()
        return products

    def _get_room_service_menu_items(self):
        self.ensure_one()
        return self.env["hotel.room.service.menu.item"].sudo().search([("outlet_id", "=", self.id)])

    def _get_pos_product_price(self, product, qty=1.0):
        # Return the product's list price for the QR menu payload
        return product.lst_price

    def _get_pos_product_category_name(self, product):
        self.ensure_one()
        menu_item = self.env["hotel.room.service.menu.item"].sudo().search(
            [("outlet_id", "=", self.id), ("product_id", "=", product.id)], limit=1
        )
        if menu_item:
            return menu_item.category_id.name
        pos_category = product.product_tmpl_id.pos_categ_ids[:1]
        return pos_category.name if pos_category else _("Uncategorized")

    def get_pos_menu_payload(self):
        self.ensure_one()
        categories = []
        category_keys = set()
        items = []
        products = self._get_pos_menu_products()
        base_url = self.env["ir.config_parameter"].sudo().get_param("web.base.url", "")
        for product in products:
            category_name = self._get_pos_product_category_name(product)
            if category_name not in category_keys:
                category_keys.add(category_name)
                categories.append(category_name)
            items.append(
                {
                    "id": product.id,
                    "name": product.display_name,
                    "category": category_name,
                    "price": self._get_pos_product_price(product),
                    "description": product.product_tmpl_id.public_description or "",
                    "outlet_id": self.id,
                    "image_url": "%s/web/image/product.product/%s/image_128" % (base_url.rstrip("/"), product.id),
                    "has_image": bool(product.image_128),
                }
            )
        return {"categories": categories, "items": items}

    def _register_hook(self):
        res = super()._register_hook()
        # Only run post-install POS config setup when the registry is fully ready
        # and this module is confirmed installed (not during upgrade/init).
        if not self.env.registry.ready:
            return res
        try:
            module = self.env["ir.module.module"].sudo().search(
                [("name", "=", "hotel_room_service_qr"), ("state", "=", "installed")], limit=1
            )
            if not module:
                return res
            Outlet = self.env["hotel.room.service.outlet"].sudo()
            outlets = Outlet.search([("active", "=", True)])
            outlets.with_context(room_service_skip_session_open=True)._ensure_pos_self_order_config()
            outlets._ensure_eh_kds_setup()
        except Exception:
            pass
        return res


class HotelRoomServiceRoomToken(models.Model):
    _name = "hotel.room.service.room.token"
    _description = "Room Service QR Token"
    _order = "room_id"

    room_id = fields.Many2one("hotel.room", required=True, ondelete="cascade", index=True)
    token = fields.Char(required=True, copy=False, index=True, default=lambda self: uuid.uuid4().hex)
    active = fields.Boolean(default=True)
    qr_url = fields.Char(compute="_compute_qr_url")
    qr_image_url = fields.Char(compute="_compute_qr_url")
    last_scanned_at = fields.Datetime(readonly=True)
    table_id = fields.Many2one("restaurant.table", string="POS Table")

    def _room_name_to_integer(self, name):
        import re
        name = (name or '').strip().upper()
        if name.isdigit():
            return int(name)
        match = re.match(r'^([A-Z])(\d+)$', name)
        if match:
            letter, digits = match.groups()
            letter_val = ord(letter) - ord('A') + 1
            return int(f"{letter_val}{digits}")
        return sum(ord(c) for c in name)

    def _ensure_pos_table(self, pos_config):
        self.ensure_one()
        if self.table_id:
            return self.table_id

        Floor = self.env['restaurant.floor'].sudo()
        floor = Floor.search([('name', '=', 'Rooms')], limit=1)
        if not floor:
            floor = Floor.create({'name': 'Rooms'})

        if not pos_config.module_pos_restaurant:
            self.env.cr.execute(
                "UPDATE pos_config SET module_pos_restaurant = true WHERE id = %s",
                [pos_config.id]
            )
            pos_config.invalidate_recordset(['module_pos_restaurant'])

        if floor not in pos_config.floor_ids:
            self.env.cr.execute(
                "INSERT INTO pos_config_restaurant_floor_rel (pos_config_id, restaurant_floor_id) VALUES (%s, %s) ON CONFLICT DO NOTHING",
                [pos_config.id, floor.id]
            )
            pos_config.invalidate_recordset(['floor_ids'])

        Table = self.env['restaurant.table'].sudo()
        table = Table.search([('room_id', '=', self.room_id.id)], limit=1)
        if not table:
            table_num = self._room_name_to_integer(self.room_id.name)
            table = Table.create({
                'floor_id': floor.id,
                'table_number': table_num,
                'room_id': self.room_id.id,
                'seats': 2,
            })
        elif table.floor_id != floor:
            table.write({'floor_id': floor.id})

        if hasattr(table, '_update_identifier') and not table.identifier:
            table._update_identifier()

        self.write({'table_id': table.id})
        return table

    @api.constrains("token", "room_id")
    def _check_unique_token_and_room(self):
        for record in self:
            duplicate_token = self.search_count([("token", "=", record.token), ("id", "!=", record.id)])
            if duplicate_token:
                raise ValidationError(_("Room service QR token must be unique."))
            duplicate_room = self.search_count([("room_id", "=", record.room_id.id), ("id", "!=", record.id)])
            if duplicate_room:
                raise ValidationError(_("Each room can only have one room service QR token."))

    @api.depends("token")
    def _compute_qr_url(self):
        base_url = self.env["ir.config_parameter"].sudo().get_param("web.base.url", "")
        for record in self:
            record.qr_url = "%s/room-service/%s" % (base_url.rstrip("/"), record.token or "")
            if record.token and record.qr_url:
                try:
                    import qrcode
                    from io import BytesIO
                    import base64
                    qr = qrcode.QRCode(version=1, box_size=10, border=1)
                    qr.add_data(record.qr_url)
                    qr.make(fit=True)
                    img = qr.make_image(fill_color="black", back_color="white")
                    buffer = BytesIO()
                    img.save(buffer, format="PNG")
                    qr_base64 = base64.b64encode(buffer.getvalue()).decode('utf-8')
                    record.qr_image_url = f"data:image/png;base64,{qr_base64}"
                except Exception:
                    record.qr_image_url = (
                        "https://api.qrserver.com/v1/create-qr-code/?size=240x240&data=%s" % record.qr_url
                    )
            else:
                record.qr_image_url = False

    def action_regenerate_token(self):
        for record in self:
            record.token = uuid.uuid4().hex

    @api.model
    def action_generate_missing_room_tokens(self):
        existing_room_ids = set(self.search([]).mapped("room_id").ids)
        missing_rooms = self.env["hotel.room"].sudo().search([("id", "not in", list(existing_room_ids) or [0])])
        for room in missing_rooms:
            self.create({"room_id": room.id})
        count = len(missing_rooms)
        message = (
            _("Created %(count)s missing room QR token(s).", count=count)
            if count
            else _("All rooms already have room QR tokens.")
        )
        return {
            "type": "ir.actions.client",
            "tag": "display_notification",
            "params": {
                "title": _("Room Service QR"),
                "message": message,
                "type": "success",
                "sticky": False,
                "next": {"type": "ir.actions.client", "tag": "reload"},
            },
        }

    def _get_active_reservation(self):
        self.ensure_one()
        biz_date = self.env.company.hotel_business_date or fields.Date.context_today(self)
        return self.env["hotel.reservation"].sudo().search(
            [
                ("room_id", "=", self.room_id.id),
                ("state", "in", ["checkin", "checkout_hold"]),
                ("checkin_date", "<=", biz_date),
                ("company_id", "in", self.env.companies.ids),
            ],
            order="id desc",
            limit=1,
        )


class HotelRoomServiceMenuCategory(models.Model):
    _name = "hotel.room.service.menu.category"
    _description = "Room Service Menu Category"
    _order = "sequence, name"

    name = fields.Char(required=True)
    active = fields.Boolean(default=True)
    sequence = fields.Integer(default=10)


class HotelRoomServiceMenuItem(models.Model):
    _name = "hotel.room.service.menu.item"
    _description = "Legacy Room Service Menu Item"
    _order = "category_id, sequence, name"

    name = fields.Char(required=True)
    active = fields.Boolean(default=True)
    sequence = fields.Integer(default=10)
    category_id = fields.Many2one("hotel.room.service.menu.category", required=True)
    product_id = fields.Many2one("product.product", required=True, domain=[("sale_ok", "=", True)])
    outlet_id = fields.Many2one("hotel.room.service.outlet", required=True)
    price = fields.Float(required=True)
    description = fields.Text()
    image_1920 = fields.Image(related="product_id.image_1920", readonly=True)


class HotelRoomServiceOrder(models.Model):
    _name = "hotel.room.service.order"
    _description = "Room Service Order"
    _inherit = ["mail.thread", "mail.activity.mixin"]
    _order = "create_date desc"

    name = fields.Char(required=True, default=lambda self: _("New"), readonly=True, copy=False)
    access_token = fields.Char(required=True, copy=False, default=lambda self: uuid.uuid4().hex, index=True)
    token_id = fields.Many2one("hotel.room.service.room.token", required=False, ondelete="restrict")
    room_id = fields.Many2one("hotel.room", related="token_id.room_id", store=True, readonly=True)
    room_number = fields.Char(string="Room No.", related="room_id.name", store=True, readonly=True)
    display_order_number = fields.Char(string="Display Order No.", compute="_compute_display_order_number", store=True)
    reservation_id = fields.Many2one("hotel.reservation", required=True, ondelete="restrict")
    partner_id = fields.Many2one(related="reservation_id.partner_id", store=True, readonly=True)
    outlet_id = fields.Many2one("hotel.room.service.outlet", required=True)
    line_ids = fields.One2many("hotel.room.service.order.line", "order_id", string="Items")
    payment_method = fields.Selection(
        [("bill_to_room", "Bill to Room"), ("pay_at_pos", "Pay at POS")],
        required=True,
        default="bill_to_room",
    )
    hotel_business_date = fields.Date(
        string="Hotel Business Date",
        readonly=True,
        index=True,
        default=lambda self: self._default_hotel_business_date(),
        help="Hotel business date captured when the room service order is created.",
    )
    pms_sync_state = fields.Selection(
        [
            ("pending", "Pending"),
            ("posted", "Posted"),
            ("not_required", "Not Required"),
            ("failed", "Failed"),
        ],
        string="PMS Sync",
        default="pending",
        readonly=True,
        copy=False,
        tracking=True,
        index=True,
    )
    state = fields.Selection(
        [
            ("draft", "Draft"),
            ("cancelled", "Cancelled"),
            ("confirmed", "Confirmed"),
            ("sent_pos", "Sent to POS"),
            ("pos_failed", "POS Send Failed"),
            ("kitchen_preparing", "Kitchen Preparing"),
            ("kitchen_ready", "Kitchen Ready"),
            ("delivered", "Delivered"),
            ("guest_confirmed", "Guest Confirmed"),
            ("folio_posted", "Posted to Folio"),
            ("paid_pos", "Paid at POS"),
            ("closed", "Closed"),
        ],
        default="draft",
        tracking=True,
        index=True,
    )
    guest_note = fields.Text()
    total_amount = fields.Float(compute="_compute_total_amount", store=True)
    currency_id = fields.Many2one(related="reservation_id.currency_id", store=True, readonly=True)
    pos_order_id = fields.Many2one("pos.order", readonly=True)
    pos_reference = fields.Char(readonly=True)
    pms_folio_id = fields.Many2one("sale.order", string="PMS Folio", readonly=True, copy=False)
    adapter_payload = fields.Text(readonly=True)
    retry_count = fields.Integer(readonly=True)
    last_error = fields.Text(readonly=True)
    sent_to_pos_at = fields.Datetime(readonly=True)
    folio_posted_at = fields.Datetime(readonly=True)
    closed_at = fields.Datetime(readonly=True)

    @api.depends("line_ids.subtotal")
    def _compute_total_amount(self):
        for order in self:
            order.total_amount = sum(order.line_ids.mapped("subtotal"))

    @api.depends("name")
    def _compute_display_order_number(self):
        for order in self:
            digits = "".join(char for char in (order.name or "") if char.isdigit())
            order.display_order_number = str(int(digits[-4:] or "0")) if digits else str(order.id or "")

    @api.model
    def _default_hotel_business_date(self):
        return self.env.company.hotel_business_date or fields.Date.context_today(self)

    @api.model
    def _business_date_from_reservation(self, reservation):
        company = reservation.company_id or self.env.company
        return company.hotel_business_date or fields.Date.context_today(self)

    @api.model_create_multi
    def create(self, vals_list):
        for vals in vals_list:
            if vals.get("name", _("New")) == _("New"):
                vals["name"] = self.env["ir.sequence"].next_by_code("hotel.room.service.order") or _("New")
            if not vals.get("hotel_business_date"):
                reservation = self.env["hotel.reservation"].sudo().browse(vals.get("reservation_id"))
                vals["hotel_business_date"] = (
                    self._business_date_from_reservation(reservation)
                    if reservation
                    else self._default_hotel_business_date()
                )
            if not vals.get("pms_sync_state"):
                vals["pms_sync_state"] = "pending" if vals.get("payment_method", "bill_to_room") == "bill_to_room" else "not_required"
        return super().create(vals_list)

    def write(self, vals):
        if vals.get("payment_method") == "pay_at_pos" and "pms_sync_state" not in vals:
            vals["pms_sync_state"] = "not_required"
        elif vals.get("payment_method") == "bill_to_room" and "pms_sync_state" not in vals:
            vals["pms_sync_state"] = "pending"
        return super().write(vals)

    def action_print_receipt(self):
        self.ensure_one()
        report = self.env.ref("hotel_room_service_qr.action_report_room_service_order")
        return report.with_context(discard_logo_check=True).report_action(self)

    def _log_adapter(self, adapter, status, message=False, payload=False):
        self.ensure_one()
        return self.env["hotel.room.service.integration.log"].sudo().create(
            {
                "order_id": self.id,
                "adapter": adapter,
                "status": status,
                "message": message,
                "payload": json.dumps(payload, indent=2, default=str) if isinstance(payload, dict) else payload,
            }
        )

    def _prepare_pos_payload(self):
        self.ensure_one()
        return {
            "source": "pos",
            "order_ref": self.name,
            "room": self.room_id.name,
            "reservation_id": self.reservation_id.id,
            "guest": self.partner_id.name,
            "payment_method": self.payment_method,
            "total_amount": self.total_amount,
            "lines": [
                {
                    "product_id": line.product_id.id,
                    "name": line.name,
                    "qty": line.quantity,
                    "price_unit": line.price_unit,
                    "subtotal": line.subtotal,
                    "note": line.note,
                }
                for line in self.line_ids
            ],
        }

    def action_cancel_before_pos(self):
        for order in self:
            if order.state not in ["draft", "confirmed", "pos_failed"]:
                raise UserError(_("Only draft, confirmed, or failed orders can be cancelled before preparation."))
            order.write({"state": "cancelled", "closed_at": fields.Datetime.now()})
            order._log_adapter("guest", "success", _("Guest cancelled before POS send."))

    def action_confirm_and_send(self):
        for order in self:
            if order._is_posted_to_room():
                raise UserError(_("Already posted to room."))
            if order.state != "draft":
                raise UserError(_("Only draft orders can be confirmed."))
            if not order.line_ids:
                raise UserError(_("Add at least one menu item before confirming."))
            order.write({"state": "confirmed"})
            order._log_adapter("guest", "success", _("Guest confirmed the room service order."))
            if order.outlet_id.auto_create_pos_order:
                order.action_send_to_pos()
        return True

    def action_send_to_pos(self):
        for order in self:
            if order._is_posted_to_room():
                raise UserError(_("Already posted to room."))
            if not order.outlet_id.auto_create_pos_order:
                raise UserError(_("POS draft order creation is disabled for outlet %s.") % order.outlet_id.display_name)
            payload = order._prepare_pos_payload()
            order.write({"adapter_payload": json.dumps(payload, indent=2, default=str)})
            try:
                pos_order = order._create_draft_pos_order_if_possible(payload)
                vals = {
                    "state": "sent_pos",
                    "sent_to_pos_at": fields.Datetime.now(),
                    "last_error": False,
                }
                if pos_order:
                    vals.update(
                        {
                            "pos_order_id": pos_order.id,
                            "pos_reference": pos_order.name if pos_order.name != "/" else pos_order.floating_order_name,
                        }
                    )
                order.write(vals)
                order._log_adapter("pos", "success", _("Order sent to POS adapter."), payload)
            except Exception as exc:
                order.write(
                    {
                        "state": "pos_failed",
                        "retry_count": order.retry_count + 1,
                        "last_error": str(exc),
                    }
                )
                order._log_adapter("pos", "failed", str(exc), payload)
        return True

    def _create_draft_pos_order_if_possible(self, payload):
        self.ensure_one()
        outlet = self.outlet_id
        if not outlet.auto_create_pos_order:
            raise UserError(_("POS draft order creation is disabled for outlet %s.") % outlet.display_name)
        if not outlet.pos_config_id:
            raise UserError(_("No POS outlet is configured for %s.") % outlet.display_name)

        session = self.env["pos.session"].sudo().search(
            [("config_id", "=", outlet.pos_config_id.id), ("state", "=", "opened")],
            order="id desc",
            limit=1,
        )
        if not session:
            raise UserError(_("No opened POS session found for outlet %s.") % outlet.display_name)

        order_uuid = str(uuid.uuid4())
        amount_total = self.total_amount
        pos_lines = []
        for index, line in enumerate(self.line_ids, start=1):
            taxes = line.product_id.taxes_id.filtered_domain(self.env["account.tax"]._check_company_domain(self.env.company))
            pos_lines.append(
                [
                    0,
                    0,
                    {
                        "uuid": str(uuid.uuid4()),
                        "name": "%s-%s" % (self.name, index),
                        "product_id": line.product_id.id,
                        "qty": line.quantity,
                        "price_unit": line.price_unit,
                        "discount": 0,
                        "tax_ids": [(6, 0, taxes.ids)],
                        "price_subtotal": line.subtotal,
                        "price_subtotal_incl": line.subtotal,
                        "full_product_name": line.name,
                        "customer_note": line.note or "",
                    },
                ]
            )

        table = self.token_id.sudo()._ensure_pos_table(outlet.pos_config_id)
        order_data = {
            "uuid": order_uuid,
            "access_token": uuid.uuid4().hex,
            "session_id": session.id,
            "config_id": outlet.pos_config_id.id,
            "table_id": table.id if table else False,
            "partner_id": self.partner_id.id,
            "date_order": fields.Datetime.now(),
            "amount_tax": 0.0,
            "amount_total": amount_total,
            "amount_paid": 0.0,
            "amount_return": 0.0,
            "state": "draft",
            "floating_order_name": "%s / Room %s" % (self.name, self.room_id.name),
            "lines": pos_lines,
            "payment_ids": [],
            "to_invoice": False,
            "source": "pos",
        }
        pos_order_id = self.env["pos.order"].sudo()._process_order(order_data, False)
        pos_order = self.env["pos.order"].sudo().browse(pos_order_id)
        try:
            pos_order.config_id.sudo().notify_synchronisation(
                session.id,
                "backend",
                {"pos.order": [pos_order.id]}
            )
        except Exception:
            pass
        return pos_order

    def action_retry_pos_send(self):
        self.filtered(lambda order: order.state == "pos_failed").action_send_to_pos()

    def action_kitchen_preparing(self):
        self.write({"state": "kitchen_preparing"})

    def action_kitchen_ready(self):
        self.write({"state": "kitchen_ready"})

    def action_delivered(self):
        self.write({"state": "delivered"})

    def action_guest_confirm_completed(self):
        for order in self:
            if order.state not in ["kitchen_ready", "delivered", "guest_confirmed"]:
                raise UserError(_("This order cannot be confirmed completed from its current status."))
            if order.state in ["kitchen_ready", "delivered"]:
                order.write({"state": "guest_confirmed"})
            if order.payment_method == "bill_to_room":
                order._post_to_pms_folio()
            else:
                order.write({"state": "paid_pos", "closed_at": fields.Datetime.now()})
                order._log_adapter("pos", "success", _("Guest selected Pay at POS; payment remains in normal POS flow."))

    def action_sync_to_pms(self):
        for order in self:
            if order._is_posted_to_room():
                raise UserError(_("Already posted to room."))
            if order.payment_method != "bill_to_room":
                order.write({"pms_sync_state": "not_required"})
                continue
            order._post_to_pms_folio()
        return {
            "type": "ir.actions.client",
            "tag": "display_notification",
            "params": {
                "title": _("Room Service PMS Sync"),
                "message": _("Room service order was synchronized with the PMS folio."),
                "type": "success",
                "sticky": False,
                "next": {"type": "ir.actions.client", "tag": "reload"},
            },
        }

    def _is_posted_to_room(self):
        self.ensure_one()
        return bool(
            self.pms_sync_state == "posted"
            or self.state == "folio_posted"
            or self.folio_posted_at
            or (self.pos_order_id and self.pos_order_id.state in ["paid", "done"])
        )

    def _post_to_pms_folio(self):
        self.ensure_one()
        if self.payment_method != "bill_to_room":
            self.write({"pms_sync_state": "not_required"})
            return
        if self._is_posted_to_room():
            raise UserError(_("Already posted to room."))
        try:
            reservation = self.reservation_id.sudo()
            if not reservation.sale_order_id:
                reservation.action_create_folio()
            folio = reservation.sale_order_id
            if not folio:
                raise UserError(_("Unable to create or find the guest folio."))

            for line in self.line_ids:
                line_vals = {
                    "order_id": folio.id,
                    "product_id": line.product_id.id,
                    "name": "%s / Room Service: %s" % (self.name, line.name),
                    "product_uom_qty": line.quantity,
                    "price_unit": line.price_unit,
                    "hotel_reservation_id": reservation.id,
                }
                if self.pos_order_id:
                    line_vals["tax_ids"] = [(5, 0, 0)]
                if "hotel_business_date" in self.env["sale.order.line"]._fields:
                    line_vals["hotel_business_date"] = self.hotel_business_date
                self.env["sale.order.line"].sudo().create(line_vals)
            vals = {
                "pms_sync_state": "posted",
                "pms_folio_id": folio.id,
                "folio_posted_at": fields.Datetime.now(),
                "last_error": False,
            }
            if self.state in ["delivered", "guest_confirmed", "paid_pos", "closed"]:
                vals.update({
                    "state": "folio_posted",
                    "closed_at": fields.Datetime.now(),
                })
            self.write(vals)
            self._log_adapter("pms", "success", _("Posted room service charge to folio through PMS reservation interface."))
        except Exception as exc:
            self.write({"pms_sync_state": "failed", "last_error": str(exc), "retry_count": self.retry_count + 1})
            self._log_adapter("pms", "failed", str(exc))
            raise

    def action_mark_paid_pos(self):
        for order in self:
            if order.pos_order_id and order.pos_order_id.state not in ["paid", "done"]:
                raise UserError(_("The linked POS order is not paid yet."))
            vals = {"pms_sync_state": "not_required"}
            if order.state in ["delivered", "guest_confirmed", "closed"]:
                vals.update({"state": "paid_pos", "closed_at": fields.Datetime.now()})
            order.write(vals)
            order._log_adapter("pos", "success", _("Room Service order marked paid at POS."))


class HotelRoomServiceOrderLine(models.Model):
    _name = "hotel.room.service.order.line"
    _description = "Room Service Order Line"
    _order = "id"

    order_id = fields.Many2one("hotel.room.service.order", required=True, ondelete="cascade")
    menu_item_id = fields.Many2one("hotel.room.service.menu.item")
    product_id = fields.Many2one("product.product", required=True, domain=[("sale_ok", "=", True)])
    name = fields.Char(required=True)
    quantity = fields.Float(required=True, default=1.0)
    price_unit = fields.Float(required=True)
    subtotal = fields.Float(compute="_compute_subtotal", store=True)
    note = fields.Char()

    def _check_can_edit_order_lines(self):
        locked_orders = self.mapped("order_id").filtered(
            lambda order: order.state != "draft" or order._is_posted_to_room()
        )
        if locked_orders:
            raise UserError(
                _("Ordered items can only be changed before the order is accepted.")
            )

    def _sync_changed_orders(self, orders):
        orders = orders.exists()
        if not orders:
            return
        for order in orders:
            order.write({
                "adapter_payload": json.dumps(order._prepare_pos_payload(), indent=2, default=str),
            })
        sync_method = getattr(orders, "_sync_pos_kitchen_status_from_room_service", None)
        if sync_method:
            sync_method()

    @api.model_create_multi
    def create(self, vals_list):
        lines = super().create(vals_list)
        lines._check_can_edit_order_lines()
        lines._sync_changed_orders(lines.mapped("order_id"))
        return lines

    def write(self, vals):
        self._check_can_edit_order_lines()
        orders = self.mapped("order_id")
        res = super().write(vals)
        self._sync_changed_orders(orders)
        return res

    def unlink(self):
        self._check_can_edit_order_lines()
        orders = self.mapped("order_id")
        res = super().unlink()
        self._sync_changed_orders(orders)
        return res

    @api.onchange("product_id")
    def _onchange_product_id(self):
        if self.product_id:
            self.name = self.product_id.display_name
            self.price_unit = self.product_id.lst_price

    @api.constrains("quantity")
    def _check_quantity(self):
        for line in self:
            if line.quantity <= 0:
                raise ValidationError(_("Quantity must be greater than zero."))

    @api.depends("quantity", "price_unit")
    def _compute_subtotal(self):
        for line in self:
            line.subtotal = line.quantity * line.price_unit


class HotelRoomServiceIntegrationLog(models.Model):
    _name = "hotel.room.service.integration.log"
    _description = "Room Service Integration Log"
    _order = "create_date desc"

    order_id = fields.Many2one("hotel.room.service.order", required=True, ondelete="cascade")
    adapter = fields.Selection([("pos", "POS"), ("pms", "PMS"), ("guest", "Guest"), ("system", "System")], required=True)
    status = fields.Selection([("success", "Success"), ("failed", "Failed"), ("retry", "Retry")], required=True)
    message = fields.Text()
    payload = fields.Text()

    @api.model
    def cron_cleanup_integration_logs(self, days=30):
        limit_date = fields.Datetime.now() - timedelta(days=days)
        logs = self.search([("create_date", "<", limit_date)])
        count = len(logs)
        logs.unlink()
        return count


class HotelRoomServiceReportWizard(models.TransientModel):
    _name = "hotel.room.service.report.wizard"
    _description = "Room Service Report Wizard"

    report_type = fields.Selection(
        [
            ("daily", "Daily"),
            ("weekly", "Weekly"),
            ("monthly", "Monthly"),
            ("yearly", "Yearly"),
            ("custom", "Custom Date Range"),
        ],
        string="Report Type",
        required=True,
        default="daily",
    )
    report_category = fields.Selection(
        [
            ("sales_summary", "Sales Summary"),
            ("item_sales", "Itemized Product Sales"),
            ("room_sales", "Room-based Sales"),
            ("order_history", "Order History & Status"),
            ("payment_method", "Payment Methods Analysis"),
            ("canceled_orders", "Canceled Orders Analysis"),
        ],
        string="Report Category",
        required=True,
        default="sales_summary",
    )
    date_start = fields.Date(string="Start Date", required=True, default=fields.Date.context_today)
    date_end = fields.Date(string="End Date", required=True, default=fields.Date.context_today)
    outlet_id = fields.Many2one("hotel.room.service.outlet", string="Outlet (Optional)")

    @api.onchange("report_type")
    def _onchange_report_type(self):
        from datetime import timedelta
        today = fields.Date.context_today(self)
        if self.report_type == "daily":
            self.date_start = today
            self.date_end = today
        elif self.report_type == "weekly":
            self.date_start = today - timedelta(days=today.weekday())
            self.date_end = self.date_start + timedelta(days=6)
        elif self.report_type == "monthly":
            self.date_start = today.replace(day=1)
            next_month = today.replace(day=28) + timedelta(days=4)
            self.date_end = next_month - timedelta(days=next_month.day)
        elif self.report_type == "yearly":
            self.date_start = today.replace(month=1, day=1)
            self.date_end = today.replace(month=12, day=31)

    def action_print_pdf(self):
        self.ensure_one()
        return self.env.ref("hotel_room_service_qr.action_report_room_service_sales").report_action(self)


class ReportRoomServiceSales(models.AbstractModel):
    _name = "report.hotel_room_service_qr.report_rs_sales_template"
    _description = "Room Service Sales Report Parser"

    @api.model
    def _get_report_values(self, docids, data=None):
        wizard = self.env["hotel.room.service.report.wizard"].browse(docids)
        domain = [
            ("create_date", ">=", fields.Datetime.to_datetime(wizard.date_start)),
            ("create_date", "<=", fields.Datetime.to_datetime(wizard.date_end)),
        ]
        if wizard.report_category == "canceled_orders":
            domain.append(("state", "=", "cancelled"))
        else:
            domain.append(("state", "!=", "cancelled"))

        if wizard.outlet_id:
            domain.append(("outlet_id", "=", wizard.outlet_id.id))

        orders = self.env["hotel.room.service.order"].sudo().search(domain, order="create_date desc")

        total_orders = len(orders)
        total_revenue = sum(order.total_amount for order in orders)
        avg_value = total_revenue / total_orders if total_orders > 0 else 0.0

        room_posted = sum(order.total_amount for order in orders if order.payment_method == "bill_to_room")
        cash_pos = sum(order.total_amount for order in orders if order.payment_method == "pay_at_pos")

        product_data = {}
        for order in orders:
            for line in order.line_ids:
                p_id = line.product_id.id
                p_name = line.product_id.display_name or line.name
                p_category = line.product_id.categ_id.name or "Uncategorized"
                if p_id not in product_data:
                    product_data[p_id] = {
                        "name": p_name,
                        "category": p_category,
                        "qty": 0.0,
                        "amount": 0.0,
                        "price_avg": 0.0,
                        "percent": 0.0,
                    }
                product_data[p_id]["qty"] += line.quantity
                product_data[p_id]["amount"] += line.subtotal

        for p_id in product_data:
            p_val = product_data[p_id]
            p_val["price_avg"] = p_val["amount"] / p_val["qty"] if p_val["qty"] > 0 else 0.0
            p_val["percent"] = (p_val["amount"] / total_revenue * 100.0) if total_revenue > 0 else 0.0

        top_products = sorted(product_data.values(), key=lambda x: x["qty"], reverse=True)[:10]
        all_products = sorted(product_data.values(), key=lambda x: x["amount"], reverse=True)

        room_data = {}
        for order in orders:
            r_id = order.room_id.id
            r_name = order.room_number or "-"
            if r_id not in room_data:
                room_data[r_id] = {
                    "room": r_name,
                    "guest": order.partner_id.name or "-",
                    "res": order.reservation_id.name or "-",
                    "count": 0,
                    "amount": 0.0,
                }
            room_data[r_id]["count"] += 1
            room_data[r_id]["amount"] += order.total_amount
        room_list = sorted(room_data.values(), key=lambda x: x["amount"], reverse=True)

        canceled_logs = {}
        if wizard.report_category == "canceled_orders":
            logs = self.env["hotel.room.service.integration.log"].sudo().search([
                ("order_id", "in", orders.ids),
                ("adapter", "=", "guest"),
            ])
            for log in logs:
                canceled_logs[log.order_id.id] = log.message

        return {
            "doc_ids": docids,
            "doc_model": "hotel.room.service.report.wizard",
            "docs": wizard,
            "orders": orders,
            "total_orders": total_orders,
            "total_revenue": total_revenue,
            "avg_value": avg_value,
            "room_posted": room_posted,
            "cash_pos": cash_pos,
            "top_products": top_products,
            "all_products": all_products,
            "room_list": room_list,
            "canceled_logs": canceled_logs,
        }
