/** @odoo-module **/

import { registry } from "@web/core/registry";
import { rpc } from "@web/core/network/rpc";

const CARD_SELECTOR = ".o_hotel_guest_chat_card";
const BUTTON_SELECTOR = ".o_hotel_guest_chat_button";
const POLL_INTERVAL = 15000;

function renderAlertStatus(status) {
    const unreadCount = Number(status.count || 0);
    for (const card of document.querySelectorAll(CARD_SELECTOR)) {
        const badge = card.querySelector(".o_hotel_guest_chat_badge");
        const counter = card.querySelector(".o_hotel_guest_chat_unread_count");
        if (counter) {
            counter.textContent = unreadCount.toString();
        }
        if (badge) {
            badge.classList.toggle("d-none", unreadCount === 0);
        }
        card.classList.toggle("guest-chat-alert-pulse", unreadCount > 0);
    }
}

registry.category("services").add("hotel_guest_chat_alert", {
    start() {
        let dashboardVisible = false;
        let pollPending = false;

        async function poll() {
            if (!document.querySelector(CARD_SELECTOR) || pollPending) {
                return;
            }
            pollPending = true;
            try {
                const status = await rpc("/hotel/guest_messages/unread_count", {});
                renderAlertStatus(status);
            } finally {
                pollPending = false;
            }
        }

        function checkDashboardVisibility() {
            const isVisible = Boolean(document.querySelector(CARD_SELECTOR));
            if (isVisible && !dashboardVisible) {
                poll();
            }
            dashboardVisible = isVisible;
        }

        document.addEventListener("click", (event) => {
            if (event.target.closest(BUTTON_SELECTOR)) {
                renderAlertStatus({ count: 0 });
            }
        });

        const observer = new MutationObserver(checkDashboardVisibility);
        observer.observe(document.body, { childList: true, subtree: true });
        const intervalId = setInterval(poll, POLL_INTERVAL);
        checkDashboardVisibility();

        return { observer, intervalId, poll };
    },
});
