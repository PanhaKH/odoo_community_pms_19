from odoo import fields, models


class HotelEmailAudit(models.Model):
    _name = 'hotel.email.audit'
    _description = 'Hotel Email Audit'
    _order = 'create_date desc, id desc'

    reservation_id = fields.Many2one(
        'hotel.reservation',
        string='Reservation',
        required=True,
        ondelete='cascade',
        index=True,
    )
    audit_type = fields.Selection([
        ('booking_confirmation', 'Booking Confirmation'),
        ('pre_arrival', 'Pre-Arrival Link'),
        ('deposit_receipt', 'Deposit Receipt'),
        ('registration_card', 'Registration Card'),
        ('final_receipt', 'Final Receipt'),
        ('incoming_guest_reply', 'Incoming Guest Reply'),
    ], string='Type', required=True, index=True)
    recipient = fields.Char(required=True)
    status = fields.Selection([
        ('queued', 'Queued'),
        ('sent', 'Sent'),
        ('failed', 'Failed'),
        ('received', 'Received'),
        ('skipped', 'Skipped'),
    ], required=True, default='sent', index=True)
    subject = fields.Char(required=True)
    mail_id = fields.Many2one('mail.mail', string='Email', ondelete='set null')
    attachment_id = fields.Many2one('ir.attachment', string='Attachment', ondelete='set null')
    source_payment_id = fields.Many2one('account.payment', string='Source Payment', ondelete='set null')
    failure_reason = fields.Text()
