import base64
import json
from string import Template

from markupsafe import escape

from odoo import http
from odoo.http import request
from odoo.tools import consteq
from odoo.tools.misc import file_path

from odoo.addons.eh_pos_kds_core.utils.brand import brand_anchor, brand_position


def _boot_blob(token, name, db_name=None):
    """The display boot config, carried only inside the brand element so the
    attribution is load bearing: remove it and the app has no token to load.
    """
    return base64.b64encode(json.dumps({"token": token, "name": name, "db": db_name}).encode()).decode()


class EhKdsBoardPage(http.Controller):
    """Serve the kitchen board page for a board access token.

    The brand mark is rendered into the page body server side, before any
    JavaScript runs. The token is the only secret, checked in constant time.
    """

    @http.route("/eh_kds/board/<token>", auth="public", type="http", website=False)
    def board_page(self, token, **kw):
        board = request.env["eh.kds.board"].sudo().search(
            [("access_token", "=", token)], limit=1
        )
        if not board or not consteq(board.access_token, token):
            raise request.not_found()
        # The token lives only in the brand element boot blob, not in session,
        # so the brand mark is load bearing for the app.
        session_info = request.env["ir.http"].session_info()
        return request.render(
            "eh_pos_kds.board_index",
            {
                "session_info": session_info,
                "brand": brand_anchor(),
                "brand_pos": brand_position(request.env),
                "boot": _boot_blob(board.access_token, board.name, request.db),
            },
        )

    @http.route("/eh_kds/status/<token>", auth="public", type="http", website=False)
    def status_page(self, token, **kw):
        board = self._board(token)
        data = board._kds_status_data()
        html = Template("""
<!DOCTYPE html>
<html>
<head>
    <meta charset="utf-8"/>
    <meta name="viewport" content="width=device-width, initial-scale=1"/>
    <meta http-equiv="refresh" content="1"/>
    <title>Order Status</title>
    <style>
        body { margin: 0; font-family: -apple-system, BlinkMacSystemFont, "Segoe UI", sans-serif; background: #101827; color: #f8fafc; }
        .wrap { min-height: 100vh; padding: 40px; box-sizing: border-box; display: grid; grid-template-rows: auto 1fr auto; gap: 28px; }
        header { display: flex; align-items: center; justify-content: space-between; gap: 24px; }
        h1 { margin: 0; font-size: 44px; font-weight: 750; }
        .now { color: #fbbf24; font-size: 28px; font-weight: 700; }
        .grid { display: grid; grid-template-columns: 1fr 1fr; gap: 24px; }
        section { background: rgba(255, 255, 255, 0.08); border: 1px solid rgba(255, 255, 255, 0.12); border-radius: 12px; padding: 24px; overflow: hidden; }
        h2 { margin: 0 0 20px; font-size: 26px; color: #cbd5e1; }
        .orders {
            display: grid;
            grid-template-columns: repeat(auto-fill, minmax(126px, 1fr));
            gap: 12px;
            align-items: start;
        }
        .order {
            width: 100%;
            max-width: 146px;
            min-height: 70px;
            border-radius: 12px;
            padding: 8px 10px;
            box-sizing: border-box;
            min-width: 0;
            justify-self: center;
            display: flex;
            align-items: center;
            justify-content: center;
            background: #3f4653;
            color: #f8fafc;
            box-shadow: 0 12px 28px rgba(0, 0, 0, 0.22), inset 0 1px 0 rgba(255, 255, 255, 0.08);
            font-size: clamp(22px, 2vw, 30px);
            line-height: 1;
            font-weight: 850;
            letter-spacing: 0;
            white-space: nowrap;
            overflow: hidden;
            text-overflow: ellipsis;
            transform-origin: center;
            animation: cardIn 260ms ease-out both;
            transition: transform 180ms ease, box-shadow 180ms ease, background 180ms ease;
            will-change: transform;
        }
        .order:hover {
            transform: translateY(-3px) scale(1.035);
            box-shadow: 0 18px 38px rgba(0, 0, 0, 0.32), inset 0 1px 0 rgba(255, 255, 255, 0.12);
        }
        .order--room {
            font-size: clamp(19px, 1.65vw, 24px);
            padding-left: 8px;
            padding-right: 8px;
        }
        .ready .order { background: #16a34a; color: white; }
        .serving .order { background: #2563eb; color: white; }
        .completed .order { background: #d1fae5; color: #14532d; opacity: 0.82; }
        .empty { color: #94a3b8; font-size: 22px; }
        footer { display: flex; align-items: center; justify-content: space-between; color: #94a3b8; font-size: 16px; }
        .brand { display: flex; align-items: center; gap: 10px; }
        .brand img { width: 32px; height: 32px; object-fit: contain; }
        @keyframes cardIn {
            from { opacity: 0; transform: translateY(10px) scale(0.96); }
            to { opacity: 1; transform: translateY(0) scale(1); }
        }
        @media (min-width: 1500px) {
            .orders { grid-template-columns: repeat(auto-fill, minmax(132px, 1fr)); gap: 12px; }
            .order { max-width: 150px; min-height: 74px; }
        }
        @media (max-width: 1100px) {
            .orders { grid-template-columns: repeat(auto-fill, minmax(118px, 1fr)); gap: 10px; }
            .order { min-height: 66px; font-size: clamp(20px, 2.7vw, 28px); }
            .order--room { font-size: clamp(18px, 2.35vw, 23px); }
        }
        @media (max-width: 800px) {
            .wrap { padding: 24px; }
            .grid { grid-template-columns: 1fr; }
            h1 { font-size: 34px; }
            .now { font-size: 22px; }
            .orders { grid-template-columns: repeat(auto-fill, minmax(108px, 1fr)); gap: 9px; }
            .order { max-width: none; min-height: 62px; font-size: clamp(19px, 5.2vw, 26px); }
            .order--room { font-size: clamp(17px, 4.4vw, 22px); }
        }
        @media (prefers-reduced-motion: reduce) {
            .order { animation: none; transition: none; }
            .order:hover { transform: none; }
        }
    </style>
</head>
<body>
    <div class="wrap">
        <header>
            <h1>Order Status</h1>
            <div class="now">Now Serving: $now_serving</div>
        </header>
        <main class="grid">
            <section>
                <h2>Preparing</h2>
                <div class="orders">$preparing</div>
            </section>
            <section class="ready">
                <h2>Ready</h2>
                <div class="orders">$ready</div>
            </section>
        </main>
        <footer>
            <span>$board_name</span>
            <span class="brand">$brand_img<span>$brand_name</span></span>
        </footer>
    </div>
</body>
</html>
""").substitute(
            board_name=escape(data["board"]["name"]),
            now_serving=escape(self._status_ref_label(data.get("now_serving") or "-")),
            preparing=self._status_orders(data.get("preparing", [])),
            ready=self._status_orders(data.get("ready", [])),
            brand_img=self._kitchen_brand_icon(),
            brand_name="Kitchen",
        )
        return request.make_response(html, headers=[("Content-Type", "text/html; charset=utf-8")])

    def _status_orders(self, orders):
        if not orders:
            return '<div class="empty">No orders</div>'
        return "".join(
            '<div class="order%s">%s</div>'
            % (
                " order--room" if self._status_order_label(order).startswith("Room ") else "",
                escape(self._status_order_label(order)),
            )
            for order in orders
        )

    def _status_order_label(self, order):
        return self._status_ref_label(order.get("ref") or "-")

    def _status_ref_label(self, ref):
        ref = (ref or "-").strip()
        marker = "Room "
        if marker in ref:
            room = ref.split(marker, 1)[1].strip()
            if room:
                return "%s%s" % (marker, room.split()[0])
        return ref

    def _kitchen_brand_icon(self):
        return """
<svg viewBox="0 0 64 64" aria-hidden="true" focusable="false" style="width:32px;height:32px;filter:drop-shadow(0 0 12px rgba(45,212,191,.24));">
    <defs>
        <linearGradient id="kdsStatusBrandGradient" x1="8" y1="8" x2="56" y2="56" gradientUnits="userSpaceOnUse">
            <stop offset="0" stop-color="#5AF06F"/>
            <stop offset="0.48" stop-color="#28D9D2"/>
            <stop offset="1" stop-color="#2386FF"/>
        </linearGradient>
    </defs>
    <rect x="6" y="6" width="52" height="52" rx="15" fill="#06101A" stroke="url(#kdsStatusBrandGradient)" stroke-width="3"/>
    <path d="M21 31c-4 0-7-3-7-7s3-7 7-7c1.5 0 3 .5 4.2 1.4C27 14.7 30.8 12 35 12c5.6 0 10.2 4 11.2 9.3.8-.2 1.6-.3 2.4-.3 4.1 0 7.4 3.3 7.4 7.4S52.7 36 48.6 36H47l-1.3 14H22.3L21 36z" fill="none" stroke="url(#kdsStatusBrandGradient)" stroke-width="3.4" stroke-linecap="round" stroke-linejoin="round"/>
    <path d="M29 31v8M35 30v9M41 31v8" stroke="url(#kdsStatusBrandGradient)" stroke-width="3.4" stroke-linecap="round"/>
    <path d="M20 45h28" stroke="#F8FAFC" stroke-width="3.4" stroke-linecap="round"/>
</svg>
"""

    def _board(self, token):
        board = request.env["eh.kds.board"].sudo().search(
            [("access_token", "=", token)], limit=1
        )
        if not board or not consteq(board.access_token, token):
            raise request.not_found()
        return board

    @http.route("/eh_kds/board/data", auth="public", type="jsonrpc")
    def board_data(self, token, **kw):
        """Full board snapshot for first paint and for reconnect."""
        return self._board(token)._kds_board_data()

    @http.route("/eh_kds/board/op", auth="public", type="jsonrpc")
    def board_op(self, token, action, card_ids, reason=None, to_index=None, **kw):
        """Token guarded write surface. The board page is public, so bumps come
        through here, not generic call_kw.

        The ``move`` action takes an absolute lane index so an offline replay is
        idempotent (re applying the same target is a no op).
        """
        board = self._board(token)
        cards = (
            request.env["eh.kds.card"].sudo().browse(card_ids).exists().filtered(
                lambda c: c.board_id == board
            )
        )
        if not cards:
            return {"ok": False, "reason": "no cards"}
        if action == "move" and to_index is not None:
            cards.move_to(int(to_index))
        elif action == "advance":
            cards.advance(1)
        elif action == "recall":
            cards.advance(-1)
        elif action == "void":
            cards.void(reason=reason)
        else:
            return {"ok": False, "reason": "unknown action"}
        return {"ok": True, "cards": [c._kds_payload() for c in cards.exists()]}

    @http.route("/eh_kds/board/stats", auth="public", type="jsonrpc")
    def board_stats(self, token, **kw):
        """Live analytics KPIs for the board metrics panel."""
        return self._board(token)._kds_stats()

    @http.route("/eh_kds/sw.js", auth="public", type="http")
    def service_worker(self, **kw):
        """Serve the board service worker from a broad scope so it can cache the
        board page. Best effort: the browser only uses it on a secure origin.
        """
        try:
            with open(file_path("eh_pos_kds/static/src/sw/sw.js")) as fp:
                content = fp.read()
        except (FileNotFoundError, ValueError):
            return request.not_found()
        return request.make_response(
            content,
            headers=[
                ("Content-Type", "application/javascript"),
                ("Service-Worker-Allowed", "/eh_kds/"),
            ],
        )
