# -*- coding: utf-8 -*-
"""Download controllers for the existing Interactive SQL Report module."""

import csv
import io
import json
import re

from odoo import http
from odoo.exceptions import AccessError
from odoo.http import content_disposition, request, serialize_exception
from odoo.tools import html_escape


def _safe_filename(value):
    cleaned = re.sub(r"[^A-Za-z0-9._-]+", "_", value or "SQL_Report").strip("._")
    return cleaned or "SQL_Report"


class XLSXReportController(http.Controller):
    """Preserve the original XLSX endpoint and provide stored-result exports."""

    @staticmethod
    def _check_access():
        if not request.env.user.has_group("base.group_system"):
            raise AccessError("Only system administrators may export SQL reports.")

    @http.route("/xlsx_reports", type="http", auth="user", methods=["POST"], csrf=False)
    def get_report_xlsx(self, model, options, output_format, report_name):
        """Backward-compatible endpoint used by the existing XLSX action."""
        self._check_access()
        report_obj = request.env[model].with_user(request.session.uid)
        options = json.loads(options)
        token = "dummy-because-api-expects-one"
        try:
            if output_format != "xlsx":
                raise ValueError("Unsupported report format")
            response = request.make_response(
                None,
                headers=[
                    ("Content-Type", "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"),
                    ("Content-Disposition", content_disposition(_safe_filename(report_name) + ".xlsx")),
                ],
            )
            report_obj.get_xlsx_report(options, response)
            response.set_cookie("fileToken", token)
            return response
        except Exception as error:
            serialized = serialize_exception(error)
            return request.make_response(
                html_escape(json.dumps({"code": 200, "message": "Odoo Server Error", "data": serialized}))
            )

    @http.route(
        "/psql_query_execute/export/<string:output_format>/<int:record_id>",
        type="http",
        auth="user",
        methods=["GET"],
    )
    def export_stored_result(self, output_format, record_id, **_kwargs):
        self._check_access()
        report = request.env["psql.query"].browse(record_id).exists()
        if not report:
            return request.not_found()
        report.check_access("read")
        data = report.result_data or {}
        columns = data.get("columns") or []
        if not columns:
            return request.make_response("No query result is available.", status=400)
        presentation = report._get_report_presentation()
        display_columns = presentation["columns"]
        display_rows = [
            row
            for group in presentation["groups"]
            for row in group["rows"]
        ]
        if not display_columns:
            return request.make_response("Select at least one visible report column.", status=400)

        dated_name = "%s_%s" % (
            _safe_filename(report.name),
            report.last_executed_date.date().isoformat() if report.last_executed_date else "latest",
        )
        if output_format == "csv":
            stream = io.StringIO(newline="")
            writer = csv.writer(stream)
            writer.writerow([column["label"] for column in display_columns])
            for row in display_rows:
                writer.writerow([cell["value"] for cell in row])
            content = "\ufeff" + stream.getvalue()
            return request.make_response(
                content.encode("utf-8"),
                headers=[
                    ("Content-Type", "text/csv; charset=utf-8"),
                    ("Content-Disposition", content_disposition(dated_name + ".csv")),
                ],
            )
        if output_format == "xlsx":
            response = request.make_response(
                None,
                headers=[
                    ("Content-Type", "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"),
                    ("Content-Disposition", content_disposition(dated_name + ".xlsx")),
                ],
            )
            report.get_xlsx_report(
                {
                    "date": report.last_executed_date.date().isoformat()
                    if report.last_executed_date
                    else "",
                },
                response,
            )
            return response
        return request.make_response("Unsupported export format.", status=400)
