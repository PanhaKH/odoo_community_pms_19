/** @odoo-module **/
import { _t } from "@web/core/l10n/translation";
import { registry } from "@web/core/registry";
import { AlertDialog } from "@web/core/confirmation_dialog/confirmation_dialog";
import { escape } from "@web/core/utils/strings";
import { Component, markup, onWillStart, useState, xml } from "@odoo/owl";
import { useService } from "@web/core/utils/hooks";

export class HotelFloorPlan extends Component {
    setup() {
        this.orm = useService("orm");
        this.action = useService("action");
        this.dialogService = useService("dialog");
        this.notification = useService("notification");
        
        this.state = useState({
            loading: true,
            editMode: false,
            viewMode: 'campus',
            zones: [],
            floors: [],
            currentZoneId: null,
            currentFloorId: null,
            rooms: [],
            elements: [],
            connections: [], 
            bgUrl: null,
            canManageReservations: false,
        });

        this.dragState = { active: false, id: null };
        onWillStart(async () => { await this.initData(); });
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

    async initData() {
        await this.loadReservationAccess();
        const zones = await this.orm.searchRead("hotel.zone", [], ['id', 'name', 'sequence', 'pos_x', 'pos_y']);
        this.state.zones = zones.sort((a, b) => a.sequence - b.sequence);
        this.state.floors = await this.orm.searchRead("hotel.floor", [], ['id', 'display_name', 'sequence', 'zone_id']);
        await this.loadCampusMap();
    }

    async loadCampusMap() {
        this.state.loading = true;
        this.state.viewMode = 'campus';
        this.state.currentZoneId = null;
        this.state.currentFloorId = null;
        this.state.bgUrl = await this.orm.call("hotel.zone", "get_campus_background", []);
        this.state.loading = false;
    }

    async selectZone(zoneId) {
        zoneId = parseInt(zoneId);
        this.state.currentZoneId = zoneId;
        this.state.viewMode = 'floor';
        const zoneFloors = this.state.floors.filter(f => f.zone_id && f.zone_id[0] === zoneId);
        if (zoneFloors.length > 0) {
            await this.selectFloor(zoneFloors[0].id);
        } else {
            this.notification.add("This building has no floors configured!", { type: "warning" });
            this.state.currentFloorId = null;
            this.state.bgUrl = null;
            this.state.rooms = [];
            this.state.elements = [];
        }
    }

    async selectFloor(floorId) {
        if (!floorId) return;
        floorId = parseInt(floorId); 
        this.state.currentFloorId = floorId;
        this.state.loading = true;

        const timestamp = new Date().getTime();
        this.state.bgUrl = `/web/image/hotel.floor/${floorId}/background_image?unique=${timestamp}`;

        this.state.elements = await this.orm.searchRead("hotel.floor.element", [['floor_id', '=', floorId]], []);
        
        const rooms = await this.orm.searchRead("hotel.room", 
            [['floor_id', '=', floorId], ['zone_id', '=', this.state.currentZoneId]], 
            ['id', 'name', 'room_type_id', 'state', 'pos_x', 'pos_y', 'shape', 'is_arrival_today', 'arrival_reservation_id', 'is_occupied', 'inhouse_reservation_id', 'is_blocked_today', 'block_id', 'active_connecting_room_ids']
        );
        
        rooms.forEach(r => {
            // Default position if missing
            if (!r.pos_x && !r.pos_y) { r.pos_x = 10; r.pos_y = 10; }

            // Assign Colors, Shortcodes, and Icons based on exact PMS states
            if (r.is_blocked_today || r.state === 'blocked') { 
                r.color = 'bg-danger'; r.shortcode = 'OOO'; r.icon = 'fa-wrench'; 
            }
            else if (r.state === 'occupied_dirty') { 
                r.color = 'bg-warning'; r.shortcode = 'OD'; r.icon = 'fa-bed'; 
            }
            else if (r.state === 'occupied_clean' || r.is_occupied) { 
                r.color = 'bg-info'; r.shortcode = 'OC'; r.icon = 'fa-user'; 
            }
            else if (r.state === 'vacant_dirty') { 
                r.color = 'bg-warning'; r.shortcode = 'VD'; r.icon = 'fa-trash'; 
            }
            else if (r.state === 'vacant_clean') { 
                r.color = 'bg-success'; r.shortcode = 'VC'; r.icon = 'fa-check'; 
            }
            else { 
                r.color = 'bg-secondary'; r.shortcode = 'N/A'; r.icon = 'fa-question'; 
            }
        });
        
        this.state.rooms = rooms;
        // Generate Connecting Lines for the Map
        this.state.connections = [];
        const drawn = new Set();
        rooms.forEach(r => {
            if (r.active_connecting_room_ids && r.active_connecting_room_ids.length > 0) {
                r.active_connecting_room_ids.forEach(targetId => {
                    const targetRoom = rooms.find(x => x.id === targetId);
                    if (targetRoom) {
                        const pairId = [r.id, targetRoom.id].sort().join('-');
                        if (!drawn.has(pairId)) {
                            drawn.add(pairId);
                            this.state.connections.push({
                                id: pairId,
                                // Adding 4% to roughly center the line on the room cards
                                x1: r.pos_x + 4, y1: r.pos_y + 4,
                                x2: targetRoom.pos_x + 4, y2: targetRoom.pos_y + 4,
                            });
                        }
                    }
                });
            }
        });
        this.state.loading = false;
    }

    toggleEditMode() {
        if (!this.state.canManageReservations) {
            this.showReviewOnlyMessage();
            return;
        }
        this.state.editMode = !this.state.editMode;
        if (!this.state.editMode) this.notification.add("Saved!", { type: "success" });
    }

    async onUploadMap(ev) {
        const file = ev.target.files[0];
        if (!file) return;
        const reader = new FileReader();
        reader.readAsDataURL(file);
        reader.onload = async () => {
            const b64 = reader.result.split(',')[1];
            if (this.state.viewMode === 'campus') {
                await this.orm.call("hotel.zone", "save_campus_background", [b64]);
                await this.loadCampusMap();
            } else if (this.state.currentFloorId) {
                await this.orm.write("hotel.floor", [this.state.currentFloorId], { background_image: b64 });
                await this.selectFloor(this.state.currentFloorId);
            }
            this.notification.add("Map Updated!", { type: "success" });
        };
    }

    onDragStart(ev, type, id, initX, initY) {
        if (!this.state.editMode) return;
        ev.preventDefault(); ev.stopPropagation();
        const container = document.querySelector('.floor-plan-container').getBoundingClientRect();
        this.dragState = { active: true, type, id, startX: ev.clientX, startY: ev.clientY, initX, initY, rect: container };
    }

    onMouseMove(ev) {
        if (!this.dragState.active) return;
        const { startX, startY, initX, initY, rect } = this.dragState;
        const dX = ((ev.clientX - startX) / rect.width) * 100;
        const dY = ((ev.clientY - startY) / rect.height) * 100;
        let nX = Math.max(0, Math.min(initX + dX, 95));
        let nY = Math.max(0, Math.min(initY + dY, 95));

        if (this.dragState.type === 'zone') {
            const z = this.state.zones.find(x => x.id === this.dragState.id);
            if(z) { z.pos_x = nX; z.pos_y = nY; }
        } else if (this.dragState.type === 'room') {
            const r = this.state.rooms.find(x => x.id === this.dragState.id);
            if(r) { r.pos_x = nX; r.pos_y = nY; }
        } else {
            const el = this.state.elements.find(x => x.id === this.dragState.id);
            if(el) { el.pos_x = nX; el.pos_y = nY; }
        }
    }

    async onDragEnd() {
        if (!this.dragState.active) return;
        const { type, id } = this.dragState;
        this.dragState.active = false;
        if (type === 'zone') {
            const z = this.state.zones.find(x => x.id === id);
            if (!z) return;
            await this.orm.write("hotel.zone", [id], { pos_x: z.pos_x, pos_y: z.pos_y });
        } else if (type === 'room') {
            const r = this.state.rooms.find(x => x.id === id);
            if (!r) return;
            await this.orm.write("hotel.room", [id], { pos_x: r.pos_x, pos_y: r.pos_y });
        } else {
            const el = this.state.elements.find(x => x.id === id);
            if (!el) return;
            await this.orm.write("hotel.floor.element", [id], { pos_x: el.pos_x, pos_y: el.pos_y });
        }
    }
    
    async addElement(type) {
        if (this.state.viewMode !== 'floor') return;
        await this.orm.create("hotel.floor.element", [{ element_type: type, floor_id: this.state.currentFloorId, pos_x: 45, pos_y: 45 }]);
        await this.selectFloor(this.state.currentFloorId);
    }
    
    showReviewOnlyMessage() {
        this.dialogService.add(AlertDialog, {
            title: _t("Reservation Review Only"),
            body: _t("Housekeeping users can review reservations only and cannot move or modify bookings."),
        });
    }

    async showReservationSummary(model, targetId) {
        if (model === 'hotel.room.block') {
            const blocks = await this.orm.searchRead(
                "hotel.room.block",
                [["id", "=", targetId]],
                ["name", "room_id", "date_from", "date_to", "reason"],
                { limit: 1 }
            );
            const block = blocks && blocks[0];
            if (block) {
                this.dialogService.add(AlertDialog, {
                    title: _t("Room Block"),
                    body: markup(`
                        <div><strong>${escape(block.name || _t("Room Block"))}</strong></div>
                        <div class="mt-2">${escape(block.room_id ? block.room_id[1] : "")}</div>
                        <div>${escape(block.date_from || "")} &rarr; ${escape(block.date_to || "")}</div>
                        <div class="text-muted mt-2">${escape(block.reason || "")}</div>
                    `),
                });
                return;
            }
        }

        const reservations = await this.orm.searchRead(
            "hotel.reservation",
            [["id", "=", targetId]],
            ["name", "partner_id", "room_id", "checkin_date", "checkout_date", "state"],
            { limit: 1 }
        );
        const reservation = reservations && reservations[0];
        if (!reservation) {
            this.showReviewOnlyMessage();
            return;
        }
        this.dialogService.add(AlertDialog, {
            title: _t("Reservation Review Only"),
            body: markup(`
                <div><strong>${escape(reservation.partner_id ? reservation.partner_id[1] : reservation.name || "")}</strong></div>
                <div class="mt-2">${escape(reservation.name || "")}</div>
                <div>${escape(reservation.room_id ? reservation.room_id[1] : _t("Unassigned"))}</div>
                <div>${escape(reservation.checkin_date || "")} &rarr; ${escape(reservation.checkout_date || "")}</div>
                <div class="text-muted mt-2">${escape(_t("Housekeeping users can review reservations only and cannot move or modify bookings."))}</div>
            `),
        });
    }

    async onRoomClick(room) {
        if (this.state.editMode) return;
        
        let targetId = false;
        let targetModel = 'hotel.reservation';
        if (room.is_blocked_today && room.block_id) {
            targetId = room.block_id[0];
            targetModel = 'hotel.room.block';
        }
        else if (room.is_occupied && room.inhouse_reservation_id) targetId = room.inhouse_reservation_id[0];
        else if (room.is_arrival_today && room.arrival_reservation_id) targetId = room.arrival_reservation_id[0];

        if (targetId) {
            if (!this.state.canManageReservations) {
                await this.showReservationSummary(targetModel, targetId);
                return;
            }
            // OPEN EXISTING RESERVATION
            this.action.doAction({
                type: 'ir.actions.act_window',
                res_model: targetModel,
                res_id: targetId,
                views: [[false, 'form']],
                target: 'current'
            });
        } else {
            if (!this.state.canManageReservations) {
                this.showReviewOnlyMessage();
                return;
            }
            // OPEN NEW RESERVATION POPUP
            this.action.doAction({ 
                type: 'ir.actions.act_window', 
                res_model: 'hotel.reservation', 
                views: [[false, 'form']], 
                target: 'new', 
                context: { 
                    default_room_id: room.id,
                    // ADDED: Auto-fill the Room Type field as well
                    default_room_type_id: room.room_type_id ? room.room_type_id[0] : false 
                } 
            });
        }
    }
}

HotelFloorPlan.template = xml`
    <div class="o_action_manager h-100 d-flex flex-column" t-on-mousemove="onMouseMove" t-on-mouseup="onDragEnd">
        <div class="d-flex justify-content-between align-items-center p-2 border-bottom bg-white shadow-sm">
            <div class="d-flex align-items-center gap-3">
                <button t-if="state.viewMode == 'floor'" class="btn btn-outline-secondary btn-sm" t-on-click="loadCampusMap">
                    <i class="fa fa-arrow-left"/> Campus
                </button>
                <h4 class="m-0 text-primary">
                    <i class="fa fa-map-o me-2"/>
                    <t t-if="state.viewMode == 'campus'">Hotel Campus Map</t>
                    <t t-else=""><t t-esc="state.zones.find(z => z.id === state.currentZoneId)?.name"/></t>
                </h4>
                <select t-if="state.viewMode == 'floor'" class="form-select form-select-sm fw-bold border-primary" style="width: 250px;" 
                        t-on-change="(ev) => this.selectFloor(ev.target.value)">
                    <t t-foreach="state.floors.filter(f => f.zone_id &amp;&amp; f.zone_id[0] === state.currentZoneId)" t-as="f" t-key="f.id">
                        <option t-att-value="f.id" t-att-selected="f.id == state.currentFloorId">
                            <t t-esc="f.display_name"/>
                        </option>
                    </t>
                </select>
            </div>
            <div class="d-flex">
                <button t-if="state.canManageReservations" class="btn" t-att-class="state.editMode ? 'btn-danger' : 'btn-outline-primary'" t-on-click="toggleEditMode">
                    <i t-att-class="state.editMode ? 'fa fa-save' : 'fa fa-pencil'"/>
                    <t t-esc="state.editMode ? ' Save Layout' : ' Design Mode'"/>
                </button>
            </div>
        </div>

        <div t-if="state.editMode &amp;&amp; state.viewMode == 'floor'" class="bg-dark text-white p-2 d-flex justify-content-center gap-2 slide-down">
            <button class="btn btn-sm btn-outline-light" t-on-click="() => this.addElement('wall')"><i class="fa fa-minus"/> Wall</button>
            <button class="btn btn-sm btn-outline-light" t-on-click="() => this.addElement('area')"><i class="fa fa-square-o"/> Area</button>
            <label class="btn btn-sm btn-outline-info">
                <i class="fa fa-upload"/> Floor Map
                <input type="file" accept="image/*" class="d-none" t-on-change="onUploadMap"/>
            </label>
        </div>
        
        <div t-if="state.editMode &amp;&amp; state.viewMode == 'campus'" class="bg-dark text-white p-2 d-flex justify-content-center">
            <label class="btn btn-sm btn-outline-info">
                <i class="fa fa-upload"/> Upload Main Campus Image
                <input type="file" accept="image/*" class="d-none" t-on-change="onUploadMap"/>
            </label>
        </div>

        <div class="floor-plan-container position-relative flex-grow-1 bg-light" 
             t-att-class="state.editMode ? 'o_edit_mode_grid' : ''"
             t-att-style="'background-image: url(' + (state.bgUrl || '') + '); background-size: cover; background-position: center; overflow: hidden;'">

             <t t-if="state.viewMode == 'campus'">
                 <t t-foreach="state.zones" t-as="z" t-key="'zone-' + z.id">
                    <div t-att-class="'zone-pin shadow border border-3 border-white d-flex flex-column align-items-center justify-content-center bg-primary text-white ' + (state.editMode ? 'draggable-el' : 'clickable')"
                         t-att-style="'position: absolute; left: ' + z.pos_x + '%; top: ' + z.pos_y + '%; width: 120px; height: 60px; z-index: 20; border-radius: 8px;'"
                         t-on-mousedown="(ev) => this.onDragStart(ev, 'zone', z.id, z.pos_x, z.pos_y)"
                         t-on-click="() => this.selectZone(z.id)">
                        <i class="fa fa-building fa-2x mb-1"/>
                        <span class="fw-bold small"><t t-esc="z.name"/></span>
                    </div>
                 </t>
             </t>

             <t t-if="state.viewMode == 'floor'">

                 <svg class="position-absolute w-100 h-100" style="z-index: 4; pointer-events: none; top: 0; left: 0;">
                     <t t-foreach="state.connections" t-as="conn" t-key="conn.id">
                         <line t-att-x1="conn.x1 + '%'" t-att-y1="conn.y1 + '%'" 
                               t-att-x2="conn.x2 + '%'" t-att-y2="conn.y2 + '%'" 
                               stroke="#ffc107" stroke-width="8" stroke-dasharray="12,12" stroke-linecap="round"/>
                     </t>
                 </svg>

                 <t t-foreach="state.elements" t-as="el" t-key="'el-' + el.id">
                     <div t-att-class="state.editMode ? 'draggable-el' : ''"
                          t-att-style="'position: absolute; left: ' + el.pos_x + '%; top: ' + el.pos_y + '%; z-index: ' + el.z_index + ';'"
                          t-on-mousedown="(ev) => this.onDragStart(ev, 'element', el.id, el.pos_x, el.pos_y)">
                         <div t-if="el.element_type == 'wall'" t-att-style="'width:'+el.width+'px; height:'+el.height+'px; background:'+el.color;"></div>
                         <div t-if="el.element_type == 'area'" t-att-style="'width:'+el.width+'px; height:'+el.height+'px; border: 2px dashed '+el.color+'; background: rgba(255,255,255,0.25);'"></div>
                         <i t-if="el.element_type == 'icon'" t-att-class="'fa '+el.icon_class" t-att-style="'font-size:'+el.font_size+'px; color:'+el.color;"/>
                         <span t-if="el.element_type == 'label'" t-att-style="'font-size:'+el.font_size+'px; color:'+el.color+'; font-weight: 600;'"><t t-esc="el.name"/></span>
                     </div>
                 </t>
                    
                 <t t-foreach="state.rooms" t-as="room" t-key="'room-' + room.id">
                    <div t-att-class="'room-card shadow border border-2 border-white rounded d-flex flex-column align-items-center justify-content-center ' + room.color + (state.editMode ? ' draggable-el' : ' clickable')"
                         t-att-style="'position: absolute; left: ' + room.pos_x + '%; top: ' + room.pos_y + '%; width: 100px; height: 80px; z-index: 10;'">
                        
                        <div class="position-absolute w-100 h-100" style="z-index: 15;"
                             t-on-mousedown="(ev) => this.onDragStart(ev, 'room', room.id, room.pos_x, room.pos_y)"
                             t-on-click="() => this.onRoomClick(room)"></div>

                        <h5 class="text-white fw-bold m-0 mb-1" style="z-index: 5;"><t t-esc="room.name"/></h5>
                        
                        <div class="d-flex align-items-center gap-1 text-white" style="font-size: 0.9em; z-index: 5; opacity: 0.9;">
                            <i t-att-class="'fa ' + room.icon"/>
                            <span class="fw-bold"><t t-esc="room.shortcode"/></span>
                        </div>

                        <div t-if="room.is_arrival_today" class="position-absolute bg-white rounded-circle shadow-sm d-flex justify-content-center align-items-center" 
                             style="top: -8px; right: -8px; width: 24px; height: 24px; z-index: 20;" title="Arrival Today">
                            <i class="fa fa-suitcase text-warning" style="font-size: 0.85em;"/>
                        </div>
                    </div>
                 </t>
             </t>
        </div>
        <style>
            .o_edit_mode_grid { background-size: 40px 40px !important; background-image: linear-gradient(to right, rgba(0,0,0,0.1) 1px, transparent 1px), linear-gradient(to bottom, rgba(0,0,0,0.1) 1px, transparent 1px) !important; background-color: #f8f9fa; }
            .draggable-el:hover { filter: brightness(1.1); outline: 1px dashed #fff; cursor: grab; }
            .clickable:hover { transform: scale(1.05); z-index: 100 !important; cursor: pointer; }
            .zone-pin { transition: transform 0.2s; box-shadow: 0 4px 8px rgba(0,0,0,0.3) !important; }
        </style>
    </div>
`;
registry.category("actions").add("hotel_management.floor_plan_view", HotelFloorPlan);
