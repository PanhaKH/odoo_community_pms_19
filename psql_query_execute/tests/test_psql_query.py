import io
import json
import zipfile

from odoo import fields
from odoo.tests import TransactionCase, tagged
from odoo.exceptions import ValidationError


class FakeResponse:

    def __init__(self):
        self.stream = io.BytesIO()


@tagged('post_install', '-at_install')
class TestPsqlQuery(TransactionCase):

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.query = cls.env['psql.query'].create({
            'name': 'Partner Query',
            'query_name': (
                "SELECT 'Alpha'::varchar AS partner_name, "
                "7::integer AS partner_count"
            ),
        })

    def test_action_execute_query_sets_html_result(self):
        self.query.action_execute_query()

        self.assertIn('partner_name', self.query.query_result)
        self.assertIn('partner_count', self.query.query_result)
        self.assertIn('Alpha', self.query.query_result)
        self.assertIn('7', self.query.query_result)
        self.assertEqual(self.query.last_execution_status, 'success')
        self.assertEqual(self.query.returned_row_count, 1)
        self.assertEqual(
            self.query.result_data['columns'],
            ['partner_name', 'partner_count'],
        )

    def test_action_run_business_report_executes_and_opens_pdf_preview(self):
        action = self.query.action_run_business_report()

        self.assertEqual(self.query.last_execution_status, 'success')
        self.assertEqual(self.query.returned_row_count, 1)
        self.assertEqual(action['type'], 'ir.actions.client')
        self.assertEqual(action['tag'], 'psql_query_execute.pdf_preview')
        self.assertIn(
            '/report/pdf/psql_query_execute.report_sql_business_document/',
            action['params']['url'],
        )

    def test_business_report_renders_pdf(self):
        self.query.action_run_business_report()
        pdf, output_type = self.env['ir.actions.report'].with_context(
            force_report_rendering=True,
        )._render_qweb_pdf(
            'psql_query_execute.action_report_sql_business',
            res_ids=self.query.ids,
        )

        self.assertEqual(output_type, 'pdf')
        self.assertTrue(pdf.startswith(b'%PDF'))

    def test_saved_report_defaults_to_my_reports(self):
        my_reports = self.env.ref('psql_query_execute.report_category_my_reports')
        self.assertEqual(self.query.category_id, my_reports)

    def test_saved_report_defaults_to_automatic_paper(self):
        self.assertEqual(self.query.paper_orientation, 'auto')

    def test_report_template_applies_saved_landscape_orientation(self):
        self.query.paper_orientation = 'landscape'
        html, output_type = self.env['ir.actions.report']._render_qweb_html(
            'psql_query_execute.action_report_sql_business',
            self.query.ids,
        )

        self.assertEqual(output_type, 'html')
        self.assertIn(b'data-report-landscape="True"', html)
        self.assertIn(b'qsql-report-header', html)
        self.assertIn(b'qsql-sticky-report-head', html)
        self.assertIn(b'qsql-report-title', html)
        self.assertIn(b'qsql-filter-table', html)
        self.assertIn(b'qsql-report-list', html)
        self.assertIn(b'qsql-page-footer', html)
        self.assertIn(b'SQL Management Report', html)
        self.assertIn(b'Printed by:', html)
        self.assertIn(b'Printed date:', html)
        self.assertIn(b'End of Report', html)

    def test_report_presentation_uses_business_labels_and_formatting(self):
        self.query.action_execute_query()
        presentation = self.query._get_report_presentation()

        self.assertEqual(
            [column['label'] for column in presentation['columns']],
            ['Partner Name', 'Partner Count'],
        )
        self.assertEqual(presentation['row_count'], 1)
        self.assertEqual(presentation['groups'][0]['rows'][0][1]['value'], '7')
        self.assertEqual(presentation['groups'][0]['rows'][0][1]['alignment'], 'right')
        self.assertAlmostEqual(
            sum(column['width_percent'] for column in presentation['columns']),
            100.0,
            places=2,
        )
        self.assertEqual(presentation['density'], 'normal')

    def test_runtime_parameter_opens_dialog_and_binds_safely(self):
        self.query.query_name = (
            "SELECT 'Alpha'::varchar AS partner_name, 7::integer AS partner_count "
            "WHERE (%(partner_name)s IS NULL OR 'Alpha' = %(partner_name)s)"
        )
        definition = self.env['psql.query.filter.definition'].create({
            'query_id': self.query.id,
            'name': 'Partner Name',
            'technical_name': 'partner_name',
            'filter_type': 'text',
        })

        action = self.query.action_run_business_report()
        self.assertEqual(action['res_model'], 'psql.query.filter.wizard')
        wizard = self.env['psql.query.filter.wizard'].browse(action['res_id'])
        wizard._populate_filter_lines()
        wizard.filter_line_ids.write({
            'apply_parameter': True,
            'value_text': "Alpha%' OR 1=1 --",
        })
        payload = self.query._execute_and_store(wizard._runtime_parameter_payload())

        self.assertTrue(payload['ok'])
        self.assertEqual(payload['row_count'], 0)
        self.assertEqual(self.query.last_filter_values[0]['definition_id'], definition.id)
        self.assertIn('Partner Name:', self.query.last_filter_summary)

    def test_runtime_date_range_and_modulo_query(self):
        report = self.env['psql.query'].create({
            'name': 'Date Filter Test',
            'query_name': (
                "SELECT gs, DATE '2026-07-01' + gs AS business_date "
                "FROM generate_series(1, 10) gs WHERE gs % 2 = 0 "
                "AND (DATE '2026-07-01' + gs) BETWEEN %(period_from)s AND %(period_to)s"
            ),
        })
        self.env['psql.query.filter.definition'].create({
            'query_id': report.id,
            'name': 'Business Period',
            'technical_name': 'period',
            'filter_type': 'date_range',
        })

        payload = report._execute_and_store({
            'values': {
                'period_from': fields.Date.from_string('2026-07-04'),
                'period_to': fields.Date.from_string('2026-07-09'),
            },
            'summary': 'Business Period: 2026-07-04 to 2026-07-09',
        })

        self.assertTrue(payload['ok'])
        self.assertEqual(payload['row_count'], 3)

    def test_roommaster_parameter_detection_and_text_binding(self):
        report = self.env['psql.query'].create({
            'name': 'roomMaster Text Test',
            'query_name': (
                "SELECT 'Alice'::varchar AS guest_name "
                "WHERE 'Alice' = {?Guest Name}"
            ),
        })

        report.action_detect_roommaster_parameters()
        definition = report.filter_definition_ids

        self.assertEqual(definition.name, 'Guest Name')
        self.assertEqual(definition.technical_name, 'guest_name')
        self.assertEqual(definition.filter_type, 'text')

        payload = report._execute_and_store({
            'values': {'guest_name': 'Alice'},
            'summary': 'Guest Name: Alice',
        })

        self.assertTrue(payload['ok'])
        self.assertEqual(payload['row_count'], 1)

    def test_auto_configure_named_date_range_placeholders(self):
        report = self.env['psql.query'].create({
            'name': 'Named Date Range Test',
            'query_name': (
                "SELECT DATE '2026-07-04' AS business_date "
                "WHERE DATE '2026-07-04' BETWEEN %(date_from)s AND %(date_to)s"
            ),
        })

        report.action_auto_configure_sql_parameters()
        definition = report.filter_definition_ids

        self.assertEqual(definition.name, 'Date')
        self.assertEqual(definition.technical_name, 'date')
        self.assertEqual(definition.filter_type, 'date_range')

        payload = report._execute_and_store({
            'values': {
                'date_from': fields.Date.from_string('2026-07-01'),
                'date_to': fields.Date.from_string('2026-07-15'),
            },
            'summary': 'Date: 2026-07-01 to 2026-07-15',
        })

        self.assertTrue(payload['ok'])
        self.assertEqual(payload['row_count'], 1)

    def test_roommaster_date_range_repeated_parameter_and_defaults(self):
        report = self.env['psql.query'].create({
            'name': 'roomMaster Range Test',
            'query_name': (
                "SELECT gs "
                "FROM generate_series(1, 5) gs "
                "WHERE DATE '2026-07-01' + gs BETWEEN {?Stay Date Range%%} "
                "AND {?Rate Code[RACK]} = {?Rate Code[RACK]}"
            ),
        })

        report.action_detect_roommaster_parameters()
        definitions = {item.technical_name: item for item in report.filter_definition_ids}

        self.assertEqual(definitions['stay_date_range'].filter_type, 'date_range')
        self.assertEqual(definitions['rate_code'].default_text, 'RACK')

        payload = report._execute_and_store({
            'values': {
                'stay_date_range_from': fields.Date.from_string('2026-07-03'),
                'stay_date_range_to': fields.Date.from_string('2026-07-05'),
                'rate_code': 'RACK',
            },
            'summary': 'Stay Date Range: 2026-07-03 to 2026-07-05',
        })

        self.assertTrue(payload['ok'])
        self.assertEqual(payload['row_count'], 3)

    def test_roommaster_boolean_integer_decimal_and_invalid_date_range(self):
        report = self.env['psql.query'].create({
            'name': 'roomMaster Type Test',
            'query_name': (
                "SELECT {?Include Cancelled%@B}::boolean AS include_cancelled, "
                "{?Number of Guests%@n5}::integer AS guest_count, "
                "{?Minimum Amount%@n10.2}::numeric AS minimum_amount, "
                "{?Stay Date Range%%} AS marker"
            ),
        })
        report.action_detect_roommaster_parameters()
        definitions = {item.technical_name: item for item in report.filter_definition_ids}

        self.assertEqual(definitions['include_cancelled'].filter_type, 'boolean')
        self.assertEqual(definitions['number_of_guests'].filter_type, 'integer')
        self.assertEqual(definitions['minimum_amount'].filter_type, 'decimal')

        payload = report._execute_and_store({
            'values': {
                'include_cancelled': True,
                'number_of_guests': 2,
                'minimum_amount': 10.5,
                'stay_date_range_from': fields.Date.from_string('2026-07-10'),
                'stay_date_range_to': fields.Date.from_string('2026-07-01'),
            },
        })

        self.assertFalse(payload['ok'])
        self.assertIn('From Date cannot be after Date To', payload['error'])

    def test_multi_selection_expands_bound_placeholders_safely(self):
        report = self.env['psql.query'].create({
            'name': 'Multi Selection Test',
            'query_name': (
                "SELECT state FROM (VALUES ('Draft'), ('Confirmed'), ('Cancelled')) AS s(state) "
                "WHERE state IN ({?Status\\?\"Draft|Confirmed|Completed|Cancelled\"})"
            ),
        })
        report.action_detect_roommaster_parameters()
        definition = report.filter_definition_ids

        self.assertEqual(definition.filter_type, 'multi_selection')
        self.assertEqual(sorted(definition.option_ids.mapped('value')), [
            'Cancelled', 'Completed', 'Confirmed', 'Draft',
        ])

        payload = report._execute_and_store({
            'values': {'status': ['Draft', 'Confirmed']},
            'summary': 'Status: Draft, Confirmed',
        })

        self.assertTrue(payload['ok'])
        self.assertEqual(payload['row_count'], 2)

    def test_dynamic_sql_and_table_lookup_options(self):
        sql_definition = self.env['psql.query.filter.definition'].create({
            'query_id': self.query.id,
            'name': 'Status',
            'technical_name': 'status',
            'filter_type': 'selection',
            'source_type': 'sql',
            'sql_lookup_query': "SELECT 'draft' AS value, 'Draft' AS label",
        })
        table_definition = self.env['psql.query.filter.definition'].create({
            'query_id': self.query.id,
            'name': 'Partner Name',
            'technical_name': 'partner_name',
            'filter_type': 'selection',
            'source_type': 'table',
            'source_table': 'res_partner',
            'source_field': 'name',
        })

        sql_definition._sync_selection_options()
        table_definition._sync_selection_options()

        self.assertEqual(sql_definition.option_ids[:1].value, 'draft')
        self.assertTrue(table_definition.option_ids)

    def test_required_empty_multi_selection_and_sql_injection_are_blocked(self):
        report = self.env['psql.query'].create({
            'name': 'Injection Parameter Test',
            'query_name': (
                "SELECT 'safe'::varchar AS value "
                "WHERE 'safe' = {?Guest Name} "
                "AND 'Draft' IN ({?Status\\?\"Draft|Confirmed\"})"
            ),
        })
        report.action_detect_roommaster_parameters()
        report.filter_definition_ids.write({'required': True})

        empty_payload = report._execute_and_store({
            'values': {'guest_name': 'safe', 'status': []},
        })
        self.assertFalse(empty_payload['ok'])
        self.assertIn('required parameter', empty_payload['error'])

        payload = report._execute_and_store({
            'values': {
                'guest_name': "safe' OR 1=1 --",
                'status': ['Draft'],
            },
        })

        self.assertTrue(payload['ok'])
        self.assertEqual(payload['row_count'], 0)

    def test_nested_category_uses_complete_path(self):
        parent = self.env['psql.query.category'].create({'name': 'Inventory Test'})
        child = self.env['psql.query.category'].create({
            'name': 'Stock',
            'parent_id': parent.id,
        })
        self.assertEqual(child.complete_name, 'Inventory Test / Stock')

    def test_saved_report_requires_category(self):
        with self.assertRaises(ValidationError):
            self.env['psql.query'].create({
                'name': 'Uncategorized',
                'query_name': 'SELECT 1',
                'category_id': False,
            })

    def test_interactive_session_conversion_assigns_my_reports(self):
        session = self.env['psql.query'].with_context(interactive_sql=True).create({
            'name': 'Interactive Test',
            'query_name': 'SELECT 1',
            'is_interactive_session': True,
            'category_id': False,
        })
        session.write({'is_interactive_session': False})
        self.assertEqual(
            session.category_id,
            self.env.ref('psql_query_execute.report_category_my_reports'),
        )

    def test_duplicate_keeps_report_category(self):
        action = self.query.action_duplicate_report()
        duplicate = self.env['psql.query'].browse(action['res_id'])
        self.assertEqual(duplicate.category_id, self.query.category_id)

    def test_valid_cte_query(self):
        self.query.query_name = (
            'WITH partners AS ('
            ' SELECT id, name FROM res_partner'
            ') SELECT * FROM partners LIMIT 20;'
        )
        payload = self.query.execute_interactive_query()

        self.assertTrue(payload['ok'])
        self.assertEqual(payload['columns'], ['id', 'name'])
        self.assertLessEqual(payload['row_count'], 20)

    def test_dangerous_and_multiple_statements_are_blocked(self):
        blocked = [
            'DELETE FROM res_partner;',
            "UPDATE res_partner SET name = 'Test';",
            'DROP TABLE res_partner;',
            'CREATE TABLE test_table (id INTEGER);',
            'SELECT * FROM res_partner; SELECT * FROM res_users;',
            'WITH removed AS (DELETE FROM res_partner RETURNING id) SELECT * FROM removed;',
            'SELECT pg_read_file(\'/etc/passwd\');',
        ]
        for statement in blocked:
            with self.subTest(statement=statement):
                self.query.query_name = statement
                payload = self.query.execute_interactive_query()
                self.assertFalse(payload['ok'])
                self.assertEqual(payload['status'], 'error')
                self.env.cr.execute('SELECT 1')
                self.assertEqual(self.env.cr.fetchone()[0], 1)

    def test_keyword_hidden_in_comment_is_blocked(self):
        self.query.query_name = 'SELECT 1 /* DROP TABLE res_partner */;'
        payload = self.query.execute_interactive_query()
        self.assertFalse(payload['ok'])
        self.assertIn('comment', payload['error'].lower())

    def test_get_report_data_returns_headers_and_rows(self):
        data = self.query._get_report_data()

        self.assertEqual(data['model'], 'psql.query')
        self.assertFalse(data['no_value'])
        self.assertEqual(data['header'], ['Partner Name', 'Partner Count'])
        self.assertEqual(data['form'], [('Alpha', '7')])
        self.assertEqual(data['ids'], self.query)
        self.assertTrue(data['date'])

    def test_action_print_query_result_xlsx(self):
        action = self.query.action_print_query_result_xlsx()
        report_data = action['data']
        options = json.loads(report_data['options'])

        self.assertEqual(action['type'], 'ir.actions.report')
        self.assertEqual(action['report_type'], 'xlsx')
        self.assertEqual(report_data['model'], 'psql.query')
        self.assertEqual(report_data['output_format'], 'xlsx')
        self.assertEqual(report_data['report_name'], 'Partner Query')
        self.assertEqual(options['header'], ['Partner Name', 'Partner Count'])
        self.assertEqual(options['form'], [['Alpha', '7']])

    def test_get_xlsx_report_writes_workbook_to_response(self):
        response = FakeResponse()
        data = {
            'header': ['partner_name', 'partner_count'],
            'form': [('Alpha', 7), ({'nested': 'value'}, None)],
            'date': '2026-06-09',
        }

        self.query.get_xlsx_report(data, response)

        content = response.stream.getvalue()
        self.assertGreater(len(content), 0)
        self.assertTrue(zipfile.is_zipfile(io.BytesIO(content)))

    def test_sql_wizard_previews_without_executing_and_inserts_explicitly(self):
        report = self.env['psql.query'].create({
            'name': 'Wizard Report',
            'query_name': 'SELECT ',
        })
        wizard = self.env['psql.query.wizard'].create({
            'query_id': report.id,
            'schema_name': 'public',
            'table_alias': 'rp',
            'row_limit': 100,
            'column_line_ids': [
                (0, 0, {'selected': True, 'column_name': 'id', 'data_type': 'integer'}),
                (0, 0, {'selected': True, 'column_name': 'name', 'data_type': 'character varying'}),
            ],
            'filter_line_ids': [
                (0, 0, {'field_name': 'rp.active', 'operator': '=', 'value': 'true'}),
            ],
            'order_line_ids': [
                (0, 0, {'field_name': 'rp.name', 'direction': 'asc', 'nulls': 'last'}),
            ],
        })
        wizard._load_table_options()
        wizard.table_option_id = wizard.table_option_ids.filtered(
            lambda option: option.schema_name == 'public' and option.table_name == 'res_partner'
        )[:1]

        wizard.action_generate_query()

        self.assertEqual(report.query_name, 'SELECT ')
        self.assertTrue(wizard.preview_ready)
        self.assertIn('FROM "public"."res_partner" AS "rp"', wizard.sql_preview)
        self.assertIn('WHERE\n    "rp"."active" =', wizard.sql_preview)
        self.assertIn('ORDER BY\n    "rp"."name" ASC NULLS LAST', wizard.sql_preview)
        self.assertTrue(wizard.sql_preview.endswith('LIMIT 100;'))

        wizard.action_insert_into_editor()
        self.assertEqual(report.query_name, wizard.sql_preview)

    def test_sql_wizard_requires_replace_or_append_for_existing_sql(self):
        report = self.env['psql.query'].create({
            'name': 'Existing SQL',
            'query_name': 'SELECT 1;',
        })
        wizard = self.env['psql.query.wizard'].create({
            'query_id': report.id,
            'schema_name': 'public',
            'table_alias': 'rp',
            'row_limit': 10,
            'column_line_ids': [(0, 0, {'selected': True, 'column_name': 'id'})],
        })
        wizard._load_table_options()
        wizard.table_option_id = wizard.table_option_ids.filtered(
            lambda option: option.schema_name == 'public' and option.table_name == 'res_partner'
        )[:1]

        with self.assertRaises(ValidationError):
            wizard.action_insert_into_editor()
        self.assertEqual(report.query_name, 'SELECT 1;')

        wizard.insert_mode = 'append'
        wizard.action_insert_into_editor()
        self.assertTrue(report.query_name.startswith('SELECT 1;\n\nSELECT'))

    def test_sql_wizard_loads_live_tables_and_column_metadata(self):
        report = self.env['psql.query'].create({'name': 'Metadata', 'query_name': 'SELECT '})
        wizard = self.env['psql.query.wizard'].create({'query_id': report.id})
        wizard._load_table_options()
        partner = wizard.table_option_ids.filtered(
            lambda option: option.schema_name == 'public' and option.table_name == 'res_partner'
        )[:1]

        self.assertTrue(partner)
        self.assertEqual(partner.object_type, 'table')
        wizard.table_option_id = partner
        wizard._onchange_table_option_id()

        id_column = wizard.column_line_ids.filtered(lambda column: column.column_name == 'id')
        company_column = wizard.column_line_ids.filtered(lambda column: column.column_name == 'company_id')
        self.assertTrue(id_column)
        self.assertTrue(id_column.primary_key)
        self.assertGreater(id_column.position, 0)
        self.assertTrue(company_column)
        self.assertTrue(company_column.foreign_key)
        self.assertTrue(wizard.field_option_ids.filtered(lambda option: option.column_name == 'name'))
