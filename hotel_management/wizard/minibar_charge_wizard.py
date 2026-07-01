from markupsafe import Markup, escape

from odoo import _, fields, models
from odoo.exceptions import UserError

class MinibarChargeWizard(models.TransientModel):
    _name = 'hotel.minibar.wizard'
    _description = 'Post Minibar Charge from Mobile'

    # The room is automatically passed in from the Kanban card
    room_id = fields.Many2one('hotel.room', string="Room", readonly=True)
    
    product_id = fields.Many2one(
        'product.product',
        string="Item Consumed",
        required=True,
        domain=[('sale_ok', '=', True), ('product_tmpl_id.is_minibar_item', '=', True)],
    )
    quantity = fields.Integer(string="Quantity", default=1, required=True)

    def _is_housekeeping_minibar_user(self):
        housekeeping_group_xmlids = (
            'hotel_management.group_hotel_housekeeper',
            'hotel_housekeeping_app.group_housekeeping_user',
            'hotel_housekeeping_app.group_housekeeping_supervisor',
            'hotel_housekeeping_app.group_housekeeping_manager',
        )
        return any(
            self.env.ref(xmlid, raise_if_not_found=False) and self.env.user.has_group(xmlid)
            for xmlid in housekeeping_group_xmlids
        )

    def _get_allowed_minibar_products(self, company):
        Product = self.env['product.product'].sudo()
        return Product.search([
            ('sale_ok', '=', True),
            ('product_tmpl_id.is_minibar_item', '=', True),
        ]).exists()

    def action_post_charge(self):
        """Post a validated minibar charge to the current active guest folio."""
        for wizard in self:
            room = wizard.room_id.exists()
            if not room:
                raise UserError(_("Please select a valid room."))
            if wizard.quantity <= 0:
                raise UserError(_("Minibar quantity must be greater than zero."))

            product = wizard.product_id.sudo().exists()
            if not product or not product.sale_ok:
                raise UserError(_("Please select an active saleable minibar product."))

            if product.lst_price < 0:
                raise UserError(_("Minibar product price cannot be negative."))

            reservation = self.env['hotel.reservation'].sudo().search([
                ('room_id', '=', room.id),
                ('state', 'in', ['checkin', 'checkout_hold']),
            ], order='checkin_date desc, id desc', limit=1)

            if not reservation:
                return {
                    'type': 'ir.actions.client',
                    'tag': 'display_notification',
                    'params': {
                        'title': 'Error!',
                        'message': f'No in-house reservation found for {room.name}.',
                        'type': 'danger',
                        'sticky': True,
                    }
                }

            allowed_products = wizard._get_allowed_minibar_products(reservation.company_id or self.env.company)
            if not allowed_products:
                raise UserError(_("No minibar product is configured. Please ask Hotel Manager/Admin to enable Minibar Item on the product form."))
            if product.id not in allowed_products.ids:
                raise UserError(_("This product is not configured as a Minibar Item. Please ask Hotel Manager/Admin to enable Minibar Item on the product form."))

            if not reservation.sale_order_id:
                raise UserError(_(
                    "Room %(room)s has an active reservation but no existing folio. "
                    "Please ask Front Office to create the folio before posting minibar charges."
                ) % {'room': wizard.room_id.display_name})

            folio = reservation.sale_order_id

            if folio:
                is_housekeeping_post = self._is_housekeeping_minibar_user()
                line_values = {
                    'order_id': folio.id,
                    'product_id': product.id,
                    'product_uom_qty': wizard.quantity,
                    'hotel_reservation_id': reservation.id,
                }
                SaleOrderLine = self.env['sale.order.line']
                if is_housekeeping_post:
                    # Scoped elevation: housekeeping can post this validated minibar
                    # line, without receiving general Sales Order Line access.
                    line = SaleOrderLine.sudo().create(line_values)
                else:
                    line = SaleOrderLine.create(line_values)

                if line.sudo().price_subtotal < 0:
                    raise UserError(_("Minibar charge amount cannot be negative."))

                (room.sudo() if is_housekeeping_post else room).write({
                    'minibar_checked': True,
                    'minibar_check_required': False,
                })

                posted_by = self.env.user.display_name
                amount = line.sudo().price_subtotal
                currency = folio.sudo().currency_id
                audit_body = Markup(
                    "<b>Minibar charge posted</b><br/>"
                    "Room: %(room)s<br/>"
                    "Reservation: %(reservation)s<br/>"
                    "Item: %(item)s<br/>"
                    "Quantity: %(quantity)s<br/>"
                    "Amount: %(amount)s %(currency)s<br/>"
                    "Posted by: %(posted_by)s"
                ) % {
                    'room': escape(room.display_name),
                    'reservation': escape(reservation.display_name),
                    'item': escape(product.display_name),
                    'quantity': wizard.quantity,
                    'amount': f'{amount:.2f}',
                    'currency': escape(currency.name or ''),
                    'posted_by': escape(posted_by),
                }
                reservation.sudo().message_post(
                    body=audit_body,
                    subtype_xmlid='mail.mt_note',
                    author_id=self.env.user.partner_id.id,
                )
            # Return visual success to Housekeeper AND close the window
            return {
                'type': 'ir.actions.client',
                'tag': 'display_notification',
                'params': {
                    'title': 'Success!',
                    'message': f'Posted {wizard.quantity}x {product.name} to {room.name}',
                    'type': 'success',
                    'sticky': False,
                    
                    # NEW: This line tells Odoo to close the popup immediately!
                    'next': {'type': 'ir.actions.act_window_close'},
                }
            }
