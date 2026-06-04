from unittest.mock import patch

from odoo import fields
from odoo.tests.common import TransactionCase, tagged


@tagged('post_install', '-at_install')
class TestHotelCityLedger(TransactionCase):

    def test_partial_company_invoice_payment_does_not_double_count_balance(self):
        company_partner = self.env['res.partner'].create({
            'name': 'First Cambodia Co., Ltd',
            'is_company': True,
        })
        guest = self.env['res.partner'].create({'name': 'City Ledger Guest'})
        room_type = self.env['hotel.room.type'].create({'name': 'City Ledger Test Room Type'})
        reservation = self.env['hotel.reservation'].create({
            'partner_id': guest.id,
            'room_type_id': room_type.id,
            'checkin_date': fields.Date.today(),
            'checkout_date': fields.Date.add(fields.Date.today(), days=1),
            'is_manual_rate': True,
            'manual_rate': 0.0,
            'city_ledger_id': company_partner.id,
            'billing_routing': 'master_all',
        })

        mocked_position = {
            'folio_total_debit': 577.50,
            'folio_total_credit': 288.75,
            'operational_balance': 288.75,
            'balance_due': 288.75,
            'credit_balance': 0.0,
            'deposit_credit': 0.0,
            'payments_received': 288.75,
        }
        mocked_invoice_totals = {
            'draft_total': 0.0,
            'posted_total': 288.75,
            'posted_residual': 0.0,
            'invoice_ids': [],
        }

        with patch.object(
            type(reservation),
            '_get_operational_folio_position',
            return_value=mocked_position,
        ), patch.object(
            type(reservation),
            '_get_company_invoice_totals',
            return_value=mocked_invoice_totals,
        ):
            position = reservation._get_company_city_ledger_position()

        self.assertAlmostEqual(position['routed_amount'], 577.50)
        self.assertAlmostEqual(position['paid_amount'], 288.75)
        self.assertAlmostEqual(position['balance'], 288.75)
        self.assertAlmostEqual(position['pending_billing'], 288.75)
        self.assertNotAlmostEqual(position['balance'], 866.25)
