/**
 * CanvasController — manages the mood board canvas element.
 *
 * Handles drag-and-drop image uploads by listening for browser drag events
 * on the canvas.  When image files are dropped, they are uploaded to the
 * backend via the ApiClient and an optional callback is invoked so the
 * sidebar can refresh its image list.
 */
class CanvasController {

    /**
     * Create the controller and bind drag-and-drop events to the canvas.
     *
     * @param {HTMLCanvasElement} canvas - The canvas DOM element.
     * @param {ApiClient} api - The API client for backend communication.
     * @param {Function} [onUploadComplete] - Optional callback invoked
     *     after all files from a single drop have been uploaded.
     */
    constructor(canvas, api, onUploadComplete) {
        /** @type {HTMLCanvasElement} */
        this.canvas = canvas;

        /** @type {ApiClient} */
        this.api = api;

        /** @type {Function|null} */
        this._onUploadComplete = onUploadComplete || null;

        this._bindDragEvents();
    }

    /* ------------------------------------------------------------------
     *  Drag-and-drop
     * ------------------------------------------------------------------ */

    /**
     * Attach dragover, dragleave, and drop listeners to the canvas.
     *
     * Dragover is intercepted to allow drops and to provide visual
     * feedback via a CSS class.  The drop handler extracts image files
     * from the DataTransfer and uploads each one.
     * @private
     */
    _bindDragEvents() {
        this.canvas.addEventListener("dragover", (e) => {
            e.preventDefault();
            e.dataTransfer.dropEffect = "copy";
            this.canvas.classList.add("canvas--dragover");
        });

        this.canvas.addEventListener("dragleave", () => {
            this.canvas.classList.remove("canvas--dragover");
        });

        this.canvas.addEventListener("drop", (e) => {
            e.preventDefault();
            this.canvas.classList.remove("canvas--dragover");
            this._handleDrop(e.dataTransfer);
        });
    }

    /**
     * Process dropped files by uploading each image to the backend.
     *
     * Non-image files are silently ignored.  After all uploads complete
     * the onUploadComplete callback is invoked (if provided).
     *
     * @param {DataTransfer} dataTransfer - The drop event's DataTransfer.
     * @private
     */
    async _handleDrop(dataTransfer) {
        const files = Array.from(dataTransfer.files).filter((f) =>
            f.type.startsWith("image/")
        );

        if (files.length === 0) {
            return;
        }

        for (const file of files) {
            try {
                await this.api.uploadImage(file);
            } catch (err) {
                console.error(`Failed to upload ${file.name}:`, err);
            }
        }

        if (this._onUploadComplete) {
            this._onUploadComplete();
        }
    }
}
