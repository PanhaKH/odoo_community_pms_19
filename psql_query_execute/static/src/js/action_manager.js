/** @odoo-module **/

import { registry } from "@web/core/registry";
import { download } from "@web/core/network/download";

// Keep the module's original XLSX report type, but use Odoo 19's supported
// download API and replace any older third-party handler safely.
registry.category("ir.actions.report handlers").add(
    "xlsx",
    async (action) => {
        if (action.report_type !== "xlsx") {
            return false;
        }
        await download({ url: "/xlsx_reports", data: action.data });
        return true;
    },
    { force: true }
);
