/** @odoo-module */

import { PaymentScreen } from "@point_of_sale/app/screens/payment_screen/payment_screen";
import { patch } from "@web/core/utils/patch";
import { useService } from "@web/core/utils/hooks";
import { AlertDialog } from "@web/core/confirmation_dialog/confirmation_dialog";
import { Dialog } from "@web/core/dialog/dialog";
import { Component, useState } from "@odoo/owl";
import { makeAwaitable } from "@point_of_sale/app/utils/make_awaitable_dialog";

// =================================================================
// 1. THE BUG FIX: Upgraded Search Popup
// =================================================================
export class RoomSearchPopup extends Component {
    static template = "hotel_management.RoomSearchPopup";
    static components = { Dialog };
    static props = {
        close: Function,
        getPayload: Function,
        list: { type: Array, optional: true },
        title: { type: String, optional: true },
    };
    static defaultProps = {
        list: [],
        title: "Search Room or Guest Name",
    };

    setup() {
        this.state = useState({ searchString: '' });
    }

    get filteredList() {
        if (!this.state.searchString) return this.props.list;
        const lowerSearch = this.state.searchString.toLowerCase();
        return this.props.list.filter(item => item.label.toLowerCase().includes(lowerSearch));
    }

    selectItem(item) {
        this.props.getPayload(item.item);
        this.props.close();
    }
}

// =================================================================
// 2. PATCH THE PAYMENT SCREEN
// =================================================================
patch(PaymentScreen.prototype, {
    setup() {
        super.setup();
        this.orm = useService("orm");
        this.dialog = useService("dialog");
    },

    async addNewPaymentLine(paymentMethod) {
        if (paymentMethod.is_room_charge) {
            
            const guests = await this.orm.call("pos.order", "get_inhouse_guests", []);
            
            if (!guests || guests.length === 0) {
                this.dialog.add(AlertDialog, {
                    title: "No Guests Found",
                    body: "There are no guests currently checked in.",
                });
                return;
            }

            const selectionList = guests.map(g => ({
                id: g.id,
                label: g.name,
                item: g,
            }));

            const selectedGuest = await makeAwaitable(this.dialog, RoomSearchPopup, {
                title: "Search Room or Guest Name",
                list: selectionList,
            });

            // THE SHIELD: Ensure selectedGuest actually exists before reading .id!
            if (selectedGuest) {
                const result = await super.addNewPaymentLine(paymentMethod);
                const paymentLine = this.currentOrder.getSelectedPaymentline();
                if (paymentLine) {
                    paymentLine.transaction_id = selectedGuest.id.toString();
                }
                return result;
            } else {
                return; // Waiter clicked Cancel or hit enter on an empty search
            }
        }

        return super.addNewPaymentLine(paymentMethod);
    }
});
