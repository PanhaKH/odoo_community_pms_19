/** @odoo-module **/
import { PosStore } from "@point_of_sale/app/services/pos_store";
import { patch } from "@web/core/utils/patch";
import { AlertDialog } from "@web/core/confirmation_dialog/confirmation_dialog";
import { _t } from "@web/core/l10n/translation";
import { useService } from "@web/core/utils/hooks";
import { rpc } from "@web/core/network/rpc";
import { getOnNotified } from "@point_of_sale/utils";
import { ask } from "@point_of_sale/app/utils/make_awaitable_dialog";


/*
 * Patching the Order class to add custom functionality.
 */
patch(PosStore.prototype, {
    async setup(env) {
        await super.setup(...arguments);
        console.log("PosStore",PosStore)

        this.kitchen = true;

    },
    async initServerData() {
        await this.processServerData();
        this.onNotified = getOnNotified(this.bus, this.config.access_token);
        return await this.afterProcessServerData();
    },
    async pay() {
        let order_name = this.getOrder()?.pos_reference;
        let self = this;
        const result = await rpc("/web/dataset/call_kw/pos.order/check_order",{
            model: 'pos.order', method: 'check_order',
            args: [order_name],
            kwargs: {},
        });
        if (result.category) {
            let title = "No category found for your current order in the kitchen.(" + result.category + ')';
            self.kitchen = false;
            await this.env.services.dialog.add(AlertDialog, {
                title: _t(title),
                body: _t("No food items found for the specified category for this kitchen. Kindly remove the selected food and update the order by clicking the 'Order' button. Following that, proceed with the payment."),
            });
            return false
        } else {
            self.kitchen = true;
        }

        const currentOrder = this.getOrder();

        if (!currentOrder.canPay()) {
            return;
        }

        if (
            currentOrder.lines.some(
                (line) => line.getProduct().tracking !== "none" && !line.hasValidProductLot()
            ) &&
            (this.pickingType.use_create_lots || this.pickingType.use_existing_lots)
        ) {
            const confirmed = await ask(this.env.services.dialog, {
                title: _t("Some Serial/Lot Numbers are missing"),
                body: _t(
                    "You are trying to sell products with serial/lot numbers, but some of them are not set.\nWould you like to proceed anyway?"
                ),
            });
            if (confirmed) {
                this.mobile_pane = "right";
                this.navigate("PaymentScreen", {
                    orderUuid: this.selectedOrderUuid,
                });
            }
        } else {
            this.mobile_pane = "right";
            this.navigate("PaymentScreen", {
                orderUuid: this.selectedOrderUuid,
            });
        }
    }


});
