/** @odoo-module **/

import { registry } from "@web/core/registry";
import { rpc } from "@web/core/network/rpc";

const CARD_SELECTOR = ".o_hotel_guest_chat_card";
const BUTTON_SELECTOR = ".o_hotel_guest_chat_button";
const POLL_INTERVAL = 30000;

function isVisible(element) {
    return !!(
        element &&
        element.offsetParent !== null &&
        element.getClientRects().length
    );
}

function getVisibleCards() {
    return Array.from(document.querySelectorAll(CARD_SELECTOR)).filter(isVisible);
}

function hasVisibleGuestChatCard() {
    return getVisibleCards().length > 0;
}

function renderAlertStatus(status) {
    const unreadCount = Number(status.count || 0);

    for (const card of getVisibleCards()) {
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
        if (window.__hotelGuestChatAlertInstalled) {
            return {};
        }
        window.__hotelGuestChatAlertInstalled = true;

        let pollTimer = null;
        let pollPending = false;

        async function pollOnce() {
            if (!hasVisibleGuestChatCard() || pollPending) {
                return;
            }

            pollPending = true;
            try {
                const status = await rpc("/hotel/guest_messages/unread_count", {});
                renderAlertStatus(status || {});
            } catch (error) {
                console.warn("Hotel guest chat unread count failed:", error);
            } finally {
                pollPending = false;
            }
        }

        function stopPolling() {
            if (pollTimer) {
                clearInterval(pollTimer);
                pollTimer = null;
            }
        }

        function startPollingIfVisible() {
            if (!hasVisibleGuestChatCard()) {
                stopPolling();
                return;
            }

            if (!pollTimer) {
                pollOnce();
                pollTimer = setInterval(function () {
                    if (hasVisibleGuestChatCard()) {
                        pollOnce();
                    } else {
                        stopPolling();
                    }
                }, POLL_INTERVAL);
            }
        }

        document.addEventListener("click", (event) => {
            if (event.target.closest(BUTTON_SELECTOR)) {
                renderAlertStatus({ count: 0 });
            }
        });

        const observer = new MutationObserver(function () {
            startPollingIfVisible();
        });

        observer.observe(document.body, { childList: true, subtree: true });

        startPollingIfVisible();

        return {
            observer,
            stopPolling,
        };
    },
});