/** @odoo-module */

import { PaymentScreen } from "@point_of_sale/app/screens/payment_screen/payment_screen";
import { patch } from "@web/core/utils/patch";
import { AlertDialog } from "@web/core/confirmation_dialog/confirmation_dialog";
import { _t } from "@web/core/l10n/translation";

patch(PaymentScreen.prototype, {
    async validateOrder(isForceValidate = false) {
        if (this.currentOrder && (this.currentOrder.is_posted_to_room || this.currentOrder.raw?.is_posted_to_room)) {
            await this.dialog.add(AlertDialog, {
                title: _t("Already Posted to Room"),
                body: _t("Already posted to room."),
            });
        }
        return await super.validateOrder(isForceValidate);
    }
});
