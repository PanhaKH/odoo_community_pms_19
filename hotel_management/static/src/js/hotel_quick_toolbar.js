/** @odoo-module **/
import { patch } from "@web/core/utils/patch";
import { ControlPanel } from "@web/search/control_panel/control_panel";
import { useService } from "@web/core/utils/hooks";
import { onWillStart, useState } from "@odoo/owl";

patch(ControlPanel.prototype, {
    setup() {
        super.setup(...arguments);
        this.actionService = useService("action");
        this.orm = useService("orm");
        this.menuService = useService("menu"); 
        this.hotelToolbarState = useState({
            canManageReservations: false,
            canUseHousekeepingTools: false,
        });
        onWillStart(async () => {
            try {
                const [canManageReservations, isHousekeeper, isSystemUser] = await Promise.all([
                    this.orm.call(
                        "hotel.reservation",
                        "user_can_manage_reservations",
                        []
                    ),
                    this.orm.call(
                        "res.users",
                        "has_group",
                        ["hotel_management.group_hotel_housekeeper"]
                    ),
                    this.orm.call(
                        "res.users",
                        "has_group",
                        ["base.group_system"]
                    ),
                ]);
                this.hotelToolbarState.canManageReservations = !!canManageReservations;
                this.hotelToolbarState.canUseHousekeepingTools = !!(isHousekeeper || isSystemUser);
            } catch (error) {
                console.warn("Reservation access check failed; using review-only toolbar.", error);
                this.hotelToolbarState.canManageReservations = false;
                this.hotelToolbarState.canUseHousekeepingTools = false;
            }
        });
    },
    
    get showHotelToolbar() {
        if (!this.hotelToolbarState.canManageReservations && !this.hotelToolbarState.canUseHousekeepingTools) {
            return false;
        }
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
        if (!this.hotelToolbarState.canManageReservations) return;
        this.actionService.doAction("hotel_management.action_hotel_express_checkin");
    },
    openDashboard() {
        if (!this.hotelToolbarState.canManageReservations) return;
        this.actionService.doAction("hotel_management.action_hotel_occupancy_client");
    },
    openReservation() {
        if (!this.hotelToolbarState.canManageReservations) return;
        this.actionService.doAction("hotel_management.action_hotel_reservation");
    },
    openRoomChart() {
        if (!this.hotelToolbarState.canManageReservations) return;
        this.actionService.doAction("hotel_management.action_hotel_tape_chart_client");
    },
    openFloorPlan() {
        if (!this.hotelToolbarState.canManageReservations) return;
        this.actionService.doAction("hotel_management.action_hotel_floor_plan");
    },
    openAvailabilityGrid() {
        if (!this.hotelToolbarState.canManageReservations) return;
        this.actionService.doAction("hotel_management.action_hotel_availability_grid_client");
    },
    openFolio() {
        if (!this.hotelToolbarState.canManageReservations) return;
        this.actionService.doAction("hotel_management.action_hotel_inhouse_guests");
    },
    openHousekeeping() {
        if (!this.hotelToolbarState.canUseHousekeepingTools) return;
        // Pointing to our brand new Mobile App action!
        this.actionService.doAction("hotel_management.action_hotel_housekeeping_mobile");
    }
});
