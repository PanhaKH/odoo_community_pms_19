(() => {
    const DATE_ERROR = "Check-out date must be later than the check-in date.";

    function valuesAreValid(checkinInput, checkoutInput) {
        return Boolean(
            checkinInput &&
            checkoutInput &&
            checkinInput.value &&
            checkoutInput.value &&
            checkinInput.value < checkoutInput.value
        );
    }

    function requiredFieldsAreComplete(form) {
        return Array.from(form.querySelectorAll("[required]")).every((field) => {
            return field.disabled || String(field.value || "").trim();
        });
    }

    function setRequiredWarning(form, show) {
        const requiredFields = Array.from(form.querySelectorAll("[required]"));
        requiredFields.forEach((field) => {
            const empty = !String(field.value || "").trim();
            field.classList.toggle("is-invalid", show && empty);
        });
        const warning = form.querySelector("[data-contact-warning]");
        if (warning) {
            warning.classList.toggle("is-visible", show);
        }
    }

    function emailIsValid(form) {
        const emailInput = form.querySelector('input[name="guest_email"]');
        if (!emailInput || !String(emailInput.value || "").trim()) {
            return true;
        }
        return emailInput.checkValidity();
    }

    function setEmailWarning(form, show) {
        const emailInput = form.querySelector('input[name="guest_email"]');
        const valid = emailIsValid(form);
        if (emailInput) {
            emailInput.classList.toggle("is-invalid", show && !valid);
        }
        const warning = form.querySelector("[data-email-warning]");
        if (warning) {
            warning.classList.toggle("is-visible", show && !valid);
        }
    }

    function setDateWarning(form, show) {
        const warning = form.querySelector(".hotel-date-warning");
        const checkinInput = form.querySelector('input[name="checkin"]');
        const checkoutInput = form.querySelector('input[name="checkout"]');
        if (warning) {
            warning.textContent = DATE_ERROR;
            warning.classList.toggle("is-visible", show);
        }
        [checkinInput, checkoutInput].forEach((input) => {
            if (!input) {
                return;
            }
            input.classList.toggle("is-invalid", show);
            input.setCustomValidity(show ? DATE_ERROR : "");
        });
    }

    function updateRoomDetailForm(form) {
        const checkinInput = form.querySelector('input[name="checkin"]');
        const checkoutInput = form.querySelector('input[name="checkout"]');
        const datesValid = valuesAreValid(checkinInput, checkoutInput);
        const datesComplete = Boolean(checkinInput && checkoutInput && checkinInput.value && checkoutInput.value);
        const showDateWarning = datesComplete && !datesValid;
        const requiredComplete = requiredFieldsAreComplete(form);
        const validEmail = emailIsValid(form);
        const canSubmit = datesValid && requiredComplete && validEmail;

        setDateWarning(form, showDateWarning);
        if (requiredComplete) {
            setRequiredWarning(form, false);
        }
        if (validEmail) {
            setEmailWarning(form, false);
        }
        form.querySelectorAll('[data-date-submit], button[type="submit"], input[type="submit"]').forEach((button) => {
            button.disabled = !canSubmit;
        });
        return canSubmit;
    }

    function bindRoomDetailForm(form) {
        if (form.dataset.hotelDateValidationBound === "1") {
            updateRoomDetailForm(form);
            return;
        }
        form.dataset.hotelDateValidationBound = "1";
        form.querySelectorAll('input[name="checkin"], input[name="checkout"], [required], input[name="guest_email"]').forEach((field) => {
            field.addEventListener("input", () => updateRoomDetailForm(form));
            field.addEventListener("change", () => updateRoomDetailForm(form));
        });
        form.addEventListener(
            "submit",
            (event) => {
                if (!updateRoomDetailForm(form)) {
                    event.preventDefault();
                    event.stopImmediatePropagation();
                    const checkinInput = form.querySelector('input[name="checkin"]');
                    const checkoutInput = form.querySelector('input[name="checkout"]');
                    if (checkinInput && checkoutInput && checkinInput.value && checkoutInput.value && !valuesAreValid(checkinInput, checkoutInput)) {
                        checkinInput.focus();
                    } else {
                        const emptyRequired = Array.from(form.querySelectorAll("[required]")).find((field) => {
                            return !field.disabled && !String(field.value || "").trim();
                        });
                        if (emptyRequired) {
                            setRequiredWarning(form, true);
                            emptyRequired.focus();
                        } else if (!emailIsValid(form)) {
                            setEmailWarning(form, true);
                            const emailInput = form.querySelector('input[name="guest_email"]');
                            if (emailInput) {
                                emailInput.focus();
                            }
                        }
                    }
                    return;
                }
                form.querySelectorAll('[data-date-submit], button[type="submit"], input[type="submit"]').forEach((button) => {
                    button.disabled = true;
                });
            },
            true
        );
        updateRoomDetailForm(form);
    }

    function bindForms() {
        document.querySelectorAll(".hotel-detail-book-form").forEach(bindRoomDetailForm);
    }

    document.addEventListener("DOMContentLoaded", bindForms);
    window.addEventListener("pageshow", bindForms);
    bindForms();
})();

(() => {
    const EDITOR_SELECTOR = ".editor_enable, .o_is_editing";
    const EDITOR_PANEL_SELECTOR = ".o_we_customize_panel, .o_we_customize_panel_wrapper";
    const OE_ATTRIBUTES = ["data-oe-model", "data-oe-id", "data-oe-field", "data-oe-type", "data-oe-expression"];

    function isWebsiteEditor() {
        const search = window.location.search || "";
        const embeddedInEditor = window.self !== window.top;
        let parentHasEditor = false;
        try {
            parentHasEditor = Boolean(
                embeddedInEditor &&
                window.parent &&
                window.parent.document &&
                window.parent.document.querySelector(".o_we_customize_panel, .o_we_customize_panel_wrapper, .o_website_preview, .o_edit_website_container")
            );
        } catch (error) {
            parentHasEditor = embeddedInEditor;
        }
        return Boolean(
            (document.body && (document.body.classList.contains("editor_enable") || document.body.classList.contains("o_is_editing"))) ||
            document.documentElement.classList.contains("editor_enable") ||
            document.documentElement.classList.contains("o_is_editing") ||
            document.querySelector(EDITOR_PANEL_SELECTOR) ||
            parentHasEditor ||
            embeddedInEditor ||
            search.includes("enable_editor=1") ||
            search.includes("edit_translations")
        );
    }

    function galleryEditorEnabled(gallery) {
        return gallery && (
            gallery.dataset.galleryEditorEnabled === "1" ||
            gallery.classList.contains("is-editor-gallery") ||
            isWebsiteEditor()
        );
    }

    function getGallery(element) {
        return element ? element.closest(".hotel-detail-gallery") : null;
    }

    function getThumbnails(gallery) {
        return Array.from(gallery.querySelectorAll(".hotel-detail-thumbs img"));
    }

    function getThumbnailItems(gallery) {
        return Array.from(gallery.querySelectorAll(".hotel-detail-thumbs .hotel-editable-image"));
    }

    function normalizeIndex(index, total) {
        return ((index % total) + total) % total;
    }

    function syncEditableMetadata(mainImage, mainImageField, thumbnail, thumbnailField) {
        OE_ATTRIBUTES.forEach((attribute) => {
            const galleryAttr = attribute.replace("data-oe-", "data-gallery-oe-");
            const value = thumbnail.getAttribute(galleryAttr) || (thumbnailField && thumbnailField.getAttribute(galleryAttr));
            if (value) {
                mainImage.setAttribute(attribute, value);
                if (mainImageField) {
                    mainImageField.setAttribute(attribute, value);
                }
            } else {
                mainImage.removeAttribute(attribute);
                if (mainImageField) {
                    mainImageField.removeAttribute(attribute);
                }
            }
        });
    }

    function setActiveGalleryImage(gallery, nextIndex) {
        const mainImage = gallery.querySelector(".hotel-gallery-current");
        const thumbnails = getThumbnails(gallery);
        if (!mainImage || !thumbnails.length) {
            return;
        }

        const currentImageIndex = normalizeIndex(nextIndex, thumbnails.length);
        const thumbnail = thumbnails[currentImageIndex];
        const thumbnailField = thumbnail.closest(".hotel-editable-image");
        const mainImageField = mainImage.closest(".hotel-editable-image");

        gallery.dataset.currentImageIndex = String(currentImageIndex);
        mainImage.src = thumbnail.dataset.gallerySrc || thumbnail.currentSrc || thumbnail.src;
        mainImage.alt = thumbnail.alt || mainImage.alt || "";
        syncEditableMetadata(mainImage, mainImageField, thumbnail, thumbnailField);

        thumbnails.forEach((item, index) => {
            const isActive = index === currentImageIndex;
            item.classList.toggle("is-active", isActive);
            item.setAttribute("aria-current", isActive ? "true" : "false");
            const wrapper = item.closest(".hotel-editable-image");
            if (wrapper) {
                wrapper.classList.toggle("is-active", isActive);
            }
        });
    }

    function getCurrentIndex(gallery) {
        const storedIndex = parseInt(gallery.dataset.currentImageIndex, 10);
        if (Number.isInteger(storedIndex)) {
            return storedIndex;
        }
        const thumbnails = getThumbnails(gallery);
        const activeIndex = thumbnails.findIndex((thumbnail) => thumbnail.classList.contains("is-active"));
        return activeIndex >= 0 ? activeIndex : 0;
    }

    function handleGalleryClick(event) {
        const editorControl = event.target.closest(".hotel-gallery-editor-delete, .hotel-gallery-editor-drag");
        if (editorControl) {
            return;
        }

        const previousButton = event.target.closest(".hotel-gallery-prev");
        const nextButton = event.target.closest(".hotel-gallery-next");
        const thumbnail = event.target.closest(".hotel-detail-thumbs img");
        const thumbnailWrapper = event.target.closest(".hotel-detail-thumbs .hotel-editable-image");
        const trigger = previousButton || nextButton || thumbnail || thumbnailWrapper;
        if (!trigger) {
            return;
        }

        const gallery = getGallery(trigger);
        if (!gallery) {
            return;
        }

        const editorMode = isWebsiteEditor();
        if (!editorMode || previousButton || nextButton) {
            event.preventDefault();
            event.stopPropagation();
            event.stopImmediatePropagation();
        }

        const thumbnails = getThumbnails(gallery);
        if (!thumbnails.length) {
            return;
        }

        if (thumbnail || thumbnailWrapper) {
            const img = thumbnail || thumbnailWrapper.querySelector("img");
            if (img) {
                const thumbnailIndex = thumbnails.indexOf(img);
                if (thumbnailIndex >= 0) {
                    setActiveGalleryImage(gallery, thumbnailIndex);
                }
            }
            return;
        }

        const currentIndex = getCurrentIndex(gallery);
        setActiveGalleryImage(gallery, nextButton ? currentIndex + 1 : currentIndex - 1);
    }

    function postForm(url, fields) {
        const body = new FormData();
        Object.entries(fields).forEach(([key, value]) => {
            body.append(key, value);
        });
        return fetch(url, {
            method: "POST",
            body,
            credentials: "same-origin",
        }).then((response) => {
            if (!response.ok) {
                throw new Error("Gallery request failed.");
            }
            return response.json();
        });
    }

    function reloadEditorPage() {
        window.location.reload();
    }

    function itemImageId(item) {
        return item.dataset.galleryImageId || (item.querySelector("img") && item.querySelector("img").dataset.galleryImageId);
    }

    function getOrderedImageIds(gallery) {
        return getThumbnailItems(gallery).map(itemImageId).filter(Boolean);
    }

    function saveGalleryOrder(gallery) {
        const orderedIds = getOrderedImageIds(gallery);
        if (!orderedIds.length) {
            return;
        }
        postForm("/hotel/gallery/image/reorder", {
            ordered_ids: JSON.stringify(orderedIds),
        }).catch(() => reloadEditorPage());
    }

    function moveItemBefore(container, draggedItem, targetItem) {
        if (!draggedItem || !targetItem || draggedItem === targetItem) {
            return;
        }
        const draggedIndex = getThumbnailItems(container.closest(".hotel-detail-gallery")).indexOf(draggedItem);
        const targetIndex = getThumbnailItems(container.closest(".hotel-detail-gallery")).indexOf(targetItem);
        container.insertBefore(draggedItem, draggedIndex < targetIndex ? targetItem.nextSibling : targetItem);
    }

    function ensureEditorItemControls(gallery, item) {
        const imageId = itemImageId(item);
        item.draggable = Boolean(imageId);
        item.classList.toggle("is-gallery-record", Boolean(imageId));
        if (!imageId || item.dataset.galleryControlsReady === "1") {
            return;
        }
        item.dataset.galleryControlsReady = "1";

        let dragButton = item.querySelector(".hotel-gallery-editor-drag");
        if (!dragButton) {
            dragButton = document.createElement("button");
            dragButton.type = "button";
            dragButton.className = "hotel-gallery-editor-drag";
            dragButton.title = "Drag to reorder";
            dragButton.setAttribute("aria-label", "Drag to reorder image");
            dragButton.innerHTML = '<i class="fa fa-arrows" aria-hidden="true"></i>';
            item.appendChild(dragButton);
        }

        let deleteButton = item.querySelector(".hotel-gallery-editor-delete");
        if (!deleteButton) {
            deleteButton = document.createElement("button");
            deleteButton.type = "button";
            deleteButton.className = "hotel-gallery-editor-delete";
            deleteButton.title = "Delete image";
            deleteButton.setAttribute("aria-label", "Delete image");
            deleteButton.innerHTML = '<i class="fa fa-trash" aria-hidden="true"></i>';
            item.appendChild(deleteButton);
        }

        deleteButton.disabled = false;
    }

    function ensureEditorControls(gallery) {
        if (!galleryEditorEnabled(gallery) || gallery.dataset.editorGalleryReady === "1") {
            return;
        }
        gallery.dataset.editorGalleryReady = "1";
        gallery.classList.add("is-editor-gallery");

        const roomTypeId = gallery.dataset.roomTypeId;
        const thumbs = gallery.querySelector(".hotel-detail-thumbs");
        if (!roomTypeId || !thumbs) {
            return;
        }

        if (!getOrderedImageIds(gallery).length && gallery.dataset.seedAttempted !== "1") {
            gallery.dataset.seedAttempted = "1";
            postForm("/hotel/gallery/image/seed", { room_type_id: roomTypeId })
                .then((result) => {
                    if (result.created) {
                        reloadEditorPage();
                    }
                })
                .catch(() => {});
        }

        getThumbnailItems(gallery).forEach((item) => {
            ensureEditorItemControls(gallery, item);
        });

        thumbs.addEventListener("click", (event) => {
            const deleteButton = event.target.closest(".hotel-gallery-editor-delete");
            if (!deleteButton || !thumbs.contains(deleteButton)) {
                return;
            }
            const item = deleteButton.closest(".hotel-editable-image.is-gallery-record");
            const imageId = item && itemImageId(item);
            if (!item || !imageId || deleteButton.disabled) {
                return;
            }
            event.preventDefault();
            event.stopPropagation();
            event.stopImmediatePropagation();
            deleteButton.disabled = true;
            postForm("/hotel/gallery/image/delete", { image_id: imageId })
                .then(() => {
                    const wasActive = item.classList.contains("is-active");
                    item.remove();
                    if (wasActive || !gallery.querySelector(".hotel-detail-thumbs .hotel-editable-image.is-active")) {
                        setActiveGalleryImage(gallery, 0);
                    }
                    saveGalleryOrder(gallery);
                })
                .catch(() => {
                    deleteButton.disabled = false;
                });
        }, true);

        getThumbnailItems(gallery).forEach((item) => {
            ensureEditorItemControls(gallery, item);
        });

        thumbs.addEventListener("dragstart", (event) => {
            const item = event.target.closest(".hotel-editable-image.is-gallery-record");
            if (!item) {
                return;
            }
            thumbs.dataset.draggingImageId = itemImageId(item);
            item.classList.add("is-dragging");
            event.dataTransfer.effectAllowed = "move";
            event.dataTransfer.setData("text/plain", thumbs.dataset.draggingImageId || "");
        });

        thumbs.addEventListener("dragover", (event) => {
            const draggedId = thumbs.dataset.draggingImageId;
            const targetItem = event.target.closest(".hotel-editable-image.is-gallery-record");
            if (!draggedId || !targetItem || !thumbs.contains(targetItem)) {
                return;
            }
            event.preventDefault();
            const draggedItem = getThumbnailItems(gallery).find((item) => itemImageId(item) === draggedId);
            moveItemBefore(thumbs, draggedItem, targetItem);
        });

        thumbs.addEventListener("dragend", () => {
            const draggedItem = thumbs.querySelector(".is-dragging");
            if (draggedItem) {
                draggedItem.classList.remove("is-dragging");
            }
            delete thumbs.dataset.draggingImageId;
            setActiveGalleryImage(gallery, 0);
            saveGalleryOrder(gallery);
        });
    }

    function initializeGalleries() {
        document.querySelectorAll(".hotel-detail-gallery").forEach((gallery) => {
            setActiveGalleryImage(gallery, getCurrentIndex(gallery));
            ensureEditorControls(gallery);
        });
    }

    document.addEventListener("click", handleGalleryClick, true);
    document.addEventListener("DOMContentLoaded", initializeGalleries);
    window.addEventListener("pageshow", initializeGalleries);
    initializeGalleries();
})();
