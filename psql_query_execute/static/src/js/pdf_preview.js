/** @odoo-module **/

import { createFileViewer } from "@web/core/file_viewer/file_viewer_hook";
import { registry } from "@web/core/registry";

const actionRegistry = registry.category("actions");

actionRegistry.add("psql_query_execute.pdf_preview", (env, action) => {
    const reportUrl = action.params?.url;
    if (!reportUrl) {
        return;
    }

    const viewer = createFileViewer();
    const pdfJsUrl = `/web/static/lib/pdfjs/web/viewer.html?file=${encodeURIComponent(
        reportUrl
    )}#pagemode=none`;
    viewer.open({
        name: `${action.params?.name || "SQL Report"}.pdf`,
        mimetype: "application/pdf",
        isPdf: true,
        isViewable: true,
        defaultSource: pdfJsUrl,
        downloadUrl: reportUrl,
    });
});
