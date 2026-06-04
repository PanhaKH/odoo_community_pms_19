import html
import re

from odoo import _, api, fields, models
from odoo.exceptions import AccessError, UserError


class HotelSqlInquestWizard(models.TransientModel):
    _name = 'hotel.sql.inquest.wizard'
    _description = 'Interactive SQL Inquest'

    sql_query = fields.Text(
        string="SQL Query",
        required=True,
        default=lambda self: self._default_sql_query(),
    )
    row_count = fields.Integer(string="Rows Returned", readonly=True)
    column_count = fields.Integer(string="Columns", readonly=True)
    execution_time_ms = fields.Float(string="Execution Time (ms)", readonly=True, digits=(16, 2))
    executed_at = fields.Datetime(string="Last Executed", readonly=True)
    result_html = fields.Html(string="Results", readonly=True, sanitize=False)
    help_html = fields.Html(
        string="Guidelines",
        readonly=True,
        sanitize=False,
        default=lambda self: self._default_help_html(),
    )

    @api.model
    def _default_sql_query(self):
        return (
            "SELECT\n"
            "    *\n"
            "FROM hotel_reservation"
        )

    @staticmethod
    def _base_help_html():
        return _(
            "<div class='alert alert-info mb-2 o_hotel_sql_inquest_notice'>"
            "<b>Read-only SQL only.</b> Use a single <code>SELECT</code> or <code>WITH ... SELECT</code> statement. "
            "Under <b>All Tables</b>, each row shows the exact query you can copy into the Query box."
            "</div>"
        )

    def _default_help_html(self):
        return self._base_help_html() + self._render_table_browser()

    def _check_sql_inquest_access(self):
        if not (self.env.user.has_group('hotel_management.group_hotel_system_admin') or self.env.user.has_group('base.group_system')):
            raise AccessError(_("You do not have permission to run SQL Inquest queries."))

    @api.model
    def default_get(self, fields_list):
        values = super().default_get(fields_list)
        if 'help_html' in fields_list:
            values['help_html'] = self._default_help_html()
        return values

    @api.model
    def list_tables(self):
        self._check_sql_inquest_access()
        self.env.cr.execute("""
            SELECT
                schemaname,
                relname AS table_name,
                COALESCE(n_live_tup, 0) AS estimated_rows
            FROM pg_stat_user_tables
            WHERE schemaname NOT IN ('information_schema')
            ORDER BY schemaname, relname
        """)
        return self.env.cr.dictfetchall()

    def _render_table_browser(self):
        rows = []
        for row in self.list_tables():
            query_example = f'SELECT * FROM "{row["schemaname"]}"."{row["table_name"]}"'
            query_attr = html.escape(query_example, quote=True)
            rows.append(
                "<tr>"
                f"<td>{html.escape(row['schemaname'])}</td>"
                f"<td>{html.escape(row['table_name'])}</td>"
                f"<td class='text-end'>{int(row['estimated_rows'] or 0)}</td>"
                "<td>"
                f"<button type='button' class='btn btn-link btn-sm p-0 text-start o_hotel_sql_query_open' data-query='{query_attr}'>"
                f"<code>{html.escape(query_example)}</code>"
                "</button>"
                "</td>"
                "</tr>"
            )
        body = "".join(rows) or "<tr><td colspan='4' class='text-center text-muted'>No tables found.</td></tr>"
        return (
            "<div class='o_hotel_sql_inquest_table_browser'>"
            "<div class='o_hotel_sql_inquest_table_browser_title'>Available Tables</div>"
            "<div class='table-responsive o_hotel_sql_inquest_table_scroll'>"
            "<table class='table table-sm table-striped table-hover mb-0 o_hotel_sql_inquest_table'>"
            "<thead><tr><th>Schema</th><th>Table</th><th class='text-end'>Rows</th><th>Query To Copy</th></tr></thead>"
            f"<tbody>{body}</tbody>"
            "</table>"
            "</div>"
            "</div>"
        )

    def _sanitize_query(self, query):
        raw_query = (query or '').strip()
        if not raw_query:
            raise UserError(_("Enter a SQL query first."))

        if raw_query.endswith(';'):
            raw_query = raw_query[:-1].strip()
        if ';' in raw_query:
            raise UserError(_("Only a single SQL statement is allowed."))

        normalized = re.sub(r'\s+', ' ', raw_query).strip().lower()
        if not normalized.startswith(('select ', 'with ')):
            raise UserError(_("Only SELECT queries are allowed."))

        forbidden = re.search(
            r'\b(insert|update|delete|drop|alter|truncate|create|grant|revoke|comment|copy|vacuum|analyze|refresh|merge|call|execute|do)\b',
            normalized,
        )
        if forbidden:
            raise UserError(_("Forbidden SQL keyword detected: %s") % forbidden.group(1).upper())

        return raw_query

    def _format_cell(self, value):
        if value is None:
            return "<span class='text-muted'>NULL</span>"
        return html.escape(str(value))

    def _render_results(self, columns, rows):
        header = ''.join(
            f"<th class='text-nowrap' style='position: sticky; top: 0; background: #f8f9fa; z-index: 1;'>{html.escape(column)}</th>"
            for column in columns
        )
        body_rows = []
        for row in rows:
            cells = ''.join(f"<td class='text-nowrap'>{self._format_cell(value)}</td>" for value in row)
            body_rows.append(f"<tr>{cells}</tr>")

        if not body_rows:
            body_rows.append(
                "<tr><td colspan='%s' class='text-center text-muted py-3'>No rows returned.</td></tr>"
                % max(len(columns), 1)
            )

        return (
            "<div class='table-responsive o_hotel_sql_inquest_result_scroll'>"
            "<table class='table table-sm table-striped table-hover mb-0 o_hotel_sql_inquest_result_table'>"
            f"<thead><tr>{header}</tr></thead>"
            f"<tbody>{''.join(body_rows)}</tbody>"
            "</table>"
            "</div>"
        )

    def action_execute_query(self):
        self.ensure_one()
        self._check_sql_inquest_access()

        query = self._sanitize_query(self.sql_query)

        try:
            self.env.cr.execute(query)
            rows = self.env.cr.fetchall()
            columns = [description[0] for description in (self.env.cr.description or [])]
        except Exception as exc:
            raise UserError(_("SQL execution failed:\n%s") % exc) from exc

        self.write({
            'row_count': len(rows),
            'column_count': len(columns),
            'execution_time_ms': 0,
            'executed_at': fields.Datetime.now(),
            'help_html': self._default_help_html(),
            'result_html': False,
        })

        return self._open_query_page()

    def _open_query_page(self):
        return {
            'type': 'ir.actions.act_window',
            'name': _('SQL Query'),
            'res_model': 'hotel.sql.inquest.wizard',
            'view_mode': 'form',
            'res_id': self.id,
            'views': [(self.env.ref('hotel_management.view_hotel_sql_inquest_query_form').id, 'form')],
            'target': 'current',
        }

    def _reopen_self(self):
        return {
            'type': 'ir.actions.act_window',
            'name': _('SQL Inquest'),
            'res_model': 'hotel.sql.inquest.wizard',
            'view_mode': 'form',
            'res_id': self.id,
            'target': 'current',
        }

    @api.model
    def execute_query(self, query):
        self._check_sql_inquest_access()
        query = self._sanitize_query(query)

        try:
            self.env.cr.execute(query)
            rows = self.env.cr.fetchall()
            columns = [description[0] for description in (self.env.cr.description or [])]
        except Exception as exc:
            raise UserError(_("SQL execution failed:\n%s") % exc) from exc

        return {
            'columns': columns,
            'rows': [[False if value is None else str(value) for value in row] for row in rows],
            'row_count': len(rows),
        }

    def action_clear_results(self):
        self.ensure_one()
        self._check_sql_inquest_access()
        self.write({
            'row_count': 0,
            'column_count': 0,
            'execution_time_ms': 0,
            'executed_at': False,
            'help_html': self._default_help_html(),
            'result_html': False,
        })
        return self._reopen_self()
