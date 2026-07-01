/** @odoo-module **/
import { _t } from "@web/core/l10n/translation";
import { registry } from "@web/core/registry";
import { AlertDialog, ConfirmationDialog } from "@web/core/confirmation_dialog/confirmation_dialog";
import { escape } from "@web/core/utils/strings";
import { Component, onWillStart, useState, xml } from "@odoo/owl";
import { useService } from "@web/core/utils/hooks";
import { markup } from "@odoo/owl";

export class HotelTapeChart extends Component {
    setup() {
        this.orm = useService("orm");
        this.action = useService("action");
        this.dialogService = useService("dialog");
        this.notification = useService("notification");
        this.state = useState({
            startDate: '',
            isDateInitialized: false, 
            businessDateStr: '', // Will be set from hotel business date on load
            days: 30, loading: true, rooms: [], bookings: [], months: [], dates: [],
            occ_include: [], occ_ignore: [], currentOccupancyRow: [], oooMode: 'ignore',
            availableRow: [], bookedRow: [], capacityRow: [],
            dragReservationId: null, dragTargetRoomId: null, dragTargetDateStr: null,
            canManageReservations: false,
        });

        this.moveDate = this.moveDate.bind(this);
        this.loadData = this.loadData.bind(this);
        this.setOOOMode = this.setOOOMode.bind(this);
        this.resetToBusinessDate = this.resetToBusinessDate.bind(this);
        
        onWillStart(async () => { await this.loadData(); });
    }
    async loadBusinessDate() {
        const businessDate = await this.orm.call(
            "hotel.reservation",
            "get_hotel_business_date_for_ui",
            []
        );
        if (businessDate) {
            this.state.startDate = businessDate;
            this.state.businessDateStr = businessDate;
            return true;
        }
        return false;
    }

    async loadReservationAccess() {
        try {
            this.state.canManageReservations = !!await this.orm.call(
                "hotel.reservation",
                "user_can_manage_reservations",
                []
            );
        } catch (error) {
            console.warn("Reservation access check failed; using review-only mode.", error);
            this.state.canManageReservations = false;
        }
    }

    // NEW: Forces the chart back to the official Audit Date
    async resetToBusinessDate() {
        this.state.loading = true;
        await this.loadBusinessDate();
        await this.loadData();
    }

    async loadData() {
        this.state.loading = true;
        try {
            // --- Sync with Hotel Business Date on first load ---
            if (!this.state.isDateInitialized) {
                const loadedBusinessDate = await this.loadBusinessDate();
                if (!loadedBusinessDate) {
                    const now = new Date();
                    const fallback = new Date(now.getTime() - now.getTimezoneOffset() * 60000).toISOString().split('T')[0];
                    this.state.startDate = fallback;
                    this.state.businessDateStr = fallback;
                }
                this.state.isDateInitialized = true;
            }
            await this.loadReservationAccess();

            // 1. DATES
            let start = new Date(this.state.startDate);
            let end = new Date(start);
            end.setDate(start.getDate() + this.state.days);
            
            // THE FIX: 'Today' is now based on the Audit Date, not the physical clock!
            const todayStr = this.state.businessDateStr;
            
            let newDates = [], newMonths = [], currentMonth = null, monthColspan = 0;
            for(let i=0; i < this.state.days; i++) {
                let d = new Date(start); d.setDate(start.getDate() + i);
                let dateStr = d.toISOString().split('T')[0];
                let monthLabel = d.toLocaleDateString('en-US', { month: 'short', year: 'numeric' });
                if (monthLabel !== currentMonth) {
                    if (currentMonth) newMonths.push({ name: currentMonth, colspan: monthColspan * 2 });
                    currentMonth = monthLabel; monthColspan = 0;
                }
                monthColspan++;
                
                // isToday determines where the blue highlight goes!
                newDates.push({ 
                    full: dateStr, 
                    day: d.getDate(), 
                    weekday: d.toLocaleDateString('en-US', { weekday: 'narrow' }), 
                    isWeekend: (d.getDay()===0 || d.getDay()===6), 
                    isToday: (dateStr === todayStr) 
                });
            }
            if (currentMonth) newMonths.push({ name: currentMonth, colspan: monthColspan * 2 });
            this.state.dates = newDates; this.state.months = newMonths;

            // 2. ROOMS
            const roomTypes = await this.orm.searchRead("hotel.room.type", [], ['id', 'code', 'name']);
            const typeMap = {}; (roomTypes || []).forEach(t => { typeMap[t.id] = t.code || t.name.substring(0, 4).toUpperCase(); });
            const rooms = await this.orm.searchRead("hotel.room", [], ['id', 'name', 'room_type_id', 'state', 'is_occupied', 'is_blocked_today'], { order: 'room_type_id asc, name asc' });
            (rooms || []).forEach(r => {
                r.type_code = r.room_type_id ? (typeMap[r.room_type_id[0]] || '') : '';
                if (r.is_blocked_today || r.state === 'blocked') { r.status_icon = 'fa-ban'; r.status_color = 'text-danger'; }
                else if (r.is_occupied || r.state.includes('occupied')) { r.status_icon = 'fa-suitcase'; r.status_color = 'text-info'; }
                else if (r.state === 'vacant_clean') { r.status_icon = 'fa-diamond'; r.status_color = 'text-success'; }
                else { r.status_icon = 'fa-diamond'; r.status_color = 'text-warning'; }
            });
            this.state.rooms = rooms || [];

            // 3. BOOKINGS
            const domain = [['checkin_date', '<=', end.toISOString().split('T')[0]], ['checkout_date', '>=', this.state.startDate], ['state', 'not in', ['cancel', 'noshow']], ['is_desk_folio', '=', false]];
            let bookings = await this.orm.searchRead("hotel.reservation", domain, ['id', 'name', 'room_id', 'partner_id', 'checkin_date', 'checkout_date', 'state']);
            const blockDomain = [['date_from', '<=', end.toISOString().split('T')[0]], ['date_to', '>=', this.state.startDate], ['state', '=', 'active']];
            const roomBlocks = await this.orm.searchRead("hotel.room.block", blockDomain, ['id', 'room_id', 'date_from', 'date_to', 'name']);
            bookings = (bookings || []).concat((roomBlocks || []).map((block) => ({
                id: `room_block_${block.id}`,
                res_id: block.id,
                res_model: "hotel.room.block",
                room_id: block.room_id,
                partner_id: false,
                checkin_date: block.date_from,
                checkout_date: block.date_to,
                state: "blocked",
                name: block.name,
            })));
            const statusPriority = { 'checkin': 1, 'confirm': 2, 'blocked': 3, 'draft': 4, 'checkout': 5 };
            bookings.sort((a, b) => { return (statusPriority[a.state] || 99) - (statusPriority[b.state] || 99); });
            
            // Calculate Total Duration
            bookings.forEach(b => {
                let startD = new Date(b.checkin_date);
                let endD = new Date(b.checkout_date);
                let diffTime = Math.abs(endD - startD);
                b.total_duration = Math.ceil(diffTime / (1000 * 60 * 60 * 24)); 
                if(b.total_duration < 1) b.total_duration = 1;
            });
            this.state.bookings = bookings || [];

            // 4. OCCUPANCY & TOTALS
            const stats = await this.orm.call("hotel.reservation", "get_availability_matrix", [this.state.startDate, this.state.days]);
            this.state.occ_include = stats ? (stats.occ_include || []) : [];
            this.state.occ_ignore = stats ? (stats.occ_ignore || []) : [];
            this.state.availableRow = stats ? (stats.totals || []) : [];
            this.state.bookedRow = stats ? (stats.booked_totals || []) : [];
            this.state.capacityRow = stats ? (stats.capacity_totals || []) : [];
            this.updateOccupancyRow();

        } catch (e) { console.error(e); } finally { this.state.loading = false; }
    }

    setOOOMode(mode) { this.state.oooMode = mode; this.updateOccupancyRow(); }
    updateOccupancyRow() { this.state.currentOccupancyRow = (this.state.oooMode === 'include') ? this.state.occ_include : this.state.occ_ignore; }

    isRoomMoveDraggable(booking) {
        return !!booking && this.state.canManageReservations && ['draft', 'confirm', 'checkin', 'checkout_hold'].includes(booking.state);
    }

    clearRoomMoveDragState() {
        this.state.dragReservationId = null;
        this.state.dragTargetRoomId = null;
        this.state.dragTargetDateStr = null;
    }

    onBookingDragStart(ev, booking) {
        if (!this.isRoomMoveDraggable(booking)) {
            ev.preventDefault();
            return;
        }
        this.state.dragReservationId = booking.id;
        this.state.dragTargetRoomId = null;
        this.state.dragTargetDateStr = null;
        ev.dataTransfer.effectAllowed = "move";
        ev.dataTransfer.setData("text/plain", String(booking.id));
    }

    onBookingDragEnd() {
        this.clearRoomMoveDragState();
    }

    onRoomCellDragOver(ev, roomId, dateStr) {
        if (!this.state.dragReservationId) {
            return;
        }
        ev.preventDefault();
        ev.dataTransfer.dropEffect = "move";
        this.state.dragTargetRoomId = roomId;
        this.state.dragTargetDateStr = dateStr;
    }

    async onRoomCellDrop(ev, roomId, dateStr) {
        if (!this.state.dragReservationId) {
            return;
        }
        ev.preventDefault();
        const draggedBooking = (this.state.bookings || []).find((booking) => booking.id === this.state.dragReservationId);
        this.clearRoomMoveDragState();
        if (!draggedBooking) {
            return;
        }
        const sameRoom = draggedBooking.room_id && draggedBooking.room_id[0] === roomId;
        const sameDate = draggedBooking.checkin_date === dateStr;
        if (sameRoom && sameDate) {
            return;
        }
        await this.openRoomMoveConfirmation(draggedBooking, roomId, dateStr);
    }

    getRoomMoveErrorMessage(error) {
        return (
            error?.data?.data?.message ||
            error?.data?.message ||
            error?.message ||
            _t("The selected room could not be used for this move.")
        );
    }

    showRoomMoveError(error) {
        this.dialogService.add(AlertDialog, {
            title: _t("Room Move Not Allowed"),
            body: this.getRoomMoveErrorMessage(error),
        });
    }

    async openRoomMoveConfirmation(booking, targetRoomId, targetDateStr) {
        const targetRoom = (this.state.rooms || []).find((room) => room.id === targetRoomId);
        if (!targetRoom) {
            return;
        }
        try {
            const preview = await this.orm.call(
                "hotel.reservation",
                "get_room_chart_drag_preview",
                [[booking.id], targetRoomId, targetDateStr]
            );
            const dateSummary = preview.dates_changed
                ? `<div class="mt-2">${escape(preview.old_checkin_date)} &rarr; ${escape(preview.old_checkout_date)}<br/><span class="text-primary">${escape(preview.new_checkin_date)} &rarr; ${escape(preview.new_checkout_date)}</span></div>`
                : `<div class="text-muted">${escape(preview.new_checkin_date)} &rarr; ${escape(preview.new_checkout_date)}</div>`;
            this.dialogService.add(ConfirmationDialog, {
                title: preview.mode === "reservation_move" ? _t("Confirm Reservation Move") : _t("Confirm Room Move"),
                body: markup(`
                    <div><strong>${escape(preview.guest_name || preview.reservation_name || "Guest")}</strong></div>
                    <div class="mt-2">${escape(preview.old_room_name)} &rarr; ${escape(preview.new_room_name)}</div>
                    ${dateSummary}
                    <div class="text-muted mt-2">${escape(preview.summary_note || "")}</div>
                `),
                confirmLabel: preview.mode === "reservation_move" ? _t("Move Reservation") : _t("Move Room"),
                confirmClass: "btn-primary",
                confirm: async () => {
                    try {
                        await this.orm.call("hotel.reservation", "action_room_chart_drag_drop", [[booking.id], targetRoomId, targetDateStr]);
                        this.notification.add(
                            preview.mode === "reservation_move" ? _t("Reservation move saved.") : _t("Room move saved."),
                            { type: "success" }
                        );
                        await this.loadData();
                    } catch (error) {
                        this.showRoomMoveError(error);
                    }
                },
                cancel: () => {},
            });
        } catch (error) {
            this.showRoomMoveError(error);
        }
    }
    
    getBookingBar(roomId, dateStr, halfDay = 'pm') {
        let isFirstCol = (dateStr === this.state.startDate);
        for (const b of (this.state.bookings || [])) {
            if (b.room_id[0] !== roomId) continue;
            if (halfDay === 'pm' && b.checkin_date === dateStr) {
                return {
                    ...b,
                    visual_slots: Math.max(1, b.total_duration * 2),
                    is_continuation: false,
                };
            }
            const isDueOutStillInHouse = ['checkin', 'checkout_hold'].includes(b.state) && b.checkout_date >= dateStr;
            if (halfDay === 'am' && isFirstCol && b.checkin_date < dateStr && (b.checkout_date > dateStr || isDueOutStillInHouse)) {
                let startChart = new Date(dateStr);
                let endBooking = new Date(b.checkout_date);
                let diffDays = Math.round((endBooking - startChart) / (1000 * 60 * 60 * 24));
                let visualSlots = Math.max(1, (diffDays * 2) + 1);
                return {
                    ...b,
                    visual_slots: visualSlots,
                    is_continuation: true,
                };
            }
        }
        return null;
    }

    getBookingColor(state) {
        const colors = { 'confirm': 'bg-success', 'checkin': 'bg-info', 'checkout': 'bg-warning', 'blocked': 'bg-dark' };
        return colors[state] || 'bg-secondary';
    }

    showReviewOnlyDialog(booking) {
        const guestName = booking.partner_id ? booking.partner_id[1] : (booking.name || _t("Room Block"));
        const roomName = booking.room_id ? booking.room_id[1] : _t("Unassigned");
        this.dialogService.add(AlertDialog, {
            title: _t("Reservation Review Only"),
            body: markup(`
                <div><strong>${escape(guestName || "")}</strong></div>
                <div class="mt-2">${escape(booking.name || "")}</div>
                <div>${escape(roomName || "")}</div>
                <div>${escape(booking.checkin_date || "")} &rarr; ${escape(booking.checkout_date || "")}</div>
                <div class="text-muted mt-2">${escape(_t("Housekeeping users can review reservations only and cannot move or modify bookings."))}</div>
            `),
        });
    }

    onCellClick(booking) {
        if (!this.state.canManageReservations) {
            this.showReviewOnlyDialog(booking);
            return;
        }
        this.action.doAction({
            type: 'ir.actions.act_window',
            res_model: booking.res_model || 'hotel.reservation',
            res_id: booking.res_id || booking.id,
            views: [[false, 'form']],
            target: 'new',
        });
    }
    onEmptyCellClick(roomId, dateStr) {
        if (!this.state.canManageReservations) {
            this.dialogService.add(AlertDialog, {
                title: _t("Reservation Review Only"),
                body: _t("Housekeeping users can review reservations only and cannot move or modify bookings."),
            });
            return;
        }
        const clickedDate = new Date(dateStr);
        const checkoutDate = new Date(clickedDate);
        checkoutDate.setDate(clickedDate.getDate() + 1);

        const room = this.state.rooms.find(r => r.id === roomId);
        const roomTypeId = room && room.room_type_id ? room.room_type_id[0] : false;

        this.action.doAction({
            type: 'ir.actions.act_window',
            res_model: 'hotel.reservation',
            views: [[false, 'form']],
            target: 'new',
            context: {
                default_room_id: roomId,
                default_room_type_id: roomTypeId,
                default_checkin_date: dateStr,
                default_checkout_date: checkoutDate.toISOString().split('T')[0],
            }
        });
    }
    moveDate(days) {
        let current = new Date(this.state.startDate); current.setDate(current.getDate() + days);
        this.state.startDate = current.toISOString().split('T')[0]; this.loadData();
    }
}

HotelTapeChart.template = xml`
    <div class="o_tape_chart_container h-100 d-flex flex-column">
        <style>
            .chart-table { border-collapse: collapse !important; background-color: white; width: 100%; table-layout: fixed; }
            .cell-pm, .header-day, .footer-day { border-right: 2px solid #777 !important; }
            .cell-am { border-right: 1px dotted #ccc !important; }
            .chart-table tr td { border-bottom: 1px solid #999 !important; height: 35px !important; vertical-align: top; padding: 0 !important; position: relative; }
            .bg-weekday { background-color: #e1f5fe !important; }
            .bg-weekend { background-color: #ffe0b2 !important; }
            .bg-today { background-color: #81d4fa !important; }
            .bg-header-base { background-color: #eee; color: #333; }
            .header-day { border-bottom: 2px solid #555; vertical-align: middle; }

            .booking-bar-float {
                position: absolute; top: 5px; left: 2px; height: 24px; z-index: 100;
                display: flex; align-items: center; padding-left: 5px;
                font-size: 11px; font-weight: bold; color: white;
                box-shadow: 2px 2px 4px rgba(0,0,0,0.4); cursor: pointer;
                white-space: nowrap; overflow: hidden; text-overflow: ellipsis; border-radius: 2px;
            }
            .booking-bar-float:hover { z-index: 101; box-shadow: 3px 3px 5px rgba(0,0,0,0.6); }
            .booking-draggable { cursor: grab; }
            .drag-target-room { box-shadow: inset 0 0 0 2px rgba(13, 110, 253, 0.25); }
            .drag-target-cell { box-shadow: inset 0 0 0 2px rgba(13, 110, 253, 0.65); }
            
            .shape-arrow { clip-path: polygon(0% 0%, 98% 0%, 100% 50%, 98% 100%, 0% 100%); }
            .shape-continuation { clip-path: polygon(0% 0%, 98% 0%, 100% 50%, 98% 100%, 0% 100%); border-left: 0 !important; border-top-left-radius: 0; border-bottom-left-radius: 0; left: 0 !important; }
            .shape-block { clip-path: none; border-radius: 3px; }
            .legend-badge { width: 12px; height: 12px; display: inline-block; margin-right: 5px; border-radius: 2px; }
        </style>

        <div class="d-flex justify-content-between align-items-center p-2 shadow-sm" style="z-index: 100; background: #fff; border-bottom: 1px solid #ddd;">
            <div class="d-flex align-items-center">
                <h3 class="m-0 text-primary me-4">Room Chart</h3>
                
                <div class="tape-legend ms-2 d-flex align-items-center border-end pe-3">
                    <span class="me-2 text-muted small font-weight-bold">ROOMS:</span>
                    <div class="legend-item me-2 small"><i class="fa fa-diamond text-success"/> VC</div>
                    <div class="legend-item me-2 small"><i class="fa fa-diamond text-warning"/> VD</div>
                    <div class="legend-item me-2 small"><i class="fa fa-suitcase text-info"/> OC</div>
                    <div class="legend-item small"><i class="fa fa-ban text-danger"/> OOO</div>
                </div>

                <div class="tape-legend ms-3 d-flex align-items-center">
                    <span class="me-2 text-muted small font-weight-bold">BOOKINGS:</span>
                    <div class="legend-item me-3 small d-flex align-items-center"><span class="legend-badge bg-secondary"/> Draft</div>
                    <div class="legend-item me-3 small d-flex align-items-center"><span class="legend-badge bg-success"/> Confirmed</div>
                    <div class="legend-item me-3 small d-flex align-items-center"><span class="legend-badge bg-info"/> In-House</div>
                    <div class="legend-item me-3 small d-flex align-items-center"><span class="legend-badge bg-dark"/> Blocked</div>
                </div>

                <div class="ms-auto btn-group btn-group-sm">
                    <input type="radio" class="btn-check" id="btn_ooo_ignore" t-att-checked="state.oooMode === 'ignore'" t-on-change="() => this.setOOOMode('ignore')"/>
                    <label class="btn btn-outline-secondary" for="btn_ooo_ignore">Ignore OOO</label>
                    <input type="radio" class="btn-check" id="btn_ooo_include" t-att-checked="state.oooMode === 'include'" t-on-change="() => this.setOOOMode('include')"/>
                    <label class="btn btn-outline-secondary" for="btn_ooo_include">Include OOO</label>
                </div>
            </div>
            <div class="btn-group ms-2">
                <button class="btn btn-outline-secondary" t-on-click="() => this.moveDate(-7)"> &lt; Prev </button>
                <button class="btn btn-primary" t-on-click="resetToBusinessDate"> Business Date / Refresh </button>
                <button class="btn btn-outline-secondary" t-on-click="() => this.moveDate(7)"> Next &gt; </button>
            </div>
        </div>

        <div style="flex: 1; overflow: auto; position: relative;">
            <t t-if="state.loading">
                <div class="d-flex justify-content-center align-items-center h-100"><i class="fa fa-circle-o-notch fa-spin fa-3x text-primary"></i></div>
            </t>
            <t t-else="">
                <table class="table chart-table mb-0">
                    <thead>
                        <tr>
                            <th class="sticky-corner bg-header-base" style="width: 160px; border-right: 2px solid #555; border-bottom: 2px solid #555;">ROOM</th>
                            <t t-foreach="state.months || []" t-as="month" t-key="month.name">
                                <th t-att-colspan="month.colspan" class="text-center font-weight-bold text-white border-left" style="background-color: #444; border-right: 2px solid #777;"><t t-esc="month.name"/></th>
                            </t>
                        </tr>
                        <tr>
                            <th class="sticky-room-col bg-header-base" style="top: 35px; z-index: 20; border-right: 2px solid #555;"></th>
                            <t t-foreach="state.dates || []" t-as="date" t-key="date.full">
                                <t t-set="h_bg" t-value="date.isToday ? 'bg-today' : (date.isWeekend ? 'bg-weekend' : 'bg-header-base')"/>
                                <th colspan="2" t-att-class="'header-day ' + h_bg" style="top: 35px; height: 40px;">
                                    <div class="text-center small font-weight-bold"><t t-esc="date.weekday"/> <br/> <span style="font-size: 1.2em;"><t t-esc="date.day"/></span></div>
                                </th>
                            </t>
                        </tr>
                    </thead>
                    <tbody>
                        <t t-foreach="state.rooms || []" t-as="room" t-key="room.id">
                            <tr>
                                <td t-att-class="'sticky-room-col bg-light'"
                                    style="border-right: 2px solid #555;">
                                    <div class="d-flex align-items-center justify-content-between px-2 h-100">
                                        <div class="d-flex align-items-center" style="white-space: nowrap; overflow: hidden;">
                                            <i t-attf-class="fa #{room.status_icon} #{room.status_color} me-2" style="font-size: 1.2em;"/>
                                            <span class="font-weight-bold text-dark text-truncate"><t t-esc="room.name"/></span>
                                        </div>
                                        <span class="badge bg-secondary ms-1" style="font-size: 0.7em;"><t t-esc="room.type_code"/></span>
                                    </div>
                                </td>
                                <t t-foreach="state.dates || []" t-as="date" t-key="date.full">
                                    <t t-set="col_bg" t-value="date.isToday ? 'bg-today' : (date.isWeekend ? 'bg-weekend' : 'bg-weekday')"/>
                                    
                                    <td t-att-class="'cell-am ' + col_bg + (state.dragTargetRoomId === room.id &amp;&amp; state.dragTargetDateStr === date.full ? ' drag-target-cell' : '')"
                                        t-on-click="() => this.onEmptyCellClick(room.id, date.full)"
                                        t-on-dragover="(ev) => this.onRoomCellDragOver(ev, room.id, date.full)"
                                        t-on-drop.stop="(ev) => this.onRoomCellDrop(ev, room.id, date.full)">
                                        <t t-set="bookingAm" t-value="this.getBookingBar(room.id, date.full, 'am')"/>
                                        <t t-if="bookingAm">
                                            <div t-att-class="'booking-bar-float ' + this.getBookingColor(bookingAm.state) + (bookingAm.state === 'blocked' ? ' shape-block' : (bookingAm.is_continuation ? ' shape-continuation' : ' shape-arrow')) + (this.isRoomMoveDraggable(bookingAm) ? ' booking-draggable' : '')"
                                                 t-att-draggable="this.isRoomMoveDraggable(bookingAm) ? 'true' : 'false'"
                                                 t-att-style="'width: calc(' + (bookingAm.visual_slots * 100) + '% - 4px);'"
                                                 t-on-click.stop="() => this.onCellClick(bookingAm)"
                                                 t-on-dragstart.stop="(ev) => this.onBookingDragStart(ev, bookingAm)"
                                                 t-on-dragend="() => this.onBookingDragEnd()">

                                                 <t t-if="bookingAm.state === 'blocked'"><i class="fa fa-ban me-1"/> BLOCK</t>
                                                 <t t-else=""><span class="me-1"><t t-esc="bookingAm.partner_id ? bookingAm.partner_id[1] : 'Res'"/></span></t>
                                            </div>
                                        </t>
                                    </td>

                                    <td t-att-class="'cell-pm ' + col_bg + (state.dragTargetRoomId === room.id &amp;&amp; state.dragTargetDateStr === date.full ? ' drag-target-cell' : '')"
                                        t-on-click="() => this.onEmptyCellClick(room.id, date.full)"
                                        t-on-dragover="(ev) => this.onRoomCellDragOver(ev, room.id, date.full)"
                                        t-on-drop.stop="(ev) => this.onRoomCellDrop(ev, room.id, date.full)">
                                        <t t-set="booking" t-value="this.getBookingBar(room.id, date.full, 'pm')"/>
                                        
                                        <t t-if="booking">
                                            <div t-att-class="'booking-bar-float ' + this.getBookingColor(booking.state) + (booking.state === 'blocked' ? ' shape-block' : (booking.is_continuation ? ' shape-continuation' : ' shape-arrow')) + (this.isRoomMoveDraggable(booking) ? ' booking-draggable' : '')"
                                                 t-att-draggable="this.isRoomMoveDraggable(booking) ? 'true' : 'false'"
                                                 t-att-style="'width: calc(' + (booking.visual_slots * 100) + '% - 4px);'" 
                                                 t-on-click.stop="() => this.onCellClick(booking)"
                                                 t-on-dragstart.stop="(ev) => this.onBookingDragStart(ev, booking)"
                                                 t-on-dragend="() => this.onBookingDragEnd()">
                                                 
                                                 <t t-if="booking.state === 'blocked'"><i class="fa fa-ban me-1"/> BLOCK</t>
                                                 <t t-else=""><span class="me-1"><t t-esc="booking.partner_id ? booking.partner_id[1] : 'Res'"/></span></t>
                                            </div>
                                        </t>
                                    </td>
                                </t>
                            </tr>
                        </t>
                    </tbody>
                    <tfoot class="bg-header-base font-weight-bold">
                        <tr style="background-color: #f8f9fa;">
                            <td class="sticky-room-col border-top" style="border-right: 2px solid #555; padding: 5px 10px; text-align: right;">Total Available</td>
                            <t t-foreach="state.availableRow || []" t-as="avail" t-key="avail_index">
                                <td colspan="2" class="footer-day border-top text-center align-middle text-primary" style="font-size: 13px;"><t t-esc="avail"/></td>
                            </t>
                        </tr>
                        <tr style="background-color: #fff;">
                            <td class="sticky-room-col border-top" style="border-right: 2px solid #555; padding: 5px 10px; text-align: right;">Total Booked</td>
                            <t t-foreach="state.bookedRow || []" t-as="booked" t-key="booked_index">
                                <td colspan="2" class="footer-day border-top text-center align-middle text-danger" style="font-size: 13px;"><t t-esc="booked"/></td>
                            </t>
                        </tr>
                        <tr style="background-color: #f8f9fa;">
                            <td class="sticky-room-col border-top" style="border-right: 2px solid #555; padding: 5px 10px; text-align: right;">Total Capacity</td>
                            <t t-foreach="state.capacityRow || []" t-as="cap" t-key="cap_index">
                                <td colspan="2" class="footer-day border-top text-center align-middle text-secondary" style="font-size: 13px;"><t t-esc="cap"/></td>
                            </t>
                        </tr>
                        <tr style="background-color: #e8f5e9;">
                            <td class="sticky-room-col border-top" style="border-right: 2px solid #555; padding: 5px 10px; text-align: right;">Occupancy %</td>
                            <t t-foreach="state.currentOccupancyRow || []" t-as="occ" t-key="occ_index">
                                <td colspan="2" class="footer-day border-top text-center align-middle text-success" style="font-size: 14px; font-weight: 900;"><t t-esc="occ"/></td>
                            </t>
                        </tr>
                    </tfoot>
                </table>
            </t>
        </div>
    </div>
`;
registry.category("actions").add("hotel_management.tape_chart_view", HotelTapeChart);
