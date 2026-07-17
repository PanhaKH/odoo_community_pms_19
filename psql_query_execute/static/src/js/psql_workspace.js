/** @odoo-module **/

import { Component, onMounted, onWillStart, useEffect, useExternalListener, useRef, useState } from "@odoo/owl";
import { CodeEditor } from "@web/core/code_editor/code_editor";
import { Dialog } from "@web/core/dialog/dialog";
import { deserializeDate, serializeDate } from "@web/core/l10n/dates";
import { x2ManyCommands } from "@web/core/orm_service";
import { registry } from "@web/core/registry";
import { useService } from "@web/core/utils/hooks";
import { standardFieldProps } from "@web/views/fields/standard_field_props";

if (!CodeEditor.MODES.includes("sql")) {
    CodeEditor.MODES.push("sql");
}

export class PsqlSqlPreviewField extends Component {
    static template = "psql_query_execute.SqlPreviewField";
    static components = { CodeEditor };
    static props = standardFieldProps;

    setup() {
        this.notification = useService("notification");
    }

    get previewValue() {
        return this.props.record.data[this.props.name] || "-- Click Generate SQL to build the preview.";
    }

    get previewSessionId() {
        return `psql-wizard-preview-${this.props.record.resId || "new"}`;
    }

    async copySql() {
        const value = this.props.record.data[this.props.name] || "";
        if (!value) {
            this.notification.add("Generate SQL before copying the preview.", { type: "warning" });
            return;
        }
        await navigator.clipboard.writeText(value);
        this.notification.add("SQL copied to the clipboard.", { type: "success" });
    }
}

export class PsqlResultDialog extends Component {
    static template = "psql_query_execute.ResultDialog";
    static components = { Dialog };
    static props = {
        close: Function,
        reportId: { type: [Number, String] },
        result: Object,
        title: String,
    };

    setup() {
        this.notification = useService("notification");
        this.action = useService("action");
        this.state = useState({
            search: "",
            sortColumn: -1,
            sortDirection: "asc",
            page: 1,
            pageSize: 100,
            showAll: false,
        });
    }

    get filteredRows() {
        const needle = this.state.search.trim().toLowerCase();
        let rows = (this.props.result.rows || []).map((values, index) => ({
            values,
            sourceIndex: index,
        }));
        if (needle) {
            rows = rows.filter((row) =>
                row.values.some((value) => this.formatValue(value).toLowerCase().includes(needle))
            );
        }
        if (this.state.sortColumn >= 0) {
            const column = this.state.sortColumn;
            const direction = this.state.sortDirection === "asc" ? 1 : -1;
            rows.sort((left, right) => {
                const a = left.values[column];
                const b = right.values[column];
                if (a === b) return 0;
                if (a === null || a === undefined) return 1;
                if (b === null || b === undefined) return -1;
                if (typeof a === "number" && typeof b === "number") return (a - b) * direction;
                return String(a).localeCompare(String(b), undefined, { numeric: true }) * direction;
            });
        }
        return rows;
    }

    get totalPages() {
        if (this.state.showAll) {
            return 1;
        }
        return Math.max(1, Math.ceil(this.filteredRows.length / this.state.pageSize));
    }

    get visibleRows() {
        if (this.state.showAll) {
            return this.filteredRows;
        }
        if (this.state.page > this.totalPages) this.state.page = this.totalPages;
        const start = (this.state.page - 1) * this.state.pageSize;
        return this.filteredRows.slice(start, start + this.state.pageSize);
    }

    sortBy(columnIndex) {
        if (this.state.sortColumn === columnIndex) {
            this.state.sortDirection = this.state.sortDirection === "asc" ? "desc" : "asc";
        } else {
            this.state.sortColumn = columnIndex;
            this.state.sortDirection = "asc";
        }
        this.state.page = 1;
    }

    previousPage() {
        this.state.page = Math.max(1, this.state.page - 1);
    }

    nextPage() {
        this.state.page = Math.min(this.totalPages, this.state.page + 1);
    }

    showAllRows() {
        this.state.showAll = true;
        this.state.page = 1;
    }

    formatValue(value) {
        if (value === null || value === undefined) return "NULL";
        if (typeof value === "number") return new Intl.NumberFormat().format(value);
        if (typeof value === "object") return JSON.stringify(value);
        return String(value);
    }

    async copyCell(value) {
        await navigator.clipboard.writeText(value === null || value === undefined ? "NULL" : String(value));
        this.notification.add("Cell copied.", { type: "info" });
    }

    exportResult(format) {
        window.location.assign(`/psql_query_execute/export/${format}/${this.props.reportId}`);
    }

    printPdf() {
        this.action.doAction({
            type: "ir.actions.client",
            tag: "psql_query_execute.pdf_preview",
            params: {
                name: this.props.title.replace(/^Query Result\s*[—-]\s*/, "") || "SQL Report",
                url: `/report/pdf/psql_query_execute.report_sql_business_document/${this.props.reportId}`,
            },
        });
    }
}

export class PsqlSaveAsReportDialog extends Component {
    static template = "psql_query_execute.SaveAsReportDialog";
    static components = { Dialog };
    static props = {
        close: Function,
        onSave: Function,
    };

    setup() {
        this.state = useState({
            name: "",
            description: "",
            saving: false,
            error: "",
        });
    }

    async save() {
        const name = this.state.name.trim();
        if (!name) {
            this.state.error = "Report Name is required.";
            return;
        }
        this.state.saving = true;
        this.state.error = "";
        try {
            await this.props.onSave(name, this.state.description.trim());
            this.props.close();
        } catch (error) {
            this.state.error = error.message || "The report could not be saved.";
        } finally {
            this.state.saving = false;
        }
    }
}

export class PsqlParameterFormField extends Component {
    static template = "psql_query_execute.ParameterFormField";

    setup() {
        this.orm = useService("orm");
        this.state = useState({
            optionsByDefinition: {},
            modelOptionsByDefinition: {},
            modelNameByDefinition: {},
            openDatePicker: null,
            pickerValues: {},
            pickerMonths: {},
            pickerViews: {},
        });
        this.openDatePicker = this.openDatePicker.bind(this);
        this.changePickerMonth = this.changePickerMonth.bind(this);
        this.changePickerYear = this.changePickerYear.bind(this);
        this.toggleMonthPicker = this.toggleMonthPicker.bind(this);
        this.selectPickerMonth = this.selectPickerMonth.bind(this);
        this.selectDate = this.selectDate.bind(this);
        this.clearDate = this.clearDate.bind(this);
        this.selectToday = this.selectToday.bind(this);
        this.updateSelection = this.updateSelection.bind(this);
        this.updateMultiSelection = this.updateMultiSelection.bind(this);
        this.updateMany2One = this.updateMany2One.bind(this);
        useExternalListener(document, "mousedown", (event) => this.closeDatePickerOnOutsideClick(event), { capture: true });
        onWillStart(() => this.loadOptions());
    }

    get lines() {
        const list = this.props.record.data[this.props.name];
        return [...(list?.records || [])].sort((left, right) => {
            const a = left.data.sequence || 0;
            const b = right.data.sequence || 0;
            return a - b;
        });
    }

    get hasLines() {
        return this.lines.length > 0;
    }

    definitionId(line) {
        const value = line.data.definition_id;
        return value?.id || value?.[0] || false;
    }

    async loadOptions() {
        const definitionIds = this.lines.map((line) => this.definitionId(line)).filter(Boolean);
        if (!definitionIds.length) {
            return;
        }
        const [definitions, options] = await Promise.all([
            this.orm.searchRead(
                "psql.query.filter.definition",
                [["id", "in", definitionIds]],
                ["filter_type", "relation_model_id", "odoo_model_id"]
            ),
            this.orm.searchRead(
                "psql.query.parameter.option",
                [["definition_id", "in", definitionIds], ["active", "=", true]],
                ["id", "label", "value", "definition_id", "sequence"],
                { order: "sequence,id" }
            ),
        ]);
        const grouped = Object.fromEntries(definitionIds.map((definitionId) => [definitionId, []]));
        for (const option of options || []) {
            const definitionId = option.definition_id?.[0] || option.definition_id?.id;
            if (definitionId) {
                grouped[definitionId] = grouped[definitionId] || [];
                grouped[definitionId].push(option);
            }
        }
        this.state.optionsByDefinition = grouped;

        const modelIds = new Set();
        for (const definition of definitions || []) {
            const modelValue = definition.relation_model_id || definition.odoo_model_id;
            const modelId = modelValue?.[0] || modelValue?.id;
            if (modelId) {
                modelIds.add(modelId);
            }
        }
        const modelRows = modelIds.size
            ? await this.orm.searchRead("ir.model", [["id", "in", [...modelIds]]], ["model"])
            : [];
        const modelById = Object.fromEntries((modelRows || []).map((row) => [row.id, row.model]));
        const modelNameByDefinition = {};
        const modelOptionsByDefinition = {};
        for (const definition of definitions || []) {
            const definitionId = definition.id;
            const modelValue = definition.relation_model_id || definition.odoo_model_id;
            const modelId = modelValue?.[0] || modelValue?.id;
            const modelName = modelById[modelId];
            if (!modelName) {
                modelOptionsByDefinition[definitionId] = [];
                continue;
            }
            modelNameByDefinition[definitionId] = modelName;
            try {
                const records = await this.orm.searchRead(modelName, [], ["display_name"], {
                    limit: 100,
                });
                modelOptionsByDefinition[definitionId] = (records || [])
                    .map((record) => ({
                        id: record.id,
                        label: record.display_name,
                        value: record.id,
                        model: modelName,
                    }))
                    .sort((left, right) => (left.label || "").localeCompare(right.label || ""));
            } catch {
                modelOptionsByDefinition[definitionId] = [];
            }
        }
        this.state.modelNameByDefinition = modelNameByDefinition;
        this.state.modelOptionsByDefinition = modelOptionsByDefinition;
    }

    optionsFor(line) {
        const definitionId = this.definitionId(line);
        return definitionId ? (this.state.optionsByDefinition?.[definitionId] || []) : [];
    }

    hasOptions(line) {
        return this.optionsFor(line).length > 0;
    }

    modelOptionsFor(line) {
        const definitionId = this.definitionId(line);
        return definitionId ? (this.state.modelOptionsByDefinition?.[definitionId] || []) : [];
    }

    hasModelOptions(line) {
        return this.modelOptionsFor(line).length > 0;
    }

    modelNameFor(line) {
        const definitionId = this.definitionId(line);
        return definitionId ? (this.state.modelNameByDefinition?.[definitionId] || "") : "";
    }

    selectionId(line) {
        const value = line.data.selection_value_id;
        return value?.id || value?.[0] || "";
    }

    multiSelectionIds(line) {
        const value = line.data.multiple_selection_value_ids;
        if (value?.currentIds) {
            return value.currentIds;
        }
        if (value?.records) {
            return value.records.map((record) => record.resId).filter(Boolean);
        }
        return [];
    }

    displayReference(line) {
        const value = line.data.many2one_value;
        return value?.display_name || value?.[1] || "";
    }

    many2oneId(line) {
        const value = line.data.many2one_value;
        if (!value) {
            return "";
        }
        if (value.resId) {
            return value.resId;
        }
        if (typeof value === "string") {
            return Number(value.split(",")[1] || 0) || "";
        }
        if (Array.isArray(value)) {
            const raw = value[0] || value[1] || "";
            return Number(String(raw).split(",").pop() || 0) || "";
        }
        return "";
    }

    normalizeDate(value) {
        if (!value) {
            return "";
        }
        if (typeof value === "string") {
            const clean = value.trim();
            const serverDate = clean.match(/^(\d{4})-(\d{2})-(\d{2})/);
            if (serverDate) {
                return `${serverDate[1]}-${serverDate[2]}-${serverDate[3]}`;
            }
            const displayDate = clean.match(/^(\d{1,2})\/(\d{1,2})\/(\d{4})$/);
            if (displayDate) {
                const day = displayDate[1].padStart(2, "0");
                const month = displayDate[2].padStart(2, "0");
                return `${displayDate[3]}-${month}-${day}`;
            }
            return "";
        }
        if (value.toFormat) {
            return serializeDate(value);
        }
        if (value.toISODate) {
            return value.toISODate();
        }
        if (value instanceof Date && !Number.isNaN(value.getTime())) {
            return this.isoFromDate(value);
        }
        if (value.year && value.month && value.day) {
            const year = String(value.year).padStart(4, "0");
            const month = String(value.month).padStart(2, "0");
            const day = String(value.day).padStart(2, "0");
            return `${year}-${month}-${day}`;
        }
        return "";
    }

    normalizeDateTime(value) {
        if (!value) {
            return "";
        }
        if (typeof value === "string") {
            return value.slice(0, 16);
        }
        if (value.toISO) {
            return value.toISO().slice(0, 16);
        }
        return String(value).slice(0, 16);
    }

    datePickerKey(line, fieldName) {
        return `${line.id || line.resId}-${fieldName}`;
    }

    formatDateDisplay(value) {
        const iso = this.normalizeDate(value);
        return this.formatIsoDateDisplay(iso);
    }

    dateFieldIso(line, fieldName) {
        const key = this.datePickerKey(line, fieldName);
        return this.state.pickerValues[key] || this.normalizeDate(line.data[fieldName]);
    }

    dateFieldDisplay(line, fieldName) {
        return this.formatIsoDateDisplay(this.dateFieldIso(line, fieldName));
    }

    formatIsoDateDisplay(iso) {
        if (!iso) {
            return "";
        }
        const [year, month, day] = iso.split("-");
        if (!year || !month || !day) {
            return "";
        }
        return `${day}/${month}/${year}`;
    }

    dateInputPlaceholder() {
        return "dd/mm/yyyy";
    }

    isoFromDate(date) {
        const year = date.getFullYear();
        const month = String(date.getMonth() + 1).padStart(2, "0");
        const day = String(date.getDate()).padStart(2, "0");
        return `${year}-${month}-${day}`;
    }

    dateFromIso(iso) {
        if (!iso) {
            return null;
        }
        const [year, month, day] = iso.split("-").map((part) => Number(part));
        if (!year || !month || !day) {
            return null;
        }
        return new Date(year, month - 1, day);
    }

    monthDateFor(line, fieldName) {
        const key = this.datePickerKey(line, fieldName);
        const stored = this.state.pickerMonths[key];
        const selected = this.dateFromIso(this.dateFieldIso(line, fieldName));
        const base = stored ? this.dateFromIso(stored) : (selected || new Date());
        return new Date(base.getFullYear(), base.getMonth(), 1);
    }

    monthTitle(line, fieldName) {
        return this.monthDateFor(line, fieldName).toLocaleDateString(undefined, {
            month: "long",
            year: "numeric",
        });
    }

    weekdayLabels() {
        return ["Sun", "Mon", "Tue", "Wed", "Thu", "Fri", "Sat"];
    }

    monthLabels() {
        return ["Jan", "Feb", "Mar", "Apr", "May", "Jun", "Jul", "Aug", "Sep", "Oct", "Nov", "Dec"];
    }

    pickerYear(line, fieldName) {
        return this.monthDateFor(line, fieldName).getFullYear();
    }

    datePickerView(line, fieldName) {
        return this.state.pickerViews[this.datePickerKey(line, fieldName)] || "days";
    }

    calendarDays(line, fieldName) {
        const monthDate = this.monthDateFor(line, fieldName);
        const selectedIso = this.dateFieldIso(line, fieldName);
        const todayIso = this.isoFromDate(new Date());
        const first = new Date(monthDate.getFullYear(), monthDate.getMonth(), 1);
        const cursor = new Date(first);
        cursor.setDate(first.getDate() - first.getDay());
        const days = [];
        for (let index = 0; index < 42; index++) {
            const date = new Date(cursor);
            const iso = this.isoFromDate(date);
            days.push({
                iso,
                number: date.getDate(),
                outside: date.getMonth() !== monthDate.getMonth(),
                selected: iso === selectedIso,
                today: iso === todayIso,
            });
            cursor.setDate(cursor.getDate() + 1);
        }
        return days;
    }

    isDatePickerOpen(line, fieldName) {
        return this.state.openDatePicker === this.datePickerKey(line, fieldName);
    }

    closeDatePickerOnOutsideClick(event) {
        if (!this.state.openDatePicker) {
            return;
        }
        if (!event.target.closest(".sql-report-parameter-dialog .o_psql_modern_date")) {
            this.state.openDatePicker = null;
        }
    }

    openDatePicker(line, fieldName) {
        const key = this.datePickerKey(line, fieldName);
        this.state.pickerValues = {
            ...this.state.pickerValues,
            [key]: this.normalizeDate(line.data[fieldName]) || this.state.pickerValues[key] || "",
        };
        this.state.openDatePicker = this.state.openDatePicker === key ? null : key;
        this.state.pickerMonths = { ...this.state.pickerMonths, [key]: this.isoFromDate(this.monthDateFor(line, fieldName)) };
        this.state.pickerViews = { ...this.state.pickerViews, [key]: "days" };
    }

    changePickerMonth(line, fieldName, delta) {
        const key = this.datePickerKey(line, fieldName);
        const monthDate = this.monthDateFor(line, fieldName);
        const next = new Date(monthDate.getFullYear(), monthDate.getMonth() + delta, 1);
        this.state.pickerMonths = { ...this.state.pickerMonths, [key]: this.isoFromDate(next) };
        this.state.pickerViews = { ...this.state.pickerViews, [key]: "days" };
    }

    changePickerYear(line, fieldName, delta) {
        const key = this.datePickerKey(line, fieldName);
        const monthDate = this.monthDateFor(line, fieldName);
        const next = new Date(monthDate.getFullYear() + delta, monthDate.getMonth(), 1);
        this.state.pickerMonths = { ...this.state.pickerMonths, [key]: this.isoFromDate(next) };
    }

    toggleMonthPicker(line, fieldName) {
        const key = this.datePickerKey(line, fieldName);
        this.state.pickerViews = {
            ...this.state.pickerViews,
            [key]: this.datePickerView(line, fieldName) === "months" ? "days" : "months",
        };
    }

    selectPickerMonth(line, fieldName, monthIndex) {
        const key = this.datePickerKey(line, fieldName);
        const monthDate = this.monthDateFor(line, fieldName);
        const next = new Date(monthDate.getFullYear(), monthIndex, 1);
        this.state.pickerMonths = { ...this.state.pickerMonths, [key]: this.isoFromDate(next) };
        this.state.pickerViews = { ...this.state.pickerViews, [key]: "days" };
    }

    selectDate(line, fieldName, iso) {
        const key = this.datePickerKey(line, fieldName);
        this.state.pickerValues = { ...this.state.pickerValues, [key]: iso };
        this.updateLine(line, { apply_parameter: true, [fieldName]: deserializeDate(iso) });
        this.state.pickerMonths = { ...this.state.pickerMonths, [key]: iso };
        this.state.pickerViews = { ...this.state.pickerViews, [key]: "days" };
        this.state.openDatePicker = null;
    }

    clearDate(line, fieldName) {
        const key = this.datePickerKey(line, fieldName);
        this.state.pickerValues = { ...this.state.pickerValues, [key]: "" };
        this.updateLine(line, { apply_parameter: true, [fieldName]: false });
        this.state.openDatePicker = null;
    }

    selectToday(line, fieldName) {
        this.selectDate(line, fieldName, this.isoFromDate(new Date()));
    }

    isDateRange(line) {
        return line.data.filter_type === "date_range";
    }

    isSelection(line) {
        return ["selection", "fixed_dropdown", "dynamic_sql"].includes(line.data.filter_type);
    }

    isMultiSelection(line) {
        return ["multi_selection", "fixed_multi", "dynamic_sql_multi", "odoo_model_multi"].includes(line.data.filter_type);
    }

    isText(line) {
        return ["text", "long_text", "time", "relative_date", "hidden"].includes(line.data.filter_type);
    }

    isBoolean(line) {
        return line.data.filter_type === "boolean";
    }

    isDate(line) {
        return ["date", "current_date"].includes(line.data.filter_type);
    }

    isDateTime(line) {
        return line.data.filter_type === "datetime";
    }

    isInteger(line) {
        return line.data.filter_type === "integer";
    }

    isDecimal(line) {
        return line.data.filter_type === "decimal";
    }

    isNumberRange(line) {
        return line.data.filter_type === "number_range";
    }

    isMany2One(line) {
        return ["many2one", "current_user", "current_company"].includes(line.data.filter_type);
    }

    updateLine(line, values) {
        line.update(values);
    }

    updateSelection(line, event) {
        const optionId = Number(event.target.value || 0);
        const option = this.optionsFor(line).find((item) => item.id === optionId);
        line.update({
            apply_parameter: true,
            selection_value_id: option ? { id: option.id, display_name: option.label } : false,
        });
    }

    updateMultiSelection(line, event) {
        const ids = [...event.target.selectedOptions].map((option) => Number(option.value)).filter(Boolean);
        line.update({
            apply_parameter: true,
            multiple_selection_value_ids: [x2ManyCommands.set(ids)],
        });
    }

    updateMany2One(line, event) {
        const recordId = Number(event.target.value || 0);
        const modelName = this.modelNameFor(line);
        line.update({
            apply_parameter: true,
            many2one_value: recordId && modelName ? `${modelName},${recordId}` : false,
        });
    }
}

export class PsqlInteractiveWorkspace extends Component {
    static template = "psql_query_execute.InteractiveWorkspace";
    static components = { CodeEditor };
    static props = { ...standardFieldProps };

    setup() {
        this.orm = useService("orm");
        this.action = useService("action");
        this.dialog = useService("dialog");
        this.notification = useService("notification");
        this.editorHost = useRef("editorHost");
        const stored = this.props.record.data.result_data || {};
        const initialSql = this.initialSqlValue();
        this.state = useState({
            sql: initialSql,
            result: {
                columns: stored.columns || [],
                rows: stored.rows || [],
                limited: Boolean(stored.limited),
            },
            status: this.props.record.data.last_execution_status || "never",
            error: this.props.record.data.last_error || "",
            duration: this.props.record.data.execution_duration || 0,
            rowCount: this.props.record.data.returned_row_count || 0,
            executedAt: this.props.record.data.last_executed_date || "",
            loading: false,
            fullscreen: Boolean(this.props.record.context?.interactive_sql),
            resultSearch: "",
            sortColumn: -1,
            sortDirection: "asc",
            page: 1,
            pageSize: 50,
            objectSearch: "",
            schemas: [],
            expandedTables: {},
        });
        this.queryDraftSaveTimer = null;
        onWillStart(() => this.loadDatabaseObjects());
        onMounted(() => {
            if (initialSql !== this.displaySql(this.props.record.data.query_name)) {
                this.props.record.update({ query_name: initialSql });
            }
            this.refreshEditorLayout(this.state.fullscreen);
        });
        useEffect(
            (fullscreen) => this.refreshEditorLayout(fullscreen),
            () => [this.state.fullscreen]
        );
    }

    refreshEditorLayout(focus = false) {
        const refresh = () => {
            const editorElement = this.editorHost.el?.querySelector(".o_psql_ace_editor");
            const editor = editorElement?.env?.editor;
            if (!editor) return;
            editor.resize(true);
            editor.renderer?.updateFull?.();
            if (focus) {
                editor.focus();
                editor.navigateFileEnd();
            }
        };
        window.requestAnimationFrame(() => window.requestAnimationFrame(refresh));
        window.setTimeout(refresh, 150);
    }

    get sessionId() {
        return this.props.record.resId || this.props.record.id || "new-qsql-report";
    }

    get isInteractiveMode() {
        return Boolean(this.props.record.context?.interactive_sql);
    }

    get draftStorageKey() {
        if (this.props.record.resId) {
            return `psql_query_execute.sql_draft.report.${this.props.record.resId}`;
        }
        if (this.isInteractiveMode) {
            return "psql_query_execute.sql_draft.interactive";
        }
        return `psql_query_execute.sql_draft.${this.props.record.id || "new"}`;
    }

    storageGet(key) {
        try {
            return window.localStorage.getItem(key);
        } catch {
            return null;
        }
    }

    storageSet(key, value) {
        try {
            window.localStorage.setItem(key, value || "");
        } catch {
            // Browser storage can be unavailable in private/sandboxed contexts.
        }
    }

    storageRemove(key) {
        try {
            window.localStorage.removeItem(key);
        } catch {
            // Ignore storage cleanup failures.
        }
    }

    initialSqlValue() {
        const recordSql = this.displaySql(this.props.record.data.query_name);
        const draftSql = this.storageGet(this.draftStorageKey);
        if (draftSql !== null && draftSql !== recordSql) {
            return draftSql;
        }
        return recordSql;
    }

    displaySql(value) {
        const sql = value || "";
        return sql.trim().toUpperCase() === "SELECT" ? "" : sql;
    }

    sqlForStorage(value = this.state.sql) {
        return value || "";
    }

    sqlForServer(value = this.state.sql) {
        return value && value.trim() ? value : "SELECT ";
    }

    get filteredRows() {
        const needle = this.state.resultSearch.trim().toLowerCase();
        let rows = (this.state.result.rows || []).map((values, index) => ({ values, sourceIndex: index }));
        if (needle) {
            rows = rows.filter((row) =>
                row.values.some((value) => this.formatValue(value).toLowerCase().includes(needle))
            );
        }
        if (this.state.sortColumn >= 0) {
            const column = this.state.sortColumn;
            const direction = this.state.sortDirection === "asc" ? 1 : -1;
            rows.sort((left, right) => {
                const a = left.values[column];
                const b = right.values[column];
                if (a === b) return 0;
                if (a === null || a === undefined) return 1;
                if (b === null || b === undefined) return -1;
                if (typeof a === "number" && typeof b === "number") return (a - b) * direction;
                return String(a).localeCompare(String(b), undefined, { numeric: true }) * direction;
            });
        }
        return rows;
    }

    get totalPages() {
        return Math.max(1, Math.ceil(this.filteredRows.length / this.state.pageSize));
    }

    get formattedDuration() {
        const duration = Number.parseFloat(this.state.duration);
        return Number.isFinite(duration) ? duration.toFixed(4) : "0.0000";
    }

    get visibleRows() {
        if (this.state.page > this.totalPages) this.state.page = this.totalPages;
        const start = (this.state.page - 1) * this.state.pageSize;
        return this.filteredRows.slice(start, start + this.state.pageSize);
    }

    async loadDatabaseObjects() {
        try {
            this.state.schemas = await this.orm.call("psql.query", "get_database_objects", [this.state.objectSearch]);
        } catch (error) {
            this.state.schemas = [];
            this.notification.add(error.message || "Could not load database objects.", { type: "warning" });
        }
    }

    onEditorChange(value) {
        this.state.sql = value;
        this.props.record.update({ query_name: value });
        this.rememberSqlDraft(value);
    }

    rememberSqlDraft(value = this.state.sql) {
        this.storageSet(this.draftStorageKey, this.sqlForStorage(value));
        this.scheduleQueryDraftSave();
    }

    scheduleQueryDraftSave() {
        if (!this.props.record.resId || this.state.loading) {
            return;
        }
        if (this.queryDraftSaveTimer) {
            window.clearTimeout(this.queryDraftSaveTimer);
        }
        this.queryDraftSaveTimer = window.setTimeout(() => {
            this.queryDraftSaveTimer = null;
            this.saveQueryDraftQuietly();
        }, 1200);
    }

    async saveQueryDraftQuietly() {
        if (!this.props.record.resId || this.state.loading) {
            return;
        }
        try {
            await this.orm.call("psql.query", "write", [[this.props.record.resId], {
                query_name: this.sqlForServer(),
            }]);
        } catch {
            // Keep the local browser draft even if the server is temporarily busy.
        }
    }

    onEditorKeydown(event) {
        if (event.key === "Enter" && (event.ctrlKey || event.metaKey)) {
            event.preventDefault();
            this.runQuery();
        }
    }

    async ensureSaved() {
        await this.props.record.update({ query_name: this.state.sql });
        const saved = await this.props.record.save({ reload: false });
        if (!saved || !this.props.record.resId) {
            throw new Error("Save the report before running it.");
        }
        return this.props.record.resId;
    }

    async ensureQueryReady() {
        this.rememberSqlDraft();
        if (this.queryDraftSaveTimer) {
            window.clearTimeout(this.queryDraftSaveTimer);
            this.queryDraftSaveTimer = null;
        }
        await this.props.record.update({ query_name: this.state.sql });
        if (this.props.record.resId) {
            await this.orm.call("psql.query", "write", [[this.props.record.resId], {
                query_name: this.sqlForServer(),
            }]);
            return this.props.record.resId;
        }
        return this.ensureSaved();
    }

    async saveReport() {
        try {
            await this.ensureSaved();
            this.notification.add("Report saved.", { type: "success" });
        } catch (error) {
            this.notification.add(error.message || "The report could not be saved.", { type: "danger" });
        }
    }

    async saveAsReport() {
        try {
            await this.ensureSaved();
            this.dialog.add(PsqlSaveAsReportDialog, {
                onSave: async (name, description) => {
                    await this.props.record.update({
                        name,
                        description,
                        is_interactive_session: false,
                    });
                    await this.props.record.save({ reload: false });
                    this.notification.add(`Report saved as “${name}”.`, { type: "success" });
                },
            });
        } catch (error) {
            this.notification.add(error.message || "The interactive session could not be prepared.", {
                type: "danger",
            });
        }
    }

    async runQuery() {
        if (this.state.loading) return;
        this.state.loading = true;
        this.state.error = "";
        try {
            const recordId = await this.ensureQueryReady();
            const payload = await this.orm.call("psql.query", "execute_interactive_query", [[recordId]]);
            if (payload.needs_parameters && payload.action) {
                await this.action.doAction(payload.action);
                return;
            }
            this.state.result = {
                columns: payload.columns || [],
                rows: payload.rows || [],
                limited: Boolean(payload.limited),
            };
            this.state.status = payload.status;
            this.state.error = payload.error || "";
            this.state.duration = payload.duration || 0;
            this.state.rowCount = payload.row_count || 0;
            this.state.executedAt = payload.executed_at || "";
            this.state.page = 1;
            if (payload.ok) {
                const message = payload.row_count
                    ? `Query executed successfully: ${payload.row_count} row(s).`
                    : "Query executed successfully. No records returned.";
                this.notification.add(message, { type: "success" });
                this.openResultDialog(recordId);
            } else {
                this.notification.add(payload.error || "Query execution failed.", { type: "danger", sticky: true });
            }
        } catch (error) {
            this.state.status = "error";
            this.state.error = error.message || "Query execution failed.";
            this.notification.add(this.state.error, { type: "danger", sticky: true });
        } finally {
            this.state.loading = false;
        }
    }

    async clearWorkspace() {
        this.state.sql = "";
        this.state.result = { columns: [], rows: [], limited: false };
        this.state.status = "never";
        this.state.error = "";
        this.state.rowCount = 0;
        this.state.duration = 0;
        this.storageRemove(this.draftStorageKey);
        if (this.queryDraftSaveTimer) {
            window.clearTimeout(this.queryDraftSaveTimer);
            this.queryDraftSaveTimer = null;
        }
        await this.props.record.update({ query_name: this.state.sql });
        if (this.props.record.resId) {
            await this.orm.call("psql.query", "action_clear_workspace", [[this.props.record.resId]]);
        }
    }

    newReport() {
        this.action.doAction({
            type: "ir.actions.act_window",
            name: "New SQL Report",
            res_model: "psql.query",
            views: [[false, "form"]],
            target: "current",
            context: {
                default_query_name: "",
            },
        });
    }

    async openWizard() {
        try {
            const recordId = await this.ensureQueryReady();
            const action = await this.orm.call("psql.query", "action_open_sql_wizard", [[recordId]]);
            await this.action.doAction(action);
        } catch (error) {
            this.notification.add(error.message || "Save the report before using the SQL Wizard.", { type: "warning" });
        }
    }

    exportResult(format) {
        if (!this.state.result.columns.length || !this.props.record.resId) return;
        window.location.assign(`/psql_query_execute/export/${format}/${this.props.record.resId}`);
    }

    openResultDialog(recordId = this.props.record.resId) {
        if (!recordId) return;
        this.dialog.add(PsqlResultDialog, {
            reportId: recordId,
            result: {
                columns: [...(this.state.result.columns || [])],
                rows: [...(this.state.result.rows || [])],
                limited: Boolean(this.state.result.limited),
            },
            title: `Query Result — ${this.props.record.data.name || "SQL Report"}`,
        });
    }

    toggleFullscreen() {
        this.state.fullscreen = !this.state.fullscreen;
    }

    sortBy(columnIndex) {
        if (this.state.sortColumn === columnIndex) {
            this.state.sortDirection = this.state.sortDirection === "asc" ? "desc" : "asc";
        } else {
            this.state.sortColumn = columnIndex;
            this.state.sortDirection = "asc";
        }
        this.state.page = 1;
    }

    previousPage() {
        this.state.page = Math.max(1, this.state.page - 1);
    }

    nextPage() {
        this.state.page = Math.min(this.totalPages, this.state.page + 1);
    }

    formatValue(value) {
        if (value === null || value === undefined) return "NULL";
        if (typeof value === "number") return new Intl.NumberFormat().format(value);
        if (typeof value === "object") return JSON.stringify(value);
        return String(value);
    }

    async copyCell(value) {
        await navigator.clipboard.writeText(value === null || value === undefined ? "NULL" : String(value));
        this.notification.add("Cell copied.", { type: "info" });
    }

    toggleTable(schemaName, tableName) {
        const key = `${schemaName}.${tableName}`;
        this.state.expandedTables[key] = !this.state.expandedTables[key];
    }

    isExpanded(schemaName, tableName) {
        return Boolean(this.state.expandedTables[`${schemaName}.${tableName}`]);
    }

    insertText(text) {
        const separator = this.state.sql && !this.state.sql.endsWith("\n") ? "\n" : "";
        this.state.sql = `${this.state.sql || ""}${separator}${text}`;
        this.props.record.update({ query_name: this.state.sql });
        this.rememberSqlDraft();
    }

    insertTable(schemaName, tableName) {
        this.insertText(`"${schemaName}"."${tableName}"`);
    }

    insertColumn(columnName) {
        this.insertText(`"${columnName}"`);
    }

    generateSelect(schemaName, tableName) {
        this.state.sql = `SELECT *\nFROM "${schemaName}"."${tableName}"\nLIMIT 100;`;
        this.props.record.update({ query_name: this.state.sql });
        this.rememberSqlDraft();
    }
}

registry.category("fields").add("psql_interactive_workspace", {
    component: PsqlInteractiveWorkspace,
    supportedTypes: ["json"],
});

registry.category("fields").add("psql_sql_preview", {
    component: PsqlSqlPreviewField,
    supportedTypes: ["text"],
});

registry.category("fields").add("psql_parameter_form", {
    component: PsqlParameterFormField,
    supportedTypes: ["one2many"],
});

export class PsqlSqlWizardUi extends Component {
    static template = "psql_query_execute.SqlWizardUi";
    static components = { CodeEditor };
    static props = standardFieldProps;

    setup() {
        this.orm = useService("orm");
        this.notification = useService("notification");
        this.action = useService("action");
        
        this.state = useState({
            step: 2,
            schema: this.props.record.data.schema_name || "public",
            tableOptionId: this.props.record.data.table_option_id ? this.props.record.data.table_option_id[0] : null,
            tableAlias: this.props.record.data.table_alias || "t",
            distinct: this.props.record.data.distinct || false,
            rowLimit: this.props.record.data.row_limit || 100,
            rowOffset: this.props.record.data.row_offset || 0,
            
            tableOptions: [],
            availableFields: [],
            selectedTableId: null,
            selectedTableAlias: "",
            
            selectedFields: [],
            joins: [],
            filters: [],
            groups: [],
            havings: [],
            orders: [],
            unions: [],
            allFieldOptions: [],
            
            sqlPreview: this.props.record.data.sql_preview || "",
            previewReady: this.props.record.data.preview_ready || false,
            editorHasSql: this.props.record.data.editor_has_sql || false,
            insertMode: this.props.record.data.insert_mode || "replace",
            
            searchQueryAvailable: "",
            searchQueryTable: "",
            selectedAvailableFieldIds: new Set(),
            selectedRightFieldId: null,
            draggedFieldId: null,
            editingJoinIds: new Set(),
            searchQueryFieldsBySection: "",
            loadingTableId: null,
        });

        onMounted(async () => {
            await this.loadInitialData();
        });
    }

    get filteredTableOptions() {
        const query = this.state.searchQueryTable.trim().toLowerCase();
        let options = this.state.tableOptions;
        if (query) {
            options = options.filter(t => t.display_name.toLowerCase().includes(query));
        }
        return options;
    }

    formatTableLabel(table) {
        if (!table) return "";
        const name = table.schema_name && table.schema_name !== "public"
            ? `${table.schema_name}.${table.table_name}`
            : table.table_name;
        return table.object_type === "view" ? `${name} (View)` : name;
    }

    get filteredAvailableFields() {
        const query = this.state.searchQueryAvailable.trim().toLowerCase();
        let fields = this.state.availableFields;
        if (query) {
            fields = fields.filter(f => 
                f.column_name.toLowerCase().includes(query) ||
                (f.description && f.description.toLowerCase().includes(query)) ||
                (f.data_type && f.data_type.toLowerCase().includes(query))
            );
        }
        return fields;
    }

    async loadInitialData() {
        const wizardId = this.props.record.resId;
        if (!wizardId) return;

        try {
            this.state.tableOptions = await this.orm.searchRead(
                "psql.query.wizard.table.option",
                [["wizard_id", "=", wizardId]],
                ["schema_name", "table_name", "object_type", "display_name"]
            );

            await this.reloadWizardLines();

            if (this.state.tableOptionId) {
                this.state.selectedTableId = this.state.tableOptionId;
                this.state.selectedTableAlias = this.state.tableAlias;
                await this.loadAvailableFieldsForTable(this.state.tableOptionId, this.state.tableAlias);
            }
        } catch (error) {
            this.notification.add(error.message || "Failed to load wizard metadata.", { type: "danger" });
        }
    }

    async reloadWizardLines() {
        const wizardId = this.props.record.resId;
        
        this.state.selectedFields = await this.orm.searchRead(
            "psql.query.wizard.column",
            [["wizard_id", "=", wizardId], ["selected", "=", true]],
            ["sequence", "selected", "field_option_id", "source_alias", "table_name", "column_name", "data_type", "nullable", "primary_key", "foreign_key", "description", "aggregate", "column_alias", "group_by", "sort_direction", "sort_nulls"]
        );
        this.state.selectedFields.sort((a, b) => a.sequence - b.sequence);

        this.state.joins = await this.orm.searchRead(
            "psql.query.wizard.join",
            [["wizard_id", "=", wizardId]],
            ["sequence", "join_type", "table_option_id", "alias", "left_field_option_id", "operator", "right_field_option_id", "left_field", "right_field"]
        );
        this.state.joins.sort((a, b) => a.sequence - b.sequence);

        this.state.filters = await this.orm.searchRead(
            "psql.query.wizard.filter",
            [["wizard_id", "=", wizardId]],
            ["sequence", "connector", "field_option_id", "field_name", "operator", "value", "value_to"]
        );

        this.state.groups = await this.orm.searchRead(
            "psql.query.wizard.group",
            [["wizard_id", "=", wizardId]],
            ["sequence", "field_option_id", "field_name"]
        );

        this.state.havings = await this.orm.searchRead(
            "psql.query.wizard.having",
            [["wizard_id", "=", wizardId]],
            ["sequence", "connector", "aggregate", "field_option_id", "field_name", "operator", "value"]
        );

        this.state.orders = await this.orm.searchRead(
            "psql.query.wizard.order",
            [["wizard_id", "=", wizardId]],
            ["sequence", "field_option_id", "field_name", "direction", "nulls"]
        );
        this.state.orders.sort((a, b) => a.sequence - b.sequence);

        this.state.unions = await this.orm.searchRead(
            "psql.query.wizard.union",
            [["wizard_id", "=", wizardId]],
            ["sequence", "union_type", "sql_text"]
        );
        this.state.unions.sort((a, b) => a.sequence - b.sequence);

        this.state.allFieldOptions = await this.orm.searchRead(
            "psql.query.wizard.field.option",
            [["wizard_id", "=", wizardId]],
            ["display_name", "column_name", "source_alias", "table_option_id", "data_type"]
        );
    }

    async loadAvailableFieldsForTable(tableOptionId, alias) {
        const wizardId = this.props.record.resId;
        this.state.loadingTableId = tableOptionId;
        try {
            await this.orm.call("psql.query.wizard", "action_load_columns_for_table", [wizardId, tableOptionId, alias]);

            const fields = await this.orm.searchRead(
                "psql.query.wizard.field.option",
                [["wizard_id", "=", wizardId], ["table_option_id", "=", tableOptionId], ["source_alias", "=", alias]],
                ["column_name", "data_type", "nullable", "default_value", "primary_key", "foreign_key", "position", "description", "display_name", "source_alias", "table_option_id"]
            );
            this.state.availableFields = fields;
            this.mergeFieldOptions(fields);
            this.state.selectedAvailableFieldIds.clear();
        } finally {
            this.state.loadingTableId = null;
        }
    }

    mergeFieldOptions(fields) {
        const byId = new Map(this.state.allFieldOptions.map(field => [field.id, field]));
        for (const field of fields) {
            byId.set(field.id, {
                ...(byId.get(field.id) || {}),
                id: field.id,
                display_name: field.display_name,
                column_name: field.column_name,
                source_alias: field.source_alias,
                table_option_id: field.table_option_id,
                data_type: field.data_type,
            });
        }
        this.state.allFieldOptions = Array.from(byId.values());
    }

    async onColumnsTableChange(ev) {
        const tableId = parseInt(ev.target.value);
        if (!tableId) return;
        this.state.selectedTableId = tableId;
        
        const table = this.state.tableOptions.find(t => t.id === tableId);
        if (!table) return;

        let alias = "";
        if (!this.state.tableOptionId) {
            alias = this.makeUniqueAlias(table.table_name, "t");
            this.state.schema = table.schema_name;
            this.state.tableOptionId = tableId;
            this.state.tableAlias = alias;
            await this.props.record.update({
                schema_name: table.schema_name,
                table_option_id: tableId,
                table_alias: alias,
            });
            await this.props.record.save();
        } else if (tableId === this.state.tableOptionId) {
            alias = this.state.tableAlias;
        } else {
            const existingJoin = this.state.joins.find(j => j.table_option_id[0] === tableId);
            if (existingJoin) {
                alias = existingJoin.alias;
            } else {
                const wizardId = this.props.record.resId;
                await this.orm.call("psql.query.wizard", "action_add_join_for_table", [wizardId, tableId]);
                await this.reloadWizardLines();
                const newJoin = this.state.joins.find(j => j.table_option_id[0] === tableId);
                alias = newJoin ? newJoin.alias : "j";
                if (newJoin) {
                    this.state.editingJoinIds.add(newJoin.id);
                }
                this.notification.add(`${this.formatTableLabel(table)} added. Define its relationship on the JOIN step.`, { type: "info" });
            }
        }
        this.state.selectedTableAlias = alias;
        await this.loadAvailableFieldsForTable(tableId, alias);
    }

    makeUniqueAlias(tableName, fallback = "j") {
        const base = tableName.split("_").map(part => part[0]).join("").slice(0, 4) || fallback;
        const used = new Set([
            ...(this.state.tableOptionId ? [this.state.tableAlias] : []),
            ...this.state.joins.map(join => join.alias),
        ].filter(Boolean));
        let alias = base;
        let suffix = 1;
        while (used.has(alias)) {
            alias = `${base}${suffix++}`;
        }
        return alias;
    }

    toggleAvailableFieldSelection(fieldId) {
        if (this.state.selectedAvailableFieldIds.has(fieldId)) {
            this.state.selectedAvailableFieldIds.delete(fieldId);
        } else {
            this.state.selectedAvailableFieldIds.add(fieldId);
        }
    }

    selectRightField(fieldId) {
        this.state.selectedRightFieldId = fieldId;
    }

    async addFields() {
        const selectedIds = Array.from(this.state.selectedAvailableFieldIds);
        if (!selectedIds.length) {
            this.notification.add("Select fields to add from the left panel.", { type: "warning" });
            return;
        }
        
        const toAdd = this.state.availableFields.filter(f => selectedIds.includes(f.id));
        const maxSeq = this.state.selectedFields.length ? Math.max(...this.state.selectedFields.map(f => f.sequence)) : 10;
        
        const commands = [];
        let seq = maxSeq + 10;
        for (const field of toAdd) {
            const exists = this.state.selectedFields.some(
                sf => sf.field_option_id && sf.field_option_id[0] === field.id
            );
            if (exists) continue;
            
            commands.push([0, 0, {
                selected: true,
                field_option_id: field.id,
                column_name: field.column_name,
                data_type: field.data_type,
                nullable: field.nullable,
                default_value: field.default_value,
                primary_key: field.primary_key,
                foreign_key: field.foreign_key,
                position: field.position,
                description: field.description,
                sequence: seq,
                aggregate: "none",
                column_alias: "",
                group_by: false,
                sort_direction: "none",
                sort_nulls: "last"
            }]);
            seq += 10;
        }
        
        if (commands.length) {
            await this.props.record.update({ column_line_ids: commands });
            await this.props.record.save();
            await this.reloadWizardLines();
            this.state.selectedAvailableFieldIds.clear();
        }
    }

    async addAllFields() {
        const toAdd = this.state.availableFields;
        if (!toAdd.length) return;
        
        const maxSeq = this.state.selectedFields.length ? Math.max(...this.state.selectedFields.map(f => f.sequence)) : 10;
        const commands = [];
        let seq = maxSeq + 10;
        for (const field of toAdd) {
            const exists = this.state.selectedFields.some(
                sf => sf.field_option_id && sf.field_option_id[0] === field.id
            );
            if (exists) continue;
            
            commands.push([0, 0, {
                selected: true,
                field_option_id: field.id,
                column_name: field.column_name,
                data_type: field.data_type,
                nullable: field.nullable,
                default_value: field.default_value,
                primary_key: field.primary_key,
                foreign_key: field.foreign_key,
                position: field.position,
                description: field.description,
                sequence: seq,
                aggregate: "none",
                column_alias: "",
                group_by: false,
                sort_direction: "none",
                sort_nulls: "last"
            }]);
            seq += 10;
        }
        
        if (commands.length) {
            await this.props.record.update({ column_line_ids: commands });
            await this.props.record.save();
            await this.reloadWizardLines();
        }
    }

    async removeField(fieldId) {
        if (!fieldId) return;
        await this.props.record.update({ column_line_ids: [[2, fieldId, 0]] });
        await this.props.record.save();
        await this.reloadWizardLines();
        this.state.selectedRightFieldId = null;
    }

    async removeAllFields() {
        await this.props.record.update({ column_line_ids: [[5, 0, 0]] });
        await this.props.record.save();
        await this.reloadWizardLines();
        this.state.selectedRightFieldId = null;
    }

    async editFormula() {
        const selectedId = this.state.selectedRightFieldId;
        if (!selectedId) {
            this.notification.add("Select a field in the right panel first.", { type: "warning" });
            return;
        }
        const field = this.state.selectedFields.find(f => f.id === selectedId);
        if (!field) return;
        
        const aliasInput = prompt(`Enter Column Alias / Formula for ${field.source_alias}.${field.column_name}:`, field.column_alias || "");
        if (aliasInput !== null) {
            await this.updateSelectedField(selectedId, { column_alias: aliasInput });
        }
    }

    async toggleGroupByAction() {
        const selectedId = this.state.selectedRightFieldId;
        if (!selectedId) {
            this.notification.add("Select a field in the right panel first.", { type: "warning" });
            return;
        }
        const field = this.state.selectedFields.find(f => f.id === selectedId);
        if (!field) return;
        await this.updateSelectedField(selectedId, { group_by: !field.group_by });
    }

    async updateSelectedField(fieldId, changes) {
        await this.props.record.update({
            column_line_ids: [[1, fieldId, changes]]
        });
        await this.props.record.save();
        await this.reloadWizardLines();
    }

    async moveFieldUp(index) {
        if (index <= 0) return;
        const fields = [...this.state.selectedFields];
        const temp = fields[index];
        fields[index] = fields[index - 1];
        fields[index - 1] = temp;
        
        const commands = fields.map((f, idx) => [1, f.id, { sequence: (idx + 1) * 10 }]);
        await this.props.record.update({ column_line_ids: commands });
        await this.props.record.save();
        await this.reloadWizardLines();
    }

    async moveFieldDown(index) {
        if (index >= this.state.selectedFields.length - 1) return;
        const fields = [...this.state.selectedFields];
        const temp = fields[index];
        fields[index] = fields[index + 1];
        fields[index + 1] = temp;
        
        const commands = fields.map((f, idx) => [1, f.id, { sequence: (idx + 1) * 10 }]);
        await this.props.record.update({ column_line_ids: commands });
        await this.props.record.save();
        await this.reloadWizardLines();
    }

    startFieldDrag(fieldId) {
        this.state.draggedFieldId = fieldId;
    }

    async dropField(targetFieldId) {
        const draggedId = this.state.draggedFieldId;
        this.state.draggedFieldId = null;
        if (!draggedId || draggedId === targetFieldId) return;
        const fields = [...this.state.selectedFields];
        const sourceIndex = fields.findIndex(field => field.id === draggedId);
        const targetIndex = fields.findIndex(field => field.id === targetFieldId);
        if (sourceIndex < 0 || targetIndex < 0) return;
        const [draggedField] = fields.splice(sourceIndex, 1);
        fields.splice(targetIndex, 0, draggedField);
        const commands = fields.map((field, index) => [1, field.id, { sequence: (index + 1) * 10 }]);
        await this.props.record.update({ column_line_ids: commands });
        await this.props.record.save();
        await this.reloadWizardLines();
    }

    getJoinSourceAlias(join) {
        if (join.left_field_option_id) {
            const option = this.state.allFieldOptions.find(field => field.id === join.left_field_option_id[0]);
            if (option) return option.source_alias;
        }
        return (join.left_field || "").split(".")[0] || "";
    }

    getJoinSourceOptions(join) {
        const sources = [];
        const baseTable = this.state.tableOptions.find(table => table.id === this.state.tableOptionId);
        if (baseTable && this.state.tableAlias) {
            sources.push({
                alias: this.state.tableAlias,
                label: `${this.formatTableLabel(baseTable)} (${this.state.tableAlias})`,
            });
        }
        for (const candidate of this.state.joins) {
            if (candidate.id === join.id) break;
            const tableId = candidate.table_option_id && candidate.table_option_id[0];
            const table = this.state.tableOptions.find(option => option.id === tableId);
            if (table && candidate.alias) {
                sources.push({ alias: candidate.alias, label: `${this.formatTableLabel(table)} (${candidate.alias})` });
            }
        }
        return sources;
    }

    getFieldsForAlias(alias) {
        return alias ? this.state.allFieldOptions.filter(field => field.source_alias === alias) : [];
    }

    getSourceOptions() {
        const sources = [];
        const baseTable = this.state.tableOptions.find(table => table.id === this.state.tableOptionId);
        if (baseTable && this.state.tableAlias) {
            sources.push({
                alias: this.state.tableAlias,
                label: `${this.formatTableLabel(baseTable)} (${this.state.tableAlias})`,
            });
        }
        for (const join of this.state.joins) {
            const tableId = join.table_option_id && join.table_option_id[0];
            const table = this.state.tableOptions.find(option => option.id === tableId);
            if (table && join.alias) {
                sources.push({ alias: join.alias, label: `${this.formatTableLabel(table)} (${join.alias})` });
            }
        }
        return sources;
    }

    getLineAlias(line) {
        if (line.field_option_id) {
            const option = this.state.allFieldOptions.find(field => field.id === line.field_option_id[0]);
            if (option) return option.source_alias;
        }
        return (line.field_name || "").split(".")[0] || this.state.tableAlias || "";
    }

    getFieldsForLine(line) {
        return this.getFieldsForAlias(this.getLineAlias(line));
    }

    async updateLineSource(lineId, alias, updater) {
        const option = this.getFieldsForAlias(alias)[0];
        if (!option) return;
        await updater(lineId, {
            field_option_id: option.id,
            field_name: `${alias}.${option.column_name}`,
        });
    }

    fieldUpdateValues(line, fieldId) {
        const id = parseInt(fieldId || 0);
        const option = this.state.allFieldOptions.find(field => field.id === id);
        return option
            ? { field_option_id: option.id, field_name: `${option.source_alias}.${option.column_name}` }
            : { field_option_id: false, field_name: line.field_name || "" };
    }

    async updateFilterSource(lineId, alias) {
        await this.updateLineSource(lineId, alias, this.updateFilter.bind(this));
    }

    async updateFilterField(line, fieldId) {
        await this.updateFilter(line.id, this.fieldUpdateValues(line, fieldId));
    }

    async updateGroupSource(lineId, alias) {
        await this.updateLineSource(lineId, alias, this.updateGroup.bind(this));
    }

    async updateGroupField(line, fieldId) {
        await this.updateGroup(line.id, this.fieldUpdateValues(line, fieldId));
    }

    async updateHavingSource(lineId, alias) {
        await this.updateLineSource(lineId, alias, this.updateHaving.bind(this));
    }

    async updateHavingField(line, fieldId) {
        await this.updateHaving(line.id, this.fieldUpdateValues(line, fieldId));
    }

    async updateOrderSource(lineId, alias) {
        await this.updateLineSource(lineId, alias, this.updateOrder.bind(this));
    }

    async updateOrderField(line, fieldId) {
        await this.updateOrder(line.id, this.fieldUpdateValues(line, fieldId));
    }

    isJoinEditing(join) {
        return this.state.editingJoinIds.has(join.id) || !join.left_field_option_id || !join.right_field_option_id;
    }

    toggleJoinEditing(joinId) {
        if (this.state.editingJoinIds.has(joinId)) {
            this.state.editingJoinIds.delete(joinId);
        } else {
            this.state.editingJoinIds.add(joinId);
        }
    }

    async addJoin() {
        if (!this.state.tableOptionId) {
            this.notification.add("Choose the first table on the Columns step before adding a JOIN.", { type: "warning" });
            this.state.step = 1;
            return;
        }
        const joinedTableIds = new Set(this.state.joins.map(join => join.table_option_id && join.table_option_id[0]));
        const target = this.state.tableOptions.find(table => table.id !== this.state.tableOptionId && !joinedTableIds.has(table.id))
            || this.state.tableOptions.find(table => table.id !== this.state.tableOptionId);
        if (!target) {
            this.notification.add("No additional table is available for a JOIN.", { type: "warning" });
            return;
        }
        const alias = this.makeUniqueAlias(target.table_name);
        const sourceAlias = this.state.joins.length
            ? this.state.joins[this.state.joins.length - 1].alias
            : this.state.tableAlias;
        await this.orm.call("psql.query.wizard", "action_load_columns_for_table", [this.props.record.resId, target.id, alias]);
        await this.reloadWizardLines();
        const sourceOption = this.getFieldsForAlias(sourceAlias).find(field => field.column_name === "id")
            || this.getFieldsForAlias(sourceAlias)[0];
        const targetFields = this.getFieldsForAlias(alias).filter(field => field.table_option_id[0] === target.id);
        const targetOption = targetFields.find(field => field.column_name === "id") || targetFields[0];
        const maxSeq = this.state.joins.length ? Math.max(...this.state.joins.map(join => join.sequence)) : 0;
        const createdIds = await this.orm.create("psql.query.wizard.join", [{
            wizard_id: this.props.record.resId,
            sequence: maxSeq + 10,
            join_type: "left",
            table_option_id: target.id,
            alias,
            left_field_option_id: sourceOption ? sourceOption.id : false,
            right_field_option_id: targetOption ? targetOption.id : false,
            operator: "=",
            left_field: sourceOption ? `${sourceAlias}.${sourceOption.column_name}` : `${sourceAlias}.id`,
            right_field: targetOption ? targetOption.column_name : "id",
        }]);
        await this.reloadWizardLines();
        const createdId = Array.isArray(createdIds) ? createdIds[0] : createdIds;
        if (createdId) this.state.editingJoinIds.add(createdId);
    }

    async removeJoin(id) {
        await this.props.record.update({ join_line_ids: [[2, id, 0]] });
        await this.props.record.save();
        this.state.editingJoinIds.delete(id);
        await this.reloadWizardLines();
    }

    async updateJoin(id, changes) {
        await this.props.record.update({ join_line_ids: [[1, id, changes]] });
        await this.props.record.save();
        await this.reloadWizardLines();
    }

    async updateJoinSourceTable(joinId, alias) {
        const option = this.getFieldsForAlias(alias).find(field => field.column_name === "id")
            || this.getFieldsForAlias(alias)[0];
        if (!option) return;
        await this.updateJoin(joinId, {
            left_field_option_id: option.id,
            left_field: `${alias}.${option.column_name}`,
        });
    }

    async updateJoinTargetTable(joinId, tableId) {
        if (!tableId) return;
        const join = this.state.joins.find(item => item.id === joinId);
        const table = this.state.tableOptions.find(item => item.id === tableId);
        if (!join || !table) return;
        const alias = join.alias || this.makeUniqueAlias(table.table_name);
        await this.orm.call("psql.query.wizard", "action_load_columns_for_table", [this.props.record.resId, tableId, alias]);
        await this.reloadWizardLines();
        const targetFields = this.getFieldsForAlias(alias).filter(field => field.table_option_id[0] === tableId);
        const targetOption = targetFields.find(field => field.column_name === "id") || targetFields[0];
        await this.updateJoin(joinId, {
            table_option_id: tableId,
            alias,
            right_field_option_id: targetOption ? targetOption.id : false,
            right_field: targetOption ? targetOption.column_name : "id",
        });
    }

    async updateJoinAlias(joinId, requestedAlias) {
        const join = this.state.joins.find(item => item.id === joinId);
        if (!join) return;
        const tableId = join.table_option_id && join.table_option_id[0];
        const table = this.state.tableOptions.find(item => item.id === tableId);
        const alias = requestedAlias.trim() || this.makeUniqueAlias(table ? table.table_name : "join");
        const previousRightOption = join.right_field_option_id
            ? this.state.allFieldOptions.find(field => field.id === join.right_field_option_id[0])
            : null;
        await this.orm.call("psql.query.wizard", "action_load_columns_for_table", [this.props.record.resId, tableId, alias]);
        await this.reloadWizardLines();
        const replacement = this.state.allFieldOptions.find(field =>
            field.table_option_id[0] === tableId &&
            field.source_alias === alias &&
            field.column_name === (previousRightOption ? previousRightOption.column_name : join.right_field)
        );
        await this.updateJoin(joinId, {
            alias,
            right_field_option_id: replacement
                ? replacement.id
                : (join.right_field_option_id ? join.right_field_option_id[0] : false),
        });
    }

    async moveJoinUp(index) {
        if (index <= 0) return;
        await this.moveJoin(index, index - 1);
    }

    async moveJoinDown(index) {
        if (index >= this.state.joins.length - 1) return;
        await this.moveJoin(index, index + 1);
    }

    async moveJoin(fromIndex, toIndex) {
        const joins = [...this.state.joins];
        [joins[fromIndex], joins[toIndex]] = [joins[toIndex], joins[fromIndex]];
        const commands = joins.map((join, index) => [1, join.id, { sequence: (index + 1) * 10 }]);
        await this.props.record.update({ join_line_ids: commands });
        await this.props.record.save();
        await this.reloadWizardLines();
    }

    async addFilter() {
        const firstField = this.state.allFieldOptions[0];
        await this.props.record.update({
            filter_line_ids: [[0, 0, {
                connector: "AND",
                operator: "=",
                field_option_id: firstField ? firstField.id : false,
                field_name: firstField ? `${firstField.source_alias}.${firstField.column_name}` : ""
            }]]
        });
        await this.props.record.save();
        await this.reloadWizardLines();
    }

    async removeFilter(id) {
        await this.props.record.update({ filter_line_ids: [[2, id, 0]] });
        await this.props.record.save();
        await this.reloadWizardLines();
    }

    async updateFilter(id, changes) {
        await this.props.record.update({ filter_line_ids: [[1, id, changes]] });
        await this.props.record.save();
        await this.reloadWizardLines();
    }

    async addGroup() {
        const firstField = this.state.allFieldOptions[0];
        await this.props.record.update({
            group_line_ids: [[0, 0, {
                field_option_id: firstField ? firstField.id : false,
                field_name: firstField ? `${firstField.source_alias}.${firstField.column_name}` : ""
            }]]
        });
        await this.props.record.save();
        await this.reloadWizardLines();
    }

    async removeGroup(id) {
        await this.props.record.update({ group_line_ids: [[2, id, 0]] });
        await this.props.record.save();
        await this.reloadWizardLines();
    }

    async updateGroup(id, changes) {
        await this.props.record.update({ group_line_ids: [[1, id, changes]] });
        await this.props.record.save();
        await this.reloadWizardLines();
    }

    async addHaving() {
        const firstField = this.state.allFieldOptions[0];
        await this.props.record.update({
            having_line_ids: [[0, 0, {
                connector: "AND",
                aggregate: "count",
                operator: ">",
                field_option_id: firstField ? firstField.id : false,
                field_name: firstField ? `${firstField.source_alias}.${firstField.column_name}` : ""
            }]]
        });
        await this.props.record.save();
        await this.reloadWizardLines();
    }

    async removeHaving(id) {
        await this.props.record.update({ having_line_ids: [[2, id, 0]] });
        await this.props.record.save();
        await this.reloadWizardLines();
    }

    async updateHaving(id, changes) {
        await this.props.record.update({ having_line_ids: [[1, id, changes]] });
        await this.props.record.save();
        await this.reloadWizardLines();
    }

    async addOrder() {
        const firstField = this.state.allFieldOptions[0];
        await this.props.record.update({
            order_line_ids: [[0, 0, {
                direction: "asc",
                nulls: "last",
                field_option_id: firstField ? firstField.id : false,
                field_name: firstField ? `${firstField.source_alias}.${firstField.column_name}` : ""
            }]]
        });
        await this.props.record.save();
        await this.reloadWizardLines();
    }

    async removeOrder(id) {
        await this.props.record.update({ order_line_ids: [[2, id, 0]] });
        await this.props.record.save();
        await this.reloadWizardLines();
    }

    async updateOrder(id, changes) {
        await this.props.record.update({ order_line_ids: [[1, id, changes]] });
        await this.props.record.save();
        await this.reloadWizardLines();
    }

    async addUnion() {
        const maxSeq = this.state.unions.length ? Math.max(...this.state.unions.map(line => line.sequence)) : 0;
        await this.props.record.update({
            union_line_ids: [[0, 0, {
                sequence: maxSeq + 10,
                union_type: "union_all",
                sql_text: "SELECT\n    -- choose matching columns here",
            }]]
        });
        await this.props.record.save();
        await this.reloadWizardLines();
    }

    async removeUnion(id) {
        await this.props.record.update({ union_line_ids: [[2, id, 0]] });
        await this.props.record.save();
        await this.reloadWizardLines();
    }

    async updateUnion(id, changes) {
        await this.props.record.update({ union_line_ids: [[1, id, changes]] });
        await this.props.record.save();
        await this.reloadWizardLines();
    }

    async saveStepChanges() {
        if (this.state.step === 1) {
            await this.props.record.update({
                schema_name: this.state.schema,
                table_option_id: this.state.tableOptionId,
                table_alias: this.state.tableAlias,
                distinct: this.state.distinct,
                row_limit: this.state.rowLimit,
                row_offset: this.state.rowOffset,
            });
            await this.props.record.save();
        } else if (this.state.step === 8) {
            await this.props.record.update({
                insert_mode: this.state.insertMode
            });
            await this.props.record.save();
        }
    }

    async setStep(step) {
        await this.saveStepChanges();
        this.state.step = step;
    }

    async prevStep() {
        await this.saveStepChanges();
        if (this.state.step > 2) {
            this.state.step--;
        }
    }

    async nextStep() {
        await this.saveStepChanges();
        if (this.state.step < 8) {
            this.state.step++;
        }
    }

    async generateSql() {
        const wizardId = this.props.record.resId;
        await this.saveStepChanges();
        try {
            await this.orm.call("psql.query.wizard", "action_generate_query", [[wizardId]]);
            await this.reloadWizardLines();
            this.state.sqlPreview = this.props.record.data.sql_preview;
            this.state.previewReady = this.props.record.data.preview_ready;
            this.state.step = 8;
            this.notification.add("SQL query generated successfully.", { type: "success" });
        } catch (error) {
            this.notification.add(error.message || "Failed to generate SQL.", { type: "danger" });
        }
    }

    async copySql() {
        if (!this.state.sqlPreview) return;
        try {
            await navigator.clipboard.writeText(this.state.sqlPreview);
            this.notification.add("SQL copied to clipboard.", { type: "success" });
        } catch {
            this.notification.add("Unable to copy SQL to the clipboard.", { type: "warning" });
        }
    }

    async insertIntoEditor() {
        const wizardId = this.props.record.resId;
        await this.saveStepChanges();
        try {
            const action = await this.orm.call("psql.query.wizard", "action_insert_into_editor", [[wizardId]]);
            this.action.doAction(action);
        } catch (error) {
            this.notification.add(error.message || "Failed to insert SQL into editor.", { type: "danger" });
        }
    }

    cancelWizard() {
        this.action.doAction({ type: "ir.actions.act_window_close" });
    }
}

registry.category("fields").add("psql_sql_wizard_ui", {
    component: PsqlSqlWizardUi,
    supportedTypes: ["text"],
});
