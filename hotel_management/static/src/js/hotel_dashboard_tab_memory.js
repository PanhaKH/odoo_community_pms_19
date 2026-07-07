/** @odoo-module **/

import { registry } from "@web/core/registry";

const STORAGE_KEY = "hotel_dashboard_active_tab_label";
const PERFORMANCE_TAB_LABEL = "Rooms & Performance";

function cleanText(el) {
    return (el && el.textContent ? el.textContent : "").replace(/\s+/g, " ").trim();
}

function findTabByLabel(label) {
    const tabs = document.querySelectorAll(
        ".o_form_view .nav-tabs .nav-link, .o_form_view [role='tab']"
    );

    for (const tab of tabs) {
        if (cleanText(tab) === label) {
            return tab;
        }
    }

    return null;
}

function restoreDashboardTab() {
    const wantedLabel = sessionStorage.getItem(STORAGE_KEY);
    if (!wantedLabel) {
        return;
    }

    const tab = findTabByLabel(wantedLabel);
    if (tab && !tab.classList.contains("active")) {
        tab.click();
    }
}

function scheduleRestore() {
    setTimeout(restoreDashboardTab, 200);
    setTimeout(restoreDashboardTab, 600);
    setTimeout(restoreDashboardTab, 1200);
}

registry.category("services").add("hotel_dashboard_tab_memory", {
    start() {
        if (window.__hotelDashboardTabMemoryInstalled) {
            return {};
        }
        window.__hotelDashboardTabMemoryInstalled = true;

        document.addEventListener("click", function (ev) {
            const target = ev.target;

            // Remember when user manually clicks dashboard notebook tab
            const tab = target.closest(".o_form_view .nav-tabs .nav-link, .o_form_view [role='tab']");
            if (tab) {
                const label = cleanText(tab);
                if (label) {
                    sessionStorage.setItem(STORAGE_KEY, label);
                }
            }

            // Before performance date buttons reload dashboard, force target tab
            const button = target.closest("button[name]");
            if (button) {
                const buttonName = button.getAttribute("name");

                if (
                    buttonName === "action_performance_date_prev" ||
                    buttonName === "action_performance_date_next" ||
                    buttonName === "action_performance_date_today" ||
                    buttonName === "action_open_performance_date_wizard" ||
                    buttonName === "action_apply"
                ) {
                    sessionStorage.setItem(STORAGE_KEY, PERFORMANCE_TAB_LABEL);
                }
            }
        }, true);

        // Restore after page/action reload
        scheduleRestore();

        // Restore after Odoo dynamically re-renders form
        const observer = new MutationObserver(function () {
            scheduleRestore();
        });

        observer.observe(document.body, {
            childList: true,
            subtree: true,
        });

        return {};
    },
});