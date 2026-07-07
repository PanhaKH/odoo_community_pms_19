/** @odoo-module **/

import { registry } from "@web/core/registry";
import { _t } from "@web/core/l10n/translation";

function isTypingTarget(target) {
    if (!target) {
        return false;
    }

    const tagName = (target.tagName || "").toLowerCase();

    return (
        tagName === "input" ||
        tagName === "textarea" ||
        tagName === "select" ||
        target.isContentEditable
    );
}

registry.category("services").add("hotel_esc_dashboard_shortcut", {
    dependencies: ["action", "orm", "notification"],

    start(env, { action, orm, notification }) {
        // Avoid duplicate listener after asset reload
        if (window.__hotelEscDashboardShortcutInstalled) {
            return {};
        }
        window.__hotelEscDashboardShortcutInstalled = true;

        let openingDashboard = false;
        let lastEscTime = 0;

        async function openHotelDashboard() {
            if (openingDashboard) {
                return;
            }

            openingDashboard = true;

            try {
                const dashboardId = await orm.call(
                    "hotel.dashboard",
                    "get_main_dashboard",
                    [],
                    {}
                );

                await action.doAction(
                    {
                        type: "ir.actions.act_window",
                        name: _t("Hotel Dashboard"),
                        res_model: "hotel.dashboard",
                        res_id: dashboardId,
                        views: [[false, "form"]],
                        view_mode: "form",
                        target: "current",
                    },
                    {
                        // Important:
                        // This resets breadcrumb instead of adding another dashboard level.
                        clearBreadcrumbs: true,

                        // Extra safety for Odoo versions that support replacing current action.
                        replaceLastAction: true,
                    }
                );
            } catch (error) {
                console.error("Hotel Esc Dashboard Shortcut Error:", error);
                notification.add(
                    _t("Could not open Hotel Dashboard."),
                    { type: "warning" }
                );
            } finally {
                openingDashboard = false;
            }
        }

        document.addEventListener("keydown", function (ev) {
            if (ev.key !== "Escape") {
                return;
            }

            // Prevent repeated fast Esc press from stacking actions
            const now = Date.now();
            if (now - lastEscTime < 700) {
                ev.preventDefault();
                ev.stopPropagation();
                return;
            }
            lastEscTime = now;

            // Do not trigger with Ctrl/Alt/Shift/Command
            if (ev.ctrlKey || ev.altKey || ev.shiftKey || ev.metaKey) {
                return;
            }

            // Do not trigger while user is typing
            if (isTypingTarget(ev.target)) {
                return;
            }

            // Keep normal Esc behavior for dialogs, popups, dropdowns
            if (
                document.querySelector(".modal.show") ||
                document.querySelector(".o_dialog") ||
                document.querySelector(".dropdown-menu.show") ||
                document.querySelector(".o_popover")
            ) {
                return;
            }

            ev.preventDefault();
            ev.stopPropagation();

            openHotelDashboard();
        });

        return {};
    },
});