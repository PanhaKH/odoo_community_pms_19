/** @odoo-module **/
import { registry } from "@web/core/registry";
import { Component, onWillStart, useState } from "@odoo/owl";
import { useService } from "@web/core/utils/hooks";

export class HotelOccupancyView extends Component {
    setup() {
        this.orm = useService("orm");
        const today = new Date();
        
        this.state = useState({
            currentYear: today.getFullYear(),
            currentMonth: today.getMonth(), // 0-indexed (0 = Jan)
            currentMonthName: "",
            metric: 'occupancy', // Default filter
            loading: true,
            calendarPadding: [],
            calendarDays: []
        });

        onWillStart(async () => { await this.loadData(); });
    }

    async loadData() {
        this.state.loading = true;
        try {
            // 1. Calculate Date Range for the View
            const year = this.state.currentYear;
            const month = this.state.currentMonth;
            
            // First day of month
            const firstDay = new Date(year, month, 1);
            // Last day of month
            const lastDay = new Date(year, month + 1, 0);
            
            // Update Header Title
            this.state.currentMonthName = firstDay.toLocaleDateString('en-US', { month: 'long' });

            // 2. Fetch Stats from Python
            // We fetch the whole month's data at once
            const startStr = firstDay.toISOString().split('T')[0];
            const endStr = lastDay.toISOString().split('T')[0];
            
            const stats = await this.orm.searchRead(
                "hotel.daily.stats",
                [['date', '>=', startStr], ['date', '<=', endStr]],
                ['date', 'occupancy_pc', 'adr', 'revpar']
            );
            
            // Map stats by date for easy lookup
            const statsMap = {};
            stats.forEach(s => statsMap[s.date] = s);

            // 3. Build Grid Data
            
            // Padding: How many empty boxes before the 1st of the month?
            // getDay(): 0=Sun, 1=Mon ...
            const startDayOfWeek = firstDay.getDay(); 
            this.state.calendarPadding = Array(startDayOfWeek).fill(0);

            // Days: 1 to 31
            const daysInMonth = lastDay.getDate();
            const dayList = [];

            for (let d = 1; d <= daysInMonth; d++) {
                // Construct date string YYYY-MM-DD
                // Note: manual formatting prevents timezone issues
                const dateStr = `${year}-${String(month + 1).padStart(2, '0')}-${String(d).padStart(2, '0')}`;
                
                const dayStat = statsMap[dateStr];
                let displayVal = "-";
                let colorClass = "hotel-occ-none";
                let rawVal = 0;

                if (dayStat) {
                    if (this.state.metric === 'occupancy') {
                        rawVal = dayStat.occupancy_pc;
                        displayVal = Math.round(rawVal) + "%";
                        // Color Logic matching your picture
                        if (rawVal >= 90) colorClass = "hotel-occ-high"; // Red
                        else if (rawVal >= 70) colorClass = "hotel-occ-med-high"; // Yellow
                        else if (rawVal >= 50) colorClass = "hotel-occ-med"; // Green
                        else colorClass = "hotel-occ-low"; // Blue
                    } 
                    else if (this.state.metric === 'adr') {
                        rawVal = dayStat.adr;
                        displayVal = "$" + Math.round(rawVal);
                        if (rawVal > 0) colorClass = "hotel-occ-low"; // Simple Blue for ADR
                    }
                    else if (this.state.metric === 'revpar') {
                        rawVal = dayStat.revpar;
                        displayVal = "$" + Math.round(rawVal);
                        if (rawVal > 0) colorClass = "hotel-occ-med-high";
                    }
                }

                dayList.push({
                    dayNum: d,
                    dateStr: dateStr,
                    value: displayVal,
                    colorClass: colorClass
                });
            }
            this.state.calendarDays = dayList;

        } catch (e) {
            console.error("Error loading occupancy:", e);
        } finally {
            this.state.loading = false;
        }
    }

    changeMonth(step) {
        let newMonth = this.state.currentMonth + step;
        let newYear = this.state.currentYear;
        
        if (newMonth > 11) { newMonth = 0; newYear++; }
        else if (newMonth < 0) { newMonth = 11; newYear--; }
        
        this.state.currentMonth = newMonth;
        this.state.currentYear = newYear;
        this.loadData();
    }
}

HotelOccupancyView.template = "hotel_management.OccupancyViewTemplate";
registry.category("actions").add("hotel_management.occupancy_view_action", HotelOccupancyView);