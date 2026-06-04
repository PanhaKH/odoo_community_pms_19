/** @odoo-module **/
import { registry } from "@web/core/registry";
import { Component, onWillStart, useState } from "@odoo/owl";
import { useService } from "@web/core/utils/hooks";

export class OccupancyComparison extends Component {
    setup() {
        this.orm = useService("orm");
        const today = new Date();
        
        // Initial State: Left = This Month, Right = Next Month
        this.state = useState({
            metric: 'occupancy_pc',
            left: {
                date: new Date(today.getFullYear(), today.getMonth(), 1),
                title: "",
                days: [],
                padding: []
            },
            right: {
                date: new Date(today.getFullYear(), today.getMonth() + 1, 1),
                title: "",
                days: [],
                padding: []
            }
        });

        onWillStart(async () => { await this.loadAllData(); });
    }

    async loadAllData() {
        await Promise.all([
            this.loadMonth('left'),
            this.loadMonth('right')
        ]);
    }

    async changeDate(side, step) {
        const current = this.state[side].date;
        // Move month by step (-1 or +1)
        const newDate = new Date(current.getFullYear(), current.getMonth() + step, 1);
        this.state[side].date = newDate;
        await this.loadMonth(side);
    }

    async loadMonth(side) {
        const targetDate = this.state[side].date;
        const year = targetDate.getFullYear();
        const month = targetDate.getMonth(); // 0-11

        // 1. Set Title
        this.state[side].title = targetDate.toLocaleDateString('en-US', { month: 'long', year: 'numeric' });

        // 2. Determine Calendar Structure
        const firstDay = new Date(year, month, 1);
        const lastDay = new Date(year, month + 1, 0);
        const startDayOfWeek = firstDay.getDay(); // 0=Sun
        const daysInMonth = lastDay.getDate();

        this.state[side].padding = Array(startDayOfWeek).fill(0);

        // 3. Fetch Data from DB using our new Python function
        const startStr = `${year}-${String(month + 1).padStart(2, '0')}-01`;
        const endStr = `${year}-${String(month + 1).padStart(2, '0')}-${String(daysInMonth).padStart(2, '0')}`;

        // THE FIX: Change searchRead to a direct model method call
        const stats = await this.orm.call(
            "hotel.dashboard",
            "get_monthly_stats",
            [startStr, endStr]
        );

        // Map data for easy lookup
        const dataMap = {};
        stats.forEach(s => dataMap[s.date] = s);

        // 4. Build Days Array
        const dayList = [];
        const metric = this.state.metric;

        for (let d = 1; d <= daysInMonth; d++) {
            const dateStr = `${year}-${String(month + 1).padStart(2, '0')}-${String(d).padStart(2, '0')}`;
            const record = dataMap[dateStr];
            
            let valDisplay = "-";
            let colorClass = "bg-white";

            if (record) {
                let val = record[metric] || 0;
                
                // Formatting & Colorful Heatmap Logic
                if (val <= 0) {
                    // Empty days are greyed out so the busy days pop!
                    valDisplay = (metric === 'occupancy_pc') ? "0%" : "$0";
                    colorClass = "bg-light text-muted"; 
                } 
                else if (metric === 'occupancy_pc') {
                    valDisplay = Math.round(val) + "%";
                    // Occupancy shifts from Blue -> Green -> Yellow -> Red based on volume
                    if (val >= 90) colorClass = "bg-danger text-white fw-bold"; 
                    else if (val >= 70) colorClass = "bg-warning text-dark fw-bold"; 
                    else if (val >= 40) colorClass = "bg-success text-white fw-bold"; 
                    else colorClass = "bg-info text-white fw-bold"; 
                } 
                else if (metric === 'adr') {
                    valDisplay = "$" + Math.round(val).toLocaleString();
                    // ADR gets a premium Deep Purple/Primary theme
                    colorClass = "bg-primary text-white fw-bold"; 
                } 
                else if (metric === 'revpar') {
                    valDisplay = "$" + Math.round(val).toLocaleString();
                    // RevPAR gets a vibrant Cyan/Teal theme
                    colorClass = "bg-info text-dark fw-bold"; 
                } 
                else if (metric === 'total_revenue') {
                    valDisplay = "$" + Math.round(val).toLocaleString();
                    // Revenue gets a "Money Green" theme. 
                    // (You can adjust the 500 threshold to match your hotel's daily targets!)
                    if (val >= 500) {
                        colorClass = "bg-success text-white fw-bold"; 
                    } else {
                        colorClass = "bg-success bg-opacity-75 text-white fw-bold"; 
                    }
                }
            }

            dayList.push({
                dayNum: d,
                date: dateStr,
                valueDisplay: valDisplay,
                colorClass: colorClass
            });
        }
        this.state[side].days = dayList;
    }
}

OccupancyComparison.template = "hotel_management.OccupancyComparisonTemplate";
registry.category("actions").add("hotel_management.occupancy_view_action", OccupancyComparison);