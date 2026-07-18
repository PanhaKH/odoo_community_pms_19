import { Component, useState, onWillStart, onWillUnmount } from "@odoo/owl";
import { useService } from "@web/core/utils/hooks";
import { rpc } from "@web/core/network/rpc";
import { readBoot } from "@eh_pos_kds_core/app/brand_guard";
import { OfflineStore } from "./offline";

/**
 * Live kitchen board. Loads a snapshot over a token guarded route, then keeps
 * itself current from the board's private bus channel. Bumps go back through the
 * token guarded op route as absolute lane moves, so an offline replay is
 * idempotent. When the network drops the board shows its cached state and queues
 * bumps, replaying them in order on reconnect.
 */
export class KdsBoard extends Component {
    static template = "eh_pos_kds.KdsBoard";
    static props = {};

    setup() {
        // Boot config (the token) comes only from the server rendered brand
        // element. No brand element means no token, so the board cannot load:
        // the attribution is load bearing.
        const boot = readBoot();
        this.token = boot ? boot.token : null;
        this.dbName = boot ? boot.db : null;
        this.bus = useService("bus_service");
        this.offline = new OfflineStore(this.token);
        this.state = useState({
            board: { name: boot ? boot.name : "Kitchen", lanes: [] },
            configMissing: !boot,
            cards: [],
            paperOut: [],
            connected: false,
            offline: false,
            queued: 0,
            lastSync: null,
            view: "lanes",
            selectedId: null,
            showMetrics: true,
            expandedStatus: false,
            selectedOutletId: "all",
            stats: null,
        });
        this.tick = useState({ now: this._clientNow() });
        this.serverOffset = 0;
        this.alerted = new Set();
        this.loadInFlight = false;

        onWillStart(async () => {
            if (!this.token) {
                return; // no boot config: degraded, render the config-missing notice
            }
            await this.load();
            await this.loadStats();
            this.subscribe();
        });

        this.timer = setInterval(() => {
            this.tick.now = this._clientNow();
            this.scanSla();
        }, 1000);
        this.metricsTimer = setInterval(() => {
            this.loadStats();
        }, 30000);
        this.snapshotTimer = setInterval(() => {
            if (this.token) {
                this.load();
            }
        }, 1000);
        this.onKey = (ev) => this.handleKey(ev);
        this.onOnline = () => this.reconnect();
        this.onOffline = () => (this.state.offline = true);
        window.addEventListener("keydown", this.onKey);
        window.addEventListener("online", this.onOnline);
        window.addEventListener("offline", this.onOffline);
        onWillUnmount(() => {
            clearInterval(this.timer);
            clearInterval(this.metricsTimer);
            clearInterval(this.snapshotTimer);
            window.removeEventListener("keydown", this.onKey);
            window.removeEventListener("online", this.onOnline);
            window.removeEventListener("offline", this.onOffline);
        });
    }

    // -- data ----------------------------------------------------------------

    boardRpc(route, params = {}, settings = {}) {
        const headers = { ...(settings.headers || {}) };
        if (this.dbName) {
            headers["X-Odoo-Database"] = this.dbName;
        }
        return rpc(route, params, { ...settings, headers });
    }

    async load() {
        if (!this.token) {
            return;
        }
        if (this.loadInFlight) {
            return;
        }
        this.loadInFlight = true;
        try {
            const data = await this.boardRpc("/eh_kds/board/data", { token: this.token });
            this.state.board = data.board;
            this.state.cards = data.cards;
            this.state.paperOut = data.paper_alerts || [];
            this.serverOffset = this._parse(data.server_time) - this._clientNow();
            this.state.offline = false;
            this.state.lastSync = new Date();
            this.offline.saveSnapshot(data);
        } catch {
            // server unreachable: fall back to the cached snapshot, read mostly
            const row = await this.offline.loadSnapshot();
            if (row && row.data) {
                this.state.board = row.data.board;
                this.state.cards = row.data.cards;
                this.state.lastSync = new Date(row.at);
            }
            this.state.offline = true;
        } finally {
            await this._refreshQueueCount();
            this.loadInFlight = false;
        }
    }

    subscribe() {
        if (!this.token) {
            return;
        }
        this.bus.addChannel(this.token);
        this.bus.subscribe("kds.card", (payload) => this.onCardEvent(payload));
        this.bus.subscribe("kds.ticket", () => this.load());
        this.bus.subscribe("kds.paper", (payload) => {
            this.state.paperOut = (payload && payload.stations) || [];
        });
        this.bus.subscribe("BUS:RECONNECT", () => this.reconnect());
        this.state.connected = true;
    }

    async reconnect() {
        await this.replayQueue();
        await this.load();
    }

    onCardEvent(payload) {
        const cards = this.state.cards;
        const idx = cards.findIndex((c) => c.id === payload.id);
        if (idx >= 0 && cards[idx].event_id > payload.event_id) {
            return; // stale echo, a newer event already applied
        }
        if (payload.status === "voided") {
            if (idx >= 0) {
                cards.splice(idx, 1);
            }
            return;
        }
        if (idx >= 0) {
            cards[idx] = payload;
        } else {
            cards.push(payload);
        }
    }

    // -- ops (optimistic, offline aware) -------------------------------------

    async op(action, cardIds, extra = {}) {
        if (!cardIds.length) {
            return;
        }
        this._applyLocal(action, cardIds, extra);
        try {
            const res = await this.boardRpc("/eh_kds/board/op", {
                token: this.token,
                action,
                card_ids: cardIds,
                ...extra,
            });
            if (res && res.ok && res.cards) {
                res.cards.forEach((c) => this.onCardEvent(c));
            }
            this.state.offline = false;
        } catch {
            await this.offline.enqueue({ action, card_ids: cardIds, ...extra });
            this.state.offline = true;
            await this._refreshQueueCount();
        }
    }

    _applyLocal(action, cardIds, extra) {
        const lanes = this.state.board.lanes;
        for (const id of cardIds) {
            const card = this.state.cards.find((c) => c.id === id);
            if (!card) {
                continue;
            }
            if (action === "void") {
                const i = this.state.cards.indexOf(card);
                this.state.cards.splice(i, 1);
            } else if (action === "move" && extra.to_index !== undefined) {
                const t = Math.max(0, Math.min(lanes.length - 1, extra.to_index));
                card.lane_index = t;
                card.lane_id = lanes[t] ? lanes[t].id : card.lane_id;
            }
        }
    }

    async replayQueue() {
        const pending = await this.offline.pending();
        for (const row of pending) {
            try {
                await this.boardRpc("/eh_kds/board/op", { token: this.token, ...row.op });
                await this.offline.drop(row.key);
            } catch {
                break; // still offline, keep the rest for the next reconnect
            }
        }
        await this._refreshQueueCount();
    }

    async _refreshQueueCount() {
        this.state.queued = (await this.offline.pending()).length;
    }

    bump(card) {
        this.op("move", [card.id], { to_index: card.lane_index + 1 });
    }

    recall(card) {
        this.op("move", [card.id], { to_index: card.lane_index - 1 });
    }

    voidCard(card) {
        this.op("void", [card.id]);
    }

    // -- metrics -------------------------------------------------------------

    async toggleMetrics() {
        this.state.expandedStatus = !this.state.expandedStatus;
        this.state.showMetrics = !this.state.expandedStatus;
        if (this.state.showMetrics) {
            await this.loadStats();
        }
    }

    async loadStats() {
        try {
            this.state.stats = await this.boardRpc("/eh_kds/board/stats", { token: this.token });
        } catch {
            // keep the last stats if the server is briefly unreachable
        }
    }

    // -- derived views -------------------------------------------------------

    laneById(id) {
        return this.state.board.lanes.find((l) => l.id === id);
    }

    outletKey(card) {
        return card.pos_config_id ? String(card.pos_config_id) : "no_outlet";
    }

    cardMatchesOutlet(card) {
        return this.state.selectedOutletId === "all" || this.outletKey(card) === this.state.selectedOutletId;
    }

    get visibleCards() {
        return this.state.cards.filter((card) => this.cardMatchesOutlet(card));
    }

    get outletOptions() {
        const outlets = new Map();
        for (const card of this.state.cards) {
            const key = this.outletKey(card);
            const name = card.pos_config_name || "No Outlet";
            if (!outlets.has(key)) {
                outlets.set(key, { id: key, name });
            }
        }
        return [
            { id: "all", name: "All Outlets" },
            ...[...outlets.values()].sort((a, b) => a.name.localeCompare(b.name)),
        ];
    }

    setOutlet(ev) {
        this.state.selectedOutletId = ev.target.value || "all";
        if (this.state.selectedId && !this.visibleCards.some((card) => card.id === this.state.selectedId)) {
            this.state.selectedId = null;
        }
    }

    cardsInLane(laneId) {
        return this.visibleCards
            .filter((c) => c.lane_id === laneId)
            .sort((a, b) => this._priorityRank(a) - this._priorityRank(b) || a.id - b.id);
    }

    groupsInLane(lane) {
        const grouped = new Map();
        for (const card of this.cardsInLane(lane.id)) {
            const key = card.ticket_id || card.ticket_ref || card.id;
            if (!grouped.has(key)) {
                grouped.set(key, {
                    id: key,
                    ref: card.ticket_ref,
                    lane,
                    cards: [],
                    placed_at: card.placed_at,
                    changed_at: card.changed_at,
                    priority: card.priority,
                });
            }
            const group = grouped.get(key);
            group.cards.push(card);
            if (this._parse(card.placed_at) < this._parse(group.placed_at)) {
                group.placed_at = card.placed_at;
            }
            if (this._parse(card.changed_at) > this._parse(group.changed_at)) {
                group.changed_at = card.changed_at;
            }
        }
        return [...grouped.values()];
    }

    displayRef(ref) {
        const value = String(ref || "-").trim();
        const marker = "Room ";
        if (value.includes(marker)) {
            const room = value.split(marker, 2)[1].trim().split(/\s+/)[0];
            if (room) {
                return `${marker}${room}`;
            }
        }
        return value;
    }

    laneTone(lane, index) {
        const name = (lane.name || "").toLowerCase();
        if (name.includes("ready")) {
            return "ready";
        }
        if (name.includes("complete") || name.includes("done")) {
            return "completed";
        }
        if (name.includes("progress") || name.includes("cook")) {
            return "cooking";
        }
        return index === 1 ? "cooking" : index === 2 ? "ready" : index >= 3 ? "completed" : "queue";
    }

    laneTitle(lane, index) {
        const tone = this.laneTone(lane, index);
        return {
            queue: "In Queue",
            cooking: "Cooking",
            ready: "Ready",
            completed: "Completed",
        }[tone];
    }

    itemCount(group) {
        return group.cards.reduce((total, card) => total + Number(card.qty || 0), 0);
    }

    groupAgeLabel(group) {
        const secs = Math.max(0, Math.floor((this._serverNow() - this._parse(group.placed_at)) / 1000));
        const minutes = Math.floor(secs / 60);
        return minutes <= 0 ? "< 1 min" : `${minutes} min`;
    }

    bumpGroup(group) {
        this.op("move", group.cards.map((card) => card.id), { to_index: group.cards[0].lane_index + 1 });
    }

    recallGroup(group) {
        this.op("move", group.cards.map((card) => card.id), { to_index: group.cards[0].lane_index - 1 });
    }

    groupSelected(group) {
        return group.cards.some((card) => card.id === this.state.selectedId);
    }

    kpiIconGlyph(icon) {
        return {
            queue: "⏳",
            chef: "♨",
            ready: "🔔",
            complete: "✅",
            timer: "T",
            alert: "!",
        }[icon] || ".";
    }

    get dashboardKpis() {
        const lanes = this.state.board.lanes || [];
        const byTone = { queue: 0, cooking: 0, ready: 0, completed: 0 };
        lanes.forEach((lane, index) => {
            byTone[this.laneTone(lane, index)] += this.groupsInLane(lane).length;
        });
        return [
            { key: "queue", label: "In Queue", value: byTone.queue, sub: "Orders", icon: "queue" },
            { key: "cooking", label: "Cooking", value: byTone.cooking, sub: "Orders", icon: "chef" },
            { key: "ready", label: "Ready", value: byTone.ready, sub: "Orders", icon: "ready" },
            { key: "completed", label: "Completed", value: byTone.completed, sub: "Orders", icon: "complete" },
        ];
    }

    get orderedCards() {
        const order = this.state.board.lanes.map((l) => l.id);
        return [...this.visibleCards].sort(
            (a, b) => order.indexOf(a.lane_id) - order.indexOf(b.lane_id) || a.id - b.id
        );
    }

    get allDay() {
        const counts = {};
        for (const c of this.visibleCards) {
            counts[c.product] = (counts[c.product] || 0) + c.qty;
        }
        return Object.entries(counts)
            .map(([product, qty]) => ({ product, qty }))
            .sort((a, b) => b.qty - a.qty);
    }

    get heatmap() {
        // open cards bucketed by the minute they were placed, last 12 minutes
        const buckets = new Array(12).fill(0);
        const now = this._serverNow();
        for (const c of this.visibleCards) {
            const ago = Math.floor((now - this._parse(c.placed_at)) / 60000);
            if (ago >= 0 && ago < 12) {
                buckets[11 - ago] += 1;
            }
        }
        const max = Math.max(1, ...buckets);
        return buckets.map((count) => {
            const pct = Math.round((100 * count) / max);
            return { count, pct, h: Math.max(6, pct) };
        });
    }

    _priorityRank(card) {
        return { vip: 0, rush: 1, normal: 2 }[card.priority] ?? 2;
    }

    // -- timing + SLA --------------------------------------------------------

    _clientNow() {
        return new Date().getTime();
    }

    _parse(iso) {
        return iso ? new Date(iso.endsWith("Z") ? iso : iso + "Z").getTime() : 0;
    }

    _serverNow() {
        return this.tick.now + this.serverOffset;
    }

    lastSyncLabel() {
        if (!this.state.lastSync) {
            return "";
        }
        const s = Math.floor((this._clientNow() - this.state.lastSync.getTime()) / 1000);
        if (s < 60) {
            return `${s}s ago`;
        }
        return `${Math.floor(s / 60)}m ago`;
    }

    ageLabel(card) {
        const secs = Math.max(0, Math.floor((this._serverNow() - this._parse(card.placed_at)) / 1000));
        const m = Math.floor(secs / 60);
        const s = secs % 60;
        return `${m}:${s.toString().padStart(2, "0")}`;
    }

    slaClass(card) {
        const lane = this.laneById(card.lane_id);
        if (!lane || !lane.sla_minutes) {
            return "";
        }
        const mins = (this._serverNow() - this._parse(card.changed_at)) / 60000;
        const r = mins / lane.sla_minutes;
        if (r >= 1) {
            return "is-danger";
        }
        if (r >= 0.8) {
            return "is-coral";
        }
        if (r >= 0.5) {
            return "is-warn";
        }
        return "";
    }

    scanSla() {
        for (const card of this.state.cards) {
            if (this.slaClass(card) === "is-danger" && !this.alerted.has(card.id)) {
                this.alerted.add(card.id);
                this._beep();
            }
        }
    }

    _beep() {
        try {
            const Ctx = window.AudioContext || window.webkitAudioContext;
            if (!Ctx) {
                return;
            }
            const ctx = (this._audio = this._audio || new Ctx());
            const osc = ctx.createOscillator();
            const gain = ctx.createGain();
            osc.frequency.value = 660;
            gain.gain.value = 0.05;
            osc.connect(gain).connect(ctx.destination);
            osc.start();
            osc.stop(ctx.currentTime + 0.15);
        } catch {
            // sound is a nicety, never fatal
        }
    }

    // -- interactions --------------------------------------------------------

    select(cardId) {
        this.state.selectedId = cardId;
    }

    _selected() {
        return this.state.cards.find((c) => c.id === this.state.selectedId);
    }

    advanceSelected(direction) {
        const card = this._selected();
        if (card) {
            this.op("move", [card.id], { to_index: card.lane_index + direction });
        }
    }

    voidSelected() {
        const card = this._selected();
        if (card) {
            this.voidCard(card);
            this.state.selectedId = null;
        }
    }

    moveSelection(step) {
        const list = this.orderedCards;
        if (!list.length) {
            return;
        }
        const idx = list.findIndex((c) => c.id === this.state.selectedId);
        const next = idx < 0 ? 0 : Math.max(0, Math.min(list.length - 1, idx + step));
        this.state.selectedId = list[next].id;
    }

    handleKey(ev) {
        switch (ev.key) {
            case "ArrowRight":
            case "Enter":
            case " ":
                this.advanceSelected(1);
                ev.preventDefault();
                break;
            case "ArrowLeft":
            case "Backspace":
                this.advanceSelected(-1);
                ev.preventDefault();
                break;
            case "ArrowDown":
                this.moveSelection(1);
                ev.preventDefault();
                break;
            case "ArrowUp":
                this.moveSelection(-1);
                ev.preventDefault();
                break;
            case "Delete":
                this.voidSelected();
                ev.preventDefault();
                break;
            case "a":
            case "A":
                this.state.view = this.state.view === "allday" ? "lanes" : "allday";
                break;
            case "m":
            case "M":
                this.toggleMetrics();
                break;
        }
    }
}
