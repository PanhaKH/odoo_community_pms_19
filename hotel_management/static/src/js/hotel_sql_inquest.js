/** @odoo-module **/

import { registry } from "@web/core/registry";
import { Component, onWillStart, useState } from "@odoo/owl";
import { useService } from "@web/core/utils/hooks";

export class HotelSqlInquest extends Component {
    setup() {
        this.orm = useService("orm");
        this.action = useService("action");
        this.notification = useService("notification");

        this.state = useState({
            loading: true,
            running: false,
            query: "",
            tables: [],
            search: "",
            selectedTable: null,
            result: {
                columns: [],
                rows: [],
                row_count: 0,
            },
        });

        onWillStart(async () => {
            await this.loadTables();
            this.state.query = [
                "SELECT",
                "    schemaname,",
                "    relname AS table_name,",
                "    n_live_tup AS estimated_rows",
                "FROM pg_stat_user_tables",
                "ORDER BY schemaname, relname",
            ].join("\n");
        });
    }

    get filteredTables() {
        const term = this.state.search.trim().toLowerCase();
        if (!term) {
            return this.state.tables;
        }
        return this.state.tables.filter((table) =>
            `${table.schemaname}.${table.table_name}`.toLowerCase().includes(term)
        );
    }

    async loadTables() {
        this.state.loading = true;
        try {
            this.state.tables = await this.orm.call("hotel.sql.inquest.wizard", "list_tables", []);
        } catch (error) {
            this.notification.add(error.message || "Could not load tables.", { type: "danger" });
        } finally {
            this.state.loading = false;
        }
    }

    onQueryInput(ev) {
        this.state.query = ev.target.value;
    }

    onSearchInput(ev) {
        this.state.search = ev.target.value;
    }

    selectTable(table) {
        this.state.selectedTable = table;
    }

    useSelectedTable() {
        if (!this.state.selectedTable) {
            return;
        }
        const { schemaname, table_name } = this.state.selectedTable;
        this.state.query = `SELECT * FROM "${schemaname}"."${table_name}"`;
    }

    async previewSelectedTable(table = null) {
        if (table) {
            this.state.selectedTable = table;
        }
        if (!this.state.selectedTable) {
            return;
        }
        this.useSelectedTable();
        await this.runQuery();
    }

    async runQuery() {
        this.state.running = true;
        try {
            await this.orm.call(
                "hotel.sql.inquest.wizard",
                "execute_query",
                [this.state.query]
            );
            await this.action.doAction("hotel_management.action_hotel_sql_report_from_query", {
                additionalContext: {
                    default_sql_query: this.state.query,
                },
            });
        } catch (error) {
            this.notification.add(error.message || "Query failed.", { type: "danger", sticky: true });
        } finally {
            this.state.running = false;
        }
    }

    async addToReport() {
        try {
            await this.action.doAction("hotel_management.action_hotel_sql_report_from_query", {
                additionalContext: {
                    default_sql_query: this.state.query,
                },
            });
        } catch (error) {
            this.notification.add(error.message || "Could not add this query to reports.", {
                type: "danger",
                sticky: true,
            });
        }
    }

    clearQuery() {
        this.state.query = "";
        this.state.result = {
            columns: [],
            rows: [],
            row_count: 0,
        };
    }
}

HotelSqlInquest.template = "hotel_management.SqlInquestTemplate";
registry.category("actions").add("hotel_management.sql_inquest_action", HotelSqlInquest);

export const hotelSqlInquestClickService = {
    dependencies: ["action"],

    start(env, { action }) {
        document.addEventListener("click", (ev) => {
            const trigger = ev.target.closest && ev.target.closest(".o_hotel_sql_query_open");
            if (!trigger) {
                return;
            }
            ev.preventDefault();
            ev.stopPropagation();
            action.doAction({
                type: "ir.actions.act_window",
                name: "SQL Inquest",
                res_model: "hotel.sql.inquest.wizard",
                views: [[false, "form"]],
                target: "new",
                context: {
                    default_sql_query: trigger.dataset.query || "",
                },
            });
        });
    },
};

registry.category("services").add("hotelSqlInquestClick", hotelSqlInquestClickService);
