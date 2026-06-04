/** @odoo-module **/

import { patch } from "@web/core/utils/patch";
import { FormRenderer } from "@web/views/form/form_renderer";

patch(FormRenderer.prototype, {
    mailLayout(hasAttachmentContainer) {
        const layout = super.mailLayout(hasAttachmentContainer);
        if (this.props.record.resModel !== "hotel.reservation") {
            return layout;
        }
        if (layout === "SIDE_CHATTER") {
            return "BOTTOM_CHATTER";
        }
        if (layout === "EXTERNAL_COMBO_XXL") {
            return "EXTERNAL_COMBO";
        }
        return layout;
    },
});
