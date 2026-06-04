/** @odoo-module **/
import { patch } from "@web/core/utils/patch";
import { ControlPanel } from "@web/search/control_panel/control_panel";
import { useService } from "@web/core/utils/hooks";

patch(ControlPanel.prototype, {
    setup() {
        super.setup(...arguments);
        this.actionService = useService("action");
        this.menuService = useService("menu"); 
    },
    
    get showHotelToolbar() {
        const currentApp = this.menuService.getCurrentApp();
        if (currentApp && currentApp.xmlid === 'hotel_management.menu_hotel_root') {
            return true;
        }
        const model = this.env.searchModel ? this.env.searchModel.resModel : '';
        if (model && model.includes('hotel')) {
            return true;
        }
        return false;
    },

    // ... existing showHotelToolbar block ...

    // NEW: Detect if we are inside the standalone Housekeeping app
    get isHousekeepingApp() {
        const currentApp = this.menuService.getCurrentApp();
        if (currentApp && currentApp.xmlid === 'hotel_housekeeping_app.menu_housekeeping_app_root') {
            return true;
        }
        return false;
    },

    // --- YOUR NEW COMMAND CENTER FUNCTIONS ---
    
    openExpressCheckin() {
        this.actionService.doAction("hotel_management.action_hotel_express_checkin");
    },
    openDashboard() {
        this.actionService.doAction("hotel_management.action_hotel_occupancy_client");
    },
    openReservation() {
        this.actionService.doAction("hotel_management.action_hotel_reservation");
    },
    openRoomChart() {
        this.actionService.doAction("hotel_management.action_hotel_tape_chart_client");
    },
    openFloorPlan() {
        this.actionService.doAction("hotel_management.action_hotel_floor_plan_kanban");
    },
    openAvailabilityGrid() {
        this.actionService.doAction("hotel_management.action_hotel_availability_grid_client");
    },
    openFolio() {
        this.actionService.doAction("hotel_management.action_hotel_inhouse_guests");
    },
    openHousekeeping() {
        // Pointing to our brand new Mobile App action!
        this.actionService.doAction("hotel_management.action_hotel_housekeeping_mobile");
    }
});