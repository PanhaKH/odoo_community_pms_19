/** @odoo-module **/

import { registry } from "@web/core/registry";
import { selectionField, SelectionField } from "@web/views/fields/selection/selection_field";

export class HotelBillingTargetField extends SelectionField {
    static props = {
        ...super.props,
        displayField: { type: String, optional: true },
    };

    get string() {
        if (this.props.readonly && this.props.displayField) {
            const displayValue = this.props.record.data[this.props.displayField];
            if (displayValue) {
                return displayValue;
            }
        }
        return super.string;
    }
}

export const hotelBillingTargetField = {
    ...selectionField,
    component: HotelBillingTargetField,
    extractProps({ options }) {
        const props = selectionField.extractProps(...arguments);
        props.displayField = options.display_field || "billing_target_display";
        return props;
    },
};

registry.category("fields").add("hotel_billing_target", hotelBillingTargetField);
