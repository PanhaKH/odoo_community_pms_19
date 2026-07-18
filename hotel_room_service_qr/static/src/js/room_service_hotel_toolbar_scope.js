/** @odoo-module **/

import { patch } from "@web/core/utils/patch";
import { ControlPanel } from "@web/search/control_panel/control_panel";

patch(ControlPanel.prototype, {
    get isRoomServiceApp() {
        const currentApp = this.menuService?.getCurrentApp?.();
        if (currentApp?.xmlid === "hotel_room_service_qr.menu_room_service_config") {
            return true;
        }

        const model = this.env.searchModel?.resModel || "";
        if (model.startsWith("hotel.room.service")) {
            return true;
        }

        const actionId = this.env.config?.actionId || "";
        return typeof actionId === "string" && actionId.startsWith("hotel_room_service_qr.");
    },
});
