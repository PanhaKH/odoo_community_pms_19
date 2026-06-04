/** @odoo-module **/
import { registry } from "@web/core/registry";

export function startScanner() {
    const video = document.getElementById('preview');
    const canvasElement = document.createElement("canvas");
    const canvas = canvasElement.getContext("2d", { willReadFrequently: true });

    if (navigator.mediaDevices && navigator.mediaDevices.getUserMedia) {
        navigator.mediaDevices.getUserMedia({ video: { facingMode: "environment" } }).then(function(stream) {
            video.srcObject = stream;
            video.setAttribute("playsinline", true);
            video.play();
            requestAnimationFrame(tick);
        });
    }

    function tick() {
        if (video.readyState === video.HAVE_ENOUGH_DATA) {
            canvasElement.height = video.videoHeight;
            canvasElement.width = video.videoWidth;
            canvas.drawImage(video, 0, 0, canvasElement.width, canvasElement.height);
            
            const imageData = canvas.getImageData(0, 0, canvasElement.width, canvasElement.height);
            // We use a free, lightweight external library to read the QR squares
            const code = window.jsQR ? window.jsQR(imageData.data, imageData.width, imageData.height, { inversionAttempts: "dontInvert" }) : null;

            if (code) {
                // SUCCESS! Found the token.
                const inputField = document.querySelector('input[name="access_token"]');
                if (inputField) {
                    inputField.value = code.data;
                    // Trigger Odoo's Python search
                    inputField.dispatchEvent(new Event('change', { bubbles: true }));
                    
                    // Stop the camera once found to save battery
                    video.srcObject.getTracks().forEach(track => track.stop());
                    return; 
                }
            }
        }
        requestAnimationFrame(tick);
    }
}

// THIS PART TRIGGERS THE CAMERA AUTOMATICALLY
registry.category("actions").add("action_start_hotel_camera", {
    async start() {
        setTimeout(() => { startScanner(); }, 500); // Wait 0.5s for pop-up animation to finish
    }
});