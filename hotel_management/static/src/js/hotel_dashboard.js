/** @odoo-module **/

import { registry } from "@web/core/registry";
import { Component, onWillStart, useState } from "@odoo/owl";
import { useService } from "@web/core/utils/hooks";

export class HotelDashboard extends Component {
    setup() {
        this.orm = useService("orm");
        this.action = useService("action");
        
        this.state = useState({
            stats: {
                total: 0,
                available: 0,
                occupied: 0,
                dirty: 0,
                maintenance: 0,
            }
        });

        onWillStart(async () => {
            await this.loadStats();
        });
    }

    async loadStats() {
        // Fetch ALL rooms to calculate counts locally
        const rooms = await this.orm.searchRead("hotel.room", [], ["state"]);
        
        this.state.stats = {
            total: rooms.length,
            available: rooms.filter(r => ['available', 'vacant_clean'].includes(r.state)).length,
            occupied: rooms.filter(r => ['occupied_clean', 'occupied_dirty'].includes(r.state)).length,
            dirty: rooms.filter(r => r.state === 'vacant_dirty').length,
            maintenance: rooms.filter(r => r.state === 'maintenance').length,
        };
    }

    viewRooms(filterType) {
        let domain = [];
        let name = "Rooms";
        let resModel = 'hotel.room'; // Default to viewing Rooms
        let viewMode = 'list,form';

        if (filterType === 'available') {
            // View: Room Inventory (Ready to Sell)
            domain = [['state', 'in', ['available', 'vacant_clean']]];
            name = "Available Rooms";
            resModel = 'hotel.room';
        } 
        else if (filterType === 'occupied') {
            // *** CHANGE: View In-House RESERVATIONS instead of Room records ***
            domain = [['state', '=', 'checkin']];
            name = "In-House Guests";
            resModel = 'hotel.reservation';
        } 
        else if (filterType === 'dirty') {
            // View: Housekeeping List
            domain = [['state', '=', 'vacant_dirty']];
            name = "Housekeeping Needed (Dirty)";
            resModel = 'hotel.room';
        } 
        else if (filterType === 'maintenance') {
            domain = [['state', '=', 'maintenance']];
            name = "Under Maintenance";
            resModel = 'hotel.room';
        }
        else {
            // All Rooms
            name = "All Rooms";
            resModel = 'hotel.room';
        }

        this.action.doAction({
            type: 'ir.actions.act_window',
            name: name,
            res_model: resModel,
            view_mode: viewMode,
            views: [[false, 'list'], [false, 'form']],
            domain: domain,
            target: 'current',
        });
    }
}

HotelDashboard.template = "hotel_management.DashboardTemplate";
registry.category("actions").add("hotel_management.dashboard_client_action", HotelDashboard);
