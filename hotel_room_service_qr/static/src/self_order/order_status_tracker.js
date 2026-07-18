import { onMounted, onWillStart, onWillUnmount, useState } from "@odoo/owl";
import { patch } from "@web/core/utils/patch";
import { rpc } from "@web/core/network/rpc";
import { CartPage } from "@pos_self_order/app/pages/cart_page/cart_page";
import { LandingPage } from "@pos_self_order/app/pages/landing_page/landing_page";
import { OrdersHistoryPage } from "@pos_self_order/app/pages/order_history_page/order_history_page";
import { PosOrder } from "@point_of_sale/app/models/pos_order";

function isRoomServiceSession() {
    return Boolean(new URLSearchParams(window.location.search).get("room_service_token"));
}

async function fetchRoomServiceTrackers(posOrderTokens = []) {
    const urlParams = new URLSearchParams(window.location.search);
    if (!posOrderTokens.length && !urlParams.get("room_service_token") && !urlParams.get("table_identifier")) {
        return { latest: null, orders: {}, allowedTokens: null, room: "" };
    }

    const result = await rpc("/room-service/pos-self/tracker/json", {
        pos_order_access_tokens: posOrderTokens,
        room_service_token: urlParams.get("room_service_token"),
        table_identifier: urlParams.get("table_identifier"),
    });
    const trackers = Object.fromEntries(
        Object.entries(result?.orders || {}).map(([token, tracker]) => [
            token,
            normalizeTracker(tracker),
        ])
    );
    if (result.latest?.id && posOrderTokens.length === 1 && !trackers[posOrderTokens[0]]) {
        trackers[posOrderTokens[0]] = normalizeTracker(result.latest);
    }
    return {
        latest: result?.latest?.id ? normalizeTracker(result.latest) : null,
        orders: trackers,
        allowedTokens: Array.isArray(result?.allowed_pos_order_tokens)
            ? result.allowed_pos_order_tokens.filter(Boolean)
            : null,
        room: result?.room || "",
    };
}

function normalizeTracker(tracker) {
    if (!tracker || typeof tracker !== "object" || !tracker.id) {
        return null;
    }
    const steps = Array.isArray(tracker.steps) ? tracker.steps : [];
    return {
        ...tracker,
        state_label: tracker.state_label || tracker.state || "Order Placed",
        updated_at_display: tracker.updated_at_display || "",
        last_error: tracker.last_error || "",
        steps: steps
            .filter((step) => step && typeof step === "object")
            .map((step, index) => ({
                key: step.key || `step-${index}`,
                label: step.label || "Order update",
                state: ["done", "current", "future", "cancelled"].includes(step.state)
                    ? step.state
                    : "future",
                number: index + 1,
            })),
    };
}

function ensureRoomServiceOrderUiState(order) {
    if (!isRoomServiceSession() || !order?.access_token) {
        return;
    }
    if (!order.uiState) {
        order.initState();
    } else if (!order.uiState.lineChanges) {
        order.uiState.lineChanges = {};
    }
}

patch(PosOrder.prototype, {
    setup() {
        super.setup(...arguments);
        ensureRoomServiceOrderUiState(this);
    },

    recomputeChanges() {
        ensureRoomServiceOrderUiState(this);
        return super.recomputeChanges(...arguments);
    },
});

patch(OrdersHistoryPage.prototype, {
    setup() {
        super.setup(...arguments);
        this.roomServiceTrackerState = useState({
            latest: null,
            orders: {},
            allowedTokens: null,
            room: "",
        });
        this.roomServiceTrackerTimer = null;
        this.roomServiceTrackerMounted = false;

        onMounted(() => {
            this.roomServiceTrackerMounted = true;
            this.loadRoomServiceTrackers();
            this.roomServiceTrackerTimer = setInterval(() => this.loadRoomServiceTrackers(), 1000);
        });
        onWillUnmount(() => {
            this.roomServiceTrackerMounted = false;
            if (this.roomServiceTrackerTimer) {
                clearInterval(this.roomServiceTrackerTimer);
            }
        });
    },

    getRoomServiceTracker(order) {
        const accessToken = order?.access_token;
        return (accessToken && this.roomServiceTrackerState?.orders?.[accessToken]) || null;
    },

    get orders() {
        const orders = super.orders;
        if (!isRoomServiceSession()) {
            return orders;
        }
        const allowedTokens = this.roomServiceTrackerState?.allowedTokens;
        if (!Array.isArray(allowedTokens)) {
            return [];
        }
        const allowed = new Set(allowedTokens);
        return orders.filter((order) => allowed.has(order?.access_token));
    },

    getLatestUnmatchedRoomServiceTracker() {
        const latest = this.roomServiceTrackerState?.latest;
        if (!latest?.id) {
            return null;
        }
        const displayedTokens = new Set(
            (this.orders || []).map((order) => order?.access_token).filter(Boolean)
        );
        return displayedTokens.has(latest.pos_order_access_token) ? null : latest;
    },

    getPrice(line) {
        try {
            return super.getPrice(...arguments);
        } catch (error) {
            // A historical self-order can reference a product which is no longer part of the
            // data loaded by the current self-order menu.  Odoo cannot rebuild its transient
            // price cache in that case, but the authoritative totals saved on the order line
            // are still available and are all the order-history view needs to display.
            const storedPrice =
                line?.config?.iface_tax_included === "total"
                    ? line?.price_subtotal_incl
                    : line?.price_subtotal;
            if (Number.isFinite(storedPrice)) {
                return storedPrice;
            }
            throw error;
        }
    },

    async loadRoomServiceTrackers() {
        const posOrderTokens = (this.orders || []).map((order) => order?.access_token).filter(Boolean);
        try {
            const result = await fetchRoomServiceTrackers(posOrderTokens);
            if (!this.roomServiceTrackerMounted) {
                return;
            }
            this.roomServiceTrackerState.latest = result.latest;
            this.roomServiceTrackerState.orders = result.orders;
            this.roomServiceTrackerState.allowedTokens = result.allowedTokens;
            this.roomServiceTrackerState.room = result.room;
        } catch {
            if (!this.roomServiceTrackerMounted) {
                return;
            }
            this.roomServiceTrackerState.latest = null;
            this.roomServiceTrackerState.orders = {};
            this.roomServiceTrackerState.allowedTokens = [];
            this.roomServiceTrackerState.room = "";
        }
    },
});

patch(CartPage.prototype, {
    setup() {
        super.setup(...arguments);
        this.roomServiceCartTrackerState = useState({ latest: null, orders: {} });
        this.roomServiceCartTrackerTimer = null;
        this.roomServiceCartTrackerMounted = false;

        onWillStart(() => {
            // Once a Room Service order has been submitted, its draft state means "waiting
            // for staff confirmation", not an editable customer cart.  Send both a direct
            // /cart visit and the landing-page action to the read-only order tracker.
            if (isRoomServiceSession() && this.selfOrder.currentOrder?.access_token) {
                this.router.navigate("orderHistory");
            }
        });

        onMounted(() => {
            this.roomServiceCartTrackerMounted = true;
            this.loadRoomServiceCartTracker();
            this.roomServiceCartTrackerTimer = setInterval(
                () => this.loadRoomServiceCartTracker(),
                1000
            );
        });
        onWillUnmount(() => {
            this.roomServiceCartTrackerMounted = false;
            if (this.roomServiceCartTrackerTimer) {
                clearInterval(this.roomServiceCartTrackerTimer);
            }
        });
    },

    getCartRoomServiceTracker() {
        const posOrderToken = this.selfOrder.currentOrder?.access_token;
        return (
            (posOrderToken && this.roomServiceCartTrackerState.orders[posOrderToken]) ||
            this.roomServiceCartTrackerState.latest ||
            null
        );
    },

    async loadRoomServiceCartTracker() {
        const posOrderToken = this.selfOrder.currentOrder?.access_token;
        const posOrderTokens = posOrderToken ? [posOrderToken] : [];
        try {
            const result = await fetchRoomServiceTrackers(posOrderTokens);
            if (!this.roomServiceCartTrackerMounted) {
                return;
            }
            this.roomServiceCartTrackerState.latest = result.latest;
            this.roomServiceCartTrackerState.orders = result.orders;
        } catch {
            if (!this.roomServiceCartTrackerMounted) {
                return;
            }
            this.roomServiceCartTrackerState.latest = null;
            this.roomServiceCartTrackerState.orders = {};
        }
    },
});

patch(LandingPage.prototype, {
    clickMyOrder() {
        if (isRoomServiceSession()) {
            this.router.navigate("orderHistory");
            return;
        }
        return super.clickMyOrder(...arguments);
    },
});
