# -*- coding: utf-8 -*-
from odoo import models, fields, api, _
from odoo.exceptions import UserError
from odoo.tools import float_is_zero

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
        """Compatibility hook for the legacy kitchen screen, if installed."""
        room_orders = self.env['hotel.room.service.order'].sudo().search([
            ('pos_order_id.config_id', '=', shop_id),
            ('state', 'in', [
                'confirmed', 'sent_pos', 'kitchen_preparing', 'kitchen_ready',
                'delivered', 'guest_confirmed', 'folio_posted', 'paid_pos', 'closed',
            ]),
        ])
        room_orders._reconcile_pos_kitchen_status()
        get_details = getattr(super(), 'get_details', None)
        if get_details:
            return get_details(shop_id, *args, **kwargs)
        return {"orders": [], "order_lines": []}

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

                        # Create the Room Service Order. Paid self-orders can go straight to kitchen queue;
                        # unpaid orders still wait for staff confirmation.
                        rs_order = self.env['hotel.room.service.order'].sudo().create({
                            'token_id': token_rec.id,
                            'reservation_id': reservation.id,
                            'outlet_id': outlet.id if outlet else False,
                            'pos_order_id': pos_order.id,
                            'state': 'sent_pos' if auto_send_to_kitchen else 'draft',
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
        if self.state in ['sent_pos', 'pos_failed']:
            return 'draft'
        if self.state == 'kitchen_preparing':
            return 'draft'
        if self.state == 'kitchen_ready':
            return 'waiting'
        if self.state in ['delivered', 'guest_confirmed', 'folio_posted', 'paid_pos', 'closed']:
            if (
                self.state in ['folio_posted', 'paid_pos', 'closed']
                and self.pos_order_id
                and 'kitchen.screen' in self.env.registry.models
                and 'order_status' in self.pos_order_id.lines._fields
            ):
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
                order._sync_eh_kds_status_from_room_service()
                continue
            else:
                kitchen_status = order._get_pos_kitchen_status_from_room_service_state()
                if not kitchen_status:
                    order._sync_eh_kds_status_from_room_service()
                    continue
                vals = {'order_status': kitchen_status}
                if 'is_cooking' in pos_order._fields:
                    vals['is_cooking'] = kitchen_status != 'cancel'
                kitchen = self.env['kitchen.screen'].sudo().search([
                    ('pos_config_id', '=', pos_order.config_id.id)
                ], limit=1) if 'kitchen.screen' in self.env.registry.models else False
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
                        order._sync_eh_kds_status_from_room_service()
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
            order._sync_eh_kds_status_from_room_service()

    def _eh_kds_models_available(self):
        return all(model in self.env.registry.models for model in (
            'eh.kds.board',
            'eh.kds.ticket',
            'eh.kds.ticket.item',
            'eh.kds.card',
        ))

    def _eh_kds_visible_states(self):
        return [
            'sent_pos', 'pos_failed', 'kitchen_preparing',
            'kitchen_ready', 'delivered', 'guest_confirmed', 'folio_posted',
            'paid_pos', 'closed',
        ]

    def _eh_kds_ticket_key(self):
        self.ensure_one()
        return 'room_service:%s' % self.id

    def _eh_kds_ticket_ref(self):
        self.ensure_one()
        return self.pos_reference or self.name or str(self.id)

    def _ensure_eh_kds_ticket(self):
        self.ensure_one()
        if not self._eh_kds_models_available():
            return self.env['hotel.room.service.order']
        if self.state not in self._eh_kds_visible_states():
            return self.env['eh.kds.ticket'].sudo()

        Ticket = self.env['eh.kds.ticket'].sudo()
        Item = self.env['eh.kds.ticket.item'].sudo()
        Card = self.env['eh.kds.card'].sudo()
        Board = self.env['eh.kds.board'].sudo()

        if self.pos_order_id:
            self.pos_order_id.sudo()._eh_kds_intake()
            ticket = Ticket.search([('pos_order_id', '=', self.pos_order_id.id)], limit=1)
            if ticket and ticket.ticket_ref != self._eh_kds_ticket_ref():
                ticket.ticket_ref = self._eh_kds_ticket_ref()
            return ticket

        if not Board.search_count([('active', '=', True)]):
            return Ticket

        ticket = Ticket.search([('internal_note', '=', self._eh_kds_ticket_key())], limit=1)
        if not ticket:
            ticket = Ticket.create({
                'ticket_ref': self._eh_kds_ticket_ref(),
                'customer_note': self.guest_note or False,
                'internal_note': self._eh_kds_ticket_key(),
            })
        touched = Board.browse()
        config = self.outlet_id.pos_config_id
        for line in self.line_ids:
            line_key = '%s:%s' % (self._eh_kds_ticket_key(), line.id)
            item = ticket.item_ids.filtered(lambda candidate, key=line_key: candidate.pos_order_line_uuid == key)[:1]
            known = (item.quantity - item.cancelled) if item else 0.0
            delta = line.quantity - known
            if delta > 0:
                if not item:
                    item = Item.create({
                        'ticket_id': ticket.id,
                        'product_id': line.product_id.id,
                        'quantity': line.quantity,
                        'pos_order_line_uuid': line_key,
                        'customer_note': line.note or False,
                    })
                    attr_value_ids = line.product_id.product_template_attribute_value_ids.ids
                    for board, lane in Board._route_item(config, line.product_id, attr_value_ids):
                        card = Card.create({'item_id': item.id, 'lane_id': lane.id})
                        card._log('placed', to_lane=lane, push=False)
                        touched |= board
                else:
                    item.quantity = line.quantity
            elif delta < 0 and item:
                item.cancelled = min(item.quantity, item.cancelled - delta)
                for card in item.card_ids.filtered(lambda candidate: candidate.status != 'voided'):
                    card._log('voided', push=False)
                    touched |= card.board_id
        for board in touched:
            board._kds_push(
                board.access_token,
                'kds.ticket',
                {'ticket_id': ticket.id, 'ticket_ref': ticket.ticket_ref, 'event': 'room_service_intake'},
            )
            board._kds_push(board.access_token, 'kds.status', {'ticket_ref': ticket.ticket_ref})
        return ticket

    def _eh_kds_target_index(self, board):
        self.ensure_one()
        lanes = list(board.lane_ids)
        if not lanes:
            return False
        last = len(lanes) - 1
        if self.state in ['sent_pos', 'pos_failed']:
            return 0
        if self.state == 'kitchen_preparing':
            return min(1, last)
        if self.state == 'kitchen_ready':
            return max(last - 1, 0)
        if self.state in ['delivered', 'guest_confirmed', 'folio_posted', 'paid_pos', 'closed']:
            return last
        return False

    def _sync_eh_kds_status_from_room_service(self):
        if self.env.context.get('room_service_skip_eh_kds_sync'):
            return True
        for order in self:
            if not order._eh_kds_models_available():
                continue
            ticket = order._ensure_eh_kds_ticket()
            if not ticket:
                continue
            cards = ticket.item_ids.card_ids.filtered(lambda card: card.status != 'voided')
            if order.state == 'cancelled':
                cards.with_context(room_service_skip_kds_to_rs_sync=True).void(reason='Room Service cancelled')
                continue
            for board in cards.board_id:
                target = order._eh_kds_target_index(board)
                if target is False:
                    continue
                board_cards = cards.filtered(lambda card, current_board=board: card.board_id == current_board)
                board_cards.with_context(room_service_skip_kds_to_rs_sync=True).move_to(target)
        return True

    def _reconcile_pos_kitchen_status(self):
        """Repair drift and align Room Service stages with Kitchen Display stages."""
        for order in self:
            order._sync_pos_kitchen_status_from_room_service()
            pos_order = order.pos_order_id.sudo()
        return True

    def _get_room_charge_payment_method_for_pos(self, pos_order):
        PaymentMethod = self.env['pos.payment.method'].sudo()
        methods = pos_order.config_id.payment_method_ids
        room_charge = methods.filtered(lambda method: method.is_room_charge)[:1]
        if room_charge:
            return room_charge
        return PaymentMethod.search([
            ('is_room_charge', '=', True),
            ('id', 'in', methods.ids),
        ], limit=1)

    def _sync_pos_status_after_room_bill_posted(self):
        """Mark the linked POS ticket paid after the folio charge succeeds."""
        Payment = self.env['pos.payment'].sudo()
        for order in self:
            pos_order = order.pos_order_id.sudo()
            if (
                not pos_order
                or order.pms_sync_state != 'posted'
                or pos_order.state in ['paid', 'done', 'cancel']
            ):
                continue

            currency = pos_order.currency_id
            amount_due = currency.round(pos_order.amount_total - pos_order.amount_paid)
            if not float_is_zero(amount_due, precision_rounding=currency.rounding):
                payment_method = order._get_room_charge_payment_method_for_pos(pos_order)
                if not payment_method:
                    order._log_adapter("pos", "failed", _("Unable to mark POS order paid: no Room Charge payment method is configured on the POS outlet."))
                    continue
                Payment.create({
                    'pos_order_id': pos_order.id,
                    'payment_method_id': payment_method.id,
                    'amount': amount_due,
                    'payment_date': fields.Datetime.now(),
                })
                pos_order._compute_prices()

            pos_order.with_context(room_service_skip_rs_sync=True).action_pos_order_paid()
            order._log_adapter("pos", "success", _("Linked POS order marked paid after the room folio charge was posted."))
            try:
                pos_order.config_id.sudo().notify_synchronisation(
                    pos_order.session_id.id,
                    self.env.context.get('device_identifier', 0),
                    {'pos.order': [pos_order.id], 'pos.payment': pos_order.payment_ids.ids}
                )
            except Exception:
                pass
        return True

    def _post_to_pms_folio(self):
        res = super()._post_to_pms_folio()
        for order in self:
            if order.pms_sync_state == 'posted':
                order._sync_pos_status_after_room_bill_posted()
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
                ref = pos_order.name if pos_order.name != '/' else pos_order.floating_order_name
                order.write({'state': 'sent_pos', 'pos_reference': ref})
                order._log_adapter("system", "success", _("Self-order accepted by staff and sent to the kitchen queue."))
            else:
                if order.state == 'draft':
                    order.write({'state': 'confirmed'})
                if order.outlet_id.auto_create_pos_order:
                    order.action_send_to_pos()
                else:
                    order.write({'state': 'sent_pos'})
                    order._log_adapter("system", "success", _("Room Service order accepted for the kitchen queue without POS draft order."))
        return True

    def action_cancel_before_pos(self):
        res = super().action_cancel_before_pos()
        for order in self:
            if order.pos_order_id and order.pos_order_id.state == 'draft':
                order.pos_order_id.sudo().write({'state': 'cancel'})
                if 'order_status' in order.pos_order_id._fields:
                    order.pos_order_id.sudo().write({'order_status': 'cancel'})
        return res


class EhKdsCard(models.Model):
    _inherit = 'eh.kds.card'

    def move_to(self, index, kind=None):
        res = super().move_to(index, kind=kind)
        if not self.env.context.get('room_service_skip_kds_to_rs_sync'):
            self._sync_room_service_from_eh_kds()
        return res

    def void(self, reason=None):
        res = super().void(reason=reason)
        if not self.env.context.get('room_service_skip_kds_to_rs_sync'):
            self._sync_room_service_from_eh_kds(cancelled=True)
        return res

    def _room_service_from_ticket(self, ticket):
        RoomService = self.env['hotel.room.service.order'].sudo()
        if ticket.pos_order_id:
            order = RoomService.search([('pos_order_id', '=', ticket.pos_order_id.id)], limit=1)
            if order:
                return order
        marker = ticket.internal_note or ''
        if marker.startswith('room_service:'):
            try:
                order = RoomService.browse(int(marker.split(':', 1)[1]))
            except (TypeError, ValueError):
                return RoomService
            return order if order.exists() else RoomService
        return RoomService

    def _room_service_state_from_ticket(self, ticket, cancelled=False):
        if cancelled:
            return 'cancelled'
        cards = ticket.item_ids.card_ids.filtered(lambda card: card.status != 'voided')
        if not cards:
            return False
        stage_rank = 0
        for board in cards.board_id:
            lanes = list(board.lane_ids)
            if not lanes:
                continue
            last = len(lanes) - 1
            ready = max(last - 1, 0)
            indexes = [lanes.index(card.lane_id) for card in cards.filtered(lambda card: card.board_id == board) if card.lane_id in lanes]
            if not indexes:
                continue
            if all(index >= last for index in indexes):
                stage_rank = max(stage_rank, 3)
            elif all(index >= ready for index in indexes):
                stage_rank = max(stage_rank, 2)
            elif any(index >= 1 for index in indexes):
                stage_rank = max(stage_rank, 1)
        return {
            0: 'sent_pos',
            1: 'kitchen_preparing',
            2: 'kitchen_ready',
            # Kitchen completion is not a Room Service completion.
            # Room Service keeps its current state until staff completes and posts the bill.
            3: False,
        }.get(stage_rank)

    def _sync_room_service_from_eh_kds(self, cancelled=False):
        for ticket in self.ticket_id:
            order = self._room_service_from_ticket(ticket)
            if not order or order.state in ['closed', 'folio_posted', 'paid_pos']:
                continue
            new_state = self._room_service_state_from_ticket(ticket, cancelled=cancelled)
            if not new_state or order.state == new_state:
                continue
            vals = {'state': new_state}
            if new_state == 'cancelled':
                vals['closed_at'] = fields.Datetime.now()
            order.with_context(
                room_service_skip_pos_kitchen_sync=True,
                room_service_skip_eh_kds_sync=True,
            ).write(vals)
        return True
