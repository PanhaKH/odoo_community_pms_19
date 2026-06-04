/** @odoo-module **/
import { registry } from "@web/core/registry";
import { Component, onWillStart, useState } from "@odoo/owl";
import { useService } from "@web/core/utils/hooks";

export class HotelAvailabilityGrid extends Component {
    setup() {
        this.orm = useService("orm");
        this.action = useService("action"); 
        
        const today = new Date();
        const offset = today.getTimezoneOffset() * 60000;
        const localDate = new Date(today.getTime() - offset);

        this.state = useState({
            startDate: localDate.toISOString().split('T')[0],
            isDateInitialized: false, 
            days: 14,
            loading: true,
            data: null,
            viewMode: 'availability', 
            ratesList: [], 
            selectedRateName: 'Show Rates' // We only need the Name now!
        });

        this.onCellClick = this.onCellClick.bind(this);
        this.moveDate = this.moveDate.bind(this);
        this.loadData = this.loadData.bind(this);
        this.toggleView = this.toggleView.bind(this);
        
        this.onDateChange = this.onDateChange.bind(this);
        onWillStart(async () => { await this.loadData(); });
    }

    // UPGRADED: Now it only passes the Name string!
    toggleView(mode, rateName = 'Show Rates') {
        this.state.viewMode = mode;
        if (rateName !== 'Show Rates') {
            this.state.selectedRateName = rateName;
        }
    }

    async loadData() {
        this.state.loading = true;
        try {
            if (!this.state.isDateInitialized) {
                const company = await this.orm.searchRead("res.company", [], ["hotel_business_date"], { limit: 1 });
                if (company && company.length > 0 && company[0].hotel_business_date) {
                    this.state.startDate = company[0].hotel_business_date;
                }
                this.state.isDateInitialized = true;
            }

            // THE FIX: Fetch all rates, but extract ONLY the unique names to remove duplicates!
            if (this.state.ratesList.length === 0) {
                const allRates = await this.orm.searchRead("hotel.rate.plan", [["active", "=", true]], ["name"]);
                // This magic Javascript line removes all duplicates!
                const uniqueNames = [...new Set(allRates.map(r => r.name))]; 
                this.state.ratesList = uniqueNames; 
            }

            const result = await this.orm.call("hotel.reservation", "get_availability_matrix", [this.state.startDate, this.state.days]);
            this.state.data = result;
        } catch (e) {
            console.error("Availability Grid Error:", e);
        } finally {
            this.state.loading = false;
        }
    }

    onCellClick(roomTypeId, dateStr) {
        const checkinDate = new Date(`${dateStr}T00:00:00`);
        const checkoutDate = new Date(checkinDate);
        checkoutDate.setDate(checkinDate.getDate() + 1);

        // 1. Find the ID of the currently selected rate plan!
        let ratePlanId = false;
        if (this.state.viewMode === 'rates' && this.state.selectedRateName !== 'Show Rates') {
            const firstRoom = this.state.data.room_types[0];
            if (firstRoom && firstRoom.rates) {
                const matchingRate = firstRoom.rates.find(r => r.name === this.state.selectedRateName);
                if (matchingRate && matchingRate.id !== 999) {
                    ratePlanId = matchingRate.id;
                }
            }
        }

        // 2. Open the form and pass ALL the defaults
        this.action.doAction({
            type: 'ir.actions.act_window',
            res_model: 'hotel.reservation',
            views: [[false, 'form']],
            target: 'new', 
            context: {
                default_room_type_id: roomTypeId,
                default_checkin_date: dateStr,
                default_checkout_date: checkoutDate.toISOString().split('T')[0],
                default_rate_plan_id: ratePlanId, // <-- BOOM! Passes the Rate Plan directly!
            }
        });
    }

    async moveDate(days) {
        if (days === 0) {
            this.state.loading = true;
            const company = await this.orm.searchRead("res.company", [], ["hotel_business_date"], { limit: 1 });
            if (company && company.length > 0 && company[0].hotel_business_date) {
                this.state.startDate = company[0].hotel_business_date;
            }
        } else {
            let current = new Date(this.state.startDate);
            current.setDate(current.getDate() + days);
            this.state.startDate = current.toISOString().split('T')[0];
        }
        await this.loadData();
    }
    async onDateChange(ev) {
        this.state.startDate = ev.target.value;
        await this.loadData();
    }
}

HotelAvailabilityGrid.template = "hotel_management.AvailabilityGridTemplate";
registry.category("actions").add("hotel_management.availability_grid_view", HotelAvailabilityGrid);
