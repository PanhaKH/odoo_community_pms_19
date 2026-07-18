/** @odoo-module */

import { ProductScreen } from "@point_of_sale/app/screens/product_screen/product_screen";
import { patch } from "@web/core/utils/patch";
import { AlertDialog } from "@web/core/confirmation_dialog/confirmation_dialog";
import { _t } from "@web/core/l10n/translation";
import { onMounted, onPatched } from "@odoo/owl";

patch(ProductScreen.prototype, {
    setup() {
        super.setup(...arguments);
        onMounted(() => this._ehKdsInstallShowKitchenStatusButton());
        onPatched(() => this._ehKdsInstallShowKitchenStatusButton());
    },

    _ehKdsInstallShowKitchenStatusButton() {
        const controlBar = document.querySelector(
            ".product-screen .control-buttons:not(.control-buttons-modal)"
        );
        if (!controlBar || controlBar.querySelector(".o_eh_kds_show_status_btn")) {
            return;
        }
        controlBar.style.flexWrap = "wrap";

        const button = document.createElement("button");
        button.type = "button";
        button.className = "btn btn-secondary btn-sm o_eh_kds_show_status_btn";
        button.title = _t("Sent to Kitchen");
        button.style.padding = "0.44rem 0.72rem";
        button.style.fontSize = "0.92rem";
        button.style.lineHeight = "1.2";
        button.style.minWidth = "0";
        button.style.width = "100%";
        button.style.flex = "1 0 100%";
        button.style.order = "20";
        button.style.whiteSpace = "nowrap";
        button.innerHTML = `<i class="fa fa-cutlery me-1" aria-hidden="true"></i>${_t("Sent to Kitchen")}`;
        button.addEventListener("click", () => this._ehKdsShowKitchenStatus());

        controlBar.appendChild(button);
        this._ehKdsRefreshShowKitchenStatusButton();
    },

    _ehKdsRefreshShowKitchenStatusButton() {
        const button = document.querySelector(".product-screen .o_eh_kds_show_status_btn");
        if (!button) {
            return;
        }
        const order = this.pos.getOrder();
        button.disabled = !order || order.isEmpty() || order.isRefund;
    },

    async _ehKdsShowKitchenStatus() {
        const order = this.pos.getOrder();
        if (!order || order.isEmpty()) {
            this.dialog.add(AlertDialog, {
                title: _t("No Order"),
                body: _t("Please add items before sending the order to the kitchen."),
            });
            return;
        }
        if (order.isRefund) {
            this.dialog.add(AlertDialog, {
                title: _t("Refund Order"),
                body: _t("Refund orders cannot be sent to the Kitchen Display."),
            });
            return;
        }

        this.ui.block();
        try {
            if (this.pos.ensureGuestCustomerCount) {
                await this.pos.ensureGuestCustomerCount(order, false);
            }

            if (this.pos.sendOrderInPreparationUpdateLastChange) {
                await this.pos.sendOrderInPreparationUpdateLastChange(order, {});
            } else if (this.pos.sendOrderInPreparation) {
                await this.pos.sendOrderInPreparation(order, { explicitReprint: true });
            }

            this.pos.addPendingOrder([order.id]);
            await this.pos.syncAllOrders({ orders: [order], force: true, throw: true });
            const result = await this.pos.data.call(
                "pos.order",
                "eh_kds_show_kitchen_status_by_uuid",
                [order.uuid],
                {},
                false
            );
            const status = result?.[0] || {};
            if (!status.ok) {
                throw new Error(status.message || "Kitchen Display route failed");
            }
            this.notification.add(_t("Order sent to Kitchen Display: In Queue"), {
                type: "success",
            });
        } catch {
            this.dialog.add(AlertDialog, {
                title: _t("Kitchen Display"),
                body: _t(
                    "The order could not be sent to the Kitchen Display. Please check the network and kitchen routing setup."
                ),
            });
        } finally {
            this.ui.unblock();
            this._ehKdsRefreshShowKitchenStatusButton();
        }
    },
});
