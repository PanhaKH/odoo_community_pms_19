from odoo import models, fields, api

# ---------------------------------------------------------
# 1. THE VAULT: Your Change Journal (Unchanged)
# ---------------------------------------------------------
class HotelChangeLog(models.Model):
    _name = 'hotel.change.log'
    _description = 'Reservation Exchange Journal'
    _order = 'create_date desc'

    reservation_id = fields.Many2one('hotel.reservation', string="Reservation", required=True, ondelete='cascade')
    user_id = fields.Many2one('res.users', string="User", default=lambda self: self.env.user, readonly=True)
    change_date = fields.Datetime(string="Date & Time", default=fields.Datetime.now, readonly=True)

    change_type = fields.Selection(
        [('field', 'Field Change'), ('action', 'Operational Action')],
        string="Type",
        default='field',
        readonly=True,
    )
    field_name = fields.Char(string="Field Changed")
    old_value = fields.Char(string="Old Value")
    new_value = fields.Char(string="New Value")
    reason = fields.Char(string="Reason")
    source_document_name = fields.Char(string="Source Document Name", readonly=True)
    source_document_ref = fields.Reference(
        selection=[
            ('hotel.reservation', 'Reservation'),
            ('sale.order', 'Folio'),
            ('sale.order.line', 'Folio Line'),
            ('account.move', 'Invoice'),
            ('account.payment', 'Payment'),
            ('hotel.daily.transaction', 'Daily Rate'),
            ('hotel.room', 'Room'),
        ],
        string="Source Document",
        readonly=True,
    )

    @api.model
    def log_reservation_event(
        self,
        reservation,
        field_name,
        old_value=False,
        new_value=False,
        *,
        change_type='field',
        reason=False,
        source_document=False,
        user=False,
        change_date=False,
    ):
        reservation = reservation.sudo() if reservation else self.env['hotel.reservation']
        if not reservation:
            return self.env['hotel.change.log']
        reservation = reservation[:1]
        values = {
            'reservation_id': reservation.id,
            'change_type': change_type or 'field',
            'field_name': field_name,
            'old_value': old_value or '',
            'new_value': new_value or '',
            'reason': reason or '',
            'user_id': (user or self.env.user).id,
            'change_date': change_date or fields.Datetime.now(),
        }
        if source_document:
            source_document = source_document[:1]
            values.update({
                'source_document_ref': f'{source_document._name},{source_document.id}',
                'source_document_name': source_document.display_name,
            })
        return self.sudo().create(values)


# ---------------------------------------------------------
# 2. THE REPORTER: The Automated Tracker for Billing
# ---------------------------------------------------------
class SaleOrderLine(models.Model):
    _inherit = 'sale.order.line'

    def write(self, vals):
        if self.env.context.get('skip_hotel_billing_audit'):
            return super(SaleOrderLine, self).write(vals)

        # We only care if they are trying to change tracked billing fields.
        tracked_fields = ['name', 'product_id', 'price_unit', 'product_uom_qty', 'discount', 'billing_target']
        if any(field in vals for field in tracked_fields):
            billing_labels = dict(self._fields['billing_target'].selection)

            for line in self:
                reservation = line.hotel_reservation_id or self.env['hotel.reservation'].search(
                    [('sale_order_id', '=', line.order_id.id)],
                    limit=1,
                )

                # Only track changes if this bill belongs to a hotel guest
                if reservation and not line.display_type:

                    # Track Price Changes
                    if 'price_unit' in vals and vals['price_unit'] != line.price_unit:
                        self.env['hotel.change.log'].log_reservation_event(
                            reservation,
                            f"Unit Price ({line.name})",
                            str(line.price_unit),
                            str(vals['price_unit']),
                            source_document=line,
                        )

                    # Track Quantity Changes (e.g., removing a charged item)
                    if 'product_uom_qty' in vals and vals['product_uom_qty'] != line.product_uom_qty:
                        self.env['hotel.change.log'].log_reservation_event(
                            reservation,
                            f"Quantity ({line.name})",
                            str(line.product_uom_qty),
                            str(vals['product_uom_qty']),
                            source_document=line,
                        )

                    # Track Discount Changes
                    if 'discount' in vals and vals['discount'] != line.discount:
                        self.env['hotel.change.log'].log_reservation_event(
                            reservation,
                            f"Discount % ({line.name})",
                            str(line.discount),
                            str(vals['discount']),
                            source_document=line,
                        )

                    if 'billing_target' in vals and vals['billing_target'] != line.billing_target:
                        self.env['hotel.change.log'].log_reservation_event(
                            reservation,
                            f"Billing Target ({line.name})",
                            billing_labels.get(line.billing_target, line.billing_target or 'Guest'),
                            billing_labels.get(vals['billing_target'], vals['billing_target'] or 'Guest'),
                            source_document=line,
                        )

                    if 'product_id' in vals and vals['product_id'] != line.product_id.id:
                        new_product = self.env['product.product'].browse(vals['product_id'])
                        self.env['hotel.change.log'].log_reservation_event(
                            reservation,
                            f"Product ({line.name})",
                            line.product_id.display_name or '',
                            new_product.display_name or '',
                            source_document=line,
                        )

                    if 'name' in vals and vals['name'] != line.name:
                        self.env['hotel.change.log'].log_reservation_event(
                            reservation,
                            "Charge Description",
                            line.name,
                            vals['name'],
                            source_document=line,
                        )

        # Finally, let Odoo save the changes to the database normally
        return super(SaleOrderLine, self).write(vals)

    @api.model_create_multi
    def create(self, vals_list):
        lines = super().create(vals_list)
        logger = self.env['hotel.change.log']
        for line in lines.filtered(lambda l: not l.display_type):
            reservation = line.hotel_reservation_id or self.env['hotel.reservation'].search(
                [('sale_order_id', '=', line.order_id.id)],
                limit=1,
            )
            if reservation:
                logger.log_reservation_event(
                    reservation,
                    "Folio Line Added",
                    '',
                    f"{line.name} | Qty {line.product_uom_qty} | Total {line.price_total}",
                    change_type='action',
                    source_document=line,
                )
        return lines

    def unlink(self):
        logger = self.env['hotel.change.log']
        snapshots = []
        for line in self.filtered(lambda l: not l.display_type):
            reservation = line.hotel_reservation_id or self.env['hotel.reservation'].search(
                [('sale_order_id', '=', line.order_id.id)],
                limit=1,
            )
            if reservation:
                snapshots.append({
                    'reservation': reservation,
                    'line_name': line.name,
                    'summary': f"{line.name} | Qty {line.product_uom_qty} | Total {line.price_total}",
                    'source_document': line.order_id or reservation,
                })
        result = super().unlink()
        for snapshot in snapshots:
            logger.log_reservation_event(
                snapshot['reservation'],
                "Folio Line Removed",
                snapshot['summary'],
                '',
                change_type='action',
                source_document=snapshot['source_document'],
            )
        return result

