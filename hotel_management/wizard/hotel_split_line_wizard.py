from odoo import models, fields, api
from odoo.exceptions import UserError

class HotelSplitLineWizard(models.TransientModel):
    _name = 'hotel.split.line.wizard'
    _description = 'Dynamic Split Folio Charge Wizard'

    line_id = fields.Many2one('sale.order.line', string='Original Line', required=True)
    currency_id = fields.Many2one(related='line_id.order_id.currency_id')
    
    # Just receives the exact total from the button!
    original_total = fields.Monetary(string='Original Total', readonly=True)
    
    split_line_ids = fields.One2many('hotel.split.line.wizard.item', 'wizard_id', string='Split Details')
    remaining_amount = fields.Monetary(string='Remaining to Split', compute='_compute_remaining', store=True)

    @api.depends('original_total', 'split_line_ids.amount')
    def _compute_remaining(self):
        for wiz in self:
            allocated = sum(wiz.split_line_ids.mapped('amount'))
            wiz.remaining_amount = wiz.original_total - allocated

    def action_split_line(self):
        self.ensure_one()
        if not self.split_line_ids:
            raise UserError("You must add at least one person to split this charge with.")
        if round(self.remaining_amount, 2) != 0.00:
            raise UserError(f"You still have {self.remaining_amount} left to allocate. The remaining balance must be exactly zero.")

        order = self.line_id.order_id
        original_desc = self.line_id.name
        biz_date = getattr(self.line_id, 'hotel_business_date', False)

        new_lines_vals = []
        for split in self.split_line_ids:
            ratio = split.amount / self.original_total
            new_qty = self.line_id.product_uom_qty * ratio
            
            val = {
                'order_id': order.id,
                'product_id': self.line_id.product_id.id,
                'name': f"{original_desc} (Split: {split.partner_id.name})",
                'product_uom_qty': new_qty,
                'price_unit': self.line_id.price_unit,
                'tax_ids': [(6, 0, self.line_id.tax_ids.ids)],
            }
            if biz_date:
                val['hotel_business_date'] = biz_date
                
            new_lines_vals.append(val)
            
        # ==========================================
        # THE ULTIMATE BYPASS: SQL VAPORIZE
        # ==========================================
        
        # 1. Manually write the negative journal entry (since we are bypassing the standard unlink)
        res = self.env['hotel.reservation'].search([('sale_order_id', '=', order.id)], limit=1)
        if res and self.line_id.price_unit > 0:
            self.env['hotel.posting.journal'].create({
                'reservation_id': res.id,
                'journal_type': 'system',
                'description': f"Deleted Charge (Split): {self.line_id.name}",
                'amount': -self.line_id.price_total,
                'business_date': self.env.company.hotel_business_date or fields.Date.context_today(self),
                'date': fields.Datetime.now(),
                'source_order_id': order.id,
                'folio_billing_target': self.line_id.billing_target or self.line_id._get_resolved_billing_target(),
            })

        # 2. Grab the ID before we destroy it
        line_id_to_delete = self.line_id.id
        
        # 3. Create the beautiful new split lines normally
        self.env['sale.order.line'].create(new_lines_vals)

        # 4. Vaporize the old line directly from the PostgreSQL database (Bypasses all Odoo errors)
        self.env.cr.execute("DELETE FROM sale_order_line WHERE id = %s", (line_id_to_delete,))
        
        # 5. Tell Odoo to wake up and refresh its memory of the Folio total
        order.invalidate_recordset(['order_line', 'amount_total'])

class HotelSplitLineWizardItem(models.TransientModel):
    _name = 'hotel.split.line.wizard.item'
    _description = 'Split Folio Charge Item'

    wizard_id = fields.Many2one('hotel.split.line.wizard', ondelete='cascade')
    currency_id = fields.Many2one(related='wizard_id.currency_id')
    partner_id = fields.Many2one('res.partner', string='Payee (Guest/Company)', required=True)
    amount = fields.Monetary(string='Amount (Incl. Tax)', required=True)
