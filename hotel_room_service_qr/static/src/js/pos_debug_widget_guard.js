/** @odoo-module */

import { DebugWidget } from "@point_of_sale/app/utils/debug/debug_widget";
import { patch } from "@web/core/utils/patch";

patch(DebugWidget.prototype, {
    get isDisabled() {
        return !this.pos.cashier || this.pos.cashier._role === "minimal";
    },
});
