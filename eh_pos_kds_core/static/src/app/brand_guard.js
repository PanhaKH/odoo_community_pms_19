/**
 * Brand guard. Two jobs, both working on a plain http kiosk (no crypto.subtle,
 * no secure context needed):
 *
 *  1. readBoot(): the display's boot config (its token) is delivered ONLY inside
 *     the server rendered brand element, as a base64 data attribute. The app
 *     reads its token from there. Delete or rename the brand element and the app
 *     has no token, so it cannot load: the attribution is load bearing.
 *
 *  2. installBrandGuard(): a light watchdog. If the brand text is ever missing
 *     from the DOM (hidden by CSS, deleted, or its text changed), a full screen
 *     watermark is painted until it is restored. Plain text comparison, so it
 *     runs everywhere, not just on https.
 *
 * None of this is DRM. The source ships readable under the licence, so a
 * determined developer can still defeat it by editing this file. The point is
 * that casual removal breaks the display and is self evident, and any removal
 * breaches the licence. See README_BRAND_PROTECTION.md.
 */

export const BRAND_OWNER = "kitchen-display";
export const BRAND_MARK = "Kitchen";

export function brandElement() {
    return document.querySelector(`[data-brand-owner="${BRAND_OWNER}"]`);
}

export function readBoot() {
    const el = brandElement();
    if (!el || !el.dataset.ehBoot) {
        return null;
    }
    try {
        return JSON.parse(atob(el.dataset.ehBoot));
    } catch {
        return null;
    }
}

export function installBrandGuard() {
    const id = "eh-brand-watermark";
    const check = () => {
        const el = brandElement();
        const present = !!el && (el.textContent || "").includes(BRAND_MARK) && isVisible(el);
        let wm = document.getElementById(id);
        if (!present && !wm) {
            wm = document.createElement("div");
            wm.id = id;
            wm.textContent = BRAND_MARK;
            wm.setAttribute(
                "style",
                "position:fixed;inset:0;display:flex;align-items:center;justify-content:center;" +
                    "font-size:9vw;font-weight:800;letter-spacing:0.04em;color:rgba(123,206,160,0.20);" +
                    "pointer-events:none;z-index:2147483647;font-family:system-ui,sans-serif;"
            );
            (document.body || document.documentElement).appendChild(wm);
        } else if (present && wm) {
            wm.remove();
        }
    };
    check();
    return setInterval(check, 5000);
}

function isVisible(el) {
    const s = window.getComputedStyle(el);
    if (s.display === "none" || s.visibility === "hidden" || parseFloat(s.opacity) < 0.05) {
        return false;
    }
    const r = el.getBoundingClientRect();
    return r.width > 1 && r.height > 1;
}
