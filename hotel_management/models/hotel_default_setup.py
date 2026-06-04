import logging

from odoo import Command, api, fields, models, _

_logger = logging.getLogger(__name__)


class ResConfigSettingsHotelDefaultSetup(models.TransientModel):
    _inherit = 'res.config.settings'

    hotel_group_deposit_account_id = fields.Many2one('account.account', string='Group Advance Deposit Liability Account')
    hotel_group_deposit_liability_account_id = fields.Many2one('account.account', string='Group Advance Deposit Liability Account')
    hotel_security_deposit_account_id = fields.Many2one('account.account', string='Security Deposit Liability Account')
    hotel_security_deposit_liability_account_id = fields.Many2one('account.account', string='Security Deposit Liability Account')
    hotel_room_revenue_account_id = fields.Many2one('account.account', string='Room Revenue Account')
    hotel_city_ledger_receivable_account_id = fields.Many2one('account.account', string='City Ledger Receivable Account')
    hotel_default_sale_tax_id = fields.Many2one('account.tax', string='Default Hotel Sales Tax')
    hotel_default_purchase_tax_id = fields.Many2one('account.tax', string='Default Hotel Purchase Tax')
    hotel_default_deposit_journal_id = fields.Many2one('account.journal', string='Default Hotel Deposit Journal')
    hotel_cash_journal_id = fields.Many2one('account.journal', string='Hotel Cash Journal')
    hotel_bank_journal_id = fields.Many2one('account.journal', string='Hotel Bank Journal')
    hotel_sales_journal_id = fields.Many2one('account.journal', string='Hotel Sales Journal')
    hotel_purchase_journal_id = fields.Many2one('account.journal', string='Hotel Purchase Journal')
    hotel_city_ledger_journal_id = fields.Many2one('account.journal', string='City Ledger Journal')

    hotel_accommodation_product_id = fields.Many2one('product.product', string='Accommodation Product')
    hotel_room_charge_product_id = fields.Many2one('product.product', string='Room Charge Product')
    hotel_advance_deposit_product_id = fields.Many2one('product.product', string='Advance Deposit Product')
    hotel_group_deposit_product_id = fields.Many2one('product.product', string='Group Advance Deposit Product')
    hotel_security_deposit_product_id = fields.Many2one('product.product', string='Security Deposit Product')
    hotel_extra_person_product_id = fields.Many2one('product.product', string='Extra Person Product')
    hotel_early_late_checkout_product_id = fields.Many2one('product.product', string='Early Check-In / Late Check-Out Product')
    hotel_early_checkin_late_checkout_product_id = fields.Many2one('product.product', string='Early Check-In / Late Check-Out Product')
    hotel_no_show_product_id = fields.Many2one('product.product', string='No Show / Cancellation Product')
    hotel_laundry_product_id = fields.Many2one('product.product', string='Laundry Service Product')
    hotel_other_charge_product_id = fields.Many2one('product.product', string='Other Hotel Charge Product')
    hotel_restaurant_product_id = fields.Many2one('product.product', string='Restaurant Charge Product')
    hotel_breakfast_product_id = fields.Many2one('product.product', string='Breakfast Product')
    hotel_minibar_product_id = fields.Many2one('product.product', string='Minibar Product')
    hotel_default_minibar_product_id = fields.Many2one('product.product', string='Default Minibar Product')
    hotel_guest_amenity_product_id = fields.Many2one('product.product', string='Guest Amenity Product')
    hotel_housekeeping_supply_product_id = fields.Many2one('product.product', string='Housekeeping Supply Product')
    hotel_maintenance_spare_product_id = fields.Many2one('product.product', string='Maintenance Spare Part Product')

    def get_values(self):
        res = super().get_values()
        setup = self.env['hotel.config.setup'].sudo()
        for field_name, model_name in setup.CONFIG_FIELDS.items():
            if field_name in self._fields:
                res[field_name] = setup._get_config_record(self.env.company, field_name, model_name).id
        return res

    def set_values(self):
        super().set_values()
        setup = self.env['hotel.config.setup'].sudo()
        for field_name in setup.CONFIG_FIELDS:
            if field_name in self._fields:
                setup._set_config_value(self.env.company, field_name, self[field_name].id or False)


class HotelConfigSetup(models.Model):
    _name = 'hotel.config.setup'
    _description = 'Hotel Default Accounting Setup'

    CONFIG_FIELDS = {
        'hotel_group_deposit_account_id': 'account.account',
        'hotel_group_deposit_liability_account_id': 'account.account',
        'hotel_security_deposit_account_id': 'account.account',
        'hotel_security_deposit_liability_account_id': 'account.account',
        'hotel_room_revenue_account_id': 'account.account',
        'hotel_city_ledger_receivable_account_id': 'account.account',
        'hotel_default_sale_tax_id': 'account.tax',
        'hotel_default_purchase_tax_id': 'account.tax',
        'hotel_default_deposit_journal_id': 'account.journal',
        'hotel_cash_journal_id': 'account.journal',
        'hotel_bank_journal_id': 'account.journal',
        'hotel_sales_journal_id': 'account.journal',
        'hotel_purchase_journal_id': 'account.journal',
        'hotel_city_ledger_journal_id': 'account.journal',
        'hotel_accommodation_product_id': 'product.product',
        'hotel_room_charge_product_id': 'product.product',
        'hotel_advance_deposit_product_id': 'product.product',
        'hotel_group_deposit_product_id': 'product.product',
        'hotel_security_deposit_product_id': 'product.product',
        'hotel_extra_person_product_id': 'product.product',
        'hotel_early_late_checkout_product_id': 'product.product',
        'hotel_early_checkin_late_checkout_product_id': 'product.product',
        'hotel_no_show_product_id': 'product.product',
        'hotel_laundry_product_id': 'product.product',
        'hotel_other_charge_product_id': 'product.product',
        'hotel_restaurant_product_id': 'product.product',
        'hotel_breakfast_product_id': 'product.product',
        'hotel_minibar_product_id': 'product.product',
        'hotel_default_minibar_product_id': 'product.product',
        'hotel_guest_amenity_product_id': 'product.product',
        'hotel_housekeeping_supply_product_id': 'product.product',
        'hotel_maintenance_spare_product_id': 'product.product',
    }

    ACCOUNT_DEFINITIONS = [
        ('hotel_account_cash', '101100', 'Hotel Cash', 'asset_cash', True),
        ('hotel_account_bank', '102100', 'Hotel Bank', 'asset_cash', True),
        ('hotel_account_guest_advance_deposit', '210100', 'Guest Advance Deposit', 'liability_current', True),
        ('hotel_account_group_advance_deposit', '210110', 'Group Advance Deposit', 'liability_current', True),
        ('hotel_account_guest_security_deposit', '210120', 'Guest Security Deposit', 'liability_current', True),
        ('hotel_account_vat_payable', '210300', 'VAT Payable', 'liability_current', True),
        ('hotel_account_guest_receivable', '110300', 'Guest Receivable', 'asset_receivable', True),
        ('hotel_account_city_ledger_receivable', '110310', 'City Ledger Receivable', 'asset_receivable', True),
        ('hotel_account_pos_room_charge_receivable', '110320', 'POS Room Charge Receivable', 'asset_receivable', True),
        ('hotel_account_room_revenue', '410100', 'Room Revenue / Accommodation Revenue', 'income', False),
        ('hotel_account_fb_revenue', '410200', 'F&B Revenue', 'income', False),
        ('hotel_account_laundry_revenue', '410300', 'Laundry Revenue', 'income', False),
        ('hotel_account_minibar_revenue', '410400', 'Minibar Revenue', 'income', False),
        ('hotel_account_other_revenue', '410500', 'Other Hotel Revenue', 'income', False),
        ('hotel_account_no_show_revenue', '410600', 'No Show / Cancellation Revenue', 'income', False),
        ('hotel_account_early_late_revenue', '410700', 'Early Check-In / Late Check-Out Revenue', 'income', False),
        ('hotel_account_extra_person_revenue', '410800', 'Extra Person Revenue', 'income', False),
        ('hotel_account_room_operating_expense', '510100', 'Room Operating Expense', 'expense', False),
        ('hotel_account_housekeeping_supplies_expense', '510200', 'Housekeeping Supplies Expense', 'expense', False),
        ('hotel_account_laundry_expense', '510300', 'Laundry Expense', 'expense', False),
        ('hotel_account_minibar_cogs', '510400', 'Minibar Cost of Goods Sold', 'expense', False),
        ('hotel_account_maintenance_expense', '510500', 'Maintenance Expense', 'expense', False),
        ('hotel_account_guest_amenities_expense', '510600', 'Guest Amenities Expense', 'expense', False),
    ]

    PRODUCT_DEFINITIONS = [
        ('hotel_product_accommodation', 'Accommodation / Room Charge', 'service', 'hotel_account_room_revenue', False, True),
        ('hotel_product_advance_deposit', 'Advance Deposit', 'service', 'hotel_account_guest_advance_deposit', False, False),
        ('hotel_product_group_advance_deposit', 'Group Advance Deposit', 'service', 'hotel_account_group_advance_deposit', False, False),
        ('hotel_product_security_deposit', 'Security Deposit', 'service', 'hotel_account_guest_security_deposit', False, False),
        ('hotel_product_extra_person', 'Extra Person Charge', 'service', 'hotel_account_extra_person_revenue', False, True),
        ('hotel_product_early_late_checkout', 'Early Check-In / Late Check-Out', 'service', 'hotel_account_early_late_revenue', False, True),
        ('hotel_product_no_show', 'No Show / Cancellation Charge', 'service', 'hotel_account_no_show_revenue', False, True),
        ('hotel_product_laundry_service', 'Laundry Service', 'service', 'hotel_account_laundry_revenue', False, True),
        ('hotel_product_other_hotel_charge', 'Other Hotel Charge', 'service', 'hotel_account_other_revenue', False, True),
        ('hotel_product_restaurant_charge', 'Restaurant Charge', 'service', 'hotel_account_fb_revenue', False, True),
        ('hotel_product_breakfast', 'Breakfast', 'service', 'hotel_account_fb_revenue', False, True),
        ('hotel_product_minibar_item', 'Minibar Item', 'consu', 'hotel_account_minibar_revenue', 'hotel_account_minibar_cogs', True),
        ('hotel_product_guest_amenity', 'Guest Amenity', 'consu', False, 'hotel_account_guest_amenities_expense', False),
        ('hotel_product_housekeeping_supply', 'Housekeeping Supply', 'consu', False, 'hotel_account_housekeeping_supplies_expense', False),
        ('hotel_product_maintenance_spare_part', 'Maintenance Spare Part', 'consu', False, 'hotel_account_maintenance_expense', False),
    ]

    JOURNAL_DEFINITIONS = [
        ('hotel_journal_cash', 'Hotel Cash', 'HCASH', 'cash', 'hotel_account_cash'),
        ('hotel_journal_bank', 'Hotel Bank', 'HBANK', 'bank', 'hotel_account_bank'),
        ('hotel_journal_sales', 'Hotel Sales Journal', 'HSALE', 'sale', False),
        ('hotel_journal_purchase', 'Hotel Purchase Journal', 'HPUR', 'purchase', False),
        ('hotel_journal_deposit', 'Hotel Deposit Journal', 'HDEP', 'cash', 'hotel_account_cash'),
        ('hotel_journal_city_ledger', 'City Ledger Journal', 'HCL', 'sale', False),
    ]

    @api.model
    def _xmlid(self, base, company):
        return 'hotel_management.%s_%s' % (base, company.id)

    @api.model
    def _config_key(self, company, field_name):
        return 'hotel_management.%s.%s' % (field_name, company.id)

    @api.model
    def _get_config_value(self, company, field_name):
        return self.env['ir.config_parameter'].sudo().get_param(self._config_key(company, field_name))

    @api.model
    def _set_config_value(self, company, field_name, value):
        key = self._config_key(company, field_name)
        Param = self.env['ir.config_parameter'].sudo()
        if value:
            Param.set_param(key, int(value))
        else:
            Param.set_param(key, '')

    @api.model
    def _get_config_record(self, company, field_name, model_name=None):
        model_name = model_name or self.CONFIG_FIELDS.get(field_name)
        record_id = self._get_config_value(company, field_name)
        if not model_name or not record_id:
            return self.env[model_name] if model_name else self.env['ir.model'].browse()
        try:
            return self.env[model_name].sudo().browse(int(record_id)).exists()
        except (TypeError, ValueError):
            return self.env[model_name]

    @api.model
    def _set_config_if_empty(self, company, field_name, record):
        if not record or self._get_config_value(company, field_name):
            return False
        self._set_config_value(company, field_name, record.id)
        return True

    @api.model
    def _get_by_xmlid(self, base, company):
        return self.env.ref(self._xmlid(base, company), raise_if_not_found=False)

    @api.model
    def _set_xmlid(self, record, base, company):
        xmlid = '%s_%s' % (base, company.id)
        existing = self.env['ir.model.data'].sudo().search([
            ('module', '=', 'hotel_management'),
            ('name', '=', xmlid),
        ], limit=1)
        values = {
            'module': 'hotel_management',
            'name': xmlid,
            'model': record._name,
            'res_id': record.id,
            'noupdate': True,
        }
        if existing:
            existing.write(values)
        else:
            self.env['ir.model.data'].sudo().create(values)

    @api.model
    def _account_code_domain(self, code, company):
        return [
            ('code', '=', code),
            ('company_ids', 'in', company.id),
        ]

    @api.model
    def _get_or_create_account(self, company, base, code, name, account_type, reconcile=False):
        Account = self.env['account.account'].with_company(company).sudo()
        account = self._get_by_xmlid(base, company)
        if not account:
            account = Account.search(self._account_code_domain(code, company), limit=1)
        if not account:
            account = Account.with_context(defer_account_code_checks=True).create({
                'name': name,
                'code': code,
                'account_type': account_type,
                'reconcile': reconcile,
                'company_ids': [Command.set(company.ids)],
            })
            _logger.info("Created hotel default account %s %s for company %s", code, name, company.display_name)
        self._set_xmlid(account, base, company)
        return account

    @api.model
    def _get_default_tax_country(self, company):
        return (
            company.account_fiscal_country_id
            or company.country_id
            or self.env.ref('base.kh', raise_if_not_found=False)
            or self.env['res.country'].sudo().search([], limit=1)
        )

    @api.model
    def _get_or_create_tax_group(self, company):
        TaxGroup = self.env['account.tax.group'].with_company(company).sudo()
        base = 'hotel_tax_group_vat_10'
        tax_group = self._get_by_xmlid(base, company)
        if tax_group and (tax_group.name or '').strip().lower() == 'vat 10%':
            return tax_group

        country = self._get_default_tax_country(company)
        domain = [('name', '=ilike', 'VAT 10%')]
        if 'company_id' in TaxGroup._fields:
            domain.append(('company_id', '=', company.id))
        if 'country_id' in TaxGroup._fields and country:
            domain.append(('country_id', '=', country.id))

        tax_group = TaxGroup.search(domain, limit=1)
        if not tax_group:
            vals = {'name': 'VAT 10%'}
            if 'company_id' in TaxGroup._fields:
                vals['company_id'] = company.id
            if 'country_id' in TaxGroup._fields and country:
                vals['country_id'] = country.id
            tax_group = TaxGroup.create(vals)
            _logger.info("Created hotel default VAT 10%% tax group for company %s", company.display_name)

        self._set_xmlid(tax_group, base, company)
        return tax_group

    @api.model
    def _get_or_create_tax(self, company, *, purchase=False):
        Tax = self.env['account.tax'].with_company(company).sudo()
        tax_use = 'purchase' if purchase else 'sale'
        base = 'hotel_tax_vat_10_purchase' if purchase else 'hotel_tax_vat_10_sale'
        tax = self._get_by_xmlid(base, company)
        if not tax:
            tax = Tax.search([
                ('type_tax_use', '=', tax_use),
                ('company_id', '=', company.id),
                ('amount_type', '=', 'percent'),
                ('amount', '=', 10.0),
            ], limit=1)
        if not tax:
            tax_group = self._get_or_create_tax_group(company)
            vals = {
                'name': 'VAT 10%% %s' % ('Purchase' if purchase else 'Sales Tax'),
                'type_tax_use': tax_use,
                'amount_type': 'percent',
                'amount': 10.0,
                'company_id': company.id,
                'tax_group_id': tax_group.id,
            }
            if 'country_id' in Tax._fields:
                vals['country_id'] = tax_group.country_id.id or self._get_default_tax_country(company).id
            tax = Tax.create(vals)
            _logger.info("Created hotel default %s VAT 10%% tax for company %s", tax_use, company.display_name)
        else:
            tax_group = self._get_or_create_tax_group(company)
            write_vals = {}
            if tax.tax_group_id != tax_group:
                write_vals['tax_group_id'] = tax_group.id
            if 'country_id' in tax._fields and not tax.country_id:
                write_vals['country_id'] = tax_group.country_id.id or self._get_default_tax_country(company).id
            if write_vals:
                tax.write(write_vals)
        self._set_xmlid(tax, base, company)
        return tax

    @api.model
    def _configure_tax_accounts(self, tax, tax_account):
        if not tax or not tax_account:
            return
        tax_lines = (tax.invoice_repartition_line_ids | tax.refund_repartition_line_ids).filtered(
            lambda line: line.repartition_type == 'tax'
        )
        lines_to_update = tax_lines.filtered(lambda line: line.account_id != tax_account)
        if lines_to_update:
            lines_to_update.write({'account_id': tax_account.id})
            _logger.info(
                "Configured tax %s to post tax repartition lines to %s %s",
                tax.display_name,
                tax_account.code,
                tax_account.name,
            )

    @api.model
    def _get_or_create_product(self, company, base, name, product_type, income_account, expense_account, sale_tax):
        Product = self.env['product.product'].sudo()
        product = self._get_by_xmlid(base, company)
        if not product:
            product = Product.search([('name', '=', name)], limit=1)
        vals = {
            'name': name,
            'type': product_type,
            'sale_ok': True,
            'purchase_ok': bool(expense_account and not income_account),
        }
        if income_account:
            vals['property_account_income_id'] = income_account.id
        if expense_account:
            vals['property_account_expense_id'] = expense_account.id
        if sale_tax:
            vals['taxes_id'] = [Command.set(sale_tax.ids)]
        else:
            vals['taxes_id'] = [Command.clear()]

        if not product:
            product = Product.create(vals)
            _logger.info("Created hotel default product %s", name)
        else:
            write_vals = {}
            for field_name, value in vals.items():
                if field_name in ('taxes_id',):
                    continue
                if field_name in product._fields and not product[field_name]:
                    write_vals[field_name] = value
            if not product.taxes_id and 'taxes_id' in vals:
                write_vals['taxes_id'] = vals['taxes_id']
            if income_account and not product.property_account_income_id:
                write_vals['property_account_income_id'] = income_account.id
            if expense_account and not product.property_account_expense_id:
                write_vals['property_account_expense_id'] = expense_account.id
            if write_vals:
                product.write(write_vals)
        self._set_xmlid(product, base, company)
        return product

    @api.model
    def _configure_direct_liquidity_payment_lines(self, journal, liquidity_account):
        if not journal or not liquidity_account or journal.type not in ('cash', 'bank'):
            return
        write_vals = {'payment_account_id': liquidity_account.id}
        payment_lines = journal.inbound_payment_method_line_ids | journal.outbound_payment_method_line_ids
        payment_lines.filtered(lambda line: line.payment_account_id != liquidity_account).write(write_vals)

    @api.model
    def _get_or_create_journal(self, company, base, name, code, journal_type, liquidity_account=False):
        Journal = self.env['account.journal'].with_company(company).sudo()
        journal = self._get_by_xmlid(base, company)
        if not journal:
            journal = Journal.search([
                ('company_id', '=', company.id),
                '|',
                ('code', '=', code),
                ('name', '=ilike', name),
            ], limit=1)
        if not journal:
            vals = {
                'name': name,
                'code': code[:5],
                'type': journal_type,
                'company_id': company.id,
            }
            if liquidity_account:
                vals['default_account_id'] = liquidity_account.id
            journal = Journal.create(vals)
            _logger.info("Created hotel default journal %s for company %s", name, company.display_name)
        elif liquidity_account and journal.default_account_id != liquidity_account:
            journal.write({'default_account_id': liquidity_account.id})
        self._configure_direct_liquidity_payment_lines(journal, liquidity_account)
        self._set_xmlid(journal, base, company)
        return journal

    @api.model
    def _company_field_column_exists(self, field_name):
        field = self.env['res.company']._fields.get(field_name)
        if not field or field.store is False:
            return False
        self.env.cr.execute("""
            SELECT 1
              FROM information_schema.columns
             WHERE table_name = 'res_company'
               AND column_name = %s
        """, [field_name])
        return bool(self.env.cr.fetchone())

    @api.model
    def _write_company_field_if_empty(self, company, field_name, record):
        if not record or field_name not in company._fields or not self._company_field_column_exists(field_name):
            return False
        company.flush_recordset([field_name])
        self.env.cr.execute(
            "SELECT %s FROM res_company WHERE id = %%s" % field_name,
            [company.id],
        )
        current_value = self.env.cr.fetchone()[0]
        if current_value:
            return False
        company.sudo().write({field_name: record.id})
        return True

    @api.model
    def _write_defaults_if_empty(self, company, accounts, products, taxes, journals):
        defaults = {
            'hotel_cash_journal_id': journals['hotel_journal_cash'],
            'hotel_bank_journal_id': journals['hotel_journal_bank'],
            'hotel_group_deposit_account_id': accounts['hotel_account_group_advance_deposit'],
            'hotel_group_deposit_liability_account_id': accounts['hotel_account_group_advance_deposit'],
            'hotel_security_deposit_account_id': accounts['hotel_account_guest_security_deposit'],
            'hotel_security_deposit_liability_account_id': accounts['hotel_account_guest_security_deposit'],
            'hotel_room_revenue_account_id': accounts['hotel_account_room_revenue'],
            'hotel_city_ledger_receivable_account_id': accounts['hotel_account_city_ledger_receivable'],
            'hotel_default_sale_tax_id': taxes['sale'],
            'hotel_default_purchase_tax_id': taxes['purchase'],
            'hotel_default_deposit_journal_id': journals['hotel_journal_deposit'],
            'hotel_sales_journal_id': journals['hotel_journal_sales'],
            'hotel_purchase_journal_id': journals['hotel_journal_purchase'],
            'hotel_city_ledger_journal_id': journals['hotel_journal_city_ledger'],
            'hotel_accommodation_product_id': products['hotel_product_accommodation'],
            'hotel_room_charge_product_id': products['hotel_product_accommodation'],
            'hotel_advance_deposit_product_id': products['hotel_product_advance_deposit'],
            'hotel_group_deposit_product_id': products['hotel_product_group_advance_deposit'],
            'hotel_security_deposit_product_id': products['hotel_product_security_deposit'],
            'hotel_extra_person_product_id': products['hotel_product_extra_person'],
            'hotel_early_late_checkout_product_id': products['hotel_product_early_late_checkout'],
            'hotel_early_checkin_late_checkout_product_id': products['hotel_product_early_late_checkout'],
            'hotel_no_show_product_id': products['hotel_product_no_show'],
            'hotel_laundry_product_id': products['hotel_product_laundry_service'],
            'hotel_other_charge_product_id': products['hotel_product_other_hotel_charge'],
            'hotel_restaurant_product_id': products['hotel_product_restaurant_charge'],
            'hotel_breakfast_product_id': products['hotel_product_breakfast'],
            'hotel_minibar_product_id': products['hotel_product_minibar_item'],
            'hotel_default_minibar_product_id': products['hotel_product_minibar_item'],
            'hotel_guest_amenity_product_id': products['hotel_product_guest_amenity'],
            'hotel_housekeeping_supply_product_id': products['hotel_product_housekeeping_supply'],
            'hotel_maintenance_spare_product_id': products['hotel_product_maintenance_spare_part'],
        }
        written = [field_name for field_name, record in defaults.items() if self._set_config_if_empty(company, field_name, record)]
        if self._write_company_field_if_empty(company, 'hotel_advance_deposit_account_id', accounts['hotel_account_guest_advance_deposit']):
            written.append('hotel_advance_deposit_account_id')
        if written:
            _logger.info("Filled empty hotel default configuration values for company %s: %s", company.display_name, sorted(written))

    @api.model
    def setup_default_hotel_accounting(self):
        companies = self.env.companies or self.env.company
        for company in companies:
            accounts = {}
            for base, code, name, account_type, reconcile in self.ACCOUNT_DEFINITIONS:
                accounts[base] = self._get_or_create_account(company, base, code, name, account_type, reconcile)

            taxes = {
                'sale': self._get_or_create_tax(company, purchase=False),
                'purchase': self._get_or_create_tax(company, purchase=True),
            }
            self._configure_tax_accounts(taxes['sale'], accounts['hotel_account_vat_payable'])

            products = {}
            for base, name, product_type, income_base, expense_base, use_sale_tax in self.PRODUCT_DEFINITIONS:
                products[base] = self._get_or_create_product(
                    company,
                    base,
                    name,
                    product_type,
                    accounts[income_base] if income_base else False,
                    accounts[expense_base] if expense_base else False,
                    taxes['sale'] if use_sale_tax else False,
                )

            journals = {}
            for base, name, code, journal_type, liquidity_account_base in self.JOURNAL_DEFINITIONS:
                journals[base] = self._get_or_create_journal(
                    company,
                    base,
                    name,
                    code,
                    journal_type,
                    accounts[liquidity_account_base] if liquidity_account_base else False,
                )

            self._write_defaults_if_empty(company, accounts, products, taxes, journals)

        return {
            'type': 'ir.actions.client',
            'tag': 'display_notification',
            'params': {
                'title': _('Hotel Accounting Setup'),
                'message': _('Default hotel accounting setup completed.'),
                'type': 'success',
                'sticky': False,
            },
        }
