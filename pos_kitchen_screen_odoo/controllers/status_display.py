# -*- coding: utf-8 -*-
import json
from datetime import timedelta

import pytz

from odoo import fields, http
from odoo.http import request


class PosKitchenStatusDisplay(http.Controller):
    """Customer-facing order status display for the POS kitchen screen."""

    @http.route("/pos/kitchen/status", type="http", auth="public", website=True)
    def kitchen_status_display(self, pos_config_id=None, **kwargs):
        kitchens = request.env["kitchen.screen"].sudo().search([])
        selected = self._safe_int(pos_config_id)
        if not selected and kitchens:
            selected = kitchens[0].pos_config_id.id
        return request.render(
            "pos_kitchen_screen_odoo.kitchen_status_display_page",
            {
                "kitchens": kitchens,
                "selected_pos_config_id": selected or 0,
            },
        )

    @http.route("/pos/kitchen/status/data", type="http", auth="public", csrf=False)
    def kitchen_status_display_data(self, pos_config_id=None, **kwargs):
        config_id = self._safe_int(pos_config_id)
        payload = self._get_status_payload(config_id)
        return request.make_response(
            json.dumps(payload),
            headers=[("Content-Type", "application/json")],
        )

    def _safe_int(self, value):
        try:
            return int(value or 0)
        except (TypeError, ValueError):
            return 0

    def _get_status_payload(self, config_id):
        Kitchen = request.env["kitchen.screen"].sudo()
        kitchen = Kitchen.search([("pos_config_id", "=", config_id)], limit=1)
        if not kitchen:
            kitchen = Kitchen.search([], limit=1)
            config_id = kitchen.pos_config_id.id if kitchen else 0
        if not kitchen:
            return {
                "kitchen": {},
                "almost_ready": [],
                "ready": [],
                "counts": {"almost_ready": 0, "ready": 0},
                "last_updated": fields.Datetime.now().isoformat(),
            }

        orders = request.env["pos.order"].sudo().search([
            ("config_id", "=", config_id),
            ("state", "!=", "cancel"),
            ("is_cooking", "=", True),
            ("order_status", "in", ["draft", "waiting", "ready"]),
        ], order="date_order asc")

        almost_ready = []
        ready = []
        for order in orders:
            item = self._serialize_order(order)
            if order.order_status == "waiting":
                ready.append(item)
            elif order.order_status == "draft":
                almost_ready.append(item)

        return {
            "kitchen": {
                "id": kitchen.id,
                "name": kitchen.sequence,
                "pos_config_id": kitchen.pos_config_id.id,
                "pos_name": kitchen.pos_config_id.name,
            },
            "almost_ready": almost_ready[:30],
            "ready": ready[:30],
            "counts": {
                "almost_ready": len(almost_ready),
                "ready": len(ready),
            },
            "last_updated": fields.Datetime.now().isoformat(),
        }

    def _serialize_order(self, order):
        user_tz = pytz.timezone(request.env.user.tz or "UTC")
        local_dt = pytz.utc.localize(order.date_order).astimezone(user_tz)
        wait = fields.Datetime.now() - order.date_order
        wait_minutes = max(0, int(wait.total_seconds() // 60))
        eta = local_dt + timedelta(minutes=int(order.avg_prepare_time or 0))
        return {
            "id": order.id,
            "name": order.name or order.pos_reference or str(order.id),
            "customer": order.partner_id.name or "",
            "table": order.table_id.name if order.table_id else "",
            "status": order.order_status,
            "time": local_dt.strftime("%H:%M"),
            "eta": eta.strftime("%H:%M"),
            "wait_minutes": wait_minutes,
        }
