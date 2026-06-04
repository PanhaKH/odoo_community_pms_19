from odoo import models, fields, api

class MinibarChargeWizard(models.TransientModel):
    _name = 'hotel.minibar.wizard'
    _description = 'Post Minibar Charge from Mobile'

    # The room is automatically passed in from the Kanban card
    room_id = fields.Many2one('hotel.room', string="Room", readonly=True)
    
    # We look up standard Odoo products. You can filter this to only show 'Minibar' category later!
    product_id = fields.Many2one('product.product', string="Item Consumed", required=True)
    quantity = fields.Integer(string="Quantity", default=1, required=True)

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

            # ==========================================
            # THE BILLING ENGINE
            # ==========================================
            
            # Using the exact field name from your database!
            if not reservation.sale_order_id:
                reservation.action_create_folio()

            folio = reservation.sale_order_id

            if folio:
                # This creates a new line item directly on the guest's bill!
                self.env['sale.order.line'].create({
                    'order_id': folio.id,               # Attach to this guest's folio
                    'product_id': wizard.product_id.id, # The Coke/Snickers they ate
                    'product_uom_qty': wizard.quantity, # How many they ate
                    'hotel_reservation_id': reservation.id,
                })
                wizard.room_id.write({
                    'minibar_checked': True,
                    'minibar_check_required': False,
                })
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
            # ==========================================
            
            # Return visual success to Housekeeper
            return {
                'type': 'ir.actions.client',
                'tag': 'display_notification',
                'params': {
                    'title': 'Success!',
                    'message': f'Posted {wizard.quantity}x {wizard.product_id.name} to {wizard.room_id.name}',
                    'type': 'success',
                    'sticky': False,
                }
            }
