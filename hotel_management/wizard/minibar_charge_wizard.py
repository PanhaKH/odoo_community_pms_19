from markupsafe import Markup, escape

from odoo import _, fields, models
from odoo.exceptions import UserError

class MinibarChargeWizard(models.TransientModel):
    _name = 'hotel.minibar.wizard'
    _description = 'Post Minibar Charge from Mobile'

    # The room is automatically passed in from the Kanban card
    room_id = fields.Many2one('hotel.room', string="Room", readonly=True)
    
    # We look up standard Odoo products. You can filter this to only show 'Minibar' category later!
    product_id = fields.Many2one('product.product', string="Item Consumed", required=True)
    quantity = fields.Integer(string="Quantity", default=1, required=True)

    def _is_housekeeping_minibar_user(self):
        housekeeping_group_xmlids = (
            'hotel_housekeeping_app.group_housekeeping_user',
            'hotel_housekeeping_app.group_housekeeping_supervisor',
            'hotel_housekeeping_app.group_housekeeping_manager',
        )
        return any(
            self.env.ref(xmlid, raise_if_not_found=False) and self.env.user.has_group(xmlid)
            for xmlid in housekeeping_group_xmlids
        )

    def action_post_charge(self):
        """ Simplified Logic: Only posts to the current active guest """
        for wizard in self:
            # We just find the most recent reservation for this room
            reservation = self.env['hotel.reservation'].search([
                ('room_id', '=', wizard.room_id.id),
                ('state', 'in', ['checkin', 'checkout_hold']),
            ], order='id desc', limit=1)

            # Failsafe just in case
            if not reservation:
                return {
                    'type': 'ir.actions.client',
                    'tag': 'display_notification',
                    'params': {
                        'title': 'Error!',
                        'message': f'No reservation found for {wizard.room_id.name}.',
                        'type': 'danger',
                        'sticky': True,
                    }
                }

            if not reservation.sale_order_id:
                raise UserError(_(
                    "Room %(room)s has an active reservation but no existing folio. "
                    "Please ask Front Office to create the folio before posting minibar charges."
                ) % {'room': wizard.room_id.display_name})

            folio = reservation.sale_order_id

            if folio:
                is_housekeeping_post = self._is_housekeeping_minibar_user()
                line_values = {
                    'order_id': folio.id,               # Attach to this guest's folio
                    'product_id': wizard.product_id.id, # The Coke/Snickers they ate
                    'product_uom_qty': wizard.quantity, # How many they ate
                    'hotel_reservation_id': reservation.id,
                }
                SaleOrderLine = self.env['sale.order.line']
                if is_housekeeping_post:
                    # Scoped elevation: housekeeping can post this validated minibar
                    # line, without receiving general Sales Order Line access.
                    line = SaleOrderLine.sudo().create(line_values)
                else:
                    line = SaleOrderLine.create(line_values)

                wizard.room_id.write({
                    'minibar_checked': True,
                    'minibar_check_required': False,
                })

                posted_by = self.env.user.display_name
                amount = line.price_subtotal
                currency = folio.sudo().currency_id if is_housekeeping_post else folio.currency_id
                audit_body = Markup(
                    "<b>Minibar charge posted</b><br/>"
                    "Item: %(item)s<br/>"
                    "Quantity: %(quantity)s<br/>"
                    "Amount: %(amount)s %(currency)s<br/>"
                    "Posted by: %(posted_by)s"
                ) % {
                    'item': escape(wizard.product_id.display_name),
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
                    'message': f'Posted {wizard.quantity}x {wizard.product_id.name} to {wizard.room_id.name}',
                    'type': 'success',
                    'sticky': False,
                    
                    # NEW: This line tells Odoo to close the popup immediately!
                    'next': {'type': 'ir.actions.act_window_close'},
                }
            }
