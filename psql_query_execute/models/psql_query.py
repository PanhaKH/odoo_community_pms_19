# -*- coding: utf-8 -*-
"""Interactive, read-only SQL reporting for the existing ``psql.query`` model."""

import base64
import io
import json
import logging
import re
import time
from datetime import date, datetime, time as dt_time, timedelta
from decimal import Decimal
from uuid import UUID

from markupsafe import escape
from psycopg2 import errors as pg_errors

from odoo import _, api, fields, models
from odoo.exceptions import AccessError, ValidationError
from odoo.tools import json_default

try:
    from odoo.tools.misc import xlsxwriter
except ImportError:  # pragma: no cover - Odoo normally provides it
    import xlsxwriter


_logger = logging.getLogger(__name__)

MAX_RESULT_ROWS = 5000
QUERY_TIMEOUT_MS = 30000

FORBIDDEN_KEYWORDS = {
    "alter", "analyze", "begin", "call", "checkpoint", "cluster", "comment",
    "commit", "copy", "create", "delete", "discard", "do", "drop", "execute",
    "grant", "insert", "into", "listen", "load", "lock", "merge", "notify",
    "prepare", "reassign", "refresh", "reindex", "release", "reset", "revoke",
    "rollback", "savepoint", "security", "set", "start", "truncate", "unlisten",
    "update", "vacuum",
}

DANGEROUS_FUNCTIONS = {
    "dblink_connect", "dblink_exec", "lo_export", "lo_import", "nextval",
    "pg_cancel_backend", "pg_log_backend_memory_contexts", "pg_read_binary_file",
    "pg_read_file", "pg_reload_conf", "pg_rotate_logfile", "pg_sleep",
    "pg_stat_file", "pg_terminate_backend", "set_config", "setval",
}

DANGEROUS_FUNCTION_PREFIXES = (
    "dblink_", "lo_", "pg_advisory_", "pg_file_", "pg_ls_", "pg_read_",
)

ROOMMASTER_PARAMETER_RE = re.compile(r"\{\?([^{}]+)\}")

PARAMETER_TYPE_SELECTION = [
    ("text", "Text"),
    ("long_text", "Long Text"),
    ("integer", "Integer"),
    ("decimal", "Decimal"),
    ("boolean", "Boolean / Yes-No"),
    ("date", "Single Date"),
    ("date_range", "Date Range"),
    ("time", "Time"),
    ("datetime", "Date and Time"),
    ("selection", "Single Selection"),
    ("multi_selection", "Multiple Selection"),
    ("fixed_dropdown", "Fixed Dropdown"),
    ("fixed_multi", "Fixed Multi-Select"),
    ("dynamic_sql", "Dynamic SQL Lookup"),
    ("dynamic_sql_multi", "Dynamic SQL Multi-Select"),
    ("many2one", "Odoo Model Lookup"),
    ("odoo_model_multi", "Odoo Model Multi-Select"),
    ("current_user", "Current User"),
    ("current_company", "Current Company"),
    ("current_date", "Current Date"),
    ("relative_date", "Relative Date"),
    ("hidden", "Hidden Technical Parameter"),
    ("number_range", "Number Range"),
]

SELECTION_PARAMETER_TYPES = {
    "selection", "multi_selection", "fixed_dropdown", "fixed_multi",
    "dynamic_sql", "dynamic_sql_multi",
}
MULTI_VALUE_PARAMETER_TYPES = {
    "multi_selection", "fixed_multi", "dynamic_sql_multi", "odoo_model_multi",
}
SINGLE_SELECTION_PARAMETER_TYPES = {"selection", "fixed_dropdown", "dynamic_sql"}
MODEL_PARAMETER_TYPES = {"many2one", "odoo_model_multi"}
TEXT_PARAMETER_TYPES = {"text", "long_text", "time", "relative_date", "hidden"}
DATE_RANGE_PARAMETER_TYPES = {"date_range", "number_range"}


def _slug_parameter_name(value):
    return re.sub(r"[^a-z0-9_]+", "_", (value or "parameter").lower()).strip("_") or "parameter"


def _normalize_parameter_type(parameter_type):
    if parameter_type in {"fixed_dropdown", "dynamic_sql"}:
        return "selection"
    if parameter_type in {"fixed_multi", "dynamic_sql_multi"}:
        return "multi_selection"
    if parameter_type == "current_user":
        return "many2one"
    if parameter_type == "current_company":
        return "many2one"
    if parameter_type == "current_date":
        return "date"
    if parameter_type == "relative_date":
        return "date"
    if parameter_type == "hidden":
        return "text"
    return parameter_type


def _source_type_for_parameter_type(parameter_type, fallback="none"):
    if parameter_type in {"fixed_dropdown", "fixed_multi"}:
        return "fixed"
    if parameter_type in {"dynamic_sql", "dynamic_sql_multi"}:
        return "sql"
    if parameter_type in {"many2one", "odoo_model_multi"}:
        return "odoo_model"
    if parameter_type in {"current_user", "current_company", "current_date", "hidden"}:
        return "hidden"
    return fallback or "none"


class PsqlQueryCategory(models.Model):
    """Unlimited hierarchical folders used to organize saved SQL reports."""

    _name = "psql.query.category"
    _description = "SQL Report Category"
    _parent_name = "parent_id"
    _parent_store = True
    _rec_name = "complete_name"
    _order = "sequence, name, id"

    name = fields.Char(required=True, translate=True)
    complete_name = fields.Char(compute="_compute_complete_name", store=True, recursive=True)
    parent_id = fields.Many2one(
        "psql.query.category",
        string="Parent Category",
        index=True,
        ondelete="restrict",
    )
    parent_path = fields.Char(index=True)
    child_ids = fields.One2many("psql.query.category", "parent_id", string="Child Categories")
    report_ids = fields.One2many("psql.query", "category_id", string="SQL Reports")
    sequence = fields.Integer(default=10)
    icon = fields.Char(help="Optional Font Awesome icon class, for example fa-hotel.")
    active = fields.Boolean(default=True)

    @api.depends("name", "parent_id.complete_name")
    def _compute_complete_name(self):
        for category in self:
            category.complete_name = (
                f"{category.parent_id.complete_name} / {category.name}"
                if category.parent_id
                else category.name
            )

    @api.constrains("parent_id")
    def _check_category_recursion(self):
        if self._has_cycle():
            raise ValidationError(_("A report category cannot be a parent of itself."))


class PsqlQuery(models.Model):
    """Saved interactive SQL report definition and its latest result."""

    _name = "psql.query"
    _description = "PostgreSQL Query"
    _inherit = ["mail.thread", "mail.activity.mixin"]
    _order = "write_date desc, id desc"

    # Existing field names are retained for backward compatibility.
    name = fields.Char(string="Report Name", required=True, tracking=True)
    query_name = fields.Text(string="SQL Query", required=True, default="SELECT ", tracking=True)
    query_result = fields.Html(string="Legacy Result", readonly=True, sanitize=True)

    description = fields.Text(string="Description")
    report_date_from = fields.Date(
        string="Report Date From",
        help="Optional start date displayed in the PDF report header.",
    )
    report_date_to = fields.Date(
        string="Report Date To",
        help="Optional end date displayed in the PDF report header.",
    )
    report_filter_summary = fields.Text(
        string="Applied Filters",
        help="Optional business-friendly filter summary displayed in the PDF report header.",
    )
    last_filter_summary = fields.Text(
        string="Last Applied Filters",
        readonly=True,
        copy=False,
        help="Runtime filter values used for the latest report execution.",
    )
    last_filter_values = fields.Json(
        string="Last Filter Values",
        readonly=True,
        copy=False,
    )
    paper_orientation = fields.Selection(
        [
            ("auto", "Automatic (Fit to Columns)"),
            ("portrait", "Portrait (Vertical)"),
            ("landscape", "Landscape (Horizontal)"),
        ],
        string="Paper Orientation",
        required=True,
        default="auto",
        tracking=True,
        help="Orientation automatically used when this report is printed as PDF.",
    )
    category_id = fields.Many2one(
        "psql.query.category",
        string="Report Category",
        default=lambda self: self._default_report_category(),
        tracking=True,
        index=True,
        ondelete="restrict",
        help="Folder in the SQL Reports tree where this report is stored.",
    )
    parameter_ids = fields.Many2many(
        "psql.query.parameter",
        string="Parameters",
        compute="_compute_parameter_ids",
        inverse="_inverse_parameter_ids",
        help="Reusable parameters selected from SQL Reports > Configuration > Parameters.",
    )
    is_interactive_session = fields.Boolean(
        string="Interactive Session",
        default=False,
        copy=False,
        index=True,
        help="Technical flag used to keep unnamed Interactive SQL sessions out of the saved Reports list.",
    )
    query_preview = fields.Char(
        string="SQL Query Preview", compute="_compute_query_preview", store=True
    )
    result_data = fields.Json(string="Latest Result Data", readonly=True, copy=False)
    last_result_metadata = fields.Json(
        string="Last Result Metadata", readonly=True, copy=False
    )
    last_executed_date = fields.Datetime(
        string="Last Executed", readonly=True, copy=False, index=True
    )
    last_execution_status = fields.Selection(
        [
            ("never", "Not Executed"),
            ("success", "Success"),
            ("empty", "No Records"),
            ("error", "Error"),
        ],
        string="Status",
        default="never",
        readonly=True,
        copy=False,
        index=True,
    )
    last_error = fields.Text(string="Last Error", readonly=True, copy=False)
    execution_duration = fields.Float(
        string="Duration (seconds)", digits=(12, 4), readonly=True, copy=False
    )
    returned_row_count = fields.Integer(
        string="Returned Rows", readonly=True, copy=False
    )
    result_limited = fields.Boolean(string="Result Limited", readonly=True, copy=False)
    has_result = fields.Boolean(
        string="Has Result", compute="_compute_has_result", store=True
    )
    report_column_ids = fields.One2many(
        "psql.query.report.column",
        "query_id",
        string="Report Columns",
        copy=True,
        help="Controls business labels, visibility, order, formatting, totals, and grouping without changing SQL.",
    )
    filter_definition_ids = fields.One2many(
        "psql.query.filter.definition",
        "query_id",
        string="Runtime Filters",
        copy=False,
        help="Selection parameters requested before this report is executed.",
    )
    parameter_memory_mode = fields.Selection(
        [
            ("none", "Do Not Remember Values"),
            ("session", "Remember Values for Current Session"),
            ("user", "Remember Last Values per User"),
            ("defaults", "Always Use Configured Defaults"),
        ],
        string="Parameter Value Memory",
        default="none",
        help="Controls how the runtime parameter popup initializes values.",
    )

    @api.model
    def _my_reports_category(self):
        category = self.env.ref("psql_query_execute.report_category_my_reports", raise_if_not_found=False)
        if not category:
            category = self.env["psql.query.category"].search([
                ("name", "=", "My Reports"),
                ("parent_id", "=", False),
            ], limit=1)
        return category

    @api.model
    def _default_report_category(self):
        if self.env.context.get("interactive_sql") or self.env.context.get("default_is_interactive_session"):
            return False
        return self._my_reports_category().id

    @api.model
    def _assign_uncategorized_reports(self):
        """Migration-safe assignment for reports created before folders existed."""
        category = self._my_reports_category()
        if category:
            self.search([
                ("is_interactive_session", "=", False),
                ("category_id", "=", False),
            ]).write({"category_id": category.id})
        return True

    @api.constrains("category_id", "is_interactive_session")
    def _check_saved_report_category(self):
        if any(not report.is_interactive_session and not report.category_id for report in self):
            raise ValidationError(_("Choose a Report Category before saving the SQL report."))

    @api.model_create_multi
    def create(self, values_list):
        for values in values_list:
            if not values.get("query_name"):
                values["query_name"] = "SELECT "
        return super().create(values_list)

    def write(self, values):
        if "query_name" in values and not values.get("query_name"):
            values = dict(values, query_name="SELECT ")
        # Converting an Interactive SQL session into a saved report should not
        # alter that page's workflow; place it in My Reports automatically.
        if values.get("is_interactive_session") is False and "category_id" not in values:
            uncategorized = self.filtered(lambda report: not report.category_id)
            categorized = self - uncategorized
            result = True
            if categorized:
                result = super(PsqlQuery, categorized).write(values)
            if uncategorized:
                category_id = self._my_reports_category().id
                report_values = dict(values, category_id=category_id)
                result = super(PsqlQuery, uncategorized).write(report_values) and result
            return result
        return super().write(values)

    def copy(self, default=None):
        """Duplicate runtime filters against the duplicate's presentation columns."""
        self.ensure_one()
        definitions = self.filter_definition_ids
        duplicate = super().copy(default)
        duplicate_columns = {
            line.source_name: line for line in duplicate.report_column_ids
        }
        for definition in definitions:
            target_column = duplicate_columns.get(definition.report_column_id.source_name)
            if target_column:
                definition.copy({
                    "query_id": duplicate.id,
                    "report_column_id": target_column.id,
                })
        return duplicate

    @api.depends("query_name")
    def _compute_query_preview(self):
        for record in self:
            compact = re.sub(r"\s+", " ", record.query_name or "").strip()
            record.query_preview = compact[:180]

    @api.depends("result_data", "returned_row_count", "last_execution_status")
    def _compute_has_result(self):
        for record in self:
            data = record.result_data or {}
            record.has_result = bool(data.get("columns"))

    @api.depends("filter_definition_ids.reusable_parameter_id")
    def _compute_parameter_ids(self):
        for report in self:
            report.parameter_ids = report.filter_definition_ids.mapped("reusable_parameter_id")

    def _inverse_parameter_ids(self):
        for report in self:
            report._sync_reusable_parameter_definitions(report.parameter_ids)

    def _sync_reusable_parameter_definitions(self, parameters):
        self.ensure_one()
        existing_by_template = {
            definition.reusable_parameter_id.id: definition
            for definition in self.filter_definition_ids.filtered("reusable_parameter_id")
        }
        selected_templates = parameters.filtered("active")
        selected_ids = set(selected_templates.ids)
        stale = self.filter_definition_ids.filtered(
            lambda definition: definition.reusable_parameter_id
            and definition.reusable_parameter_id.id not in selected_ids
        )
        if stale:
            stale.unlink()
        sequence = max(self.filter_definition_ids.mapped("sequence") or [0]) + 10
        for template in selected_templates.sorted("sequence"):
            values = template._definition_values(query_id=self.id, sequence=sequence)
            definition = existing_by_template.get(template.id)
            if definition:
                definition.write({key: value for key, value in values.items() if key not in {"query_id", "sequence"}})
                definition._sync_selection_options()
            else:
                definition = self.env["psql.query.filter.definition"].create(values)
                definition._sync_selection_options()
                sequence += 10

    @staticmethod
    def _friendly_column_label(name):
        special = {
            "id": "No.",
            "display_name": "Display Name",
            "create_uid": "Created By",
            "write_uid": "Updated By",
            "create_date": "Created On",
            "write_date": "Updated On",
        }
        if name in special:
            return special[name]
        label = re.sub(r"_id$", "", name or "")
        return re.sub(r"[_\s]+", " ", label).strip().title() or _("Column")

    @staticmethod
    def _guess_display_type(values):
        samples = [value for value in values if value is not None][:20]
        if not samples:
            return "auto"
        if all(isinstance(value, bool) for value in samples):
            return "text"
        if all(isinstance(value, int) and not isinstance(value, bool) for value in samples):
            return "integer"
        if all(isinstance(value, (int, float)) and not isinstance(value, bool) for value in samples):
            return "decimal"
        strings = [str(value) for value in samples]
        if all(re.match(r"^-?\d+$", value) for value in strings):
            return "integer"
        if all(re.match(r"^-?\d+(\.\d+)?$", value) for value in strings):
            return "decimal"
        if all(re.match(r"^\d{4}-\d{2}-\d{2}[ T]\d{2}:\d{2}", value) for value in strings):
            return "datetime"
        if all(re.match(r"^\d{4}-\d{2}-\d{2}$", value) for value in strings):
            return "date"
        return "auto"

    def _sync_report_columns(self, columns, rows):
        """Synchronize presentation metadata only; query output remains untouched."""
        self.ensure_one()
        existing = {line.source_name: line for line in self.report_column_ids}
        technical = {"id", "create_uid", "write_uid"}
        total_words = ("amount", "total", "price", "cost", "qty", "quantity", "rate", "balance")
        for index, name in enumerate(columns):
            values = [row[index] for row in rows[:50] if index < len(row)]
            display_type = self._guess_display_type(values)
            defaults = {
                "sequence": (index + 1) * 10,
                "label": self._friendly_column_label(name),
                "visible": name not in technical,
                "display_type": display_type,
                "alignment": "auto",
                "show_total": (
                    display_type in {"integer", "decimal"}
                    and any(word in name.lower() for word in total_words)
                    and not name.lower().endswith("_id")
                ),
            }
            if name not in existing:
                self.env["psql.query.report.column"].create(dict(
                    defaults,
                    query_id=self.id,
                    source_name=name,
                ))
        stale = self.report_column_ids.filtered(lambda line: line.source_name not in columns)
        stale.unlink()

    @staticmethod
    def _format_report_value(value, display_type):
        if value is None:
            return "—"
        if display_type in {"date", "datetime"} or (
            display_type == "auto" and isinstance(value, str)
            and re.match(r"^\d{4}-\d{2}-\d{2}([ T]\d{2}:\d{2})?", value)
        ):
            try:
                parsed = datetime.fromisoformat(str(value).replace("Z", "+00:00"))
                if display_type == "date" or len(str(value)) == 10:
                    return parsed.strftime("%d %b %Y")
                return parsed.strftime("%d %b %Y %H:%M")
            except (TypeError, ValueError):
                pass
        if display_type == "integer":
            try:
                return f"{int(value):,}"
            except (TypeError, ValueError):
                pass
        if display_type == "decimal":
            try:
                return f"{float(value):,.2f}"
            except (TypeError, ValueError):
                pass
        if isinstance(value, (dict, list, tuple)):
            return json.dumps(value, ensure_ascii=False, default=json_default)
        return str(value)

    @staticmethod
    def _report_column_weight(definition, sample_values):
        """Estimate a stable print width from a small, bounded value sample."""
        display_type = definition["display_type"]
        label_length = len(definition["label"] or "")
        lengths = sorted(len(str(value or "")) for value in sample_values)
        # The 80th percentile ignores occasional huge values which would make
        # every other column unnecessarily narrow. Long values are ellipsized.
        sample_length = lengths[min(len(lengths) - 1, int(len(lengths) * 0.8))] if lengths else 0
        if display_type == "date":
            return 11.0
        if display_type == "datetime":
            return 16.0
        if display_type == "integer":
            return float(max(5, min(10, max(label_length, sample_length))))
        if display_type == "decimal":
            return float(max(7, min(13, max(label_length, sample_length))))
        return float(max(6, min(28, max(label_length, sample_length))))

    def _get_report_presentation(self):
        """Return a formatted view of stored rows for PDF/CSV/XLSX presentation."""
        self.ensure_one()
        data = self.result_data or {}
        source_columns = data.get("columns") or []
        source_rows = data.get("rows") or []
        configured = {line.source_name: line for line in self.report_column_ids}
        definitions = []
        for index, source_name in enumerate(source_columns):
            line = configured.get(source_name)
            guessed_type = self._guess_display_type([
                row[index] for row in source_rows[:50] if index < len(row)
            ])
            visible = line.visible if line else source_name not in {"id", "create_uid", "write_uid"}
            if not visible:
                continue
            definitions.append({
                "index": index,
                "source_name": source_name,
                "label": line.label if line else self._friendly_column_label(source_name),
                "display_type": line.display_type if line else guessed_type,
                "alignment": line.alignment if line else "auto",
                "show_total": bool(line and line.show_total),
                "group_by": bool(line and line.group_by),
                "relation_model": line.relation_model_id.model if line and line.relation_model_id else False,
                "sequence": line.sequence if line else (index + 1) * 10,
            })
        definitions.sort(key=lambda item: (item["sequence"], item["index"]))

        relation_cache = {}
        # Resolve relational display names in one query per model/column. The
        # previous per-cell lookup became very expensive on large PDF reports.
        for definition in definitions:
            relation_model = definition["relation_model"]
            if not relation_model or relation_model not in self.env:
                continue
            relation_ids = set()
            for row in source_rows:
                if definition["index"] >= len(row):
                    continue
                try:
                    value = row[definition["index"]]
                    if value not in (None, False, ""):
                        relation_ids.add(int(value))
                except (TypeError, ValueError):
                    continue
            try:
                records = self.env[relation_model].browse(relation_ids).exists()
                names = {record.id: record.display_name for record in records}
                relation_cache.update({
                    (relation_model, relation_id): names.get(relation_id, False)
                    for relation_id in relation_ids
                })
            except AccessError:
                relation_cache.update({
                    (relation_model, relation_id): False for relation_id in relation_ids
                })

        totals = [0.0 for _definition in definitions]
        has_total = False
        formatted_rows = []
        for source_row in source_rows:
            cells = []
            for position, definition in enumerate(definitions):
                raw_value = source_row[definition["index"]] if definition["index"] < len(source_row) else None
                value = raw_value
                relation_model = definition["relation_model"]
                if relation_model and raw_value not in (None, False, "") and relation_model in self.env:
                    try:
                        cache_key = (relation_model, int(raw_value))
                        value = relation_cache.get(cache_key) or raw_value
                    except (TypeError, ValueError):
                        value = raw_value
                display_type = definition["display_type"]
                alignment = definition["alignment"]
                if alignment == "auto":
                    alignment = "right" if display_type in {"integer", "decimal"} else (
                        "center" if display_type in {"date", "datetime"} else "left"
                    )
                if definition["show_total"] and not isinstance(raw_value, bool):
                    try:
                        totals[position] += float(raw_value)
                        has_total = True
                    except (TypeError, ValueError):
                        pass
                cells.append({
                    "raw": raw_value,
                    "value": self._format_report_value(value, display_type),
                    "alignment": alignment,
                    "display_type": display_type,
                })
            formatted_rows.append(cells)

        group_position = next((index for index, item in enumerate(definitions) if item["group_by"]), None)
        groups = []
        for cells in formatted_rows:
            group_label = cells[group_position]["value"] if group_position is not None else False
            if not groups or groups[-1]["label"] != group_label:
                groups.append({"label": group_label, "rows": []})
            groups[-1]["rows"].append(cells)

        sample_size = min(len(formatted_rows), 80)
        weights = []
        for position, definition in enumerate(definitions):
            sample_values = [
                formatted_rows[row_index][position]["value"]
                for row_index in range(sample_size)
            ]
            weights.append(self._report_column_weight(definition, sample_values))
        total_weight = sum(weights) or 1.0
        for definition, weight in zip(definitions, weights):
            definition["width_percent"] = round(weight * 100.0 / total_weight, 3)

        total_cells = []
        for position, definition in enumerate(definitions):
            total_cells.append({
                "value": self._format_report_value(
                    totals[position],
                    "integer" if definition["display_type"] == "integer" else "decimal",
                ) if definition["show_total"] else ("Total" if position == 0 and has_total else ""),
                "alignment": "right" if definition["show_total"] else "left",
            })
        estimated_width = sum(weights)
        landscape = self.paper_orientation == "landscape" or (
            self.paper_orientation == "auto"
            and (len(definitions) > 7 or estimated_width > 88)
        )
        column_count = len(definitions)
        density = (
            "normal" if column_count <= 8 and estimated_width <= 88 else
            "compact" if column_count <= 16 else
            "dense" if column_count <= 30 else
            "ultra"
        )
        return {
            "columns": definitions,
            "groups": groups,
            "row_count": len(source_rows),
            "has_total": has_total,
            "totals": total_cells,
            "landscape": landscape,
            "density": density,
            "estimated_width": estimated_width,
            "large_dataset": len(source_rows) > 500 or column_count > 20,
            "screen_min_width": min(6400, max(960, int(estimated_width * 8))),
        }

    def _ensure_sql_admin(self):
        if not self.env.user.has_group("base.group_system"):
            raise AccessError(_("Only system administrators may use Interactive SQL Reports."))

    @staticmethod
    def _scan_sql(sql_text):
        """Return executable code and comments using a PostgreSQL-aware lexer.

        Strings, quoted identifiers, dollar-quoted bodies, line comments, and
        nested block comments are recognized so statement separators and tokens
        cannot be hidden from validation.
        """
        code = []
        comments = []
        length = len(sql_text)
        index = 0
        state = "normal"
        block_depth = 0
        dollar_tag = ""

        while index < length:
            char = sql_text[index]
            nxt = sql_text[index + 1] if index + 1 < length else ""

            if state == "normal":
                if char == "'":
                    state = "single"
                    code.append(" ")
                elif char == '"':
                    state = "double"
                    code.append(" ")
                elif char == "-" and nxt == "-":
                    state = "line_comment"
                    comments.append("  ")
                    code.extend("  ")
                    index += 1
                elif char == "/" and nxt == "*":
                    state = "block_comment"
                    block_depth = 1
                    comments.append("  ")
                    code.extend("  ")
                    index += 1
                elif char == "$":
                    match = re.match(r"\$[A-Za-z_][A-Za-z0-9_]*\$|\$\$", sql_text[index:])
                    if match:
                        dollar_tag = match.group(0)
                        state = "dollar"
                        code.extend(" " * len(dollar_tag))
                        index += len(dollar_tag) - 1
                    else:
                        code.append(char)
                else:
                    code.append(char)

            elif state == "single":
                code.append(" ")
                if char == "'" and nxt == "'":
                    code.append(" ")
                    index += 1
                elif char == "'":
                    state = "normal"

            elif state == "double":
                # Quoted identifiers are retained as a neutral token boundary.
                code.append(" ")
                if char == '"' and nxt == '"':
                    code.append(" ")
                    index += 1
                elif char == '"':
                    state = "normal"

            elif state == "dollar":
                if sql_text.startswith(dollar_tag, index):
                    code.extend(" " * len(dollar_tag))
                    index += len(dollar_tag) - 1
                    state = "normal"
                else:
                    code.append(" ")

            elif state == "line_comment":
                comments.append(char)
                code.append("\n" if char == "\n" else " ")
                if char == "\n":
                    state = "normal"

            elif state == "block_comment":
                comments.append(char)
                code.append("\n" if char == "\n" else " ")
                if char == "/" and nxt == "*":
                    block_depth += 1
                    comments.append(nxt)
                    code.append(" ")
                    index += 1
                elif char == "*" and nxt == "/":
                    block_depth -= 1
                    comments.append(nxt)
                    code.append(" ")
                    index += 1
                    if block_depth == 0:
                        state = "normal"
            index += 1

        if state in {"single", "double", "dollar", "block_comment"}:
            raise ValidationError(_("The SQL contains an unterminated string, identifier, or comment."))
        return "".join(code), "".join(comments)

    @classmethod
    def _validate_read_only_sql(cls, query):
        sql_text = (query or "").strip()
        if not sql_text:
            raise ValidationError(_("Enter a SQL query before running the report."))

        code, comments = cls._scan_sql(sql_text)
        statements = [part.strip() for part in code.split(";") if part.strip()]
        if len(statements) != 1:
            raise ValidationError(_("Multiple SQL statements are not allowed."))
        # A semicolon is accepted only as the final non-whitespace character.
        if ";" in code and code.rstrip()[-1:] != ";":
            raise ValidationError(_("Multiple SQL statements are not allowed."))

        statement = statements[0]
        tokens = re.findall(r"[A-Za-z_][A-Za-z0-9_$]*|[(),]", statement.lower())
        if not tokens or tokens[0] not in {"select", "with", "explain"}:
            raise ValidationError(_("Only read-only SELECT, WITH, and EXPLAIN SELECT statements are allowed."))

        token_words = {token for token in tokens if token[0].isalpha() or token[0] == "_"}
        blocked = sorted(token_words.intersection(FORBIDDEN_KEYWORDS))
        if blocked:
            raise ValidationError(_("Blocked SQL operation: %s", blocked[0].upper()))

        comment_words = set(re.findall(r"[A-Za-z_][A-Za-z0-9_$]*", comments.lower()))
        hidden = sorted(comment_words.intersection(FORBIDDEN_KEYWORDS))
        if hidden:
            raise ValidationError(_("Blocked SQL keyword found inside a comment: %s", hidden[0].upper()))

        if tokens[0] == "explain":
            if "analyze" in token_words or not ({"select", "with"} & token_words):
                raise ValidationError(_("Only EXPLAIN SELECT is allowed; EXPLAIN ANALYZE is blocked."))

        for position, token in enumerate(tokens[:-1]):
            if tokens[position + 1] != "(":
                continue
            if token in DANGEROUS_FUNCTIONS or token.startswith(DANGEROUS_FUNCTION_PREFIXES):
                raise ValidationError(_("Dangerous PostgreSQL function is not allowed: %s", token))

        return sql_text.rstrip().rstrip(";").rstrip(), tokens[0]

    @staticmethod
    def _serialize_cell(value):
        if value is None:
            return None
        if isinstance(value, (datetime, date, dt_time)):
            return value.isoformat(sep=" ") if isinstance(value, datetime) else value.isoformat()
        if isinstance(value, (Decimal, UUID)):
            return str(value)
        if isinstance(value, bytes):
            return "base64:" + base64.b64encode(value).decode("ascii")
        if isinstance(value, (str, int, float, bool)):
            return value
        if isinstance(value, (dict, list, tuple)):
            return json.loads(json.dumps(value, default=json_default))
        return str(value)

    @staticmethod
    def _friendly_database_error(error):
        if isinstance(error, pg_errors.QueryCanceled):
            return _("Query timeout exceeded (30 seconds).")
        if isinstance(error, pg_errors.UndefinedTable):
            return _("Table does not exist: %s", getattr(error.diag, "message_primary", error))
        if isinstance(error, pg_errors.UndefinedColumn):
            return _("Column does not exist: %s", getattr(error.diag, "message_primary", error))
        if isinstance(error, pg_errors.InsufficientPrivilege):
            return _("Permission denied while reading the requested database object.")
        if isinstance(error, pg_errors.SyntaxError):
            return _("Invalid SQL syntax: %s", getattr(error.diag, "message_primary", error))
        primary = getattr(getattr(error, "diag", None), "message_primary", None)
        return primary or str(error) or _("The query could not be executed.")

    @staticmethod
    def _legacy_html(columns, rows):
        header = "".join("<th>%s</th>" % escape(column) for column in columns)
        body = []
        for row in rows:
            cells = "".join(
                "<td>%s</td>" % ("NULL" if value is None else escape(str(value)))
                for value in row
            )
            body.append("<tr>%s</tr>" % cells)
        return (
            '<div class="table-responsive"><table class="table table-sm table-hover">'
            "<thead><tr>%s</tr></thead><tbody>%s</tbody></table></div>"
            % (header, "".join(body))
        )

    def _store_execution(self, *, columns=None, rows=None, duration=0.0,
                         status="success", error_message=False, limited=False):
        columns = columns or []
        rows = rows or []
        data = {"columns": columns, "rows": rows, "limited": bool(limited)}
        metadata = {
            "columns": [{"name": name, "position": index + 1} for index, name in enumerate(columns)],
            "row_count": len(rows),
            "limited": bool(limited),
        }
        values = {
            "result_data": data,
            "last_result_metadata": metadata,
            "last_executed_date": fields.Datetime.now(),
            "last_execution_status": status,
            "last_error": error_message or False,
            "execution_duration": round(duration, 4),
            "returned_row_count": len(rows),
            "result_limited": bool(limited),
            "query_result": self._legacy_html(columns, rows) if columns else False,
        }
        self.with_context(tracking_disable=True).write(values)
        if status in {"success", "empty"}:
            self._sync_report_columns(columns, rows)
        return {
            "ok": status in {"success", "empty"},
            "status": status,
            "error": error_message or False,
            "duration": values["execution_duration"],
            "row_count": len(rows),
            "limited": bool(limited),
            "columns": columns,
            "rows": rows,
            "executed_at": fields.Datetime.to_string(values["last_executed_date"]),
        }

    @staticmethod
    def _normalize_sql_placeholders(sql_text):
        """Accept :name and normalize it to psycopg's named mapping syntax."""
        return re.sub(
            r"(?<!:):([A-Za-z_][A-Za-z0-9_]*)",
            lambda match: f"%({match.group(1)})s",
            sql_text,
        )

    @staticmethod
    def _parse_roommaster_parameter(raw_spec):
        """Parse roomMaster-style ``{?...}`` parameter tokens.

        Supported forms include default values (``[RACK]``), boolean/numeric
        suffixes, date ranges (``%%``), fixed selections, and dynamic lookup
        hints. The parser is deliberately tolerant because reports copied from
        roomMaster commonly vary in escaping style.
        """
        spec = (raw_spec or "").strip()
        if not spec:
            raise ValidationError(_("Invalid parameter syntax: empty parameter name."))

        default_value = False
        default_match = re.search(r"\[([^\]]*)\]\s*$", spec)
        if default_match:
            default_value = default_match.group(1)
            spec = spec[:default_match.start()].strip()

        suffix = ""
        for marker in ("%%", "%@B"):
            if spec.endswith(marker):
                suffix = marker
                spec = spec[:-len(marker)].strip()
                break
        numeric_match = re.search(r"%@n(\d+)?(?:\.(\d+))?$", spec, re.I)
        number_format = False
        if numeric_match:
            suffix = "%@n"
            number_format = numeric_match.group(0)[2:]
            spec = spec[:numeric_match.start()].strip()

        lookup_spec = ""
        separator = "\\\\"
        if separator in spec:
            label, lookup_spec = spec.split(separator, 1)
        elif "\\" in spec:
            label, lookup_spec = spec.split("\\", 1)
        else:
            label = spec
        label = label.strip()
        lookup_spec = lookup_spec.strip()
        if not label:
            raise ValidationError(_("Invalid parameter syntax: missing parameter label in {%s}.", raw_spec))

        allow_multiple = False
        source_type = "none"
        fixed_values = ""
        source_table = ""
        source_field = ""
        sql_lookup_query = ""
        filter_type = "text"

        if suffix == "%%":
            filter_type = "date_range"
        elif suffix == "%@B":
            filter_type = "boolean"
        elif suffix == "%@n":
            filter_type = "decimal" if "." in (number_format or "") else "integer"
        elif lookup_spec:
            allow_multiple = lookup_spec.startswith("?")
            lookup_body = lookup_spec[1:] if allow_multiple else lookup_spec
            lookup_body = lookup_body.strip()
            if len(lookup_body) >= 2 and lookup_body[0] in "\"'" and lookup_body[-1] == lookup_body[0]:
                lookup_body = lookup_body[1:-1]
                source_type = "fixed"
                fixed_values = lookup_body
                filter_type = "multi_selection" if allow_multiple else "selection"
            elif re.match(r"^[A-Za-z_][A-Za-z0-9_]*\.[A-Za-z_][A-Za-z0-9_]*$", lookup_body):
                source_type = "table"
                source_table, source_field = lookup_body.split(".", 1)
                filter_type = "multi_selection" if allow_multiple else "selection"
            else:
                source_type = "sql"
                sql_lookup_query = lookup_body
                filter_type = "multi_selection" if allow_multiple else "selection"
        elif "date range" in label.lower():
            filter_type = "date_range"
        elif "date" in label.lower():
            filter_type = "date"

        return {
            "name": label,
            "technical_name": _slug_parameter_name(label),
            "filter_type": filter_type,
            "required": True,
            "visible": True,
            "default_text": default_value if filter_type in {"text", "selection", "multi_selection"} else False,
            "default_number": float(default_value) if default_value and filter_type in {"integer", "decimal"} else 0.0,
            "default_boolean": str(default_value).lower() in {"1", "true", "yes", "y"} if default_value and filter_type == "boolean" else False,
            "allow_multiple_values": allow_multiple,
            "source_type": source_type,
            "source_table": source_table,
            "source_field": source_field,
            "fixed_selection_values": fixed_values,
            "sql_lookup_query": sql_lookup_query,
            "number_format": number_format,
        }

    @classmethod
    def _roommaster_parameter_specs(cls, sql_text):
        specs = []
        seen = set()
        for match in ROOMMASTER_PARAMETER_RE.finditer(sql_text or ""):
            raw_spec = match.group(1)
            spec = cls._parse_roommaster_parameter(raw_spec)
            technical_name = spec["technical_name"]
            if technical_name in seen:
                continue
            seen.add(technical_name)
            spec["raw_spec"] = raw_spec
            specs.append(spec)
        return specs

    @staticmethod
    def _label_from_technical_name(technical_name):
        label = re.sub(r"[_\s]+", " ", technical_name or "parameter").strip().title()
        replacements = {
            "Id": "ID",
            "Url": "URL",
            "Sql": "SQL",
        }
        for old, new in replacements.items():
            label = re.sub(rf"\b{old}\b", new, label)
        return label or _("Parameter")

    @classmethod
    def _guess_parameter_type(cls, technical_name):
        name = (technical_name or "").lower()
        if "date" in name or name in {"from", "to"}:
            return "date"
        if name.startswith(("is_", "has_", "include_", "show_", "with_")) or name in {"active", "enabled"}:
            return "boolean"
        if any(word in name for word in ("amount", "price", "rate", "total", "balance", "percent", "percentage")):
            return "decimal"
        if any(word in name for word in ("count", "number", "qty", "quantity", "days", "nights", "guests")):
            return "integer"
        return "text"

    @classmethod
    def _named_parameter_specs(cls, sql_text):
        normalized = cls._normalize_sql_placeholders(sql_text or "")
        ordered = []
        for match in re.finditer(r"%\(([A-Za-z_][A-Za-z0-9_]*)\)s", normalized):
            name = match.group(1)
            if name not in ordered:
                ordered.append(name)

        specs = []
        consumed = set()
        names = set(ordered)
        for name in ordered:
            if name in consumed:
                continue
            if name.endswith("_from"):
                base = name[:-5]
                to_name = f"{base}_to"
                if to_name in names:
                    consumed.update({name, to_name})
                    specs.append({
                        "name": cls._label_from_technical_name(base),
                        "technical_name": base,
                        "filter_type": "date_range" if "date" in base.lower() or base in {"period", "range"} else "number_range",
                        "required": True,
                        "visible": True,
                        "source_type": "none",
                    })
                    continue
            if name.endswith("_to") and f"{name[:-3]}_from" in names:
                consumed.add(name)
                continue
            consumed.add(name)
            specs.append({
                "name": cls._label_from_technical_name(name),
                "technical_name": name,
                "filter_type": cls._guess_parameter_type(name),
                "required": True,
                "visible": True,
                "source_type": "none",
            })
        return specs

    def _sql_parameter_specs(self):
        self.ensure_one()
        specs = []
        seen = set()
        for spec in self._roommaster_parameter_specs(self.query_name):
            technical_name = spec["technical_name"]
            seen.add(technical_name)
            specs.append(spec)
        named_sql = self._roommaster_sql_to_named_placeholders(self.query_name)
        for spec in self._named_parameter_specs(named_sql):
            technical_name = spec["technical_name"]
            if technical_name in seen:
                continue
            seen.add(technical_name)
            specs.append(spec)
        return specs

    def _auto_configure_sql_parameter_definitions(self):
        self.ensure_one()
        specs = self._sql_parameter_specs()
        if not specs:
            stale = self.filter_definition_ids
            removed = len(stale)
            stale.unlink()
            return {"specs": 0, "created": 0, "updated": 0, "linked": 0, "removed": removed}
        spec_names = {spec["technical_name"] for spec in specs}
        stale = self.filter_definition_ids.filtered(
            lambda definition: definition.technical_name not in spec_names
        )
        removed = len(stale)
        stale.unlink()
        existing = {definition.technical_name: definition for definition in self.filter_definition_ids}
        templates = {
            parameter.technical_name: parameter
            for parameter in self.env["psql.query.parameter"].search([
                ("technical_name", "in", [spec["technical_name"] for spec in specs]),
            ])
        }
        sequence = max(self.filter_definition_ids.mapped("sequence") or [0]) + 10
        created = 0
        updated = 0
        linked = 0
        missing = []
        for spec in specs:
            template = templates.get(spec["technical_name"])
            if not template:
                missing.append(spec["name"])
                continue
            values = template._definition_values(query_id=self.id, sequence=sequence)
            definition = existing.get(spec["technical_name"])
            if definition:
                definition.write({key: value for key, value in values.items() if key not in {"query_id", "sequence"}})
                definition._sync_selection_options()
                updated += 1
            else:
                definition = self.env["psql.query.filter.definition"].create(values)
                definition._sync_selection_options()
                existing[definition.technical_name] = definition
                sequence += 10
                created += 1
        if missing:
            if len(missing) == 1:
                raise ValidationError(_(
                    'Parameter "%s" was not found.\n\nPlease create it in:\n\nConfiguration → Parameters',
                    missing[0],
                ))
            raise ValidationError(_(
                "The following parameters were not found: %s.\n\nPlease create them in:\n\nConfiguration → Parameters",
                ", ".join(missing),
            ))
        return {"specs": len(specs), "created": created, "updated": updated, "linked": linked, "removed": removed}

    def _roommaster_sql_to_named_placeholders(self, sql_text):
        self.ensure_one()

        def replacement(match):
            spec = self._parse_roommaster_parameter(match.group(1))
            name = spec["technical_name"]
            if spec["filter_type"] in {"date_range", "number_range"}:
                return f"%({name}_from)s AND %({name}_to)s"
            return f"%({name})s"

        return ROOMMASTER_PARAMETER_RE.sub(replacement, sql_text or "")

    @staticmethod
    def _extract_sql_placeholder_names(sql_text):
        normalized = PsqlQuery._normalize_sql_placeholders(sql_text)
        return set(re.findall(r"%\(([A-Za-z_][A-Za-z0-9_]*)\)s", normalized))

    @staticmethod
    def _escape_sql_literal_percents(sql_text):
        """Escape modulo/LIKE percent signs without changing named placeholders."""
        return re.sub(r"%(?!\([A-Za-z_][A-Za-z0-9_]*\)s|%)", "%%", sql_text)

    def _configured_sql_parameter_names(self):
        names = set()
        for definition in self.filter_definition_ids.filtered("active"):
            names.update(definition._placeholder_names())
        return names

    def _prepare_sql_parameters(self, sql_text, runtime_parameters):
        self.ensure_one()
        sql_text = self._roommaster_sql_to_named_placeholders(sql_text)
        definitions = self.filter_definition_ids.filtered("active")
        invalid_selections = definitions.filtered(
            lambda item: item.filter_type in {"selection", "multi_selection"}
            and not item.option_ids.filtered("active")
        )
        if invalid_selections:
            raise ValidationError(_(
                "Add Selection Values for parameter(s): %s.",
                ", ".join(invalid_selections.mapped("name")),
            ))
        normalized_sql = self._normalize_sql_placeholders(sql_text)
        placeholders = self._extract_sql_placeholder_names(normalized_sql)
        configured = self._configured_sql_parameter_names()
        unknown = sorted(placeholders - configured)
        if unknown:
            raise ValidationError(_(
                "Unknown SQL parameter(s): %s. Create matching Report Parameters first.",
                ", ".join(unknown),
            ))
        if placeholders and runtime_parameters is None:
            raise ValidationError(_(
                "This query requires parameters. Use Run Report and complete the Report Parameters popup."
            ))

        payload = runtime_parameters or {}
        bound_values = {
            name: value
            for name, value in dict(payload.get("values") or {}).items()
            if name in placeholders
        }
        missing_values = sorted(placeholders - set(bound_values))
        if missing_values:
            raise ValidationError(_(
                "SQL parameter value(s) were not supplied: %s.",
                ", ".join(missing_values),
            ))
        for definition in definitions:
            definition_values = {
                name: bound_values.get(name)
                for name in definition._placeholder_names()
                if name in placeholders
            }
            if not definition_values:
                continue
            if definition.required and any(value in (None, "", [], ()) for value in definition_values.values()):
                raise ValidationError(_("Enter the required parameter: %s", definition.name))
            definition._validate_parameter_values(definition_values)
        execution_sql, execution_values = self._expand_list_parameters(
            self._escape_sql_literal_percents(normalized_sql) if placeholders else normalized_sql,
            bound_values,
        )
        return (
            execution_sql,
            execution_values,
            payload.get("summary") or "",
            payload.get("stored_values") or [],
        )

    @staticmethod
    def _expand_list_parameters(sql_text, bound_values):
        expanded_values = {}
        expanded_sql = sql_text
        for name, value in (bound_values or {}).items():
            if isinstance(value, (list, tuple)):
                items = list(value)
                if not items:
                    expanded_sql = expanded_sql.replace(f"%({name})s", "NULL")
                    continue
                placeholders = []
                for index, item in enumerate(items):
                    item_name = f"{name}_{index}"
                    placeholders.append(f"%({item_name})s")
                    expanded_values[item_name] = item
                expanded_sql = expanded_sql.replace(f"%({name})s", ", ".join(placeholders))
            else:
                expanded_values[name] = value
        return expanded_sql, expanded_values

    def _hidden_parameter_payload(self):
        self.ensure_one()
        values = {}
        stored_values = []
        for definition in self.filter_definition_ids.filtered("active").sorted("sequence"):
            parameter_values = definition._hidden_default_values()
            if definition.required and any(value in (None, "", [], ()) for value in parameter_values.values()):
                raise ValidationError(_("Configure a default for hidden required parameter: %s", definition.name))
            values.update(parameter_values)
            stored_values.append({
                "definition_id": definition.id,
                "label": definition.name,
                "technical_name": definition.technical_name,
                "values": {
                    key: self._serialize_cell(value)
                    for key, value in parameter_values.items()
                },
            })
        return {"values": values, "summary": "", "stored_values": stored_values}

    def _execute_and_store(self, runtime_parameters=None):
        self.ensure_one()
        self._ensure_sql_admin()
        started = time.perf_counter()

        try:
            sql_for_validation = self._roommaster_sql_to_named_placeholders(self.query_name)
            sql_text, statement_type = self._validate_read_only_sql(sql_for_validation)
            placeholders = self._extract_sql_placeholder_names(sql_text)
            if placeholders - self._configured_sql_parameter_names():
                self._auto_configure_sql_parameter_definitions()
        except Exception as error:
            message = error.args[0] if isinstance(error, ValidationError) else str(error)
            return self._store_execution(
                duration=time.perf_counter() - started,
                status="error",
                error_message=message,
            )

        try:
            prepared_sql, bound_parameters, filter_summary, stored_filter_values = (
                self._prepare_sql_parameters(sql_text, runtime_parameters)
            )
        except Exception as error:
            message = error.args[0] if isinstance(error, ValidationError) else str(error)
            return self._store_execution(
                duration=time.perf_counter() - started,
                status="error",
                error_message=message,
            )

        cursor = self.env.cr
        savepoint = "qsql_interactive_execution"
        cursor.execute("SAVEPOINT %s" % savepoint)
        try:
            cursor.execute("SET LOCAL statement_timeout TO '%sms'" % QUERY_TIMEOUT_MS)
            if statement_type in {"select", "with"}:
                execution_sql = (
                    f"SELECT * FROM ({prepared_sql}) AS qsql_parameterized_result "
                    f"LIMIT {MAX_RESULT_ROWS + 1}"
                )
            else:
                execution_sql = prepared_sql
            cursor.execute(execution_sql, bound_parameters or None)
            columns = [description.name for description in (cursor.description or [])]
            raw_rows = cursor.fetchall() if cursor.description else []
            limited = len(raw_rows) > MAX_RESULT_ROWS
            raw_rows = raw_rows[:MAX_RESULT_ROWS]
            rows = [[self._serialize_cell(value) for value in row] for row in raw_rows]
            cursor.execute("ROLLBACK TO SAVEPOINT %s" % savepoint)
            cursor.execute("RELEASE SAVEPOINT %s" % savepoint)
            status = "success" if rows else "empty"
            payload = self._store_execution(
                columns=columns,
                rows=rows,
                duration=time.perf_counter() - started,
                status=status,
                limited=limited,
            )
            self.with_context(tracking_disable=True).write({
                "last_filter_summary": filter_summary or False,
                "last_filter_values": stored_filter_values or False,
            })
            payload["filter_summary"] = filter_summary
            return payload
        except Exception as error:
            cursor.execute("ROLLBACK TO SAVEPOINT %s" % savepoint)
            cursor.execute("RELEASE SAVEPOINT %s" % savepoint)
            message = self._friendly_database_error(error)
            _logger.info("Interactive SQL report %s failed: %s", self.id, message)
            return self._store_execution(
                duration=time.perf_counter() - started,
                status="error",
                error_message=message,
            )

    def execute_interactive_query(self):
        """RPC endpoint used by the interactive workspace."""
        self.ensure_one()
        sql_for_validation = self._roommaster_sql_to_named_placeholders(self.query_name)
        sql_text, _statement_type = self._validate_read_only_sql(sql_for_validation)
        placeholders = self._extract_sql_placeholder_names(sql_text)
        if placeholders:
            self._auto_configure_sql_parameter_definitions()
            visible_parameters = self.filter_definition_ids.filtered(
                lambda definition: definition.active
                and definition.visible
                and placeholders.intersection(definition._placeholder_names())
            )
            if visible_parameters:
                return {
                    "ok": False,
                    "needs_parameters": True,
                    "action": self.action_open_filter_wizard(),
                    "status": "parameters",
                    "error": "",
                    "duration": 0,
                    "row_count": 0,
                    "columns": [],
                    "rows": [],
                    "executed_at": fields.Datetime.to_string(fields.Datetime.now()),
                }
        return self._execute_and_store()

    def action_execute_query(self):
        """Backward-compatible object button action."""
        self.ensure_one()
        payload = self._execute_and_store()
        if payload["ok"]:
            message = _("Query executed successfully: %s row(s).", payload["row_count"])
            notification_type = "success"
        else:
            message = payload["error"]
            notification_type = "danger"
        return {
            "type": "ir.actions.client",
            "tag": "display_notification",
            "params": {
                "title": _("Interactive SQL Report"),
                "message": message,
                "type": notification_type,
                "sticky": not payload["ok"],
                "next": {"type": "ir.actions.client", "tag": "reload"},
            },
        }

    def action_run_business_report(self):
        """Execute through the existing safe path and preview its business PDF."""
        self.ensure_one()
        active_parameters = self.filter_definition_ids.filtered("active")
        placeholders = self._extract_sql_placeholder_names(
            self._roommaster_sql_to_named_placeholders(self.query_name)
        )
        visible_parameters = active_parameters.filtered(
            lambda definition: definition.visible
            and placeholders.intersection(definition._placeholder_names())
        )
        if visible_parameters and not self.env.context.get("skip_filter_wizard"):
            return self.action_open_filter_wizard()
        payload = self._execute_and_store(
            self._hidden_parameter_payload() if placeholders and active_parameters else None
        )
        if not payload["ok"]:
            raise ValidationError(payload["error"])
        return {
            "type": "ir.actions.client",
            "tag": "psql_query_execute.pdf_preview",
            "params": {
                "name": self.name or _("SQL Report"),
                "url": (
                    "/report/pdf/"
                    f"psql_query_execute.report_sql_business_document/{self.id}"
                ),
            },
        }

    def action_open_filter_wizard(self):
        self.ensure_one()
        self._ensure_sql_admin()
        wizard = self.env["psql.query.filter.wizard"].create({"query_id": self.id})
        wizard._populate_filter_lines()
        return {
            "type": "ir.actions.act_window",
            "name": _("Report Parameters"),
            "res_model": "psql.query.filter.wizard",
            "res_id": wizard.id,
            "view_mode": "form",
            "views": [(self.env.ref("psql_query_execute.psql_query_filter_wizard_view_form").id, "form")],
            "target": "new",
            "context": {"dialog_size": "large"},
        }

    def action_clear_workspace(self):
        self.ensure_one()
        self._ensure_sql_admin()
        self.write({
            "query_name": "SELECT ",
            "query_result": False,
            "result_data": False,
            "last_result_metadata": False,
            "last_execution_status": "never",
            "last_error": False,
            "execution_duration": 0.0,
            "returned_row_count": 0,
            "result_limited": False,
        })
        return {"type": "ir.actions.client", "tag": "reload"}

    def action_duplicate_report(self):
        self.ensure_one()
        duplicate = self.copy({"name": _("%s (Copy)", self.name)})
        return {
            "type": "ir.actions.act_window",
            "name": duplicate.name,
            "res_model": "psql.query",
            "res_id": duplicate.id,
            "view_mode": "form",
            "target": "current",
        }

    @api.model
    def get_database_objects(self, search_term=None):
        self._ensure_sql_admin()
        term = "%%%s%%" % (search_term or "")
        self.env.cr.execute(
            """
            SELECT t.table_schema, t.table_name, t.table_type,
                   c.column_name, c.data_type, c.ordinal_position
              FROM information_schema.tables t
              JOIN information_schema.columns c
                ON c.table_schema = t.table_schema
               AND c.table_name = t.table_name
             WHERE t.table_schema NOT IN ('pg_catalog', 'information_schema', 'pg_toast')
               AND (%s = '%%%%' OR t.table_name ILIKE %s OR c.column_name ILIKE %s)
             ORDER BY t.table_schema, t.table_name, c.ordinal_position
             LIMIT 8000
            """,
            [term, term, term],
        )
        schemas = {}
        for schema, table, table_type, column, data_type, _position in self.env.cr.fetchall():
            schema_entry = schemas.setdefault(schema, {"name": schema, "tables": {}})
            table_entry = schema_entry["tables"].setdefault(
                table,
                {
                    "name": table,
                    "schema": schema,
                    "type": "view" if "VIEW" in table_type else "table",
                    "columns": [],
                },
            )
            table_entry["columns"].append({"name": column, "type": data_type})
        return [
            {"name": schema["name"], "tables": list(schema["tables"].values())}
            for schema in schemas.values()
        ]

    def action_open_sql_wizard(self):
        self.ensure_one()
        self._ensure_sql_admin()
        wizard_view = self.env.ref("psql_query_execute.psql_query_wizard_view_form")
        wizard = self.env["psql.query.wizard"].create({"query_id": self.id})
        wizard._load_table_options()
        return {
            "type": "ir.actions.act_window",
            "name": _("SQL Wizard"),
            "res_model": "psql.query.wizard",
            "res_id": wizard.id,
            "view_mode": "form",
            "views": [(wizard_view.id, "form")],
            "target": "new",
            "flags": {"mode": "edit"},
            "context": {
                "default_query_id": self.id,
                "dialog_size": "extra-large",
                "form_view_initial_mode": "edit",
            },
        }

    def action_auto_configure_sql_parameters(self):
        self.ensure_one()
        self._ensure_sql_admin()
        result = self._auto_configure_sql_parameter_definitions()
        if not result["specs"]:
            raise ValidationError(_("No SQL parameters were found in the query. Use roomMaster tokens like {?Guest Name} or SQL placeholders like %(guest_name)s."))
        return {
            "type": "ir.actions.client",
            "tag": "display_notification",
            "params": {
                "title": _("SQL Parameters"),
                "message": _("Auto-configured %s parameter(s): %s report link(s) created, %s updated, %s reusable parameter(s) created.", result["specs"], result["created"], result["updated"], result["linked"]),
                "type": "success",
                "next": {"type": "ir.actions.client", "tag": "reload"},
            },
        }

    def action_detect_roommaster_parameters(self):
        return self.action_auto_configure_sql_parameters()

    def action_link_reusable_parameters(self):
        self.ensure_one()
        self._ensure_sql_admin()
        return {
            "type": "ir.actions.act_window",
            "name": _("Link Reusable Parameters"),
            "res_model": "psql.query.parameter",
            "view_mode": "list,form",
            "target": "current",
            "domain": [("active", "=", True)],
            "context": {
                "link_to_query_id": self.id,
            },
        }

    def action_export_xlsx(self):
        self.ensure_one()
        self._ensure_sql_admin()
        if not self.has_result:
            raise ValidationError(_("Run the query before exporting a result."))
        return {"type": "ir.actions.act_url", "url": f"/psql_query_execute/export/xlsx/{self.id}", "target": "self"}

    def action_export_csv(self):
        self.ensure_one()
        self._ensure_sql_admin()
        if not self.has_result:
            raise ValidationError(_("Run the query before exporting a result."))
        return {"type": "ir.actions.act_url", "url": f"/psql_query_execute/export/csv/{self.id}", "target": "self"}

    def _get_report_data(self):
        self.ensure_one()
        self._ensure_sql_admin()
        if not self.result_data:
            payload = self._execute_and_store()
            if not payload["ok"]:
                raise ValidationError(payload["error"])
        presentation = self._get_report_presentation()
        return {
            "ids": self,
            "model": "psql.query",
            "no_value": not bool(presentation["row_count"]),
            "header": [column["label"] for column in presentation["columns"]],
            "form": [
                tuple(cell["value"] for cell in row)
                for group in presentation["groups"]
                for row in group["rows"]
            ],
            "date": fields.Date.context_today(self),
        }

    def action_print_query_result_xlsx(self):
        """Keep the original report action for compatibility."""
        self.ensure_one()
        data = self._get_report_data()
        return {
            "type": "ir.actions.report",
            "report_type": "xlsx",
            "data": {
                "model": "psql.query",
                "output_format": "xlsx",
                "options": json.dumps(data, default=json_default),
                "report_name": self.name or "Query Report",
            },
        }

    def get_xlsx_report(self, data, response):
        """Generate an XLSX matching the business PDF presentation."""
        self.ensure_one()
        presentation = self._get_report_presentation()
        columns = presentation["columns"]
        output = io.BytesIO()
        workbook = xlsxwriter.Workbook(output, {"in_memory": True})
        sheet = workbook.add_worksheet("Query Result")
        title_format = workbook.add_format({
            "bold": True, "font_size": 18, "font_color": "#9B7A32", "align": "center",
        })
        company_format = workbook.add_format({"bold": True, "font_size": 13, "font_color": "#333333"})
        meta_format = workbook.add_format({"font_size": 9, "font_color": "#666666"})
        meta_right_format = workbook.add_format({"font_size": 9, "font_color": "#666666", "align": "right"})
        filter_format = workbook.add_format({"font_size": 9, "font_color": "#222222"})
        filter_right_format = workbook.add_format({"font_size": 9, "font_color": "#222222", "align": "right"})
        header_format = workbook.add_format({
            "bold": True, "bg_color": "#F2EAD7", "top": 1, "bottom": 1,
            "font_color": "#000000", "valign": "vcenter",
        })
        cell_formats = {
            alignment: workbook.add_format({
                "bottom": 1, "bottom_color": "#DDDDDD", "align": alignment, "valign": "vcenter",
            })
            for alignment in ("left", "center", "right")
        }
        group_format = workbook.add_format({
            "bold": True, "bg_color": "#F7F3E9", "font_color": "#9B7A32", "bottom": 1,
        })
        total_format = workbook.add_format({
            "bold": True, "top": 1, "bg_color": "#F2EAD7", "align": "right",
        })
        last_column = max(len(columns) - 1, 0)
        sheet.write(0, 0, self.env.company.display_name, company_format)
        sheet.write(1, 0, _("SQL Management Report"), meta_format)
        sheet.write(0, last_column, _("Printed by: %s", self.env.user.display_name), meta_right_format)
        sheet.write(1, last_column, _("Printed date: %s", fields.Datetime.context_timestamp(
            self, fields.Datetime.now()
        ).strftime("%Y-%m-%d %H:%M")), meta_right_format)
        if last_column:
            sheet.merge_range(3, 0, 3, last_column, self.name or _("SQL Report"), title_format)
        else:
            sheet.write(3, 0, self.name or _("SQL Report"), title_format)
        sheet.write(5, 0, _("Company: %s", self.env.company.display_name), filter_format)
        period = ""
        if self.report_date_from or self.report_date_to:
            period = _("Period: %s - %s", self.report_date_from or "...", self.report_date_to or "...")
        else:
            period = _("Category: %s", self.category_id.complete_name or _("Uncategorized"))
        sheet.write(5, last_column, period, filter_right_format)
        active_filter_summary = self.last_filter_summary or self.report_filter_summary
        if active_filter_summary:
            sheet.write(6, 0, _("Filters: %s", active_filter_summary), filter_format)
        header_row = 8
        for column_index, column in enumerate(columns):
            sheet.write(header_row, column_index, column["label"], header_format)
        row_index = header_row + 1
        for group in presentation["groups"]:
            if group["label"] is not False:
                if last_column:
                    sheet.merge_range(row_index, 0, row_index, last_column, group["label"], group_format)
                else:
                    sheet.write(row_index, 0, group["label"], group_format)
                row_index += 1
            for row in group["rows"]:
                for column_index, cell in enumerate(row):
                    sheet.write(row_index, column_index, cell["value"], cell_formats[cell["alignment"]])
                row_index += 1
        if presentation["has_total"]:
            for column_index, cell in enumerate(presentation["totals"]):
                sheet.write(row_index, column_index, cell["value"], total_format)
            row_index += 1
        sheet.write(row_index + 1, 0, _("End of Report (%s records)", presentation["row_count"]), meta_format)
        for column_index, column in enumerate(columns):
            sample = [
                str(row[column_index]["value"])
                for group in presentation["groups"]
                for row in group["rows"][:100]
                if column_index < len(row)
            ]
            width = min(50, max([len(column["label"]), 12] + [len(value) for value in sample]) + 2)
            sheet.set_column(column_index, column_index, width)
        sheet.freeze_panes(header_row + 1, 0)
        sheet.autofilter(header_row, 0, max(row_index - 1, header_row), last_column)
        sheet.set_landscape() if presentation["landscape"] else sheet.set_portrait()
        sheet.fit_to_pages(1, 0)
        sheet.repeat_rows(0, header_row)
        sheet.set_margins(0.25, 0.25, 0.4, 0.4)
        workbook.close()
        output.seek(0)
        response.stream.write(output.read())
        output.close()


class PsqlQueryParameter(models.Model):
    _name = "psql.query.parameter"
    _description = "Reusable SQL Report Parameter"
    _order = "sequence, name, id"

    sequence = fields.Integer(string="Display Order", default=10)
    active = fields.Boolean(default=True)
    name = fields.Char(string="Parameter Name", required=True)
    label = fields.Char(string="Label")
    technical_name = fields.Char(required=True)
    description = fields.Text()
    placeholder = fields.Char(compute="_compute_placeholder", store=True)
    filter_type = fields.Selection(
        PARAMETER_TYPE_SELECTION,
        string="Parameter Type",
        required=True,
        default="text",
    )
    required = fields.Boolean()
    default_value_type = fields.Selection(
        [
            ("static", "Static Value"),
            ("today", "Today"),
            ("yesterday", "Yesterday"),
            ("month_start", "Start of Current Month"),
            ("month_end", "End of Current Month"),
            ("current_user", "Current User"),
            ("current_company", "Current Company"),
            ("current_datetime", "Current Datetime"),
            ("current_language", "Current Language"),
            ("current_timezone", "Current Timezone"),
        ],
        string="Default Value Type",
        default="static",
    )
    default_text = fields.Char(string="Default Text")
    default_number = fields.Float(string="Default / Minimum")
    default_number_to = fields.Float(string="Default Maximum")
    default_date = fields.Date(string="Default / From Date")
    default_date_to = fields.Date(string="Default To Date")
    default_datetime = fields.Datetime(string="Default Datetime")
    default_boolean = fields.Boolean(string="Default Boolean")
    default_relation_id = fields.Integer(string="Default Record ID")
    help_text = fields.Text(string="Help Text")
    visible = fields.Boolean(string="Show in Popup", default=True)
    hidden = fields.Boolean(string="Hidden")
    read_only = fields.Boolean(string="Read Only")
    allow_multiple_values = fields.Boolean(string="Allow Multiple Values")
    show_in_report_header = fields.Boolean(string="Show in Report Header", default=True)
    show_in_pdf_header = fields.Boolean(string="Show in PDF Header", default=True)
    source_type = fields.Selection(
        [
            ("none", "Manual Entry"),
            ("fixed", "Fixed Selection Values"),
            ("table", "Dynamic Table Lookup"),
            ("sql", "Dynamic SQL Lookup"),
            ("odoo_model", "Odoo Model Lookup"),
            ("hidden", "Hidden Context Value"),
        ],
        string="Data Source Type",
        default="none",
    )
    fixed_selection_values = fields.Text(
        string="Fixed Selection Values",
        help="One value per line, or pipe-separated values. Use Label=Value when label and stored value differ.",
    )
    sql_lookup_query = fields.Text(string="SQL Lookup Query")
    odoo_model_id = fields.Many2one(
        "ir.model",
        string="Odoo Model",
        ondelete="set null",
        domain="[('transient', '=', False)]",
    )
    display_field = fields.Char(string="Display Field", default="display_name")
    value_field = fields.Char(string="Value Field", default="id")
    domain = fields.Char(string="Domain or Filter")
    source_table = fields.Char(string="Source Table")
    source_field = fields.Char(string="Source Field")
    parent_parameter_id = fields.Many2one(
        "psql.query.parameter",
        string="Parent Parameter",
        ondelete="set null",
    )
    validation_rule = fields.Char(string="Validation Rules")
    date_format = fields.Char(string="Date Format")
    number_format = fields.Char(string="Number Format")
    report_definition_ids = fields.One2many(
        "psql.query.filter.definition",
        "reusable_parameter_id",
        string="Linked Reports",
        readonly=True,
    )

    @api.model_create_multi
    def create(self, values_list):
        for values in values_list:
            if not values.get("technical_name"):
                values["technical_name"] = _slug_parameter_name(values.get("name") or values.get("label"))
            if not values.get("label"):
                values["label"] = values.get("name")
            if values.get("filter_type"):
                values["source_type"] = _source_type_for_parameter_type(
                    values["filter_type"], values.get("source_type")
                )
            if values.get("hidden"):
                values["visible"] = False
        return super().create(values_list)

    def write(self, values):
        if values.get("filter_type"):
            values = dict(values)
            values["source_type"] = _source_type_for_parameter_type(
                values["filter_type"], values.get("source_type")
            )
        if values.get("hidden"):
            values = dict(values)
            values["visible"] = False
        return super().write(values)

    @api.depends("technical_name", "filter_type")
    def _compute_placeholder(self):
        for parameter in self:
            name = parameter.technical_name or "parameter"
            if parameter.filter_type in DATE_RANGE_PARAMETER_TYPES:
                parameter.placeholder = f"%({name}_from)s / %({name}_to)s"
            else:
                parameter.placeholder = f"%({name})s"

    @api.constrains("technical_name")
    def _check_technical_name(self):
        for parameter in self:
            if not re.match(r"^[a-z_][a-z0-9_]*$", parameter.technical_name or ""):
                raise ValidationError(_(
                    "Technical Name must use lowercase letters, numbers, and underscores, and cannot start with a number."
                ))
            duplicate = self.search_count([
                ("technical_name", "=", parameter.technical_name),
                ("id", "!=", parameter.id),
            ])
            if duplicate:
                raise ValidationError(_("Technical Name must be unique."))

    def _definition_values(self, query_id=None, sequence=None):
        self.ensure_one()
        values = {
            "query_id": query_id,
            "reusable_parameter_id": self.id,
            "sequence": sequence if sequence is not None else self.sequence,
            "active": self.active,
            "visible": self.visible,
            "hidden": self.hidden,
            "name": self.label or self.name,
            "technical_name": self.technical_name,
            "filter_type": self.filter_type,
            "required": self.required,
            "help_text": self.help_text,
            "read_only": self.read_only,
            "allow_multiple_values": self.allow_multiple_values,
            "show_in_report_header": self.show_in_report_header,
            "show_in_pdf_header": self.show_in_pdf_header,
            "source_type": self.source_type,
            "source_table": self.source_table,
            "source_field": self.source_field,
            "odoo_model_id": self.odoo_model_id.id,
            "relation_model_id": self.odoo_model_id.id,
            "display_field": self.display_field,
            "value_field": self.value_field,
            "domain": self.domain,
            "fixed_selection_values": self.fixed_selection_values,
            "sql_lookup_query": self.sql_lookup_query,
            "validation_rule": self.validation_rule,
            "date_format": self.date_format,
            "number_format": self.number_format,
            "default_value_type": self.default_value_type,
            "default_text": self.default_text,
            "default_number": self.default_number,
            "default_number_to": self.default_number_to,
            "default_date": self.default_date,
            "default_date_to": self.default_date_to,
            "default_datetime": self.default_datetime,
            "default_boolean": self.default_boolean,
            "default_relation_id": self.default_relation_id,
        }
        return {key: value for key, value in values.items() if value is not None}

    @api.model
    def _standard_parameter_specs(self):
        selection_values = "Draft=draft\nConfirmed=confirm\nCompleted=done\nCancelled=cancel"
        status_values = (
            "Draft=draft\n"
            "Confirmed=confirm\n"
            "Guaranteed=guaranteed\n"
            "Waitlist=waitlist\n"
            "In-House=checkin\n"
            "Checkout Hold=checkout_hold\n"
            "Checked Out=checkout\n"
            "No-Show=noshow\n"
            "Cancelled=cancel\n"
            "Maintenance Block=blocked"
        )
        payment_values = "Draft\nPending\nPaid\nPosted\nCancelled"
        room_status_values = (
            "Vacant Clean=vacant_clean\n"
            "Vacant Dirty=vacant_dirty\n"
            "Occupied Clean=occupied_clean\n"
            "Occupied Dirty=occupied_dirty\n"
            "Out of Order=blocked\n"
            "Available=available"
        )

        def spec(name, technical_name=None, filter_type="text", sequence=10, **extra):
            values = {
                "name": name,
                "label": name,
                "technical_name": technical_name or _slug_parameter_name(name),
                "filter_type": filter_type,
                "sequence": sequence,
                "active": True,
                "required": extra.pop("required", False),
                "visible": extra.pop("visible", True),
                "hidden": extra.pop("hidden", False),
                "read_only": extra.pop("read_only", False),
                "allow_multiple_values": extra.pop("allow_multiple_values", filter_type in MULTI_VALUE_PARAMETER_TYPES),
                "show_in_report_header": extra.pop("show_in_report_header", not extra.get("hidden", False)),
                "show_in_pdf_header": extra.pop("show_in_pdf_header", not extra.get("hidden", False)),
                "source_type": extra.pop("source_type", _source_type_for_parameter_type(filter_type, "none")),
                "display_field": extra.pop("display_field", "display_name"),
                "value_field": extra.pop("value_field", "id"),
                "default_value_type": extra.pop("default_value_type", "static"),
                "help_text": extra.pop("help_text", _("Standard SQL Reports parameter.")),
            }
            values.update(extra)
            return values

        specs = []
        sequence = 10

        def add(name, filter_type="text", technical_name=None, step=10, **extra):
            nonlocal sequence
            specs.append(spec(name, technical_name, filter_type, sequence, **extra))
            sequence += step

        for name in [
            "From Date", "To Date", "Report Date", "Booking Date", "Check-in Date",
            "Check-out Date", "Entry Date", "Created Date", "Updated Date",
        ]:
            add(name, "date")
        for name in [
            "Date Range", "Stay Date Range", "Booking Date Range", "Check-in Date Range",
            "Check-out Date Range", "Created Date Range",
        ]:
            add(name, "date_range", required=(name == "Date Range"))
        for name in [
            "Guest Name", "Customer Name", "Room Number", "Confirmation Number",
            "Reference Number", "Phone Number", "Email", "Description", "Search Text",
        ]:
            add(name, "text")
        for name in ["Integer", "Minimum Value", "Maximum Value", "Number of Guests", "Number of Rooms", "Number of Nights"]:
            add(name, "integer")
        for name in ["Minimum Amount", "Maximum Amount", "Percentage"]:
            add(name, "decimal")
        for name in [
            "Include Cancelled", "Include Inactive", "Include Zero Amount",
            "Include Posted Records", "Include Completed Records", "Show Details", "Group Results",
        ]:
            add(name, "boolean", default_boolean=False)

        fixed_selections = {
            "Status": status_values,
            "Room Status": room_status_values,
            "Reservation Status": status_values,
            "Payment Status": payment_values,
            "Order Status": selection_values,
            "Payment Method": "Cash\nCredit Card\nBank Transfer\nCity Ledger",
            "Room Type": "",
            "Rate Code": "RACK\nBAR\nCORP\nCOMP",
            "Market Segment": "Direct\nCorporate\nOnline Travel Agent\nGroup",
            "Nationality": "",
            "Country": "",
            "Currency": "",
            "Company": "",
            "User": "",
            "Employee": "",
            "Department": "",
            "Customer": "",
            "Product": "",
            "Product Category": "",
            "Outlet": "",
            "Branch": "",
        }
        for name, values in fixed_selections.items():
            add(name, "selection", source_type="fixed" if values else "none", fixed_selection_values=values)

        for name in [
            "Multiple Statuses", "Multiple Room Types", "Multiple Rooms", "Multiple Payment Methods",
            "Multiple Companies", "Multiple Users", "Multiple Employees", "Multiple Products",
            "Multiple Product Categories", "Multiple Outlets",
        ]:
            fixed = {
                "Multiple Statuses": status_values,
                "Multiple Room Types": "",
                "Multiple Rooms": "101\n102\n103",
                "Multiple Payment Methods": "Cash\nCredit Card\nBank Transfer\nCity Ledger",
            }.get(name, "")
            add(name, "multi_selection", source_type="fixed" if fixed else "none", fixed_selection_values=fixed, allow_multiple_values=True)

        model_parameters = {
            "Company": "res.company",
            "User": "res.users",
            "Employee": "hr.employee",
            "Department": "hr.department",
            "Customer": "res.partner",
            "Product": "product.product",
            "Product Category": "product.category",
            "Country": "res.country",
            "Currency": "res.currency",
            "Room Type": "hotel.room.type",
            "Outlet": "hotel.room.service.outlet",
            "Payment Method": "account.payment.method",
        }
        for item in specs:
            model_name = model_parameters.get(item["name"])
            if not model_name:
                continue
            model = self.env["ir.model"].sudo().search([("model", "=", model_name)], limit=1)
            if model:
                item.update({
                    "filter_type": "many2one",
                    "source_type": "odoo_model",
                    "odoo_model_id": model.id,
                    "display_field": "display_name",
                    "value_field": "id",
                })

        hidden_specs = [
            ("Current User", "current_user", "current_user"),
            ("Current User ID", "current_user_id", "current_user"),
            ("Current Company", "current_company", "current_company"),
            ("Current Company ID", "current_company_id", "current_company"),
            ("Current Date", "current_date", "today"),
            ("Current Datetime", "current_datetime", "current_datetime"),
            ("Current Language", "current_language", "current_language"),
            ("Current Timezone", "current_timezone", "current_timezone"),
            ("Current Fiscal Year", "current_fiscal_year", "static"),
            ("Active Company IDs", "active_company_ids", "static"),
        ]
        for name, technical_name, default_type in hidden_specs:
            add(
                name,
                "hidden",
                technical_name=technical_name,
                hidden=True,
                visible=False,
                read_only=True,
                source_type="hidden",
                default_value_type=default_type,
                show_in_report_header=False,
                show_in_pdf_header=False,
            )

        relative_names = [
            "Today", "Yesterday", "This Week", "Last Week", "This Month", "Last Month",
            "This Quarter", "Last Quarter", "This Year", "Last Year", "Month to Date",
            "Quarter to Date", "Year to Date", "Last 7 Days", "Last 30 Days",
            "Last 90 Days", "Custom Date Range",
        ]
        for name in relative_names:
            default_type = {
                "Today": "today",
                "Yesterday": "yesterday",
                "This Month": "month_start",
                "This Year": "static",
            }.get(name, "static")
            add(name, "date_range" if name not in {"Today", "Yesterday"} else "date", default_value_type=default_type)

        priority_defaults = {
            "date_range": {
                "sequence": 10,
                "required": True,
                "show_in_report_header": True,
                "show_in_pdf_header": True,
                "help_text": _("Primary report period. Displays From Date and To Date in the runtime popup."),
            },
            "from_date": {
                "sequence": 20,
                "required": False,
                "help_text": _("Optional standalone start date when a report does not use Date Range."),
            },
            "to_date": {
                "sequence": 30,
                "required": False,
                "help_text": _("Optional standalone end date when a report does not use Date Range."),
            },
            "status": {
                "sequence": 40,
                "required": False,
                "source_type": "fixed",
                "fixed_selection_values": status_values,
                "help_text": _("Reservation status. Values match the hotel reservation state field."),
            },
            "room_type": {
                "sequence": 50,
                "required": False,
                "help_text": _("Room type lookup from the Hotel Room Type model."),
            },
            "company": {
                "sequence": 60,
                "required": False,
                "help_text": _("Company lookup. Use with company_id filters when reports should be company-specific."),
            },
            "customer": {
                "sequence": 70,
                "required": False,
                "help_text": _("Customer lookup from Contacts."),
            },
            "user": {
                "sequence": 80,
                "required": False,
                "help_text": _("Odoo user lookup for user-specific reports."),
            },
            "product": {
                "sequence": 90,
                "required": False,
                "help_text": _("Product lookup for sales, inventory, and accounting reports."),
            },
            "guest_name": {
                "sequence": 100,
                "required": False,
                "help_text": _("Optional guest or customer name search text."),
            },
            "room_number": {
                "sequence": 110,
                "required": False,
                "help_text": _("Optional room number search text."),
            },
            "include_cancelled": {
                "sequence": 120,
                "required": False,
                "default_boolean": False,
                "help_text": _("Enable this only when cancelled records should be included."),
            },
            "include_inactive": {
                "sequence": 130,
                "required": False,
                "default_boolean": False,
                "help_text": _("Enable this only when archived or inactive records should be included."),
            },
            "minimum_amount": {
                "sequence": 140,
                "required": False,
                "help_text": _("Optional minimum amount filter for revenue, balance, payment, or total fields."),
            },
            "maximum_amount": {
                "sequence": 150,
                "required": False,
                "help_text": _("Optional maximum amount filter for revenue, balance, payment, or total fields."),
            },
            "current_user": {
                "sequence": 890,
                "hidden": True,
                "visible": False,
                "read_only": True,
                "show_in_report_header": False,
                "show_in_pdf_header": False,
            },
            "current_user_id": {
                "sequence": 900,
                "hidden": True,
                "visible": False,
                "read_only": True,
                "show_in_report_header": False,
                "show_in_pdf_header": False,
            },
            "current_company": {
                "sequence": 905,
                "hidden": True,
                "visible": False,
                "read_only": True,
                "show_in_report_header": False,
                "show_in_pdf_header": False,
            },
            "current_company_id": {
                "sequence": 910,
                "hidden": True,
                "visible": False,
                "read_only": True,
                "show_in_report_header": False,
                "show_in_pdf_header": False,
            },
            "current_date": {
                "sequence": 920,
                "hidden": True,
                "visible": False,
                "read_only": True,
                "show_in_report_header": False,
                "show_in_pdf_header": False,
            },
            "current_datetime": {
                "sequence": 930,
                "hidden": True,
                "visible": False,
                "read_only": True,
                "show_in_report_header": False,
                "show_in_pdf_header": False,
            },
            "current_language": {
                "sequence": 940,
                "hidden": True,
                "visible": False,
                "read_only": True,
                "show_in_report_header": False,
                "show_in_pdf_header": False,
            },
            "current_timezone": {
                "sequence": 950,
                "hidden": True,
                "visible": False,
                "read_only": True,
                "show_in_report_header": False,
                "show_in_pdf_header": False,
            },
            "active_company_ids": {
                "sequence": 960,
                "hidden": True,
                "visible": False,
                "read_only": True,
                "show_in_report_header": False,
                "show_in_pdf_header": False,
            },
        }
        for item in specs:
            item.update(priority_defaults.get(item["technical_name"], {}))
        return specs

    @api.model
    def _ensure_default_parameters(self, restore=False):
        """Create or restore the standard reusable parameter library.

        Installation and upgrades call this with ``restore=False`` so customer
        edits are preserved. The Configuration button calls it with
        ``restore=True`` as an explicit repair action.
        """
        self = self.sudo()
        imd = self.env["ir.model.data"].sudo()
        created = 0
        linked = 0
        restored = 0
        for values in self._standard_parameter_specs():
            technical_name = values["technical_name"]
            xml_name = f"parameter_{technical_name}"
            xml_id = f"psql_query_execute.{xml_name}"
            parameter_by_xml = self.env.ref(xml_id, raise_if_not_found=False)
            parameter_by_technical = self.search([("technical_name", "=", technical_name)], limit=1)
            parameter = parameter_by_technical or parameter_by_xml
            if not parameter:
                parameter = self.create(values)
                created += 1
            elif restore:
                parameter.write(values)
                restored += 1
            existing_xml = imd.search([
                ("module", "=", "psql_query_execute"),
                ("name", "=", xml_name),
            ], limit=1)
            if not existing_xml:
                imd.create({
                    "module": "psql_query_execute",
                    "name": xml_name,
                    "model": "psql.query.parameter",
                    "res_id": parameter.id,
                    "noupdate": True,
                })
                linked += 1
            elif existing_xml.res_id != parameter.id:
                existing_xml.write({"model": "psql.query.parameter", "res_id": parameter.id})
                linked += 1
        _logger.info(
            "SQL Reports default parameters ready: %s created, %s restored, %s external ids linked.",
            created, restored, linked,
        )
        return {"created": created, "restored": restored, "linked": linked}

    @api.model
    def init_default_parameters(self):
        """Seed standard reusable parameters without overwriting admin changes."""
        self._ensure_default_parameters(restore=False)
        return True

    def action_auto_generate_defaults(self):
        """Repair the standard parameter library from Configuration > Parameters."""
        result = self.env["psql.query.parameter"].sudo()._ensure_default_parameters(restore=True)
        return {
            "type": "ir.actions.client",
            "tag": "display_notification",
            "params": {
                "title": _("Default Parameters Generated"),
                "message": _(
                    "Default SQL Report parameters are ready. Created: %(created)s, restored: %(restored)s, linked: %(linked)s.",
                    created=result["created"],
                    restored=result["restored"],
                    linked=result["linked"],
                ),
                "type": "success",
                "sticky": False,
                "next": {"type": "ir.actions.client", "tag": "reload"},
            },
        }


class PsqlQueryFilterDefinition(models.Model):
    _name = "psql.query.filter.definition"
    _description = "SQL Report Parameter"
    _order = "sequence, id"

    query_id = fields.Many2one("psql.query", required=True, ondelete="cascade", index=True)
    reusable_parameter_id = fields.Many2one(
        "psql.query.parameter",
        string="Reusable Parameter",
        ondelete="set null",
        help="Optional reusable parameter configuration from SQL Reports > Configuration > Parameters.",
    )
    sequence = fields.Integer(default=10)
    active = fields.Boolean(default=True)
    visible = fields.Boolean(default=True, help="Show this parameter in the Run Report popup.")
    hidden = fields.Boolean(string="Hidden")
    name = fields.Char(string="Parameter Label", required=True)
    technical_name = fields.Char(
        help="Lowercase SQL-safe name, for example date_from or room_number.",
    )
    placeholder = fields.Char(compute="_compute_placeholder", store=True)
    filter_type = fields.Selection(
        PARAMETER_TYPE_SELECTION,
        string="Parameter Type",
        required=True,
        default="text",
    )
    required = fields.Boolean(help="Users must enter this parameter before the report can run.")
    help_text = fields.Text(string="Help Text")
    read_only = fields.Boolean(string="Read Only")
    allow_multiple_values = fields.Boolean(string="Allow Multiple Values")
    show_in_report_header = fields.Boolean(string="Show in Report Header", default=True)
    show_in_pdf_header = fields.Boolean(string="Show in PDF Header", default=True)
    source_type = fields.Selection(
        [
            ("none", "Manual Entry"),
            ("fixed", "Fixed Selection Values"),
            ("table", "Dynamic Table Lookup"),
            ("sql", "Dynamic SQL Lookup"),
            ("odoo_model", "Odoo Model Lookup"),
            ("hidden", "Hidden Context Value"),
        ],
        string="Source Type",
        default="none",
    )
    source_table = fields.Char(string="Source Table")
    source_field = fields.Char(string="Source Field")
    odoo_model_id = fields.Many2one(
        "ir.model",
        string="Odoo Model",
        ondelete="set null",
        domain="[('transient', '=', False)]",
    )
    display_field = fields.Char(string="Display Field", default="display_name")
    value_field = fields.Char(string="Value Field", default="id")
    domain = fields.Char(string="Domain")
    fixed_selection_values = fields.Text(
        string="Fixed Selection Values",
        help="One value per line, or pipe-separated values. Use Label=Value when label and stored value differ.",
    )
    sql_lookup_query = fields.Text(string="SQL Lookup Query")
    validation_rule = fields.Char(string="Validation Rule")
    date_format = fields.Char(string="Date Format")
    number_format = fields.Char(string="Number Format")
    default_value_type = fields.Selection(
        [
            ("static", "Static Value"),
            ("today", "Today"),
            ("yesterday", "Yesterday"),
            ("month_start", "Start of Current Month"),
            ("month_end", "End of Current Month"),
            ("current_user", "Current User"),
            ("current_company", "Current Company"),
            ("current_datetime", "Current Datetime"),
            ("current_language", "Current Language"),
            ("current_timezone", "Current Timezone"),
        ],
        string="Default Value Type",
        default="static",
    )
    report_column_id = fields.Many2one(
        "psql.query.report.column",
        string="Field / Column Reference",
        ondelete="set null",
        domain="[('query_id', '=', query_id)]",
    )
    relation_model_id = fields.Many2one(
        "ir.model",
        string="Many2one Model",
        ondelete="set null",
        domain="[('transient', '=', False)]",
    )
    option_ids = fields.One2many(
        "psql.query.parameter.option", "definition_id", string="Selection Values", copy=True
    )
    default_text = fields.Char(string="Default Text")
    default_number = fields.Float(string="Default / Minimum")
    default_number_to = fields.Float(string="Default Maximum")
    default_date = fields.Date(string="Default / From Date")
    default_date_to = fields.Date(string="Default To Date")
    default_datetime = fields.Datetime(string="Default Datetime")
    default_boolean = fields.Boolean(string="Default Boolean")
    default_relation_id = fields.Integer(string="Default Record ID")

    def _template_field_names(self):
        return [
            "name", "technical_name", "filter_type", "required", "help_text",
            "read_only", "allow_multiple_values", "show_in_report_header",
            "show_in_pdf_header", "hidden", "visible", "source_type", "source_table", "source_field",
            "odoo_model_id", "display_field", "value_field", "domain",
            "fixed_selection_values", "sql_lookup_query", "validation_rule",
            "date_format", "number_format", "default_value_type", "default_text",
            "default_number", "default_number_to", "default_date", "default_date_to",
            "default_datetime", "default_boolean", "default_relation_id",
        ]

    def _apply_reusable_parameter(self):
        for definition in self.filtered("reusable_parameter_id"):
            template = definition.reusable_parameter_id
            values = {
                field_name: template[field_name]
                for field_name in definition._template_field_names()
                if field_name in template._fields and field_name in definition._fields
            }
            if template.odoo_model_id:
                values["relation_model_id"] = template.odoo_model_id.id
            definition.update(values)

    @api.onchange("reusable_parameter_id")
    def _onchange_reusable_parameter_id(self):
        self._apply_reusable_parameter()

    @api.model_create_multi
    def create(self, values_list):
        for values in values_list:
            if not values.get("technical_name"):
                base = _slug_parameter_name(values.get("name") or "parameter")
                candidate = base
                suffix = 2
                while self.search_count([
                    ("query_id", "=", values.get("query_id")),
                    ("technical_name", "=", candidate),
                ]):
                    candidate = f"{base}_{suffix}"
                    suffix += 1
                values["technical_name"] = candidate
            if values.get("filter_type"):
                values["source_type"] = _source_type_for_parameter_type(
                    values["filter_type"], values.get("source_type")
                )
            if values.get("hidden"):
                values["visible"] = False
        records = super().create(values_list)
        records._sync_selection_options()
        return records

    def write(self, values):
        if values.get("filter_type"):
            values = dict(values)
            values["source_type"] = _source_type_for_parameter_type(
                values["filter_type"], values.get("source_type")
            )
        if values.get("hidden"):
            values = dict(values)
            values["visible"] = False
        result = super().write(values)
        if {"fixed_selection_values", "source_type", "source_table", "source_field", "sql_lookup_query"} & set(values):
            self._sync_selection_options()
        return result

    def init(self):
        self.env.cr.execute(
            """
            UPDATE psql_query_filter_definition
               SET technical_name = 'parameter_' || id::text
             WHERE technical_name IS NULL OR technical_name = ''
            """
        )

    @api.depends("technical_name", "filter_type")
    def _compute_placeholder(self):
        for definition in self:
            name = definition.technical_name or "parameter"
            if definition.filter_type in DATE_RANGE_PARAMETER_TYPES:
                definition.placeholder = f"%({name}_from)s / %({name}_to)s"
            else:
                definition.placeholder = f"%({name})s"

    def _placeholder_names(self):
        self.ensure_one()
        if self.filter_type in DATE_RANGE_PARAMETER_TYPES:
            return {f"{self.technical_name}_from", f"{self.technical_name}_to"}
        return {self.technical_name}

    def _context_default_value(self):
        self.ensure_one()
        today = fields.Date.context_today(self)
        if self.default_value_type == "today":
            return today
        if self.default_value_type == "yesterday":
            return today - timedelta(days=1)
        if self.default_value_type == "month_start":
            return today.replace(day=1)
        if self.default_value_type == "month_end":
            start = today.replace(day=1)
            return (start.replace(day=28) + timedelta(days=4)).replace(day=1) - timedelta(days=1)
        if self.filter_type == "current_user" or self.default_value_type == "current_user":
            return self.env.user.id
        if self.filter_type == "current_company" or self.default_value_type == "current_company":
            return self.env.company.id
        if self.filter_type == "current_date":
            return today
        if self.default_value_type == "current_datetime":
            return fields.Datetime.now()
        if self.default_value_type == "current_language":
            return self.env.context.get("lang") or self.env.user.lang
        if self.default_value_type == "current_timezone":
            return self.env.context.get("tz") or self.env.user.tz
        return None

    def _hidden_default_values(self):
        self.ensure_one()
        name = self.technical_name
        context_value = self._context_default_value()
        normalized_type = _normalize_parameter_type(self.filter_type)
        if context_value is not None and self.filter_type not in DATE_RANGE_PARAMETER_TYPES:
            return {name: context_value}
        if self.filter_type == "date_range":
            value_from = self.default_date
            value_to = self.default_date_to
            if context_value and self.default_value_type in {"today", "yesterday", "month_start", "month_end"}:
                value_from = context_value
                value_to = context_value
            return {f"{name}_from": value_from, f"{name}_to": value_to}
        if self.filter_type == "number_range":
            return {f"{name}_from": self.default_number, f"{name}_to": self.default_number_to}
        value = {
            "date": self.default_date,
            "datetime": self.default_datetime,
            "text": self.default_text,
            "long_text": self.default_text,
            "time": self.default_text,
            "relative_date": self.default_date,
            "hidden": self.default_text,
            "integer": int(self.default_number or 0),
            "decimal": self.default_number,
            "boolean": self.default_boolean,
            "selection": self.option_ids.filtered("active")[:1].value or None,
            "multi_selection": self.option_ids.filtered("active").mapped("value") or None,
            "many2one": self.default_relation_id or None,
        }.get(self.filter_type) if self.filter_type in {"long_text", "time", "relative_date", "hidden"} else {
            "date": self.default_date,
            "datetime": self.default_datetime,
            "text": self.default_text,
            "integer": int(self.default_number or 0),
            "decimal": self.default_number,
            "boolean": self.default_boolean,
            "selection": self.option_ids.filtered("active")[:1].value or None,
            "multi_selection": self.option_ids.filtered("active").mapped("value") or None,
            "many2one": self.default_relation_id or None,
        }.get(normalized_type)
        return {name: value}

    def _selection_pairs_from_text(self, values_text):
        pairs = []
        raw_values = []
        for line in (values_text or "").splitlines():
            raw_values.extend(part.strip() for part in line.split("|"))
        for item in raw_values:
            if not item:
                continue
            if "=" in item:
                label, value = item.split("=", 1)
            else:
                label = value = item
            pairs.append((label.strip(), value.strip()))
        return pairs

    def _validate_lookup_sql(self, sql_text):
        query_model = self.query_id or self.env["psql.query"]
        query_model._validate_read_only_sql(sql_text)
        if re.search(r"%\(|:\w+|\{\?", sql_text or ""):
            raise ValidationError(_("Lookup SQL cannot contain runtime placeholders: %s", self.name))

    def _dynamic_lookup_pairs(self):
        self.ensure_one()
        if self.source_type == "fixed":
            return self._selection_pairs_from_text(self.fixed_selection_values)
        if self.source_type == "table":
            if not re.fullmatch(r"[A-Za-z_][A-Za-z0-9_]*(?:\.[A-Za-z_][A-Za-z0-9_]*)?", self.source_table or ""):
                raise ValidationError(_("Invalid source table for parameter: %s", self.name))
            if not re.fullmatch(r"[A-Za-z_][A-Za-z0-9_]*", self.source_field or ""):
                raise ValidationError(_("Invalid source field for parameter: %s", self.name))
            parts = self.source_table.split(".", 1)
            schema, table = ("public", parts[0]) if len(parts) == 1 else parts
            sql = (
                f"SELECT DISTINCT {PsqlQueryWizard._quote_identifier(self.source_field)}::text AS value "
                f"FROM {PsqlQueryWizard._quote_identifier(schema)}.{PsqlQueryWizard._quote_identifier(table)} "
                f"WHERE {PsqlQueryWizard._quote_identifier(self.source_field)} IS NOT NULL "
                "ORDER BY 1 LIMIT 1000"
            )
            self.env.cr.execute(sql)
            return [(row[0], row[0]) for row in self.env.cr.fetchall()]
        if self.source_type == "sql":
            query_model = self.query_id or self.env["psql.query"]
            sql_text, statement_type = query_model._validate_read_only_sql(self.sql_lookup_query)
            if statement_type == "explain":
                raise ValidationError(_("Lookup SQL must return values, not EXPLAIN output: %s", self.name))
            self._validate_lookup_sql(sql_text)
            self.env.cr.execute(f"SELECT * FROM ({sql_text}) AS qsql_lookup_source LIMIT 1000")
            rows = self.env.cr.fetchall()
            pairs = []
            for row in rows:
                if not row:
                    continue
                value = row[0]
                label = row[1] if len(row) > 1 else row[0]
                if value not in (None, False, ""):
                    pairs.append((str(label), str(value)))
            return pairs
        return []

    def _sync_selection_options(self):
        for definition in self.filtered(lambda item: item.filter_type in SELECTION_PARAMETER_TYPES):
            if definition.source_type not in {"fixed", "table", "sql"}:
                continue
            pairs = definition._dynamic_lookup_pairs()
            existing = {option.value: option for option in definition.option_ids}
            seen = set()
            sequence = 10
            for label, value in pairs:
                seen.add(value)
                if value in existing:
                    existing[value].write({"label": label, "sequence": sequence, "active": True})
                else:
                    self.env["psql.query.parameter.option"].create({
                        "definition_id": definition.id,
                        "sequence": sequence,
                        "label": label,
                        "value": value,
                    })
                sequence += 10
            stale = definition.option_ids.filtered(lambda option: option.value not in seen)
            if stale:
                stale.write({"active": False})

    def _validation_limits(self):
        self.ensure_one()
        limits = {}
        for part in re.split(r"[;\n]+", self.validation_rule or ""):
            if "=" not in part:
                continue
            key, value = part.split("=", 1)
            limits[key.strip().lower()] = value.strip()
        return limits

    def _validate_parameter_values(self, parameter_values):
        self.ensure_one()
        limits = self._validation_limits()
        values = list((parameter_values or {}).values())
        if self.filter_type == "date_range":
            value_from = parameter_values.get(f"{self.technical_name}_from")
            value_to = parameter_values.get(f"{self.technical_name}_to")
            if value_from and value_to and value_from > value_to:
                raise ValidationError(_(
                    "Unable to run the report.\n\nParameter: %s\nIssue: From Date cannot be later than To Date.",
                    self.name,
                ))
        if self.filter_type in MULTI_VALUE_PARAMETER_TYPES and self.required and not values[0]:
            raise ValidationError(_("Choose at least one value for: %s", self.name))
        if self.filter_type in SELECTION_PARAMETER_TYPES:
            allowed = set(self.option_ids.filtered("active").mapped("value"))
            first_value = values[0] if values else None
            selected = first_value if isinstance(first_value, list) else ([first_value] if first_value else [])
            invalid = [value for value in selected if value not in allowed]
            if invalid:
                raise ValidationError(_("Invalid selection for %s: %s", self.name, ", ".join(map(str, invalid))))
        if self.filter_type in {"integer", "decimal", "number_range"}:
            for value in [item for item in values if item not in (None, "", [], ())]:
                try:
                    number = float(value)
                except (TypeError, ValueError):
                    raise ValidationError(_("Invalid number for: %s", self.name))
                if limits.get("min") and number < float(limits["min"]):
                    raise ValidationError(_("Minimum value for %s is %s.", self.name, limits["min"]))
                if limits.get("max") and number > float(limits["max"]):
                    raise ValidationError(_("Maximum value for %s is %s.", self.name, limits["max"]))
        if self.filter_type in {"date", "date_range", "current_date", "relative_date"}:
            min_date = fields.Date.from_string(limits["min_date"]) if limits.get("min_date") else None
            max_date = fields.Date.from_string(limits["max_date"]) if limits.get("max_date") else None
            for value in [item for item in values if item not in (None, "", [], ())]:
                parsed = fields.Date.from_string(value) if isinstance(value, str) else value
                if min_date and parsed < min_date:
                    raise ValidationError(_("Minimum date for %s is %s.", self.name, min_date))
                if max_date and parsed > max_date:
                    raise ValidationError(_("Maximum date for %s is %s.", self.name, max_date))
        if self.filter_type in TEXT_PARAMETER_TYPES and values:
            text = values[0] or ""
            if limits.get("min_length") and len(text) < int(limits["min_length"]):
                raise ValidationError(_("Minimum length for %s is %s.", self.name, limits["min_length"]))
            if limits.get("max_length") and len(text) > int(limits["max_length"]):
                raise ValidationError(_("Maximum length for %s is %s.", self.name, limits["max_length"]))
            if limits.get("allowed") and not re.fullmatch(limits["allowed"], text):
                raise ValidationError(_("Invalid characters for: %s", self.name))

    @api.onchange("name")
    def _onchange_name(self):
        for definition in self:
            if definition.name and not definition.technical_name:
                definition.technical_name = _slug_parameter_name(definition.name)

    @api.onchange("odoo_model_id")
    def _onchange_odoo_model_id(self):
        for definition in self:
            if definition.odoo_model_id:
                definition.relation_model_id = definition.odoo_model_id
                if definition.filter_type not in MODEL_PARAMETER_TYPES:
                    definition.filter_type = "many2one"
                definition.source_type = "odoo_model"

    @api.onchange("report_column_id")
    def _onchange_report_column_id(self):
        for definition in self:
            if definition.report_column_id:
                definition.name = definition.name or definition.report_column_id.label

    @api.constrains("technical_name")
    def _check_technical_name(self):
        for definition in self:
            if not re.match(r"^[a-z_][a-z0-9_]*$", definition.technical_name or ""):
                raise ValidationError(_(
                    "Technical Name must use lowercase letters, numbers, and underscores, and cannot start with a number."
                ))
            duplicate = self.search_count([
                ("query_id", "=", definition.query_id.id),
                ("technical_name", "=", definition.technical_name),
                ("id", "!=", definition.id),
            ])
            if duplicate:
                raise ValidationError(_("Technical Name must be unique within the report."))

    @api.constrains("query_id", "report_column_id")
    def _check_report_column_query(self):
        for definition in self.filtered("report_column_id"):
            if definition.report_column_id.query_id != definition.query_id:
                raise ValidationError(_("The referenced field must belong to the same SQL report."))

    @api.constrains("filter_type", "relation_model_id")
    def _check_type_configuration(self):
        for definition in self:
            if definition.filter_type in MODEL_PARAMETER_TYPES and not (definition.relation_model_id or definition.odoo_model_id):
                raise ValidationError(_("Choose a Many2one Model for parameter: %s", definition.name))

    def action_duplicate_parameter(self):
        self.ensure_one()
        base_name = self.technical_name
        suffix = 2
        technical_name = f"{base_name}_{suffix}"
        while self.search_count([
            ("query_id", "=", self.query_id.id),
            ("technical_name", "=", technical_name),
        ]):
            suffix += 1
            technical_name = f"{base_name}_{suffix}"
        self.copy({
            "name": _("%s (Copy)", self.name),
            "technical_name": technical_name,
            "sequence": self.sequence + 1,
        })
        return True

    def action_move_up(self):
        self.ensure_one()
        previous = self.search([
            ("query_id", "=", self.query_id.id),
            ("sequence", "<", self.sequence),
        ], order="sequence desc, id desc", limit=1)
        if previous:
            previous_sequence = previous.sequence
            previous.sequence = self.sequence
            self.sequence = previous_sequence
        return True

    def action_move_down(self):
        self.ensure_one()
        following = self.search([
            ("query_id", "=", self.query_id.id),
            ("sequence", ">", self.sequence),
        ], order="sequence, id", limit=1)
        if following:
            following_sequence = following.sequence
            following.sequence = self.sequence
            self.sequence = following_sequence
        return True


class PsqlQueryParameterOption(models.Model):
    _name = "psql.query.parameter.option"
    _description = "SQL Report Parameter Selection Value"
    _order = "sequence, id"
    _rec_name = "label"

    definition_id = fields.Many2one(
        "psql.query.filter.definition", required=True, ondelete="cascade", index=True
    )
    sequence = fields.Integer(default=10)
    active = fields.Boolean(default=True)
    label = fields.Char(required=True)
    value = fields.Char(required=True)


class PsqlQueryFilterWizard(models.TransientModel):
    _name = "psql.query.filter.wizard"
    _description = "Report Parameters"

    query_id = fields.Many2one("psql.query", required=True, readonly=True, ondelete="cascade")
    has_date_range_lines = fields.Boolean(compute="_compute_line_groups")
    has_other_lines = fields.Boolean(compute="_compute_line_groups")
    has_selection_lines = fields.Boolean(compute="_compute_line_groups")
    has_multi_selection_lines = fields.Boolean(compute="_compute_line_groups")
    has_text_lines = fields.Boolean(compute="_compute_line_groups")
    has_boolean_lines = fields.Boolean(compute="_compute_line_groups")
    has_date_lines = fields.Boolean(compute="_compute_line_groups")
    has_datetime_lines = fields.Boolean(compute="_compute_line_groups")
    has_number_lines = fields.Boolean(compute="_compute_line_groups")
    has_many2one_lines = fields.Boolean(compute="_compute_line_groups")
    date_range_label = fields.Char(readonly=True)
    date_range_from = fields.Date(string="From Date")
    date_range_to = fields.Date(string="To Date")
    filter_line_ids = fields.One2many(
        "psql.query.filter.wizard.line", "wizard_id", string="Report Parameters"
    )
    date_range_line_ids = fields.One2many(
        "psql.query.filter.wizard.line",
        "wizard_id",
        string="Date Ranges",
        domain=[("is_date_range", "=", True)],
    )
    other_line_ids = fields.One2many(
        "psql.query.filter.wizard.line",
        "wizard_id",
        string="Other Parameters",
        domain=[("is_date_range", "=", False)],
    )
    selection_line_ids = fields.One2many(
        "psql.query.filter.wizard.line",
        "wizard_id",
        string="Selections",
        domain=[("is_selection", "=", True)],
    )
    multi_selection_line_ids = fields.One2many(
        "psql.query.filter.wizard.line",
        "wizard_id",
        string="Multiple Selections",
        domain=[("is_multi_selection", "=", True)],
    )
    text_line_ids = fields.One2many(
        "psql.query.filter.wizard.line",
        "wizard_id",
        string="Text Parameters",
        domain=[("is_text", "=", True)],
    )
    boolean_line_ids = fields.One2many(
        "psql.query.filter.wizard.line",
        "wizard_id",
        string="Boolean Parameters",
        domain=[("is_boolean", "=", True)],
    )
    date_line_ids = fields.One2many(
        "psql.query.filter.wizard.line",
        "wizard_id",
        string="Date Parameters",
        domain=[("is_single_date", "=", True)],
    )
    datetime_line_ids = fields.One2many(
        "psql.query.filter.wizard.line",
        "wizard_id",
        string="Date & Time Parameters",
        domain=[("is_datetime", "=", True)],
    )
    number_line_ids = fields.One2many(
        "psql.query.filter.wizard.line",
        "wizard_id",
        string="Number Parameters",
        domain=[("is_number", "=", True)],
    )
    many2one_line_ids = fields.One2many(
        "psql.query.filter.wizard.line",
        "wizard_id",
        string="Record Parameters",
        domain=[("is_many2one", "=", True)],
    )

    @api.depends(
        "filter_line_ids.is_date_range",
        "filter_line_ids.is_selection",
        "filter_line_ids.is_multi_selection",
        "filter_line_ids.is_text",
        "filter_line_ids.is_boolean",
        "filter_line_ids.is_single_date",
        "filter_line_ids.is_datetime",
        "filter_line_ids.is_number",
        "filter_line_ids.is_many2one",
    )
    def _compute_line_groups(self):
        for wizard in self:
            wizard.has_date_range_lines = any(wizard.filter_line_ids.mapped("is_date_range"))
            wizard.has_selection_lines = any(wizard.filter_line_ids.mapped("is_selection"))
            wizard.has_multi_selection_lines = any(wizard.filter_line_ids.mapped("is_multi_selection"))
            wizard.has_text_lines = any(wizard.filter_line_ids.mapped("is_text"))
            wizard.has_boolean_lines = any(wizard.filter_line_ids.mapped("is_boolean"))
            wizard.has_date_lines = any(wizard.filter_line_ids.mapped("is_single_date"))
            wizard.has_datetime_lines = any(wizard.filter_line_ids.mapped("is_datetime"))
            wizard.has_number_lines = any(wizard.filter_line_ids.mapped("is_number"))
            wizard.has_many2one_lines = any(wizard.filter_line_ids.mapped("is_many2one"))
            wizard.has_other_lines = any([
                wizard.has_selection_lines,
                wizard.has_multi_selection_lines,
                wizard.has_text_lines,
                wizard.has_boolean_lines,
                wizard.has_date_lines,
                wizard.has_datetime_lines,
                wizard.has_number_lines,
                wizard.has_many2one_lines,
            ])

    def _populate_filter_lines(self):
        self.ensure_one()
        commands = [fields.Command.clear()]
        self.query_id.filter_definition_ids._sync_selection_options()
        sql_text = self.query_id._roommaster_sql_to_named_placeholders(self.query_id.query_name)
        placeholders = self.query_id._extract_sql_placeholder_names(sql_text)
        remembered = {}
        if self.query_id.parameter_memory_mode == "user":
            for item in self.query_id.last_filter_values or []:
                remembered[item.get("definition_id")] = item.get("values") or {}
        for definition in self.query_id.filter_definition_ids.filtered(
            lambda item: item.active
            and item.visible
            and placeholders.intersection(item._placeholder_names())
        ).sorted("sequence"):
            defaults = definition._hidden_default_values()
            remembered_values = remembered.get(definition.id) or {}
            if remembered_values and self.query_id.parameter_memory_mode == "user":
                defaults.update(remembered_values)
            default_name = definition.technical_name
            default_from = defaults.get(f"{default_name}_from")
            default_to = defaults.get(f"{default_name}_to")
            default_value = defaults.get(default_name)
            selection = definition.option_ids.filtered(lambda option: option.active and option.value == default_value)[:1]
            normalized_type = _normalize_parameter_type(definition.filter_type)
            commands.append(fields.Command.create({
                "definition_id": definition.id,
                "apply_parameter": definition.required or any([
                    definition.default_text,
                    definition.default_number,
                    definition.default_number_to,
                    definition.default_date,
                    definition.default_date_to,
                    definition.default_datetime,
                    definition.default_boolean,
                    definition.default_relation_id,
                    default_value,
                    default_from,
                    default_to,
                ]),
                "value_text": default_value if definition.filter_type in TEXT_PARAMETER_TYPES else definition.default_text,
                "value_integer": int((default_value if normalized_type == "integer" else definition.default_number) or 0),
                "value_decimal": (default_value if normalized_type == "decimal" else definition.default_number) or 0.0,
                "value_number_from": default_from or definition.default_number,
                "value_number_to": default_to or definition.default_number_to,
                "value_date": default_value if normalized_type == "date" else definition.default_date,
                "value_date_from": default_from or definition.default_date,
                "value_date_to": default_to or definition.default_date_to,
                "value_datetime": default_value if normalized_type == "datetime" else definition.default_datetime,
                "value_boolean": bool(default_value) if default_value is not None else definition.default_boolean,
                "date_preset": "custom",
                "selection_value_id": selection.id or (
                    definition.option_ids.filtered("active")[:1].id
                    if definition.required and definition.option_ids else False
                ),
                "multiple_selection_value_ids": [
                    fields.Command.set(definition.option_ids.filtered(
                        lambda option: option.active and option.value in (default_value or [])
                    ).ids)
                ] if isinstance(default_value, list) else False,
                "many2one_value": (
                    f"{(definition.relation_model_id or definition.odoo_model_id).model},{default_value or definition.default_relation_id}"
                    if (definition.relation_model_id or definition.odoo_model_id)
                    and (default_value or definition.default_relation_id) else False
                ),
            }))
        self.filter_line_ids = commands
        date_line = self.filter_line_ids.filtered("is_date_range")[:1]
        if date_line:
            self.date_range_label = date_line.name
            self.date_range_from = date_line.value_date_from
            self.date_range_to = date_line.value_date_to

    def _sync_direct_parameter_fields(self):
        self.ensure_one()
        date_line = self.filter_line_ids.filtered("is_date_range")[:1]
        if date_line:
            date_line.write({
                "apply_parameter": True,
                "value_date_from": self.date_range_from,
                "value_date_to": self.date_range_to,
            })

    @staticmethod
    def _json_value(value):
        if isinstance(value, datetime):
            return fields.Datetime.to_string(value)
        if isinstance(value, date):
            return fields.Date.to_string(value)
        if isinstance(value, tuple):
            return list(value)
        return value

    def _runtime_parameter_payload(self):
        self.ensure_one()
        values = {}
        summaries = []
        stored_values = []
        lines = {line.definition_id.id: line for line in self.filter_line_ids}
        for definition in self.query_id.filter_definition_ids.filtered("active").sorted("sequence"):
            line = lines.get(definition.id)
            parameter_values = line._parameter_values() if line else definition._hidden_default_values()
            if line and not line.apply_parameter:
                parameter_values = {name: None for name in definition._placeholder_names()}
            if definition.required and any(value in (None, "", [], ()) for value in parameter_values.values()):
                raise ValidationError(_("Enter the required parameter: %s", definition.name))
            definition._validate_parameter_values(parameter_values)
            values.update(parameter_values)
            display_value = line._display_value() if line and line.apply_parameter else False
            if display_value and not definition.hidden and definition.show_in_report_header:
                summaries.append(f"{definition.name}: {display_value}")
            stored_values.append({
                "definition_id": definition.id,
                "label": definition.name,
                "technical_name": definition.technical_name,
                "values": {key: self._json_value(value) for key, value in parameter_values.items()},
            })
        return {
            "values": values,
            "summary": "; ".join(summaries),
            "stored_values": stored_values,
        }

    def action_preview_report(self):
        self.ensure_one()
        payload = self.query_id._execute_and_store(self._runtime_parameter_payload())
        if not payload["ok"]:
            raise ValidationError(payload["error"])
        return {
            "type": "ir.actions.client",
            "tag": "psql_query_execute.pdf_preview",
            "params": {
                "name": self.query_id.name or _("SQL Report"),
                "url": f"/report/pdf/psql_query_execute.report_sql_business_document/{self.query_id.id}",
            },
        }


class PsqlQueryFilterWizardLine(models.TransientModel):
    _name = "psql.query.filter.wizard.line"
    _description = "Report Parameter Value"
    _order = "sequence, id"

    wizard_id = fields.Many2one(
        "psql.query.filter.wizard", required=True, ondelete="cascade", index=True
    )
    definition_id = fields.Many2one(
        "psql.query.filter.definition", required=True, readonly=True, ondelete="cascade"
    )
    sequence = fields.Integer(related="definition_id.sequence")
    name = fields.Char(related="definition_id.name")
    technical_name = fields.Char(related="definition_id.technical_name")
    filter_type = fields.Selection(related="definition_id.filter_type")
    required = fields.Boolean(related="definition_id.required")
    help_text = fields.Text(related="definition_id.help_text")
    relation_model_id = fields.Many2one(related="definition_id.relation_model_id")
    read_only = fields.Boolean(related="definition_id.read_only")
    is_date_range = fields.Boolean(compute="_compute_runtime_type_flags", store=True)
    is_selection = fields.Boolean(compute="_compute_runtime_type_flags", store=True)
    is_multi_selection = fields.Boolean(compute="_compute_runtime_type_flags", store=True)
    is_text = fields.Boolean(compute="_compute_runtime_type_flags", store=True)
    is_boolean = fields.Boolean(compute="_compute_runtime_type_flags", store=True)
    is_single_date = fields.Boolean(compute="_compute_runtime_type_flags", store=True)
    is_datetime = fields.Boolean(compute="_compute_runtime_type_flags", store=True)
    is_number = fields.Boolean(compute="_compute_runtime_type_flags", store=True)
    is_many2one = fields.Boolean(compute="_compute_runtime_type_flags", store=True)
    apply_parameter = fields.Boolean(string="Use")
    value_text = fields.Char(string="Text Value")
    value_integer = fields.Integer(string="Integer Value")
    value_decimal = fields.Float(string="Decimal Value")
    value_date = fields.Date(string="Date")
    value_datetime = fields.Datetime(string="Date & Time")
    value_boolean = fields.Boolean(string="Yes")
    selection_value_id = fields.Many2one(
        "psql.query.parameter.option",
        string="Selection Value",
        domain="[('definition_id', '=', definition_id), ('active', '=', True)]",
    )
    multiple_selection_value_ids = fields.Many2many(
        "psql.query.parameter.option",
        "psql_filter_wizard_line_option_rel",
        "wizard_line_id",
        "option_id",
        string="Values",
        domain="[('definition_id', '=', definition_id), ('active', '=', True)]",
    )
    many2one_value = fields.Reference(selection="_reference_models", string="Record")
    date_preset = fields.Selection(
        [
            ("today", "Today"),
            ("yesterday", "Yesterday"),
            ("this_week", "This Week"),
            ("last_week", "Last Week"),
            ("this_month", "This Month"),
            ("last_month", "Last Month"),
            ("this_year", "This Year"),
            ("custom", "Custom Date Range"),
        ],
        default="custom",
        string="Period",
    )
    value_date_from = fields.Date(string="Date From")
    value_date_to = fields.Date(string="Date To")
    value_number_from = fields.Float(string="Minimum")
    value_number_to = fields.Float(string="Maximum")

    @api.depends("definition_id.filter_type")
    def _compute_runtime_type_flags(self):
        for line in self:
            parameter_type = line.definition_id.filter_type
            line.is_date_range = parameter_type == "date_range"
            line.is_selection = parameter_type in SINGLE_SELECTION_PARAMETER_TYPES or parameter_type == "selection"
            line.is_multi_selection = parameter_type in MULTI_VALUE_PARAMETER_TYPES or parameter_type == "multi_selection"
            line.is_text = parameter_type in TEXT_PARAMETER_TYPES
            line.is_boolean = parameter_type == "boolean"
            line.is_single_date = parameter_type in {"date", "current_date", "relative_date"}
            line.is_datetime = parameter_type == "datetime"
            line.is_number = parameter_type in {"integer", "decimal", "number_range"}
            line.is_many2one = parameter_type in MODEL_PARAMETER_TYPES or parameter_type == "many2one"

    @api.model
    def _reference_models(self):
        definitions = self.env["psql.query.filter.definition"].search([
            ("filter_type", "in", list(MODEL_PARAMETER_TYPES))
        ])
        models_to_show = definitions.mapped("relation_model_id") | definitions.mapped("odoo_model_id")
        return [(model.model, model.name) for model in models_to_show]

    def _date_range(self):
        self.ensure_one()
        today = fields.Date.context_today(self)
        preset = self.date_preset
        if preset == "today":
            return today, today
        if preset == "yesterday":
            return today - timedelta(days=1), today - timedelta(days=1)
        this_week_start = today - timedelta(days=today.weekday())
        if preset == "this_week":
            return this_week_start, this_week_start + timedelta(days=6)
        if preset == "last_week":
            start = this_week_start - timedelta(days=7)
            return start, start + timedelta(days=6)
        if preset == "this_month":
            start = today.replace(day=1)
            next_month = (start.replace(day=28) + timedelta(days=4)).replace(day=1)
            return start, next_month - timedelta(days=1)
        if preset == "last_month":
            end = today.replace(day=1) - timedelta(days=1)
            return end.replace(day=1), end
        if preset == "this_year":
            return date(today.year, 1, 1), date(today.year, 12, 31)
        return self.value_date_from, self.value_date_to

    def _parameter_values(self):
        self.ensure_one()
        definition = self.definition_id
        name = definition.technical_name
        parameter_type = definition.filter_type
        normalized_type = _normalize_parameter_type(parameter_type)
        if parameter_type == "date_range":
            value_from, value_to = self._date_range()
            if value_from and value_to and value_from > value_to:
                raise ValidationError(_("Date From cannot be after Date To for: %s", definition.name))
            return {f"{name}_from": value_from, f"{name}_to": value_to}
        if parameter_type == "number_range":
            if self.value_number_from > self.value_number_to:
                raise ValidationError(_("Minimum cannot be greater than Maximum for: %s", definition.name))
            return {f"{name}_from": self.value_number_from, f"{name}_to": self.value_number_to}
        value = {
            "date": self.value_date,
            "datetime": self.value_datetime,
            "text": self.value_text,
            "long_text": self.value_text,
            "time": self.value_text,
            "hidden": self.value_text,
            "integer": self.value_integer,
            "decimal": self.value_decimal,
            "boolean": self.value_boolean,
            "selection": self.selection_value_id.value if self.selection_value_id else None,
            "multi_selection": self.multiple_selection_value_ids.mapped("value") or None,
            "many2one": self.many2one_value.id if self.many2one_value else None,
        }.get(parameter_type, {
            "date": self.value_date,
            "datetime": self.value_datetime,
            "text": self.value_text,
            "integer": self.value_integer,
            "decimal": self.value_decimal,
            "boolean": self.value_boolean,
            "selection": self.selection_value_id.value if self.selection_value_id else None,
            "multi_selection": self.multiple_selection_value_ids.mapped("value") or None,
            "many2one": self.many2one_value.id if self.many2one_value else None,
        }.get(normalized_type))
        if normalized_type == "many2one" and self.many2one_value:
            relation_model = definition.relation_model_id or definition.odoo_model_id
            if self.many2one_value._name != relation_model.model:
                raise ValidationError(_("Choose a record from %s for: %s", relation_model.name, definition.name))
        return {name: value}

    def _display_value(self):
        values = self._parameter_values()
        if self.filter_type in SINGLE_SELECTION_PARAMETER_TYPES and self.selection_value_id:
            return self.selection_value_id.label
        if self.filter_type in MULTI_VALUE_PARAMETER_TYPES:
            return ", ".join(self.multiple_selection_value_ids.mapped("label"))
        if self.filter_type in MODEL_PARAMETER_TYPES and self.many2one_value:
            return self.many2one_value.display_name
        clean = [str(value) for value in values.values() if value not in (None, "", [], ())]
        return " to ".join(clean)


class PsqlQueryReportColumn(models.Model):
    _name = "psql.query.report.column"
    _description = "SQL Report Presentation Column"
    _order = "sequence, id"

    query_id = fields.Many2one(
        "psql.query",
        required=True,
        ondelete="cascade",
        index=True,
    )
    sequence = fields.Integer(default=10)
    source_name = fields.Char(string="SQL Column", required=True, readonly=True)
    label = fields.Char(string="Report Label", required=True)
    visible = fields.Boolean(default=True)
    display_type = fields.Selection(
        [
            ("auto", "Automatic"),
            ("text", "Text"),
            ("integer", "Integer"),
            ("decimal", "Decimal (2 places)"),
            ("date", "Date"),
            ("datetime", "Date & Time"),
        ],
        required=True,
        default="auto",
    )
    alignment = fields.Selection(
        [
            ("auto", "Automatic"),
            ("left", "Left"),
            ("center", "Center"),
            ("right", "Right"),
        ],
        required=True,
        default="auto",
    )
    show_total = fields.Boolean(string="Total")
    group_by = fields.Boolean(string="Group Rows")
    relation_model_id = fields.Many2one(
        "ir.model",
        string="ID Name Model",
        ondelete="set null",
        help="Optional Odoo model used to replace numeric IDs with record names in exports.",
    )


class PsqlQueryWizard(models.TransientModel):
    _name = "psql.query.wizard"
    _description = "Interactive SQL Query Wizard"

    query_id = fields.Many2one("psql.query", required=True, ondelete="cascade")
    schema_name = fields.Selection(selection="_schema_selection", required=True, default="public")
    table_option_ids = fields.One2many("psql.query.wizard.table.option", "wizard_id", string="Available Tables")
    table_option_count = fields.Integer(compute="_compute_metadata_counts")
    table_option_id = fields.Many2one(
        "psql.query.wizard.table.option", string="Table / View", ondelete="set null"
    )
    field_option_ids = fields.One2many("psql.query.wizard.field.option", "wizard_id", string="Available Fields")
    field_option_count = fields.Integer(compute="_compute_metadata_counts")
    table_key = fields.Char(readonly=True)
    table_name = fields.Char(readonly=True)
    table_alias = fields.Char(string="Alias", default="t")
    distinct = fields.Boolean()
    column_line_ids = fields.One2many("psql.query.wizard.column", "wizard_id", string="Columns")
    join_line_ids = fields.One2many("psql.query.wizard.join", "wizard_id", string="Joins")
    filter_line_ids = fields.One2many("psql.query.wizard.filter", "wizard_id", string="WHERE Filters")
    group_line_ids = fields.One2many("psql.query.wizard.group", "wizard_id", string="GROUP BY")
    having_line_ids = fields.One2many("psql.query.wizard.having", "wizard_id", string="HAVING")
    order_line_ids = fields.One2many("psql.query.wizard.order", "wizard_id", string="ORDER BY")
    union_line_ids = fields.One2many("psql.query.wizard.union", "wizard_id", string="UNION")
    row_limit = fields.Integer(default=100, required=True)
    row_offset = fields.Integer(default=0)
    sql_preview = fields.Text(readonly=True)
    preview_ready = fields.Boolean(readonly=True)
    editor_has_sql = fields.Boolean(compute="_compute_editor_has_sql")
    insert_mode = fields.Selection(
        [("replace", "Replace Existing SQL"), ("append", "Append SQL")],
        string="Existing SQL",
    )

    @api.model
    def _schema_selection(self):
        self.env.cr.execute(
            "SELECT schema_name FROM information_schema.schemata "
            "WHERE schema_name NOT IN ('pg_catalog','information_schema','pg_toast') "
            "AND schema_name NOT LIKE 'pg\\_%' ESCAPE '\\' "
            "ORDER BY schema_name"
        )
        return [(row[0], row[0]) for row in self.env.cr.fetchall()]

    @api.model
    def _table_selection(self):
        self.env.cr.execute(
            """
            SELECT table_schema, table_name, table_type
              FROM information_schema.tables
             WHERE table_schema NOT IN ('pg_catalog', 'information_schema', 'pg_toast')
               AND table_schema NOT LIKE 'pg\\_%' ESCAPE '\\'
             ORDER BY table_schema, table_name
            """
        )
        return [
            (f"{schema}.{table}", f"{schema}.{table} ({'View' if 'VIEW' in kind else 'Table'})")
            for schema, table, kind in self.env.cr.fetchall()
        ]

    def _load_table_options(self):
        """Load lightweight table/view names once; columns remain lazy-loaded."""
        for wizard in self:
            wizard.table_option_ids.unlink()
            self.env.cr.execute(
                """
                SELECT table_schema, table_name, table_type
                  FROM information_schema.tables
                 WHERE table_schema NOT IN ('pg_catalog', 'information_schema', 'pg_toast')
                   AND table_schema NOT LIKE 'pg\\_%' ESCAPE '\\'
                 ORDER BY table_schema, table_name
                """
            )
            values = [{
                "wizard_id": wizard.id,
                "schema_name": schema,
                "table_name": table,
                "object_type": "view" if "VIEW" in kind else "table",
            } for schema, table, kind in self.env.cr.fetchall()]
            if values:
                self.env["psql.query.wizard.table.option"].create(values)
        return True

    def _column_metadata(self, schema, table):
        self.env.cr.execute(
            """
            WITH primary_columns AS (
                SELECT kcu.table_schema,
                       kcu.table_name,
                       kcu.column_name,
                       TRUE AS primary_key
                  FROM information_schema.table_constraints tc
                  JOIN information_schema.key_column_usage kcu
                    ON kcu.constraint_catalog = tc.constraint_catalog
                   AND kcu.constraint_schema = tc.constraint_schema
                   AND kcu.constraint_name = tc.constraint_name
                 WHERE tc.constraint_type = 'PRIMARY KEY'
                   AND tc.table_schema = %s
                   AND tc.table_name = %s
            ),
            foreign_columns AS (
                SELECT kcu.table_schema,
                       kcu.table_name,
                       kcu.column_name,
                       ccu.table_schema || '.' || ccu.table_name || '.' || ccu.column_name AS foreign_key
                  FROM information_schema.table_constraints tc
                  JOIN information_schema.key_column_usage kcu
                    ON kcu.constraint_catalog = tc.constraint_catalog
                   AND kcu.constraint_schema = tc.constraint_schema
                   AND kcu.constraint_name = tc.constraint_name
                  JOIN information_schema.constraint_column_usage ccu
                    ON ccu.constraint_catalog = tc.constraint_catalog
                   AND ccu.constraint_schema = tc.constraint_schema
                   AND ccu.constraint_name = tc.constraint_name
                 WHERE tc.constraint_type = 'FOREIGN KEY'
                   AND tc.table_schema = %s
                   AND tc.table_name = %s
            )
            SELECT a.attname AS column_name,
                   pg_catalog.format_type(a.atttypid, a.atttypmod) AS data_type,
                   NOT a.attnotnull AS nullable,
                   pg_catalog.pg_get_expr(ad.adbin, ad.adrelid) AS column_default,
                   a.attnum AS ordinal_position,
                   COALESCE(pk.primary_key, FALSE) AS primary_key,
                   fk.foreign_key,
                   d.description
              FROM pg_catalog.pg_class cls
              JOIN pg_catalog.pg_namespace ns
                ON ns.oid = cls.relnamespace
              JOIN pg_catalog.pg_attribute a
                ON a.attrelid = cls.oid
              LEFT JOIN pg_catalog.pg_attrdef ad
                ON ad.adrelid = cls.oid
               AND ad.adnum = a.attnum
              LEFT JOIN primary_columns pk
                ON pk.table_schema = ns.nspname
               AND pk.table_name = cls.relname
               AND pk.column_name = a.attname
              LEFT JOIN foreign_columns fk
                ON fk.table_schema = ns.nspname
               AND fk.table_name = cls.relname
               AND fk.column_name = a.attname
              LEFT JOIN pg_catalog.pg_description d
                ON d.objoid = cls.oid
               AND d.objsubid = a.attnum
             WHERE ns.nspname = %s
               AND cls.relname = %s
               AND a.attnum > 0
               AND NOT a.attisdropped
             ORDER BY a.attnum
            """,
            [schema, table, schema, table, schema, table],
        )
        return self.env.cr.fetchall()

    def _legacy_column_metadata(self, schema, table):
        self.env.cr.execute(
            """
            SELECT c.column_name,
                   c.data_type,
                   c.is_nullable = 'YES' AS nullable,
                   c.column_default,
                   c.ordinal_position,
                   EXISTS (
                       SELECT 1
                         FROM information_schema.table_constraints tc
                         JOIN information_schema.key_column_usage kcu
                           ON kcu.constraint_catalog = tc.constraint_catalog
                          AND kcu.constraint_schema = tc.constraint_schema
                          AND kcu.constraint_name = tc.constraint_name
                        WHERE tc.constraint_type = 'PRIMARY KEY'
                          AND tc.table_schema = c.table_schema
                          AND tc.table_name = c.table_name
                          AND kcu.column_name = c.column_name
                   ) AS primary_key,
                   (
                       SELECT ccu.table_schema || '.' || ccu.table_name || '.' || ccu.column_name
                         FROM information_schema.table_constraints tc
                         JOIN information_schema.key_column_usage kcu
                           ON kcu.constraint_catalog = tc.constraint_catalog
                          AND kcu.constraint_schema = tc.constraint_schema
                          AND kcu.constraint_name = tc.constraint_name
                         JOIN information_schema.constraint_column_usage ccu
                           ON ccu.constraint_catalog = tc.constraint_catalog
                          AND ccu.constraint_schema = tc.constraint_schema
                          AND ccu.constraint_name = tc.constraint_name
                        WHERE tc.constraint_type = 'FOREIGN KEY'
                          AND tc.table_schema = c.table_schema
                          AND tc.table_name = c.table_name
                          AND kcu.column_name = c.column_name
                        LIMIT 1
                   ) AS foreign_key,
                   d.description
              FROM information_schema.columns c
              LEFT JOIN pg_catalog.pg_class pg_c ON pg_c.relname = c.table_name
              LEFT JOIN pg_catalog.pg_namespace pg_n ON pg_n.oid = pg_c.relnamespace AND pg_n.nspname = c.table_schema
              LEFT JOIN pg_catalog.pg_attribute pg_a ON pg_a.attrelid = pg_c.oid AND pg_a.attname = c.column_name
              LEFT JOIN pg_catalog.pg_description d ON d.objoid = pg_c.oid AND d.objsubid = pg_a.attnum
             WHERE c.table_schema=%s AND c.table_name=%s
             ORDER BY c.ordinal_position
            """,
            [schema, table],
        )
        return self.env.cr.fetchall()

    def _sync_field_options(self):
        for wizard in self:
            sources = []
            if wizard.table_option_id:
                sources.append((wizard.table_option_id, wizard.table_alias or "t"))
            for join in wizard.join_line_ids:
                if join.table_option_id and join.alias:
                    sources.append((join.table_option_id, join.alias))
            source_keys = {(option.id, alias) for option, alias in sources}
            wizard.field_option_ids.filtered(
                lambda field: (field.table_option_id.id, field.source_alias) not in source_keys
            ).unlink()
            for option, alias in sources:
                wizard._ensure_field_options(option, alias)

    def _ensure_field_options(self, table_option, alias):
        self.ensure_one()
        if not table_option or not alias:
            return
        existing = self.field_option_ids.filtered(
            lambda option: option.table_option_id == table_option and option.source_alias == alias
        )
        if existing:
            return
        values = [{
            "wizard_id": self.id,
            "table_option_id": table_option.id,
            "source_alias": alias,
            "column_name": name,
            "data_type": data_type,
            "nullable": nullable,
            "default_value": default,
            "primary_key": primary,
            "foreign_key": foreign,
            "position": position,
            "description": description,
        } for name, data_type, nullable, default, position, primary, foreign, description in self._column_metadata(
            table_option.schema_name, table_option.table_name
        )]
        if values:
            self.env["psql.query.wizard.field.option"].create(values)

    @api.depends("query_id.query_name")
    def _compute_editor_has_sql(self):
        for wizard in self:
            sql = (wizard.query_id.query_name or "").strip()
            wizard.editor_has_sql = bool(sql and sql.upper() != "SELECT")

    @api.depends("table_option_ids", "field_option_ids", "schema_name")
    def _compute_metadata_counts(self):
        table_model = self.env["psql.query.wizard.table.option"]
        field_model = self.env["psql.query.wizard.field.option"]
        for wizard in self:
            wizard.table_option_count = table_model.search_count([
                ("wizard_id", "=", wizard.id), ("schema_name", "=", wizard.schema_name)
            ]) if wizard.id else 0
            wizard.field_option_count = field_model.search_count([
                ("wizard_id", "=", wizard.id)
            ]) if wizard.id else 0

    @api.onchange("schema_name")
    def _onchange_schema_name(self):
        if self.table_option_id and self.table_option_id.schema_name != self.schema_name:
            self.table_option_id = False
            self.table_key = False
            self.table_name = False
            origin = self._origin
            if origin.id:
                origin.column_line_ids.unlink()
                origin.field_option_ids.unlink()
            self.column_line_ids = [(5, 0, 0)]

    @api.onchange("table_option_id")
    def _onchange_table_option_id(self):
        if not self.table_option_id:
            self.table_name = False
            self.table_key = False
            self.column_line_ids = [(5, 0, 0)]
            return
        schema = self.table_option_id.schema_name
        table = self.table_option_id.table_name
        self.schema_name = schema
        self.table_name = table
        self.table_key = f"{schema}.{table}"
        alias = "".join(part[0] for part in table.split("_") if part)[:4] or "t"
        self.table_alias = alias
        metadata = self._column_metadata(schema, table)
        origin = self._origin
        if origin.id:
            # Metadata dropdown rows must exist for name_search, but output
            # column rows must remain normal onchange commands. Creating the
            # latter on _origin makes web_save treat them as stale and unlink
            # them immediately after table selection.
            origin.field_option_ids.unlink()
            origin._ensure_field_options(self.table_option_id, alias)
            for join in origin.join_line_ids:
                origin._ensure_field_options(join.table_option_id, join.alias)
        self.column_line_ids = [(5, 0, 0)] + [(0, 0, {
            "column_name": name, "data_type": data_type, "nullable": nullable,
            "default_value": default, "primary_key": primary, "foreign_key": foreign,
            "position": position, "sequence": position, "description": description,
        }) for name, data_type, nullable, default, position, primary, foreign, description in metadata]

    @api.onchange("table_alias")
    def _onchange_table_alias(self):
        if self._origin.id and self.table_alias:
            self._origin.table_alias = self.table_alias
            self._origin._sync_field_options()
            self.field_option_ids = self._origin.field_option_ids

    def action_add_join_for_table(self, table_option_id):
        self.ensure_one()
        if self.table_option_id.id == table_option_id:
            return
        existing = self.join_line_ids.filtered(lambda j: j.table_option_id.id == table_option_id)
        if existing:
            return
        table_option = self.env["psql.query.wizard.table.option"].browse(table_option_id)
        table = table_option.table_name
        alias = "".join(part[0] for part in table.split("_") if part)[:4] or "j"
        existing_aliases = {self.table_alias} | {j.alias for j in self.join_line_ids if j.alias}
        base_alias = alias
        counter = 1
        while alias in existing_aliases:
            alias = f"{base_alias}{counter}"
            counter += 1
        
        self.env["psql.query.wizard.join"].create({
            "wizard_id": self.id,
            "join_type": "left",
            "table_option_id": table_option_id,
            "alias": alias,
            "left_field": f"{self.table_alias}.id",
            "right_field": "id",
        })
        self._sync_field_options()
        return True

    def action_load_columns_for_table(self, table_option_id, alias):
        self.ensure_one()
        table_option = self.env["psql.query.wizard.table.option"].browse(table_option_id)
        self._ensure_field_options(table_option, alias)
        return True

    @staticmethod
    def _quote_identifier(identifier):
        return '"%s"' % identifier.replace('"', '""')

    def _available_columns(self, schema=None, table=None):
        if (not schema or not table) and self.table_option_id:
            source_schema = self.table_option_id.schema_name
            source_table = self.table_option_id.table_name
            schema = schema or source_schema
            table = table or source_table
        self.env.cr.execute(
            "SELECT column_name FROM information_schema.columns "
            "WHERE table_schema=%s AND table_name=%s ORDER BY ordinal_position",
            [schema or self.schema_name, table or self.table_name],
        )
        return [row[0] for row in self.env.cr.fetchall()]

    @staticmethod
    def _validate_alias(alias, label):
        if not alias or not re.fullmatch(r"[A-Za-z_][A-Za-z0-9_]*", alias):
            raise ValidationError(_("%s must be a valid SQL alias.", label))

    def _qualified_field(self, expression, aliases, columns_by_alias, label):
        value = (expression or "").strip()
        match = re.fullmatch(r"(?:(?P<alias>[A-Za-z_][A-Za-z0-9_]*)\.)?(?P<column>[A-Za-z_][A-Za-z0-9_]*)", value)
        if not match:
            raise ValidationError(_("%s must be a column name such as rp.name.", label))
        alias = match.group("alias") or self.table_alias
        column = match.group("column")
        if alias not in aliases or column not in columns_by_alias.get(alias, set()):
            raise ValidationError(_("Unknown column in %s: %s", label, value))
        return f"{self._quote_identifier(alias)}.{self._quote_identifier(column)}"

    def _option_field(self, option, fallback, aliases, columns_by_alias, label):
        if option:
            expression = f"{option.source_alias}.{option.column_name}"
        else:
            expression = fallback
        return self._qualified_field(expression, aliases, columns_by_alias, label)

    def _literal(self, value):
        return self.env.cr.mogrify("%s", [value]).decode()

    def _condition_sql(self, line, aliases, columns_by_alias, label):
        field_sql = self._option_field(
            getattr(line, "field_option_id", False), line.field_name, aliases, columns_by_alias, label
        )
        operator = line.operator.upper()
        if operator in ("IS NULL", "IS NOT NULL"):
            return f"{field_sql} {operator}"
        if operator == "BETWEEN":
            if line.value in (False, None, "") or line.value_to in (False, None, ""):
                raise ValidationError(_("Both values are required for BETWEEN."))
            return f"{field_sql} BETWEEN {self._literal(line.value)} AND {self._literal(line.value_to)}"
        if operator in ("IN", "NOT IN"):
            values = [item.strip() for item in (line.value or "").split(",") if item.strip()]
            if not values:
                raise ValidationError(_("Enter one or more comma-separated values for %s.", operator))
            return f"{field_sql} {operator} ({', '.join(self._literal(value) for value in values)})"
        if line.value in (False, None):
            raise ValidationError(_("A value is required for %s.", operator))
        return f"{field_sql} {operator} {self._literal(line.value)}"

    def _build_sql(self):
        self.ensure_one()
        self.query_id._ensure_sql_admin()
        if not self.schema_name or not self.table_option_id:
            raise ValidationError(_("Select a schema and table before generating SQL."))
        source_schema = self.table_option_id.schema_name
        source_table = self.table_option_id.table_name
        if source_schema != self.schema_name:
            raise ValidationError(_("The selected table does not belong to schema %s.", self.schema_name))
        if not 1 <= (self.row_limit or 0) <= MAX_RESULT_ROWS:
            raise ValidationError(_("LIMIT must be between 1 and %s.", MAX_RESULT_ROWS))
        if (self.row_offset or 0) < 0:
            raise ValidationError(_("OFFSET cannot be negative."))

        self._validate_alias(self.table_alias, _("Source alias"))
        aliases = {self.table_alias}
        columns_by_alias = {self.table_alias: set(self._available_columns())}
        if not columns_by_alias[self.table_alias]:
            raise ValidationError(_("The selected table or view no longer exists."))

        join_parts = []
        for join in self.join_line_ids.sorted("sequence"):
            if not join.table_option_id:
                raise ValidationError(_("Choose a table for every JOIN row."))
            schema = join.table_option_id.schema_name
            table = join.table_option_id.table_name
            self._validate_alias(join.alias, _("JOIN alias"))
            if join.alias in aliases:
                raise ValidationError(_("Aliases must be unique. Duplicate: %s", join.alias))
            right_columns = set(self._available_columns(schema, table))
            if not right_columns:
                raise ValidationError(_("JOIN table %s.%s does not exist.", schema, table))
            left_sql = self._option_field(
                join.left_field_option_id, join.left_field, aliases, columns_by_alias, _("JOIN left field")
            )
            right_name = join.right_field_option_id.column_name if join.right_field_option_id else (join.right_field or "").strip()
            if right_name not in right_columns:
                raise ValidationError(_("Unknown JOIN right field: %s", right_name))
            right_sql = f"{self._quote_identifier(join.alias)}.{self._quote_identifier(right_name)}"
            join_parts.append(
                f"{join.join_type.upper()} JOIN {self._quote_identifier(schema)}.{self._quote_identifier(table)} "
                f"AS {self._quote_identifier(join.alias)}\n    ON {left_sql} {join.operator} {right_sql}"
            )
            aliases.add(join.alias)
            columns_by_alias[join.alias] = right_columns

        selected = self.column_line_ids.filtered("selected").sorted("sequence")
        if not selected:
            raise ValidationError(_("Select at least one output column."))
        select_parts = []
        for line in selected:
            alias = line.field_option_id.source_alias if line.field_option_id else self.table_alias
            expression = f"{self._quote_identifier(alias)}.{self._quote_identifier(line.column_name)}"
            if line.aggregate == "count_distinct":
                expression = f"COUNT(DISTINCT {expression})"
            elif line.aggregate and line.aggregate != "none":
                expression = f"{line.aggregate.upper()}({expression})"
            if line.column_alias:
                self._validate_alias(line.column_alias, _("Column alias"))
                expression += f" AS {self._quote_identifier(line.column_alias)}"
            select_parts.append(expression)

        sql = "SELECT"
        if self.distinct:
            sql += " DISTINCT"
        sql += "\n    " + ",\n    ".join(select_parts)
        sql += f"\nFROM {self._quote_identifier(source_schema)}.{self._quote_identifier(source_table)} AS {self._quote_identifier(self.table_alias)}"
        if join_parts:
            sql += "\n" + "\n".join(join_parts)

        filters = []
        for index, line in enumerate(self.filter_line_ids.sorted("sequence")):
            condition = self._condition_sql(line, aliases, columns_by_alias, _("WHERE field"))
            prefix = "" if index == 0 else f"{line.connector} "
            filters.append(prefix + condition)
        if filters:
            sql += "\nWHERE\n    " + "\n    ".join(filters)

        groups = [
            self._option_field(line.field_option_id, line.field_name, aliases, columns_by_alias, _("GROUP BY field"))
            for line in self.group_line_ids.sorted("sequence")
        ]
        for line in selected.filtered("group_by"):
            alias = line.field_option_id.source_alias if line.field_option_id else self.table_alias
            item = f"{self._quote_identifier(alias)}.{self._quote_identifier(line.column_name)}"
            if item not in groups:
                groups.append(item)
        if groups:
            sql += "\nGROUP BY\n    " + ",\n    ".join(groups)

        having = []
        for index, line in enumerate(self.having_line_ids.sorted("sequence")):
            field_sql = self._option_field(line.field_option_id, line.field_name, aliases, columns_by_alias, _("HAVING field"))
            if not line.aggregate or line.aggregate == "none":
                raise ValidationError(_("Choose an aggregate for every HAVING row."))
            expression = f"{line.aggregate.upper()}({field_sql})"
            if line.operator in ("IS NULL", "IS NOT NULL"):
                condition = f"{expression} {line.operator}"
            else:
                if line.value in (False, None):
                    raise ValidationError(_("A value is required for HAVING."))
                condition = f"{expression} {line.operator} {self._literal(line.value)}"
            having.append(("" if index == 0 else f"{line.connector} ") + condition)
        if having:
            sql += "\nHAVING\n    " + "\n    ".join(having)

        orders = []
        for line in self.order_line_ids.sorted("sequence"):
            field_sql = self._option_field(line.field_option_id, line.field_name, aliases, columns_by_alias, _("ORDER BY field"))
            orders.append(f"{field_sql} {line.direction.upper()} NULLS {line.nulls.upper()}")
        for line in selected.filtered(lambda c: c.sort_direction and c.sort_direction != 'none').sorted("sequence"):
            alias = line.field_option_id.source_alias if line.field_option_id else self.table_alias
            field_sql = f"{self._quote_identifier(alias)}.{self._quote_identifier(line.column_name)}"
            orders.append(f"{field_sql} {line.sort_direction.upper()} NULLS {line.sort_nulls.upper()}")
        if orders:
            sql += "\nORDER BY\n    " + ",\n    ".join(orders)
        sql += f"\nLIMIT {self.row_limit}"
        if self.row_offset:
            sql += f"\nOFFSET {self.row_offset}"
        union_lines = self.union_line_ids.sorted("sequence")
        if not union_lines:
            return sql + ";"
        union_parts = [f"({sql})"]
        for line in union_lines:
            union_sql = (line.sql_text or "").strip().rstrip(";")
            if not union_sql:
                raise ValidationError(_("Enter SQL for every UNION row."))
            if not re.match(r"^\s*(WITH|SELECT)\b", union_sql, flags=re.IGNORECASE):
                raise ValidationError(_("UNION rows must start with SELECT or WITH."))
            union_parts.append(f"{line.union_type.replace('_', ' ').upper()}\n({union_sql})")
        return "\n".join(union_parts) + ";"

    def action_generate_query(self):
        self.ensure_one()
        self.write({"sql_preview": self._build_sql(), "preview_ready": True})
        # Returning False keeps the current dialog open; Odoo reloads its form
        # record after the object button completes.
        return False

    def action_clear_preview(self):
        self.ensure_one()
        self.write({"sql_preview": False, "preview_ready": False})
        return False

    def action_insert_into_editor(self):
        self.ensure_one()
        sql = self._build_sql()
        current = (self.query_id.query_name or "").strip()
        has_existing = bool(current and current.upper() != "SELECT")
        if has_existing and not self.insert_mode:
            raise ValidationError(_("The SQL Editor already contains a query. Choose Replace Existing SQL or Append SQL."))
        if has_existing and self.insert_mode == "append":
            sql = current.rstrip() + "\n\n" + sql
        self.query_id.write({"query_name": sql})
        view_xmlid = "psql_query_execute.psql_query_interactive_view_form" if self.query_id.is_interactive_session else "psql_query_execute.psql_query_view_form"
        return {
            "type": "ir.actions.act_window",
            "name": _("Interactive SQL"),
            "res_model": "psql.query",
            "res_id": self.query_id.id,
            "view_mode": "form",
            "views": [(self.env.ref(view_xmlid).id, "form")],
            "target": "current",
            "context": {"interactive_sql": bool(self.query_id.is_interactive_session)},
        }


class PsqlQueryWizardTableOption(models.TransientModel):
    _name = "psql.query.wizard.table.option"
    _description = "SQL Wizard Table or View Option"
    _rec_name = "display_name"
    _order = "schema_name, table_name"

    wizard_id = fields.Many2one("psql.query.wizard", required=True, ondelete="cascade", index=True)
    schema_name = fields.Char(required=True, index=True)
    table_name = fields.Char(required=True, index=True)
    object_type = fields.Selection([("table", "Table"), ("view", "View")], required=True)
    display_name = fields.Char(compute="_compute_display_name", store=True, index=True)

    @api.depends("schema_name", "table_name", "object_type")
    def _compute_display_name(self):
        for option in self:
            option.display_name = f"{option.schema_name}.{option.table_name} ({option.object_type.title()})"


class PsqlQueryWizardFieldOption(models.TransientModel):
    _name = "psql.query.wizard.field.option"
    _description = "SQL Wizard Searchable Field Option"
    _rec_name = "display_name"
    _order = "source_alias, position, id"

    wizard_id = fields.Many2one("psql.query.wizard", required=True, ondelete="cascade", index=True)
    table_option_id = fields.Many2one("psql.query.wizard.table.option", required=True, ondelete="cascade", index=True)
    source_alias = fields.Char(required=True, index=True)
    column_name = fields.Char(required=True, index=True)
    data_type = fields.Char()
    nullable = fields.Boolean()
    default_value = fields.Char()
    primary_key = fields.Boolean()
    foreign_key = fields.Char()
    position = fields.Integer()
    description = fields.Char(readonly=True)
    display_name = fields.Char(compute="_compute_display_name", store=True, index=True)

    @api.depends("source_alias", "column_name", "data_type")
    def _compute_display_name(self):
        for option in self:
            suffix = f" — {option.data_type}" if option.data_type else ""
            option.display_name = f"{option.source_alias}.{option.column_name}{suffix}"


class PsqlQueryWizardColumn(models.TransientModel):
    _name = "psql.query.wizard.column"
    _description = "SQL Wizard Column"
    _order = "sequence, id"

    wizard_id = fields.Many2one("psql.query.wizard", required=True, ondelete="cascade")
    sequence = fields.Integer(default=10)
    selected = fields.Boolean()
    field_option_id = fields.Many2one("psql.query.wizard.field.option", string="Field Option", ondelete="cascade")
    source_alias = fields.Char(string="Table Alias", related="field_option_id.source_alias", store=True)
    table_name = fields.Char(string="Table Name", related="field_option_id.table_option_id.table_name", store=True)
    column_name = fields.Char(required=True)
    data_type = fields.Char()
    nullable = fields.Boolean()
    default_value = fields.Char()
    primary_key = fields.Boolean()
    foreign_key = fields.Char()
    position = fields.Integer()
    description = fields.Char()
    aggregate = fields.Selection([
        ("none", "None"), ("count", "COUNT"), ("count_distinct", "COUNT DISTINCT"),
        ("sum", "SUM"), ("avg", "AVG"), ("min", "MIN"), ("max", "MAX"),
    ], default="none")
    column_alias = fields.Char(string="Column Alias")
    group_by = fields.Boolean(string="GROUP BY")
    sort_direction = fields.Selection([("none", "None"), ("asc", "ASC"), ("desc", "DESC")], default="none")
    sort_nulls = fields.Selection([("first", "FIRST"), ("last", "LAST")], default="last")


class PsqlQueryWizardJoin(models.TransientModel):
    _name = "psql.query.wizard.join"
    _description = "SQL Wizard Join"
    _order = "sequence, id"

    wizard_id = fields.Many2one("psql.query.wizard", required=True, ondelete="cascade")
    sequence = fields.Integer(default=10)
    join_type = fields.Selection([("inner", "INNER"), ("left", "LEFT"), ("right", "RIGHT"), ("full", "FULL")], default="inner", required=True)
    table_option_id = fields.Many2one(
        "psql.query.wizard.table.option", string="Join Table", required=True, ondelete="cascade"
    )
    alias = fields.Char(required=True)
    left_field_option_id = fields.Many2one("psql.query.wizard.field.option", string="Left Table Field", ondelete="set null")
    right_field_option_id = fields.Many2one("psql.query.wizard.field.option", string="Right Table Field", ondelete="set null")
    left_field = fields.Char(required=True, help="Qualified field, for example rp.company_id")
    operator = fields.Selection([("=", "="), ("<>", "<>"), (">", ">"), (">=", ">="), ("<", "<"), ("<=", "<=")], default="=", required=True)
    right_field = fields.Char(required=True, help="Column name from the joined table, for example id")

    @api.onchange("table_option_id")
    def _onchange_table_option_id(self):
        if not self.table_option_id:
            self.right_field_option_id = False
            return
        if not self.alias:
            table = self.table_option_id.table_name
            self.alias = "".join(part[0] for part in table.split("_") if part)[:4] or "j"
        wizard = self.wizard_id._origin if self.wizard_id._origin.id else self.wizard_id
        if wizard.id:
            if self._origin.id:
                self._origin.write({"table_option_id": self.table_option_id.id, "alias": self.alias})
            wizard._sync_field_options()
            wizard._ensure_field_options(self.table_option_id, self.alias)

    @api.onchange("left_field_option_id")
    def _onchange_left_field_option_id(self):
        if self.left_field_option_id:
            self.left_field = f"{self.left_field_option_id.source_alias}.{self.left_field_option_id.column_name}"

    @api.onchange("right_field_option_id")
    def _onchange_right_field_option_id(self):
        if self.right_field_option_id:
            self.right_field = self.right_field_option_id.column_name


FILTER_OPERATORS = [(op, op) for op in ("=", "<>", ">", ">=", "<", "<=", "LIKE", "ILIKE", "NOT LIKE", "IN", "NOT IN", "BETWEEN", "IS NULL", "IS NOT NULL")]


class PsqlQueryWizardFilter(models.TransientModel):
    _name = "psql.query.wizard.filter"
    _description = "SQL Wizard WHERE Filter"
    _order = "sequence, id"

    wizard_id = fields.Many2one("psql.query.wizard", required=True, ondelete="cascade")
    sequence = fields.Integer(default=10)
    connector = fields.Selection([("AND", "AND"), ("OR", "OR")], default="AND", required=True)
    field_option_id = fields.Many2one("psql.query.wizard.field.option", string="Field", ondelete="set null")
    field_name = fields.Char(required=True, help="Column or qualified column, for example rp.active")
    operator = fields.Selection(FILTER_OPERATORS, default="=", required=True)
    value = fields.Char()
    value_to = fields.Char(string="Second Value")

    @api.onchange("field_option_id")
    def _onchange_field_option_id(self):
        if self.field_option_id:
            self.field_name = f"{self.field_option_id.source_alias}.{self.field_option_id.column_name}"


class PsqlQueryWizardGroup(models.TransientModel):
    _name = "psql.query.wizard.group"
    _description = "SQL Wizard GROUP BY"
    _order = "sequence, id"

    wizard_id = fields.Many2one("psql.query.wizard", required=True, ondelete="cascade")
    sequence = fields.Integer(default=10)
    field_option_id = fields.Many2one("psql.query.wizard.field.option", string="Field", ondelete="set null")
    field_name = fields.Char(required=True)

    @api.onchange("field_option_id")
    def _onchange_field_option_id(self):
        if self.field_option_id:
            self.field_name = f"{self.field_option_id.source_alias}.{self.field_option_id.column_name}"


class PsqlQueryWizardHaving(models.TransientModel):
    _name = "psql.query.wizard.having"
    _description = "SQL Wizard HAVING"
    _order = "sequence, id"

    wizard_id = fields.Many2one("psql.query.wizard", required=True, ondelete="cascade")
    sequence = fields.Integer(default=10)
    connector = fields.Selection([("AND", "AND"), ("OR", "OR")], default="AND", required=True)
    aggregate = fields.Selection([("count", "COUNT"), ("sum", "SUM"), ("avg", "AVG"), ("min", "MIN"), ("max", "MAX")], required=True)
    field_option_id = fields.Many2one("psql.query.wizard.field.option", string="Field", ondelete="set null")
    field_name = fields.Char(required=True)
    operator = fields.Selection([(op, op) for op in ("=", "<>", ">", ">=", "<", "<=", "IS NULL", "IS NOT NULL")], default=">", required=True)
    value = fields.Char()

    @api.onchange("field_option_id")
    def _onchange_field_option_id(self):
        if self.field_option_id:
            self.field_name = f"{self.field_option_id.source_alias}.{self.field_option_id.column_name}"


class PsqlQueryWizardOrder(models.TransientModel):
    _name = "psql.query.wizard.order"
    _description = "SQL Wizard ORDER BY"
    _order = "sequence, id"

    wizard_id = fields.Many2one("psql.query.wizard", required=True, ondelete="cascade")
    sequence = fields.Integer(default=10)
    field_option_id = fields.Many2one("psql.query.wizard.field.option", string="Field", ondelete="set null")
    field_name = fields.Char(required=True)
    direction = fields.Selection([("asc", "ASC"), ("desc", "DESC")], default="asc", required=True)
    nulls = fields.Selection([("first", "FIRST"), ("last", "LAST")], default="last", required=True)

    @api.onchange("field_option_id")
    def _onchange_field_option_id(self):
        if self.field_option_id:
            self.field_name = f"{self.field_option_id.source_alias}.{self.field_option_id.column_name}"


class PsqlQueryWizardUnion(models.TransientModel):
    _name = "psql.query.wizard.union"
    _description = "SQL Wizard UNION Query"
    _order = "sequence, id"

    wizard_id = fields.Many2one("psql.query.wizard", required=True, ondelete="cascade")
    sequence = fields.Integer(default=10)
    union_type = fields.Selection([("union", "UNION"), ("union_all", "UNION ALL")], default="union", required=True)
    sql_text = fields.Text(string="SELECT Query", required=True)
