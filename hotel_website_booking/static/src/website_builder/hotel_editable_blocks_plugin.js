import { Plugin } from "@html_editor/plugin";
import { withSequence } from "@html_editor/utils/resource";
import { registry } from "@web/core/registry";

const HOTEL_BLOCK_SELECTOR = "[data-hotel-editable-block]";

class HotelEditableBlocksPlugin extends Plugin {
    static id = "hotelEditableBlocksPlugin";
    static dependencies = ["builderOptions", "history"];

    resources = {
        has_overlay_options: {
            hasOption: (el) => this.isHotelBlock(el),
        },
        get_overlay_buttons: withSequence(2, {
            getButtons: this.getOverlayButtons.bind(this),
        }),
        get_options_container_top_buttons: this.getOptionsContainerButtons.bind(this),
    };

    isHotelBlock(el) {
        return Boolean(el?.matches?.(HOTEL_BLOCK_SELECTOR));
    }

    getOverlayButtons(target) {
        if (!this.isHotelBlock(target)) {
            return [];
        }
        return [this.getRemoveButton(target)];
    }

    getOptionsContainerButtons(target) {
        if (!this.isHotelBlock(target)) {
            return [];
        }
        return [this.getRemoveButton(target)];
    }

    getRemoveButton(target) {
        return {
            class: "oe_snippet_remove bg-danger fa fa-trash",
            title: "Remove this hotel block",
            handler: () => this.removeBlock(target),
        };
    }

    removeBlock(target) {
        const nextTarget = target.previousElementSibling || target.nextElementSibling || target.parentElement;
        target.remove();
        if (nextTarget) {
            this.dependencies.builderOptions.setNextTarget(nextTarget);
        }
        this.dependencies.history.addStep();
    }
}

registry.category("website-plugins").add(HotelEditableBlocksPlugin.id, HotelEditableBlocksPlugin);
