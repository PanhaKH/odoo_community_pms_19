/** @odoo-module **/

import { registry } from "@web/core/registry";

const QR_DIALOG_TITLE = "Express QR Check-In";
const MIN_TOKEN_LENGTH = 6;
const AUTO_FIND_DELAY = 500;

// Keep submitted tokens at browser level.
// This prevents repeated auto-click even if Odoo refreshes/re-renders the dialog.
const submittedTokens = new Set();

function clean(value) {
    return (value || "").trim();
}

function isVisible(el) {
    return !!(el && el.offsetParent !== null);
}

function findQrDialog() {
    const dialogs = document.querySelectorAll(".modal.show, .modal, .o_dialog");
    for (const dialog of dialogs) {
        const text = clean(dialog.textContent);
        if (text.includes(QR_DIALOG_TITLE)) {
            return dialog;
        }
    }
    return null;
}

function findTokenInput(dialog) {
    if (!dialog) {
        return null;
    }

    return (
        dialog.querySelector("input[placeholder='Paste Token Here...']") ||
        dialog.querySelector("input[placeholder*='Token']") ||
        dialog.querySelector("input[placeholder*='token']") ||
        dialog.querySelector("input[type='text']")
    );
}

function findFindGuestButton(dialog) {
    if (!dialog) {
        return null;
    }

    const buttons = dialog.querySelectorAll("button, .btn");
    for (const button of buttons) {
        const label = clean(button.textContent).toLowerCase();
        const name = clean(button.getAttribute("name")).toLowerCase();

        if (
            label === "find guest" ||
            label.includes("find guest") ||
            name.includes("find_guest") ||
            name.includes("find")
        ) {
            return button;
        }
    }

    return null;
}

registry.category("services").add("hotel_qr_auto_find_guest", {
    start() {
        if (window.__hotelQrAutoFindInstalled) {
            return {};
        }
        window.__hotelQrAutoFindInstalled = true;

        let timer = null;

        function scheduleAutoFind(input) {
            clearTimeout(timer);

            timer = setTimeout(function () {
                const dialog = findQrDialog();
                if (!dialog) {
                    return;
                }

                const currentInput = findTokenInput(dialog);
                const button = findFindGuestButton(dialog);

                if (!currentInput || !button) {
                    return;
                }

                const token = clean(currentInput.value);

                if (!token || token.length < MIN_TOKEN_LENGTH) {
                    return;
                }

                // Main protection: same token auto-submit only one time.
                if (submittedTokens.has(token)) {
                    return;
                }

                if (button.disabled || button.classList.contains("disabled") || !isVisible(button)) {
                    return;
                }

                submittedTokens.add(token);
                button.click();
            }, AUTO_FIND_DELAY);
        }

        function handleTokenEvent(ev) {
            const dialog = findQrDialog();
            if (!dialog || !dialog.contains(ev.target)) {
                return;
            }

            const input = findTokenInput(dialog);
            if (!input || ev.target !== input) {
                return;
            }

            scheduleAutoFind(input);
        }

        document.addEventListener("input", handleTokenEvent, true);
        document.addEventListener("change", handleTokenEvent, true);
        document.addEventListener("keyup", handleTokenEvent, true);

        document.addEventListener(
            "paste",
            function (ev) {
                const dialog = findQrDialog();
                if (!dialog || !dialog.contains(ev.target)) {
                    return;
                }

                const input = findTokenInput(dialog);
                if (input && ev.target === input) {
                    setTimeout(function () {
                        scheduleAutoFind(input);
                    }, 100);
                }
            },
            true
        );

        return {};
    },
});