/**
 * CanvasController — manages the mood board canvas element.
 *
 * Renders images and placeholders on an HTML5 canvas using a 2D drawing
 * context.  Handles drag-and-drop uploads: when files are dropped a white
 * placeholder rectangle (1/3 of the canvas dimensions) is shown immediately
 * at the cursor position while the upload runs in the background.  Once the
 * image is available the placeholder is replaced with the actual image,
 * fitted to the placeholder bounds while preserving the original aspect
 * ratio.  Multiple concurrent uploads are supported.
 */
class CanvasController {

    /**
     * Create the controller, set up the canvas context, and start rendering.
     *
     * @param {HTMLCanvasElement} canvas - The canvas DOM element.
     * @param {ApiClient} api - The API client for backend communication.
     * @param {Object} options - Configuration options.
     * @param {Function} [options.onUploadComplete] - Callback invoked after
     *     each individual image upload completes (e.g. to refresh sidebar).
     * @param {Function} [options.getProjectName] - Returns the current
     *     project name, used to build image URLs.
     */
    constructor(canvas, api, options = {}) {
        /** @type {HTMLCanvasElement} */
        this.canvas = canvas;

        /** @type {CanvasRenderingContext2D} */
        this.ctx = canvas.getContext("2d");

        /** @type {ApiClient} */
        this.api = api;

        /** @type {Function|null} */
        this._onUploadComplete = options.onUploadComplete || null;

        /** @type {Function|null} */
        this._getProjectName = options.getProjectName || null;

        /**
         * Array of canvas items (placeholders and loaded images).
         * Each item has: { id, x, y, width, height, type, img, imageRecord }
         * @type {Array<Object>}
         */
        this._items = [];

        /** @type {number} Counter for generating temporary item IDs. */
        this._nextTempId = 1;

        /** @type {boolean} Whether a render has been scheduled. */
        this._renderScheduled = false;

        this._syncCanvasSize();
        this._bindDragEvents();
        this._bindResizeEvent();
        this._scheduleRender();
    }

    /* ------------------------------------------------------------------
     *  Canvas sizing
     * ------------------------------------------------------------------ */

    /**
     * Match the canvas drawing buffer to its CSS layout size.
     *
     * The canvas element stretches via CSS but the drawing buffer must
     * be explicitly sized to avoid blurry rendering.
     * @private
     */
    _syncCanvasSize() {
        const rect = this.canvas.getBoundingClientRect();
        this.canvas.width = rect.width;
        this.canvas.height = rect.height;
    }

    /**
     * Listen for window resize events and re-sync the canvas size.
     * @private
     */
    _bindResizeEvent() {
        window.addEventListener("resize", () => {
            this._syncCanvasSize();
            this._scheduleRender();
        });
    }

    /* ------------------------------------------------------------------
     *  Rendering
     * ------------------------------------------------------------------ */

    /**
     * Schedule a single render on the next animation frame.
     *
     * Multiple calls between frames are coalesced into one render pass.
     * @private
     */
    _scheduleRender() {
        if (this._renderScheduled) {
            return;
        }
        this._renderScheduled = true;
        requestAnimationFrame(() => {
            this._renderScheduled = false;
            this._render();
        });
    }

    /**
     * Clear the canvas and draw all items (placeholders and images).
     *
     * Items are drawn in array order — items added later appear on top.
     * Placeholders are white filled rectangles.  Images are drawn with
     * drawImage fitted to their bounding box.
     * @private
     */
    _render() {
        const { ctx, canvas } = this;
        ctx.clearRect(0, 0, canvas.width, canvas.height);

        for (const item of this._items) {
            if (item.type === "placeholder") {
                ctx.fillStyle = "#ffffff";
                ctx.fillRect(item.x, item.y, item.width, item.height);
            } else if (item.type === "image" && item.img) {
                ctx.drawImage(item.img, item.x, item.y, item.width, item.height);
            }
        }
    }

    /* ------------------------------------------------------------------
     *  Drag-and-drop
     * ------------------------------------------------------------------ */

    /**
     * Attach dragover, dragleave, and drop listeners to the canvas.
     *
     * Dragover is intercepted to allow drops and to provide visual
     * feedback via a CSS class.  The drop handler records the cursor
     * position and starts the upload pipeline for each image file.
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
            this._handleDrop(e);
        });
    }

    /**
     * Process a drop event by creating placeholders and uploading files.
     *
     * For each dropped image file a white placeholder is immediately
     * placed at the cursor position.  The upload and image loading then
     * proceed asynchronously — each file is handled independently so
     * multiple concurrent uploads work without blocking each other.
     *
     * @param {DragEvent} event - The native drop event.
     * @private
     */
    _handleDrop(event) {
        const files = Array.from(event.dataTransfer.files).filter((f) =>
            f.type.startsWith("image/")
        );

        if (files.length === 0) {
            return;
        }

        /* Compute drop position relative to the canvas element. */
        const rect = this.canvas.getBoundingClientRect();
        const dropX = event.clientX - rect.left;
        const dropY = event.clientY - rect.top;

        for (const file of files) {
            this._uploadAndDisplay(file, dropX, dropY);
        }
    }

    /**
     * Upload a single file and transition its placeholder to a real image.
     *
     * 1. Create a white placeholder centred on (dropX, dropY).
     * 2. Upload the file via the API (async, non-blocking).
     * 3. On success, load the image from the server.
     * 4. Fit the image into the placeholder bounds (aspect ratio preserved).
     * 5. Persist the computed position back to the database.
     *
     * @param {File} file - The image file to upload.
     * @param {number} dropX - X position of the drop in canvas coordinates.
     * @param {number} dropY - Y position of the drop in canvas coordinates.
     * @private
     */
    _uploadAndDisplay(file, dropX, dropY) {
        /* Create placeholder. */
        const placeholderW = this.canvas.width / 3;
        const placeholderH = this.canvas.height / 3;
        const item = {
            id: `temp_${this._nextTempId++}`,
            x: dropX - placeholderW / 2,
            y: dropY - placeholderH / 2,
            width: placeholderW,
            height: placeholderH,
            type: "placeholder",
            img: null,
            imageRecord: null,
        };

        this._items.push(item);
        this._scheduleRender();

        /* Upload then load — entirely async. */
        this.api.uploadImage(file)
            .then((record) => {
                item.imageRecord = record;
                return this._loadImage(record);
            })
            .then((img) => {
                /* Fit image within the placeholder bounds. */
                const fitted = this._fitImage(
                    img.naturalWidth,
                    img.naturalHeight,
                    item.x + item.width / 2,
                    item.y + item.height / 2,
                    placeholderW,
                    placeholderH
                );

                item.type = "image";
                item.img = img;
                item.x = fitted.x;
                item.y = fitted.y;
                item.width = fitted.width;
                item.height = fitted.height;
                item.id = item.imageRecord.id;

                this._scheduleRender();

                /* Persist position to the database. */
                this.api.updateImage(item.imageRecord.id, {
                    pos_x: item.x,
                    pos_y: item.y,
                    scale: item.width / img.naturalWidth,
                }).catch((err) => {
                    console.error("Failed to persist image position:", err);
                });

                /* Notify sidebar to refresh its image list. */
                if (this._onUploadComplete) {
                    this._onUploadComplete();
                }
            })
            .catch((err) => {
                console.error(`Failed to upload/display ${file.name}:`, err);
                /* Remove the failed placeholder. */
                const idx = this._items.indexOf(item);
                if (idx !== -1) {
                    this._items.splice(idx, 1);
                    this._scheduleRender();
                }
            });
    }

    /* ------------------------------------------------------------------
     *  Image loading
     * ------------------------------------------------------------------ */

    /**
     * Load an image from the server given an image database record.
     *
     * Builds the URL from the current project name and the record's
     * filename, then returns a promise that resolves with the loaded
     * HTMLImageElement.
     *
     * @param {Object} record - The image database record (needs ``filename``).
     * @returns {Promise<HTMLImageElement>} The loaded image element.
     * @private
     */
    _loadImage(record) {
        return new Promise((resolve, reject) => {
            const img = new Image();
            img.onload = () => resolve(img);
            img.onerror = () => reject(new Error(`Failed to load image: ${record.filename}`));

            const projectName = this._getProjectName
                ? this._getProjectName()
                : "Untitled Project";
            img.src = `/projects/${encodeURIComponent(projectName)}/${encodeURIComponent(record.filename)}`;
        });
    }

    /**
     * Compute fitted dimensions for an image within a bounding box.
     *
     * The image is scaled to fit entirely within the placeholder while
     * maintaining its original aspect ratio, then centred on the given
     * centre point.
     *
     * @param {number} naturalW - The image's natural width.
     * @param {number} naturalH - The image's natural height.
     * @param {number} centerX - The X coordinate of the placeholder centre.
     * @param {number} centerY - The Y coordinate of the placeholder centre.
     * @param {number} boxW - The placeholder width.
     * @param {number} boxH - The placeholder height.
     * @returns {{ x: number, y: number, width: number, height: number }}
     * @private
     */
    _fitImage(naturalW, naturalH, centerX, centerY, boxW, boxH) {
        const imgRatio = naturalW / naturalH;
        const boxRatio = boxW / boxH;

        let fitW, fitH;
        if (imgRatio > boxRatio) {
            fitW = boxW;
            fitH = boxW / imgRatio;
        } else {
            fitH = boxH;
            fitW = boxH * imgRatio;
        }

        return {
            x: centerX - fitW / 2,
            y: centerY - fitH / 2,
            width: fitW,
            height: fitH,
        };
    }

    /* ------------------------------------------------------------------
     *  Project switching
     * ------------------------------------------------------------------ */

    /**
     * Clear all items from the canvas.
     *
     * Used when switching projects to start with a blank slate before
     * loading the new project's images.
     */
    clear() {
        this._items = [];
        this._scheduleRender();
    }

    /**
     * Load all images for the current project from the database.
     *
     * Fetches the image list from the API and creates canvas items for
     * each record, loading the actual image files from the server.
     * Items are positioned according to their stored pos_x/pos_y values.
     */
    async loadImages() {
        let images;
        try {
            images = await this.api.listImages();
        } catch (err) {
            console.error("Failed to load images:", err);
            return;
        }

        for (const record of images) {
            const item = {
                id: record.id,
                x: record.pos_x,
                y: record.pos_y,
                width: 0,
                height: 0,
                type: "placeholder",
                img: null,
                imageRecord: record,
            };

            /* If the image has been positioned before (scale != default),
               show a placeholder at that location.  Otherwise use a
               default placeholder size. */
            if (record.scale !== 1.0) {
                /* We don't know the natural size yet — show a small
                   placeholder until the image loads. */
                item.width = 100;
                item.height = 100;
            } else {
                item.width = this.canvas.width / 3;
                item.height = this.canvas.height / 3;
            }

            this._items.push(item);
            this._scheduleRender();

            /* Load the actual image asynchronously. */
            this._loadImage(record)
                .then((img) => {
                    item.type = "image";
                    item.img = img;

                    if (record.scale !== 1.0) {
                        /* Use stored scale to compute display size. */
                        item.width = img.naturalWidth * record.scale;
                        item.height = img.naturalHeight * record.scale;
                    } else {
                        /* First load — fit into placeholder bounds. */
                        const fitted = this._fitImage(
                            img.naturalWidth,
                            img.naturalHeight,
                            item.x + item.width / 2,
                            item.y + item.height / 2,
                            this.canvas.width / 3,
                            this.canvas.height / 3
                        );
                        item.x = fitted.x;
                        item.y = fitted.y;
                        item.width = fitted.width;
                        item.height = fitted.height;
                    }

                    this._scheduleRender();
                })
                .catch((err) => {
                    console.error(`Failed to load ${record.filename}:`, err);
                });
        }
    }
}
