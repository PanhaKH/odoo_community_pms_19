# -*- coding: utf-8 -*-
from odoo import models, fields, api, _
from odoo.exceptions import UserError

class RestaurantTable(models.Model):
    _inherit = 'restaurant.table'

    room_id = fields.Many2one('hotel.room', string="Room", ondelete="cascade")

    @api.depends('room_id', 'room_id.name', 'table_number', 'floor_id')
    def _compute_display_name(self):
        for table in self:
            if table.room_id:
                table.display_name = _("Room %s") % table.room_id.name
            else:
                table.display_name = f"{table.floor_id.name}, {table.table_number}"


class PosConfig(models.Model):
    _inherit = "pos.config"

    hide_in_pos = fields.Boolean(string="Hide in POS Dashboard", default=False)

    @api.model
    def _search(self, domain, offset=0, limit=None, order=None, *, active_test=True, bypass_access=False):
        if self.env.context.get('from_room_service'):
            outlets = self.env['hotel.room.service.outlet'].sudo().search([('active', '=', True)])
            pos_config_ids = outlets.mapped('pos_config_id').ids
            # Safely build domain: convert to list first to avoid double-wrapping a Domain object
            base_domain = fields.Domain(list(domain) if domain else [])
            domain = base_domain & fields.Domain([('id', 'in', pos_config_ids)])
        return super()._search(domain, offset=offset, limit=limit, order=order, active_test=active_test, bypass_access=bypass_access)

    def notify_synchronisation(self, session_id, device_identifier, records={}):
        if self.env.context.get('skip_pos_notification'):
            return False
        return super().notify_synchronisation(session_id, device_identifier, records)

    def read_config_open_orders(self, domain, record_ids=[]):
        # Make a mutable copy to avoid modifying the caller's dict
        domain = dict(domain or {})
        if domain and "pos.order" in domain:
            domain["pos.order"] = fields.Domain(list(domain["pos.order"]) if domain["pos.order"] else []) & fields.Domain([("is_room_service_pending", "=", False)])
        return super().read_config_open_orders(domain, record_ids)



class PosOrder(models.Model):
    _inherit = 'pos.order'

    is_room_service_pending = fields.Boolean(string="Room Service Pending", default=False)
    is_posted_to_room = fields.Boolean(compute="_compute_is_posted_to_room", string="Is Posted to Room")

    def _compute_is_posted_to_room(self):
        for order in self:
            # Check if there is a room service order linked to this POS order
            rs_order = self.env['hotel.room.service.order'].sudo().search([('pos_order_id', '=', order.id)], limit=1)
            if rs_order and rs_order._is_posted_to_room():
                order.is_posted_to_room = True
                continue
            # Also check if it's already posted directly on the reservation folio
            if order.hotel_reservation_id and order.hotel_reservation_id.sale_order_id:
                ref = order.pos_reference or order.name
                duplicate_line = self.env['sale.order.line'].sudo().search_count([
                    ('order_id', '=', order.hotel_reservation_id.sale_order_id.id),
                    ('hotel_reservation_id', '=', order.hotel_reservation_id.id),
                    ('name', 'in', [f"Restaurant Bill: {ref}", f"Room Service: {ref}"]),
                ])
                if duplicate_line > 0:
                    order.is_posted_to_room = True
                    continue
            order.is_posted_to_room = False

    @api.model
    def _load_pos_data_read(self, records, config):
        res = super()._load_pos_data_read(records, config)
        for record_dict in res:
            record_id = record_dict.get('id')
            if record_id:
                record = records.browse(record_id)
                record_dict['is_posted_to_room'] = record.is_posted_to_room
        return res

    @api.model
    def _load_pos_data_domain(self, data, config):
        domain = super()._load_pos_data_domain(data, config)
        return domain + [('is_room_service_pending', '=', False)]

    @api.model
    def read_pos_orders(self, domain=False):
        domain = list(domain or [])
        domain.append(('is_room_service_pending', '=', False))
        return super().read_pos_orders(domain)

    @api.model
    def get_details(self, shop_id, *args, **kwargs):
        """Reconcile Room Service links before the Kitchen Display reads its counters."""
        room_orders = self.env['hotel.room.service.order'].sudo().search([
            ('pos_order_id.config_id', '=', shop_id),
            ('state', 'in', [
                'confirmed', 'sent_pos', 'kitchen_preparing', 'kitchen_ready',
                'delivered', 'guest_confirmed', 'folio_posted', 'paid_pos', 'closed',
            ]),
        ])
        room_orders._reconcile_pos_kitchen_status()
        return super().get_details(shop_id, *args, **kwargs)

    @api.model
    def sync_from_ui(self, orders):
        is_room_service = False
        for order in orders:
            table_id = order.get('table_id') or order.get('self_ordering_table_id')
            if table_id:
                table = self.env['restaurant.table'].sudo().browse(table_id)
                if table.exists() and table.room_id:
                    is_room_service = True
                    break
        if is_room_service:
            self = self.with_context(skip_pos_notification=True)
        return super().sync_from_ui(orders)

    def _send_notification(self, order_ids):
        visible_orders = order_ids.filtered(lambda order: not order.is_room_service_pending)
        if visible_orders:
            return super()._send_notification(visible_orders)
        return None

    @api.model
    def _process_order(self, order, existing_order):
        self = self.with_context(room_service_current_order_uuid=order.get('uuid'))
        pos_order_id = super()._process_order(order, existing_order)
        pos_order = self.browse(pos_order_id)

        # Check if the order is from self-ordering and linked to a room table
        if pos_order.source in ['mobile', 'kiosk'] and pos_order.self_ordering_table_id:
            table = pos_order.self_ordering_table_id
            if table.room_id:
                # Find the token record for this room
                token_rec = self.env['hotel.room.service.room.token'].sudo().search([
                    ('room_id', '=', table.room_id.id)
                ], limit=1)
                if token_rec:
                    reservation = token_rec._get_active_reservation()
                    if reservation:
                        # Find the corresponding Room Service Outlet
                        outlet = self.env['hotel.room.service.outlet'].sudo().search([
                            ('pos_config_id', '=', pos_order.config_id.id),
                            ('active', '=', True)
                        ], limit=1)
                        if not outlet:
                            outlet = self.env['hotel.room.service.outlet'].sudo().search([('active', '=', True)], limit=1)

                        is_paid = pos_order.amount_paid >= pos_order.amount_total if pos_order.amount_total > 0 else False
                        has_room_charge = any(p.payment_method_id.is_room_charge for p in pos_order.payment_ids)
                        pay_method = 'bill_to_room'
                        if (is_paid and not has_room_charge) or (pos_order.payment_ids and not has_room_charge):
                            pay_method = 'pay_at_pos'

                        auto_send_to_kitchen = bool(is_paid)

                        # Create the Room Service Order. Paid self-orders should go straight to POS/Kitchen;
                        # unpaid orders still wait for staff confirmation.
                        rs_order = self.env['hotel.room.service.order'].sudo().create({
                            'token_id': token_rec.id,
                            'reservation_id': reservation.id,
                            'outlet_id': outlet.id if outlet else False,
                            'pos_order_id': pos_order.id,
                            'state': 'kitchen_preparing' if auto_send_to_kitchen else 'draft',
                            'payment_method': pay_method,
                            'line_ids': [
                                (0, 0, {
                                    'product_id': line.product_id.id,
                                    'name': line.product_id.display_name,
                                    'quantity': line.qty,
                                    'price_unit': line.price_unit,
                                    'note': line.customer_note,
                                }) for line in pos_order.lines
                            ]
                        })

                        # Sync RSO name to POS floating_order_name and RS reference immediately on creation
                        tracking_name = f"{rs_order.name} / Room {table.room_id.name}"
                        pos_order.write({
                            'is_room_service_pending': not auto_send_to_kitchen,
                            'hotel_reservation_id': reservation.id,
                            'floating_order_name': tracking_name
                        })
                        if auto_send_to_kitchen:
                            rs_order._sync_pos_kitchen_status_from_room_service()
                            try:
                                pos_order.config_id.sudo().notify_synchronisation(
                                    pos_order.session_id.id,
                                    self.env.context.get('device_identifier', 0),
                                    {'pos.order': [pos_order.id]}
                                )
                            except Exception:
                                pass
                        rs_order.write({
                            'pos_reference': tracking_name
                        })

                        # Log integration success
                        log_message = (
                            _("Paid room service order created from POS self-order and sent to Kitchen.")
                            if auto_send_to_kitchen else
                            _("Pending room service order created from POS self-order with tracking name.")
                        )
                        rs_order._log_adapter("system", "success", log_message)
        return pos_order_id

    def _create_hotel_charge(self, reservation, amount, ref):
        pos_order = self.env['pos.order']
        current_uuid = self.env.context.get('room_service_current_order_uuid')
        if current_uuid:
            pos_order = self.env['pos.order'].sudo().search([('uuid', '=', current_uuid)], limit=1)

        rs_order = self.env['hotel.room.service.order'].sudo()
        if pos_order:
            rs_order = rs_order.search([('pos_order_id', '=', pos_order.id)], limit=1)

        already_posted = False
        if rs_order and rs_order._is_posted_to_room():
            already_posted = True

        if not already_posted and reservation.sale_order_id:
            duplicate_line = self.env['sale.order.line'].sudo().search([
                ('order_id', '=', reservation.sale_order_id.id),
                ('hotel_reservation_id', '=', reservation.id),
                ('name', 'in', [f"Restaurant Bill: {ref}", f"Room Service: {ref}"]),
            ], limit=1)
            if duplicate_line:
                already_posted = True

        if already_posted:
            if rs_order:
                vals = {
                    'pms_sync_state': 'posted',
                    'pms_folio_id': reservation.sale_order_id.id if reservation.sale_order_id else False,
                    'folio_posted_at': fields.Datetime.now() if not rs_order.folio_posted_at else rs_order.folio_posted_at,
                    'last_error': False,
                }
                if rs_order.state in ['delivered', 'guest_confirmed', 'paid_pos', 'closed']:
                    vals.update({
                        'state': 'folio_posted',
                        'closed_at': fields.Datetime.now() if not rs_order.closed_at else rs_order.closed_at,
                    })
                rs_order.write(vals)
                folio_name = reservation.sale_order_id.name or str(reservation.sale_order_id.id)
                rs_order.message_post(body=_("Room Service Order marked as posted (already posted on folio %s).") % folio_name)
            # Skip posting again, return False (prevent double charge)
            return False

        result = super()._create_hotel_charge(reservation, amount, ref)

        if rs_order:
            vals = {
                'pms_sync_state': 'posted',
                'pms_folio_id': reservation.sale_order_id.id if reservation.sale_order_id else False,
                'folio_posted_at': fields.Datetime.now(),
                'last_error': False,
            }
            if rs_order.state in ['delivered', 'guest_confirmed', 'paid_pos', 'closed']:
                vals.update({
                    'state': 'folio_posted',
                    'closed_at': fields.Datetime.now(),
                })
            rs_order.write(vals)
            rs_order._log_adapter("pos", "success", _("POS posted the room charge; Room Service marked it as already posted."))
            folio_name = reservation.sale_order_id.name or str(reservation.sale_order_id.id)
            rs_order.message_post(body=_("POS validated and posted the room service charge to Room Folio (Folio: %s) successfully.") % folio_name)
        return result

    def write(self, vals):
        res = super(PosOrder, self).write(vals)
        if not self.env.context.get('room_service_skip_rs_sync') and ('order_status' in vals or 'state' in vals):
            for order in self:
                rs_order = self.env['hotel.room.service.order'].sudo().search([('pos_order_id', '=', order.id)], limit=1)
                if rs_order and rs_order.state not in ['closed', 'cancelled']:
                    if 'order_status' in vals:
                        new_status = vals['order_status']
                        if new_status == 'draft':
                            if rs_order.state in ['confirmed', 'sent_pos', 'pos_failed']:
                                rs_order.with_context(room_service_skip_pos_kitchen_sync=True).write({'state': 'kitchen_preparing'})
                        elif new_status == 'waiting':
                            rs_order.with_context(room_service_skip_pos_kitchen_sync=True).write({'state': 'kitchen_ready'})
                        elif new_status == 'ready':
                            if rs_order.state != 'delivered':
                                rs_order.with_context(room_service_skip_pos_kitchen_sync=True).write({'state': 'delivered'})
                        elif new_status == 'cancel':
                            rs_order.with_context(room_service_skip_pos_kitchen_sync=True).write({'state': 'cancelled', 'closed_at': fields.Datetime.now()})
                    if vals.get('state') == 'cancel':
                        rs_order.with_context(room_service_skip_pos_kitchen_sync=True).write({'state': 'cancelled', 'closed_at': fields.Datetime.now()})
                    elif vals.get('state') in ['paid', 'done'] and rs_order.state in ['delivered', 'guest_confirmed']:
                        if rs_order.payment_method == 'pay_at_pos':
                            rs_order.with_context(room_service_skip_pos_kitchen_sync=True).write({'state': 'paid_pos', 'closed_at': fields.Datetime.now()})
                        elif rs_order.payment_method == 'bill_to_room':
                            has_room_charge = any(p.payment_method_id.is_room_charge for p in order.payment_ids)
                            if not has_room_charge:
                                rs_order.with_context(room_service_skip_pos_kitchen_sync=True).write({'state': 'paid_pos', 'closed_at': fields.Datetime.now(), 'pms_sync_state': 'not_required'})
        return res


class HotelRoomServiceOrder(models.Model):
    _inherit = 'hotel.room.service.order'

    log_ids = fields.One2many(
        "hotel.room.service.integration.log",
        "order_id",
        string="Integration Logs",
        readonly=True,
    )

    def write(self, vals):
        res = super().write(vals)
        if 'state' in vals and not self.env.context.get('room_service_skip_pos_kitchen_sync'):
            self._sync_pos_kitchen_status_from_room_service()
        return res

    def action_send_to_pos(self):
        res = super().action_send_to_pos()
        self._reconcile_pos_kitchen_status()
        return res

    def _get_pos_kitchen_status_from_room_service_state(self):
        self.ensure_one()
        if self.state in ['confirmed', 'sent_pos', 'pos_failed', 'kitchen_preparing']:
            return 'draft'
        if self.state == 'kitchen_ready':
            return 'waiting'
        if self.state in ['delivered', 'guest_confirmed', 'folio_posted', 'paid_pos', 'closed']:
            if self.state in ['folio_posted', 'paid_pos', 'closed'] and self.pos_order_id:
                kitchen = self.env['kitchen.screen'].sudo().search([
                    ('pos_config_id', '=', self.pos_order_id.config_id.id)
                ], limit=1)
                kitchen_lines = self.pos_order_id.lines
                if kitchen and kitchen.pos_categ_ids:
                    kitchen_lines = kitchen_lines.filtered(
                        lambda line: line.product_id.pos_categ_ids and any(
                            category.id in kitchen.pos_categ_ids.ids
                            for category in line.product_id.pos_categ_ids
                        )
                    )
                elif kitchen:
                    # A kitchen without category restrictions handles all lines.
                    kitchen_lines = self.pos_order_id.lines
                if kitchen_lines:
                    statuses = set(kitchen_lines.mapped('order_status'))
                    if statuses and statuses != {'ready'}:
                        if 'waiting' in statuses or 'ready' in statuses:
                            return 'waiting'
                        return 'draft'
            return 'ready'
        if self.state == 'cancelled':
            return 'cancel'
        return False

    def _sync_pos_kitchen_status_from_room_service(self):
        for order in self:
            pos_order = order.pos_order_id.sudo()
            if not pos_order or 'order_status' not in pos_order._fields:
                continue
            kitchen_status = order._get_pos_kitchen_status_from_room_service_state()
            if not kitchen_status:
                continue
            vals = {'order_status': kitchen_status}
            if 'is_cooking' in pos_order._fields:
                vals['is_cooking'] = kitchen_status != 'cancel'
            kitchen = self.env['kitchen.screen'].sudo().search([
                ('pos_config_id', '=', pos_order.config_id.id)
            ], limit=1)
            kitchen_lines = pos_order.lines
            if kitchen:
                if kitchen.pos_categ_ids:
                    kitchen_lines = kitchen_lines.filtered(
                        lambda line: line.product_id.pos_categ_ids and any(
                            category.id in kitchen.pos_categ_ids.ids
                            for category in line.product_id.pos_categ_ids
                        )
                    )
                else:
                    # A kitchen without category restrictions handles all lines.
                    kitchen_lines = pos_order.lines
                if kitchen_status not in ['cancel', 'ready'] and not kitchen_lines:
                    continue
            order_vals = {
                field_name: value
                for field_name, value in vals.items()
                if pos_order[field_name] != value
            }
            if order_vals:
                pos_order.with_context(room_service_skip_rs_sync=True).write(order_vals)
            line_vals = {'order_status': kitchen_status}
            if 'is_cooking' in pos_order.lines._fields:
                line_vals['is_cooking'] = kitchen_status != 'cancel'
            line_changed = False
            if kitchen_lines:
                for line in kitchen_lines:
                    changed_line_vals = {
                        field_name: value
                        for field_name, value in line_vals.items()
                        if line[field_name] != value
                    }
                    if changed_line_vals:
                        line.with_context(room_service_skip_rs_sync=True).write(changed_line_vals)
                        line_changed = True
            if line_changed and not order_vals:
                self.env['bus.bus']._sendone(
                    f'pos_order_created_{pos_order.config_id.id}',
                    'notification',
                    {
                        'res_model': 'pos.order',
                        'message': 'pos_order_updated',
                        'order_id': pos_order.id,
                        'config_id': pos_order.config_id.id,
                    },
                )

    def _reconcile_pos_kitchen_status(self):
        """Repair drift and align Room Service stages with Kitchen Display stages."""
        for order in self:
            order._sync_pos_kitchen_status_from_room_service()
            pos_order = order.pos_order_id.sudo()
            if (
                pos_order
                and order.state in ['confirmed', 'sent_pos']
                and not pos_order.is_room_service_pending
                and pos_order.is_cooking
                and pos_order.order_status == 'draft'
            ):
                # Once the order is visible in Kitchen Display's Cooking column, expose
                # the same stage in the Room Service monitor.
                order.with_context(room_service_skip_pos_kitchen_sync=True).write({
                    'state': 'kitchen_preparing',
                })
        return True

    def _post_to_pms_folio(self):
        res = super()._post_to_pms_folio()
        for order in self:
            if order.pms_sync_state == 'posted':
                folio_name = order.pms_folio_id.name if order.pms_folio_id else str(order.pms_folio_id.id)
                order.message_post(body=_("Room Service Order bill posted to Room Folio (Folio: %s) successfully.") % folio_name)
        return res

    def _is_posted_to_room(self):
        self.ensure_one()
        res = super()._is_posted_to_room()
        if res:
            return True
        if self.reservation_id and self.reservation_id.sale_order_id:
            ref = self.pos_reference or self.name
            duplicate_line = self.env['sale.order.line'].sudo().search_count([
                ('order_id', '=', self.reservation_id.sale_order_id.id),
                ('hotel_reservation_id', '=', self.reservation_id.id),
                ('name', 'in', [
                    f"Restaurant Bill: {ref}",
                    f"Room Service: {ref}",
                    f"Room Service: {self.name}",
                    f"Restaurant Bill: {self.name}"
                ]),
            ])
            if duplicate_line > 0:
                return True
        return False

    def action_confirm_and_send(self):
        for order in self:
            if order._is_posted_to_room():
                raise UserError(_("Already posted to room."))
        return super().action_confirm_and_send()

    def action_sync_to_pms(self):
        for order in self:
            if order._is_posted_to_room():
                raise UserError(_("Already posted to room."))
        return super().action_sync_to_pms()

    def action_confirm_to_pos(self):
        for order in self:
            if order._is_posted_to_room():
                raise UserError(_("Already posted to room."))
            if order.pos_order_id and order.pos_order_id.is_room_service_pending:
                pos_order = order.pos_order_id
                # Confirming the pending self-order to POS
                order.write({'state': 'confirmed'})
                # Sync RSO name to POS floating_order_name for tracking and make it visible in POS cashier as draft
                pos_order.sudo().write({
                    'is_room_service_pending': False,
                    'floating_order_name': f"{order.name} / Room {order.room_id.name}"
                })
                pos_order.config_id.notify_synchronisation(
                    pos_order.session_id.id,
                    self.env.context.get('device_identifier', 0),
                    {'pos.order': [pos_order.id]}
                )
                # The accepted POS order is immediately visible in the Kitchen
                # Display's Cooking stage, so expose the same state everywhere.
                ref = pos_order.name if pos_order.name != '/' else pos_order.floating_order_name
                order.write({'state': 'kitchen_preparing', 'pos_reference': ref})
                order._log_adapter("system", "success", _("Self-order confirmed by staff and sent to POS as draft order (active on screen)."))
            else:
                if order.state == 'draft':
                    order.write({'state': 'confirmed'})
                if order.outlet_id.auto_create_pos_order:
                    order.action_send_to_pos()
                else:
                    order.write({'state': 'kitchen_preparing'})
                    order._log_adapter("system", "success", _("Room Service order accepted for kitchen preparation without POS draft order."))
        return True

    def action_cancel_before_pos(self):
        res = super().action_cancel_before_pos()
        for order in self:
            if order.pos_order_id and order.pos_order_id.state == 'draft':
                order.pos_order_id.sudo().write({'state': 'cancel'})
                if hasattr(order.pos_order_id, 'order_status'):
                    order.pos_order_id.sudo().write({'order_status': 'cancel'})
        return res
