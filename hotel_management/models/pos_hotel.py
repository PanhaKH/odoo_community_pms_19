from odoo import models, fields, api, _
from odoo.exceptions import UserError

class PosPaymentMethod(models.Model):
    _inherit = 'pos.payment.method'
    # RENAMED STRING
    is_room_charge = fields.Boolean(string="Is Bill To Room Charge", help="Check this to allow charging to hotel rooms.")

    @api.model
    def _link_room_charge_methods_to_pos_configs(self):
        room_charge_methods = self.search([('is_room_charge', '=', True)])
        if not room_charge_methods:
            return

        for config in self.env['pos.config'].search([]):
            missing_methods = room_charge_methods - config.payment_method_ids
            if missing_methods:
                config.with_context(bypass_payment_method_ids_forbidden_change=True).write({
                    'payment_method_ids': [fields.Command.link(method.id) for method in missing_methods],
                })

    @api.model
    def _load_pos_data_fields(self, config):
        fields_to_load = super()._load_pos_data_fields(config)
        return [*fields_to_load, 'is_room_charge']

class PosOrder(models.Model):
    _inherit = 'pos.order'

    hotel_reservation_id = fields.Many2one('hotel.reservation', string="Charged to Room", readonly=True)

    @api.model
    def _process_order(self, order, existing_order):
        # 1. Process the standard order
        pos_order_id = super()._process_order(order, existing_order)
        pos_order = self.browse(pos_order_id)

        # 2. Look for Bill To Room Charges
        for payment in pos_order.payment_ids:
            if payment.payment_method_id.is_room_charge:
                reservation = False
                
                # THE BUG FIX: The Javascript popup saves the guest ID into the 'transaction_id'. 
                # We MUST read it here so we charge the exact room they clicked on!
                if payment.transaction_id:
                    try:
                        res_id = int(payment.transaction_id)
                        reservation = self.env['hotel.reservation'].browse(res_id)
                    except ValueError:
                        pass
                
                # Fallback: Try to get room from selected POS Customer if popup failed
                if not reservation or not reservation.exists():
                    if pos_order.partner_id:
                        reservation = self.env['hotel.reservation'].search([
                            ('partner_id', '=', pos_order.partner_id.id),
                            ('state', '=', 'checkin')  # Must be currently checked in
                        ], limit=1)

                # 3. Check if we actually found a valid room
                if reservation and reservation.exists():
                    pos_order.write({'hotel_reservation_id': reservation.id})
                    self._create_hotel_charge(reservation, payment.amount, pos_order.pos_reference or pos_order.name)
                else:
                    # 4. THE BLOCKER: If no room is found, stop everything and warn the waiter!
                    raise UserError(_("ERROR: This customer is not currently checked into a room! You cannot use 'Bill To Room Charge' for a non-guest. Please use Cash or Credit Card."))
        
        return pos_order_id

    def _create_hotel_charge(self, reservation, amount, ref):
        if not reservation.sale_order_id:
            reservation.action_create_folio()
            
        product = self.env['product.product'].search([('name', '=', 'Restaurant Charge')], limit=1)
        if not product:
            product = self.env['product.product'].create({'name': 'Restaurant Charge', 'type': 'service'})

        # Create the line on the Folio and explicitly block the double tax!
        self.env['sale.order.line'].create({
            'order_id': reservation.sale_order_id.id,
            'product_id': product.id,
            'name': f"Restaurant Bill: {ref}",
            'product_uom_qty': 1,
            'price_unit': amount,
            'hotel_reservation_id': reservation.id,
            'tax_ids': [(5, 0, 0)],  # Keep restaurant room charges tax-free.
        })

    @api.model
    def get_inhouse_guests(self):
        guests = self.env['hotel.reservation'].search([('state', '=', 'checkin')])
        res_list = []
        for g in guests:
            # 1. Safely handle Desk Folios that don't have physical rooms
            if getattr(g, 'is_desk_folio', False):
                room_display = "Desk Folio"
            else:
                room_display = g.room_id.name if g.room_id else "Unassigned"
                
            # 2. Format the name cleanly
            guest_name = g.partner_id.name if g.partner_id else "No Name"
            
            res_list.append({
                'id': g.id,
                'name': f"[{room_display}] - {guest_name}"
            })
        return res_list


