import json
import zipfile
from io import BytesIO

from odoo import http, fields
from odoo.http import content_disposition, request


class HotelRoomServiceKitchenStatusDisplay(http.Controller):
    """Compatibility endpoints backed by the eh_pos_kds Kitchen Display."""

    @http.route("/pos/kitchen/status", type="http", auth="public", website=True)
    def kitchen_status_display(self, pos_config_id=None, **kwargs):
        board = self._get_kds_board(pos_config_id)
        if board:
            return request.redirect("/eh_kds/status/%s" % board.access_token)
        return request.not_found()

    @http.route("/pos/kitchen/status/data", type="http", auth="public", csrf=False)
    def kitchen_status_display_data(self, pos_config_id=None, **kwargs):
        payload = self._get_status_payload(self._safe_int(pos_config_id))
        return request.make_response(
            json.dumps(payload),
            headers=[("Content-Type", "application/json")],
        )

    def _safe_int(self, value):
        try:
            return int(value or 0)
        except (TypeError, ValueError):
            return 0

    def _get_kds_board(self, pos_config_id=None):
        Board = request.env["eh.kds.board"].sudo()
        domain = [("active", "=", True)]
        if pos_config_id:
            board = Board.search(domain + [("pos_config_ids", "in", [pos_config_id])], limit=1)
            if board:
                return board
        return Board.search(domain, order="sequence, id", limit=1)

    def _get_status_payload(self, config_id):
        board = self._get_kds_board(config_id)
        if not board:
            return {
                "kitchen": {},
                "almost_ready": [],
                "ready": [],
                "counts": {"almost_ready": 0, "ready": 0},
                "last_updated": fields.Datetime.now().isoformat(),
            }

        request.env["hotel.room.service.order"].sudo().search([
            ("state", "in", HotelRoomServiceQrController.DISPLAY_STATES),
        ])._reconcile_pos_kitchen_status()
        data = board._kds_status_data()
        almost_ready = [self._serialize_kds_status_item(item, "preparing") for item in data.get("preparing", [])]
        ready = [self._serialize_kds_status_item(item, "ready") for item in data.get("ready", [])]

        return {
            "kitchen": {
                "id": board.id,
                "name": board.name,
                "pos_config_id": config_id or 0,
                "pos_name": board.name,
            },
            "almost_ready": almost_ready[:30],
            "ready": ready[:30],
            "counts": {
                "almost_ready": len(almost_ready),
                "ready": len(ready),
            },
            "last_updated": fields.Datetime.now().isoformat(),
        }

    def _serialize_kds_status_item(self, item, status):
        return {
            "id": item.get("ticket_id"),
            "name": item.get("ref") or str(item.get("ticket_id") or ""),
            "customer": "",
            "table": "",
            "status": status,
            "time": "",
            "eta": "",
            "wait_minutes": 0,
        }


class HotelRoomServiceQrController(http.Controller):
    DISPLAY_STATES = [
        "draft",
        "confirmed",
        "sent_pos",
        "pos_failed",
        "kitchen_preparing",
        "kitchen_ready",
        "delivered",
        "guest_confirmed",
        "folio_posted",
        "paid_pos",
        "closed",
    ]
    ROOM_STATUS_ACTIVE_STATES = [
        "draft",
        "confirmed",
        "sent_pos",
        "pos_failed",
        "kitchen_preparing",
        "kitchen_ready",
        "delivered",
        "guest_confirmed",
    ]

    def _get_monitor_summary(self, orders):
        return {
            "awaiting_confirmation": len(orders.filtered(lambda order: order.state == "draft")),
            "waiting": len(orders.filtered(lambda order: order.state in ["confirmed", "sent_pos", "pos_failed"])),
            "preparing": len(orders.filtered(lambda order: order.state == "kitchen_preparing")),
            "ready": len(orders.filtered(lambda order: order.state == "kitchen_ready")),
            "completed": len(orders.filtered(lambda order: order.state in ["delivered", "guest_confirmed", "folio_posted", "paid_pos", "closed"])),
        }

    def _get_monitor_menu_payload(self, outlet):
        menu_items = request.env["hotel.room.service.menu.item"].sudo().search([
            ("active", "=", True),
            ("outlet_id", "=", outlet.id),
        ], order="category_id, sequence, name")
        menu_payload = []
        categories_by_id = {}
        for item in menu_items:
            item_payload = {
                "id": item.id,
                "product_id": item.product_id.id,
                "name": item.name or item.product_id.display_name,
                "price": item.price,
                "description": item.description or "",
                "category_id": item.category_id.id,
                "category_name": item.category_id.name,
            }
            menu_payload.append(item_payload)
            category_payload = categories_by_id.setdefault(item.category_id.id, {
                "id": item.category_id.id,
                "name": item.category_id.name,
                "items": [],
            })
            category_payload["items"].append(item_payload)
        return menu_payload, list(categories_by_id.values())

    def _reconcile_monitor_kitchen_orders(self):
        orders = request.env["hotel.room.service.order"].sudo().search([
            ("state", "in", self.DISPLAY_STATES),
            ("pos_order_id", "!=", False),
        ])
        orders._reconcile_pos_kitchen_status()

    def _get_monitor_order_number(self, order):
        """Use the same customer-facing reference as the POS receipt when possible."""
        pos_order = order.pos_order_id.sudo()
        if pos_order and pos_order.pos_reference:
            return pos_order.pos_reference
        return order.pos_reference or order.display_order_number or order.name

    def _get_monitor_guest_phone(self, order):
        partner = order.partner_id.sudo()
        return getattr(partner, "mobile", False) or getattr(partner, "phone", False) or ""

    def _get_token_record(self, token):
        token_record = request.env["hotel.room.service.room.token"].sudo().search(
            [("token", "=", token), ("active", "=", True)],
            limit=1,
        )
        if token_record:
            token_record.sudo().write({"last_scanned_at": fields.Datetime.now()})
        return token_record

    def _render_error(self, message, status=200):
        return request.render("hotel_room_service_qr.room_service_error", {"message": message}, status=status)

    def _get_qr_download_tokens(self, ids=None, download_all=False):
        Token = request.env["hotel.room.service.room.token"]
        if download_all:
            return Token.search([("active", "=", True)], order="room_id")
        token_ids = []
        for raw_id in (ids or "").split(","):
            if raw_id.strip().isdigit():
                token_ids.append(int(raw_id.strip()))
        return Token.browse(token_ids).exists()

    @http.route("/room-service/qr/<int:token_id>/download.png", type="http", auth="user")
    def room_service_qr_download_png(self, token_id, **kw):
        token = request.env["hotel.room.service.room.token"].browse(token_id).exists()
        if not token:
            return request.not_found()
        png_data = token._get_qr_png_bytes()
        return request.make_response(
            png_data,
            headers=[
                ("Content-Type", "image/png"),
                ("Content-Length", str(len(png_data))),
                ("Content-Disposition", content_disposition(token._get_qr_filename("png"))),
            ],
        )

    @http.route("/room-service/qr/download.zip", type="http", auth="user")
    def room_service_qr_download_zip(self, ids=None, all=None, **kw):
        tokens = self._get_qr_download_tokens(ids=ids, download_all=bool(all))
        if not tokens:
            return request.not_found()

        buffer = BytesIO()
        used_names = set()
        with zipfile.ZipFile(buffer, "w", zipfile.ZIP_DEFLATED) as archive:
            for token in tokens:
                filename = token._get_qr_filename("png")
                if filename in used_names:
                    filename = "room-service-qr-room-%s-%s.png" % (token.room_number or token.id, token.id)
                used_names.add(filename)
                archive.writestr(filename, token._get_qr_png_bytes())

        zip_data = buffer.getvalue()
        return request.make_response(
            zip_data,
            headers=[
                ("Content-Type", "application/zip"),
                ("Content-Length", str(len(zip_data))),
                ("Content-Disposition", content_disposition("room-service-qr-codes.zip")),
            ],
        )

    @http.route("/room-service/order-display", type="http", auth="user")
    def room_service_order_display(self, **kw):
        Order = request.env["hotel.room.service.order"].sudo()
        self._reconcile_monitor_kitchen_orders()
        state_labels = dict(Order._fields["state"].selection)
        now = fields.Datetime.now()

        orders = Order.search(
            [("state", "in", self.DISPLAY_STATES)],
            order="create_date asc, id asc",
        )
        summary = self._get_monitor_summary(orders)
        orders_data = []
        for order in orders:
            lines = []
            total_items = 0
            for line in order.line_ids:
                total_items += line.quantity
                lines.append({
                    'id': line.id,
                    'menu_item_id': line.menu_item_id.id,
                    'product_id': line.product_id.id,
                    'name': line.product_id.display_name or line.name,
                    'qty': line.quantity,
                    'price_unit': line.price_unit,
                    'subtotal': line.subtotal,
                    'note': line.note or '',
                })
            menu_items, menu_categories = self._get_monitor_menu_payload(order.outlet_id)
            wait_minutes = 0
            if order.create_date:
                wait_minutes = max(0, int((now - order.create_date).total_seconds() // 60))
            orders_data.append({
                'id': order.id,
                'number': self._get_monitor_order_number(order),
                'name': order.name,
                'room': order.room_number or '-',
                'guest': order.partner_id.name or '',
                'guest_phone': self._get_monitor_guest_phone(order),
                'state': order.state,
                'state_label': state_labels.get(order.state, order.state),
                'status_group': self._get_monitor_status_group(order.state),
                'date_utc': (order.create_date.isoformat() + 'Z') if order.create_date else '',
                'date_str': order.create_date.strftime("%Y-%m-%d %H:%M") if order.create_date else '',
                'time_str': order.create_date.strftime("%I:%M %p") if order.create_date else '',
                'wait_minutes': wait_minutes,
                'total_items': total_items,
                'total': order.total_amount,
                'lines': lines,
                'can_edit_items': order.state == 'draft',
                'menu_items': menu_items,
                'menu_categories': menu_categories,
                'note': order.guest_note or '',
                'payment': order.payment_method,
            })
        closed_sessions = []
        outlets = request.env["hotel.room.service.outlet"].sudo().search([("active", "=", True)])
        for outlet in outlets:
            if outlet.auto_create_pos_order and outlet.pos_config_id:
                session = request.env["pos.session"].sudo().search(
                    [("config_id", "=", outlet.pos_config_id.id), ("state", "=", "opened")],
                    limit=1,
                )
                if not session:
                    closed_sessions.append(outlet.name)

        return request.render(
            "hotel_room_service_qr.room_service_order_display",
            {
                "current_order": orders[:1],
                "queue_orders": orders[1:],
                "state_labels": state_labels,
                "orders_data": orders_data,
                "orders_data_json": json.dumps(orders_data),
                "summary": summary,
                "summary_json": json.dumps(summary),
                "closed_sessions": closed_sessions,
                "closed_sessions_json": json.dumps(closed_sessions),
            },
        )

    def _get_monitor_status_group(self, state):
        if state == "draft":
            return "awaiting_confirmation"
        if state in ["confirmed", "sent_pos", "pos_failed"]:
            return "waiting"
        if state == "kitchen_preparing":
            return "preparing"
        if state == "kitchen_ready":
            return "ready"
        if state == "delivered":
            return "delivered"
        return "completed"

    def _get_tracker_steps(self, order):
        state_to_index = {
            "draft": 0,
            "confirmed": 1,
            "sent_pos": 2,
            "pos_failed": 2,
            "kitchen_preparing": 3,
            "kitchen_ready": 4,
            "delivered": 5,
            "guest_confirmed": 6,
            "folio_posted": 6,
            "paid_pos": 6,
            "closed": 6,
        }
        steps = [
            ("placed", "Order Placed"),
            ("confirmed", "Confirmed"),
            ("sent_pos", "Sent to Kitchen"),
            ("cooking", "Cooking"),
            ("ready", "Ready to Deliver"),
            ("delivered", "Delivered"),
            ("completed", "Completed"),
        ]
        current_index = state_to_index.get(order.state, 0)
        cancelled = order.state == "cancelled"
        result = []
        for index, (key, label) in enumerate(steps):
            if cancelled:
                step_state = "future"
            elif index < current_index:
                step_state = "done"
            elif index == current_index:
                step_state = "current"
            else:
                step_state = "future"
            result.append({"key": key, "label": label, "state": step_state})
        if cancelled:
            result.append({"key": "cancelled", "label": "Cancelled", "state": "cancelled"})
        return result

    def _get_tracker_payload(self, order):
        order = order.sudo()
        state_labels = dict(order._fields["state"].selection)
        customer_state_labels = {
            "draft": "Awaiting Confirmation",
        }
        return {
            "id": order.id,
            "access_token": order.access_token or "",
            "pos_order_access_token": order.pos_order_id.access_token or "",
            "name": order.name or "",
            "number": self._get_monitor_order_number(order),
            "room": order.room_number or "",
            "guest": order.partner_id.name or "",
            "state": order.state,
            "state_label": customer_state_labels.get(
                order.state, state_labels.get(order.state, order.state)
            ),
            "last_error": order.last_error or "",
            "updated_at": order.write_date.strftime("%Y-%m-%d %H:%M:%S") if order.write_date else "",
            "updated_at_display": order.write_date.strftime("%b %d, %I:%M %p") if order.write_date else "",
            "steps": self._get_tracker_steps(order),
        }

    def _get_latest_room_service_order_for_pos_self(self, pos_order_access_tokens=None, room_service_token=None, table_identifier=None):
        Order = request.env["hotel.room.service.order"].sudo()
        orders = Order.browse()
        pos_order_access_tokens = [token for token in (pos_order_access_tokens or []) if token]
        if pos_order_access_tokens:
            pos_orders = request.env["pos.order"].sudo().search([("access_token", "in", pos_order_access_tokens)])
            if pos_orders:
                orders = Order.search(
                    [("pos_order_id", "in", pos_orders.ids)],
                    order="create_date desc, id desc",
                )

        token_record = False
        room = False
        if room_service_token:
            token_record = request.env["hotel.room.service.room.token"].sudo().search(
                [("token", "=", room_service_token), ("active", "=", True)],
                limit=1,
            )
            room = token_record.room_id

        if not room and table_identifier:
            table = request.env["restaurant.table"].sudo().search([("identifier", "=", table_identifier)], limit=1)
            room = table.room_id if table else False

        if not room and token_record:
            room = token_record.room_id

        if room:
            orders |= Order.search(
                [("room_id", "=", room.id)], order="create_date desc, id desc", limit=1
            )
        elif token_record:
            orders |= Order.search(
                [("token_id", "=", token_record.id)], order="create_date desc, id desc", limit=1
            )
        return orders.sorted(lambda order: (order.create_date, order.id), reverse=True)

    @http.route("/room-service/pos-self/tracker/json", type="jsonrpc", auth="public", website=True)
    def room_service_pos_self_tracker_json(self, pos_order_access_tokens=None, room_service_token=None, table_identifier=None, **kw):
        Order = request.env["hotel.room.service.order"].sudo()
        orders = Order.browse()
        scope_room = False

        # A Room Service QR token is the authoritative browser-data boundary.  Never trust
        # POS access tokens supplied from local storage until they have been scoped to the
        # room token that was scanned for this request.
        token_record = False
        if room_service_token:
            token_record = request.env["hotel.room.service.room.token"].sudo().search(
                [("token", "=", room_service_token), ("active", "=", True)], limit=1
            )
        if token_record:
            scope_room = token_record.room_id
            orders = Order.search(
                [("token_id", "=", token_record.id)], order="create_date desc, id desc"
            )
        elif table_identifier:
            table = request.env["restaurant.table"].sudo().search(
                [("identifier", "=", table_identifier)], limit=1
            )
            scope_room = table.room_id if table else False
            if scope_room:
                orders = Order.search(
                    [("room_id", "=", scope_room.id)], order="create_date desc, id desc"
                )
        elif pos_order_access_tokens:
            # Retain the generic POS-self tracker behavior outside a Room Service QR session.
            orders = self._get_latest_room_service_order_for_pos_self(
                pos_order_access_tokens=pos_order_access_tokens,
            )

        trackers_by_pos_token = {}
        latest = False
        for order in orders:
            payload = self._get_tracker_payload(order)
            if order.pos_order_id.access_token:
                trackers_by_pos_token[order.pos_order_id.access_token] = payload
            if not latest:
                latest = payload
        return {
            "has_order": bool(orders),
            "latest": latest or {},
            "orders": trackers_by_pos_token,
            "allowed_pos_order_tokens": list(trackers_by_pos_token),
            "room": scope_room.name if scope_room else "",
        }

    def _get_room_status_payload(self):
        Room = request.env["hotel.room"].sudo()
        Reservation = request.env["hotel.reservation"].sudo()
        Order = request.env["hotel.room.service.order"].sudo()
        order_labels = dict(Order._fields["state"].selection)
        biz_date = request.env.company.hotel_business_date or fields.Date.context_today(request.env.user)

        rooms = Room.search([], order="zone_id, floor_id, name")
        active_orders = Order.search(
            [("room_id", "in", rooms.ids), ("state", "in", self.ROOM_STATUS_ACTIVE_STATES)],
            order="create_date desc, id desc",
        )
        order_by_room = {}
        for order in active_orders:
            if order.room_id.id not in order_by_room:
                order_by_room[order.room_id.id] = order

        inhouse_reservations = Reservation.search(
            [
                ("room_id", "in", rooms.ids),
                ("state", "in", ["checkin", "checkout_hold"]),
                ("checkin_date", "<=", biz_date),
                ("company_id", "in", request.env.companies.ids),
            ],
            order="id desc",
        )
        reservation_by_room = {}
        for reservation in inhouse_reservations:
            if reservation.room_id.id not in reservation_by_room:
                reservation_by_room[reservation.room_id.id] = reservation

        rooms_data = []
        zones = {}
        floors = {}
        for room in rooms:
            order = order_by_room.get(room.id)
            reservation = reservation_by_room.get(room.id)
            zone_name = room.zone_id.name or "No Building"
            floor_name = room.floor_id.display_name or room.floor_id.name or "No Floor"
            zones[zone_name] = zone_name
            floors[floor_name] = floor_name
            rooms_data.append(
                {
                    "id": room.id,
                    "number": room.name or "",
                    "type": room.room_type_id.name or "",
                    "zone": zone_name,
                    "floor": floor_name,
                    "guest": reservation.partner_id.name if reservation else "",
                    "has_order": bool(order),
                    "order_id": order.id if order else False,
                    "order_name": order.name if order else "",
                    "order_status": order_labels.get(order.state, order.state) if order else "",
                    "order_state": order.state if order else "",
                    "order_url": "/web#id=%s&model=hotel.room.service.order&view_type=form" % order.id if order else "",
                    "room_orders_url": "/web#model=hotel.room.service.order&view_type=list&domain=%s"
                    % json.dumps([["room_id", "=", room.id]]),
                }
            )
        return {
            "rooms": rooms_data,
            "zones": sorted(zones),
            "floors": sorted(floors),
            "summary": {
                "total": len(rooms_data),
                "ordered": len([room for room in rooms_data if room["has_order"]]),
                "no_order": len([room for room in rooms_data if not room["has_order"]]),
            },
        }

    @http.route("/room-service/room-status", type="http", auth="user")
    def room_service_room_status(self, **kw):
        payload = self._get_room_status_payload()
        return request.render(
            "hotel_room_service_qr.room_service_room_status",
            {
                "rooms_data_json": json.dumps(payload["rooms"]),
                "zones_json": json.dumps(payload["zones"]),
                "floors_json": json.dumps(payload["floors"]),
                "summary_json": json.dumps(payload["summary"]),
            },
        )

    @http.route("/room-service/room-status/json", type="jsonrpc", auth="user", methods=["POST"], csrf=True)
    def room_service_room_status_json(self, **kw):
        return self._get_room_status_payload()

    @http.route("/room-service/order-display/<int:order_id>/<string:action_name>", type="http", auth="user", methods=["POST"], csrf=True)
    def room_service_monitor_action(self, order_id, action_name, **post):
        order = request.env["hotel.room.service.order"].sudo().browse(order_id).exists()
        if not order:
            return request.not_found()
        if action_name == "accept":
            order.action_confirm_to_pos()
        elif action_name == "preparing":
            order.action_kitchen_preparing()
        elif action_name == "ready":
            order.action_kitchen_ready()
        elif action_name == "complete":
            order.action_guest_confirm_completed()
        return request.redirect("/room-service/order-display")

    @http.route("/room-service/order-display/json", type="jsonrpc", auth="user", methods=["POST"], csrf=True)
    def room_service_order_display_json(self, **kw):
        Order = request.env["hotel.room.service.order"].sudo()
        self._reconcile_monitor_kitchen_orders()
        state_labels = dict(Order._fields["state"].selection)
        now = fields.Datetime.now()

        orders = Order.search(
            [("state", "in", self.DISPLAY_STATES)],
            order="create_date asc, id asc",
        )
        summary = self._get_monitor_summary(orders)
        orders_data = []
        for order in orders:
            lines = []
            total_items = 0
            for line in order.line_ids:
                total_items += line.quantity
                lines.append({
                    'id': line.id,
                    'menu_item_id': line.menu_item_id.id,
                    'product_id': line.product_id.id,
                    'name': line.product_id.display_name or line.name,
                    'qty': line.quantity,
                    'price_unit': line.price_unit,
                    'subtotal': line.subtotal,
                    'note': line.note or '',
                })
            menu_items, menu_categories = self._get_monitor_menu_payload(order.outlet_id)
            wait_minutes = 0
            if order.create_date:
                wait_minutes = max(0, int((now - order.create_date).total_seconds() // 60))
            orders_data.append({
                'id': order.id,
                'number': self._get_monitor_order_number(order),
                'name': order.name,
                'room': order.room_number or '-',
                'guest': order.partner_id.name or '',
                'guest_phone': self._get_monitor_guest_phone(order),
                'state': order.state,
                'state_label': state_labels.get(order.state, order.state),
                'status_group': self._get_monitor_status_group(order.state),
                'date_utc': (order.create_date.isoformat() + 'Z') if order.create_date else '',
                'date_str': order.create_date.strftime("%Y-%m-%d %H:%M") if order.create_date else '',
                'time_str': order.create_date.strftime("%I:%M %p") if order.create_date else '',
                'wait_minutes': wait_minutes,
                'total_items': total_items,
                'total': order.total_amount,
                'lines': lines,
                'can_edit_items': order.state == 'draft',
                'menu_items': menu_items,
                'menu_categories': menu_categories,
                'note': order.guest_note or '',
                'payment': order.payment_method,
            })
        closed_sessions = []
        outlets = request.env["hotel.room.service.outlet"].sudo().search([("active", "=", True)])
        for outlet in outlets:
            if outlet.auto_create_pos_order and outlet.pos_config_id:
                session = request.env["pos.session"].sudo().search(
                    [("config_id", "=", outlet.pos_config_id.id), ("state", "=", "opened")],
                    limit=1,
                )
                if not session:
                    closed_sessions.append(outlet.name)

        return {
            "orders": orders_data,
            "summary": summary,
            "closed_sessions": closed_sessions,
        }

    @http.route("/room-service/order-display/edit-line/json", type="jsonrpc", auth="user", methods=["POST"], csrf=True)
    def room_service_monitor_edit_line_json(self, order_id, operation, line_id=None, menu_item_id=None, quantity=None, **post):
        order = request.env["hotel.room.service.order"].sudo().browse(int(order_id or 0)).exists()
        if not order:
            return {"success": False, "error": "Order not found."}
        if order.state != "draft":
            return {"success": False, "error": "Order items can only be edited before the order is accepted."}

        try:
            Line = request.env["hotel.room.service.order.line"].sudo()
            if operation == "update_qty":
                line = Line.browse(int(line_id or 0)).exists()
                if not line or line.order_id.id != order.id:
                    return {"success": False, "error": "Order line not found."}
                qty = float(quantity or 0)
                if qty <= 0:
                    line.unlink()
                else:
                    line.write({"quantity": qty})
            elif operation == "remove":
                line = Line.browse(int(line_id or 0)).exists()
                if not line or line.order_id.id != order.id:
                    return {"success": False, "error": "Order line not found."}
                line.unlink()
            elif operation == "add":
                menu_item = request.env["hotel.room.service.menu.item"].sudo().browse(int(menu_item_id or 0)).exists()
                if not menu_item or not menu_item.active or menu_item.outlet_id.id != order.outlet_id.id:
                    return {"success": False, "error": "Menu item not found for this outlet."}
                qty = float(quantity or 1)
                if qty <= 0:
                    return {"success": False, "error": "Quantity must be greater than zero."}
                existing = order.line_ids.filtered(lambda line: line.menu_item_id.id == menu_item.id)[:1]
                if existing:
                    existing.write({"quantity": existing.quantity + qty})
                else:
                    Line.create({
                        "order_id": order.id,
                        "menu_item_id": menu_item.id,
                        "product_id": menu_item.product_id.id,
                        "name": menu_item.name or menu_item.product_id.display_name,
                        "quantity": qty,
                        "price_unit": menu_item.price,
                    })
            elif operation == "change":
                line = Line.browse(int(line_id or 0)).exists()
                if not line or line.order_id.id != order.id:
                    return {"success": False, "error": "Order line not found."}
                menu_item = request.env["hotel.room.service.menu.item"].sudo().browse(int(menu_item_id or 0)).exists()
                if not menu_item or not menu_item.active or menu_item.outlet_id.id != order.outlet_id.id:
                    return {"success": False, "error": "Menu item not found for this outlet."}
                qty = float(quantity or line.quantity or 1)
                if qty <= 0:
                    return {"success": False, "error": "Quantity must be greater than zero."}
                line.write({
                    "menu_item_id": menu_item.id,
                    "product_id": menu_item.product_id.id,
                    "name": menu_item.name or menu_item.product_id.display_name,
                    "quantity": qty,
                    "price_unit": menu_item.price,
                })
            else:
                return {"success": False, "error": "Unsupported edit operation."}
            return {"success": True}
        except Exception as e:
            return {"success": False, "error": str(e)}

    @http.route("/room-service/order-display/action/json", type="jsonrpc", auth="user", methods=["POST"], csrf=True)
    def room_service_monitor_action_json(self, order_id, action_name, **post):
        order = request.env["hotel.room.service.order"].sudo().browse(order_id).exists()
        if not order:
            return {"success": False, "error": "Order not found."}
        try:
            if action_name == "accept":
                order.action_confirm_to_pos()
            elif action_name == "preparing":
                order.action_kitchen_preparing()
            elif action_name == "ready":
                order.action_kitchen_ready()
            elif action_name == "complete":
                order.action_guest_confirm_completed()
            return {"success": True}
        except Exception as e:
            return {"success": False, "error": str(e)}

    @http.route("/hotel/room-service/<string:reservation_token>", type="http", auth="public", website=True)
    def room_service_from_booking(self, reservation_token, **kw):
        """Allow guests to access room service directly from their booking confirmation page."""
        reservation = request.env["hotel.reservation"].sudo().search(
            [("access_token", "=", reservation_token)], limit=1
        )
        if not reservation:
            return self._render_error("Reservation not found. Please check your booking link.", status=404)

        if not reservation.room_id:
            return self._render_error("No room is assigned to this reservation yet. Please contact the front desk.")

        # Find the room's QR token
        token_record = request.env["hotel.room.service.room.token"].sudo().search(
            [("room_id", "=", reservation.room_id.id), ("active", "=", True)], limit=1
        )
        if not token_record:
            return self._render_error(
                "Room service is not yet configured for this room. Please contact the front desk."
            )

        # Redirect to the standard room-service menu URL
        return request.redirect("/room-service/%s" % token_record.token)

    @http.route("/room-service/<string:token>", type="http", auth="public", website=True)
    def room_service_menu(self, token, **kw):
        token_record = self._get_token_record(token)
        if not token_record:
            return self._render_error("This room service QR code is invalid or inactive.", status=404)

        reservation = token_record._get_active_reservation()
        if not reservation:
            return self._render_error("No active in-house guest was found for this room. Please contact Front Desk.")

        # --- Find the POS config linked to a room service outlet ---
        outlet = request.env["hotel.room.service.outlet"].sudo().search(
            [("active", "=", True), ("pos_config_id", "!=", False)], limit=1
        )
        if not outlet:
            # Fallback: try any active outlet and trigger config setup
            outlet = request.env["hotel.room.service.outlet"].sudo().search(
                [("active", "=", True)], limit=1
            )
            if outlet:
                try:
                    outlet._ensure_pos_self_order_config()
                    outlet = request.env["hotel.room.service.outlet"].sudo().browse(outlet.id)
                except Exception:
                    pass

        if not outlet or not outlet.pos_config_id:
            return self._render_error(
                "Room service ordering is not yet configured. Please contact the front desk."
            )

        pos_config = outlet.pos_config_id.sudo()

        # --- Ensure this room has a POS table and get its identifier ---
        try:
            table = token_record.sudo()._ensure_pos_table(pos_config)
        except Exception:
            table = token_record.table_id

        # --- Build the pos_self_order URL and redirect ---
        params = []
        if pos_config.access_token:
            params.append("access_token=%s" % pos_config.access_token)
        if table and table.identifier:
            params.append("table_identifier=%s" % table.identifier)
        params.append("room_service_token=%s" % token_record.token)

        redirect_url = "/pos-self/%s?%s" % (
            pos_config.id,
            "&".join(params),
        )
        return request.redirect(redirect_url)

    @http.route("/room-service/<string:token>/review", type="http", auth="public", website=True, methods=["POST"], csrf=True)
    def room_service_review(self, token, **post):
        token_record = self._get_token_record(token)
        if not token_record:
            return self._render_error("This room service QR code is invalid or inactive.", status=404)

        reservation = token_record._get_active_reservation()
        if not reservation:
            return self._render_error("No active in-house guest was found for this room. Please contact Front Desk.")

        selected_lines = []
        outlet = request.env["hotel.room.service.outlet"].sudo()
        outlets = request.env["hotel.room.service.outlet"].sudo().search([("active", "=", True)])
        for candidate_outlet in outlets:
            allowed_products = candidate_outlet._get_pos_menu_products()
            for product in allowed_products:
                field_key = "%s_%s" % (candidate_outlet.id, product.id)
                raw_qty = post.get("qty_%s" % field_key)
                try:
                    qty = float(raw_qty or 0)
                except ValueError:
                    qty = 0
                if qty <= 0:
                    continue
                if not outlet:
                    outlet = candidate_outlet
                if candidate_outlet != outlet:
                    return self._render_error("Please order from one outlet at a time.")
                selected_lines.append(
                    (
                        product,
                        qty,
                        candidate_outlet._get_pos_product_price(product, qty),
                        (post.get("note_%s" % field_key) or "").strip(),
                    )
                )

        if not selected_lines:
            return self._render_error("Please select at least one item before reviewing your order.")

        order = request.env["hotel.room.service.order"].sudo().create(
            {
                "token_id": token_record.id,
                "reservation_id": reservation.id,
                "outlet_id": outlet.id,
                "payment_method": post.get("payment_method") if post.get("payment_method") in ["bill_to_room", "pay_at_pos"] else "bill_to_room",
                "guest_note": (post.get("guest_note") or "").strip(),
                "line_ids": [
                    (
                        0,
                        0,
                        {
                            "product_id": product.id,
                            "name": product.display_name,
                            "quantity": qty,
                            "price_unit": price,
                            "note": note,
                        },
                    )
                    for product, qty, price, note in selected_lines
                ],
            }
        )
        return request.render("hotel_room_service_qr.room_service_review", {"order": order})

    @http.route("/room-service/order/<string:access_token>/confirm", type="http", auth="public", website=True, methods=["POST"], csrf=True)
    def room_service_confirm(self, access_token, **post):
        order = request.env["hotel.room.service.order"].sudo().search([("access_token", "=", access_token)], limit=1)
        if not order:
            return self._render_error("Order not found.", status=404)
        order.action_confirm_and_send()
        return request.redirect("/room-service/order/%s/status" % order.access_token)

    @http.route("/room-service/order/<string:access_token>/cancel", type="http", auth="public", website=True, methods=["POST"], csrf=True)
    def room_service_cancel(self, access_token, **post):
        order = request.env["hotel.room.service.order"].sudo().search([("access_token", "=", access_token)], limit=1)
        if not order:
            return self._render_error("Order not found.", status=404)
        order.action_cancel_before_pos()
        return request.render("hotel_room_service_qr.room_service_cancelled", {"order": order})

    @http.route("/room-service/order/<string:access_token>/status", type="http", auth="public", website=True)
    def room_service_status(self, access_token, **kw):
        order = request.env["hotel.room.service.order"].sudo().search([("access_token", "=", access_token)], limit=1)
        if not order:
            return self._render_error("Order not found.", status=404)
        return request.render("hotel_room_service_qr.room_service_status", {"order": order})

    @http.route("/room-service/order/<string:access_token>/status/json", type="jsonrpc", auth="public", website=True)
    def room_service_status_json(self, access_token, **kw):
        order = request.env["hotel.room.service.order"].sudo().search([("access_token", "=", access_token)], limit=1)
        if not order:
            return {"error": "Order not found"}
        return {
            "state": order.state,
            "state_label": dict(order._fields['state'].selection).get(order.state, order.state),
            "last_error": order.last_error or "",
            "updated_at": order.write_date.strftime("%Y-%m-%d %H:%M:%S") if order.write_date else "",
            "updated_at_display": order.write_date.strftime("%b %d, %I:%M %p") if order.write_date else "",
        }

    @http.route("/room-service/order/<string:access_token>/completed", type="http", auth="public", website=True, methods=["POST"], csrf=True)
    def room_service_completed(self, access_token, **post):
        order = request.env["hotel.room.service.order"].sudo().search([("access_token", "=", access_token)], limit=1)
        if not order:
            return self._render_error("Order not found.", status=404)
        order.action_guest_confirm_completed()
        return request.redirect("/room-service/order/%s/status" % order.access_token)
