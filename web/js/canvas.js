/**
 * CanvasController — manages the mood board canvas element.
 *
 * Renders images and placeholders on an HTML5 canvas using a 2D drawing
 * context.  Maintains a camera transform for infinite-canvas style panning
 * and zooming while storing item positions in stable world coordinates.
 * Handles drag-and-drop and button-based uploads with placeholders that are
 * replaced by loaded images once the backend stores the file.
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
     * @param {Function} [options.onChange] - Callback invoked after any
     *     canvas change (z-order, delete) that the sidebar should reflect.
     * @param {Function} [options.onSelectionChange] - Callback invoked when
     *     the selected image changes or its position/size is updated.
     *     Receives an info object or null when deselected.
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
        this._onChange = options.onChange || null;

        /** @type {Function|null} */
        this._onSelectionChange = options.onSelectionChange || null;

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

        /** @type {Object|null} The currently selected canvas item. */
        this._selectedItem = null;

        /** @type {number} Horizontal camera offset in canvas pixels. */
        this._panX = 0;

        /** @type {number} Vertical camera offset in canvas pixels. */
        this._panY = 0;

        /** @type {number} Current camera zoom factor. */
        this._zoom = 1;

        /** @type {number} Minimum allowed zoom factor. */
        this._minZoom = 0.15;

        /** @type {number} Maximum allowed zoom factor. */
        this._maxZoom = 5;

        /** @type {boolean} Whether the user is dragging a selected image. */
        this._dragging = false;

        /** @type {boolean} Whether the user is panning the camera. */
        this._panning = false;

        /** @type {number} Offset from cursor to item origin at drag start. */
        this._dragOffsetX = 0;

        /** @type {number} Offset from cursor to item origin at drag start. */
        this._dragOffsetY = 0;

        /** @type {number} Last mouse X in canvas pixels while panning. */
        this._lastPanX = 0;

        /** @type {number} Last mouse Y in canvas pixels while panning. */
        this._lastPanY = 0;

        /** @type {boolean} Whether the user is resizing a selected image. */
        this._resizing = false;

        /** @type {string|null} Which corner handle is being dragged: "tl", "tr", "bl", "br". */
        this._resizeCorner = null;

        /** @type {number} Mouse X position at resize start. */
        this._resizeStartX = 0;

        /** @type {number} Mouse Y position at resize start. */
        this._resizeStartY = 0;

        /** @type {number} Item width at resize start. */
        this._resizeStartWidth = 0;

        /** @type {number} Item height at resize start. */
        this._resizeStartHeight = 0;

        /** @type {number} Item X position at resize start. */
        this._resizeStartItemX = 0;

        /** @type {number} Item Y position at resize start. */
        this._resizeStartItemY = 0;

        this._syncCanvasSize();
        this._buildActionPanel();
        this._buildCanvasToolbar();
        this._bindDragEvents();
        this._bindMouseEvents();
        this._bindWheelEvent();
        this._bindResizeEvent();
        this._centerView();
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
        ctx.setTransform(1, 0, 0, 1, 0, 0);
        ctx.clearRect(0, 0, canvas.width, canvas.height);

        this._drawGrid();

        ctx.save();
        ctx.setTransform(this._zoom, 0, 0, this._zoom, this._panX, this._panY);

        for (const item of this._items) {
            if (item.type === "placeholder") {
                ctx.fillStyle = "#ffffff";
                ctx.fillRect(item.x, item.y, item.width, item.height);
            } else if (item.type === "image" && item.img) {
                ctx.drawImage(item.img, item.x, item.y, item.width, item.height);
            }

            /* Draw selection outline for the selected item. */
            if (item === this._selectedItem) {
                this._drawSelectionOutline(item);
            }
        }

        ctx.restore();

        this._updateActionPanelPosition();
        this._updateCanvasToolbar();
    }

    /**
     * Draw a world-space grid behind all items.
     *
     * The grid is computed from the current camera viewport so it appears to
     * continue indefinitely as the user pans and zooms.
     * @private
     */
    _drawGrid() {
        const { ctx, canvas } = this;
        const topLeft = this._canvasToWorld(0, 0);
        const bottomRight = this._canvasToWorld(canvas.width, canvas.height);
        const step = this._gridStep();
        const startX = Math.floor(topLeft.x / step) * step;
        const endX = Math.ceil(bottomRight.x / step) * step;
        const startY = Math.floor(topLeft.y / step) * step;
        const endY = Math.ceil(bottomRight.y / step) * step;

        ctx.save();
        ctx.setTransform(this._zoom, 0, 0, this._zoom, this._panX, this._panY);
        ctx.lineWidth = 1 / this._zoom;

        for (let x = startX; x <= endX; x += step) {
            ctx.strokeStyle = x === 0 ? "rgba(232, 232, 255, 0.22)" : "rgba(232, 232, 255, 0.08)";
            ctx.beginPath();
            ctx.moveTo(x, startY);
            ctx.lineTo(x, endY);
            ctx.stroke();
        }

        for (let y = startY; y <= endY; y += step) {
            ctx.strokeStyle = y === 0 ? "rgba(232, 232, 255, 0.22)" : "rgba(232, 232, 255, 0.08)";
            ctx.beginPath();
            ctx.moveTo(startX, y);
            ctx.lineTo(endX, y);
            ctx.stroke();
        }

        ctx.restore();
    }

    /**
     * Choose a pleasant grid spacing for the current zoom level.
     *
     * @returns {number} Grid step in world units.
     * @private
     */
    _gridStep() {
        const targetPixels = 80;
        const rawStep = targetPixels / this._zoom;
        const power = Math.pow(10, Math.floor(Math.log10(rawStep)));
        const normalized = rawStep / power;
        if (normalized < 2) {
            return power;
        }
        if (normalized < 5) {
            return power * 2;
        }
        return power * 5;
    }

    /**
     * Draw a black-and-white dashed outline around a canvas item.
     *
     * Two passes are used: first a black dashed stroke, then a white
     * dashed stroke offset by the dash length.  This creates an
     * alternating black/white pattern that is visible against any
     * background colour.
     *
     * @param {Object} item - The canvas item to outline.
     * @private
     */
    _drawSelectionOutline(item) {
        const { ctx } = this;
        const pad = 2;
        const x = item.x - pad;
        const y = item.y - pad;
        const w = item.width + pad * 2;
        const h = item.height + pad * 2;
        const dashLen = 6;

        ctx.save();
        ctx.lineWidth = 2 / this._zoom;

        /* Black dashes. */
        ctx.strokeStyle = "#000000";
        ctx.setLineDash([dashLen / this._zoom, dashLen / this._zoom]);
        ctx.lineDashOffset = 0;
        ctx.strokeRect(x, y, w, h);

        /* White dashes offset to fill the gaps. */
        ctx.strokeStyle = "#ffffff";
        ctx.lineDashOffset = dashLen / this._zoom;
        ctx.strokeRect(x, y, w, h);

        /* Draw corner resize handles — filled white squares with black border. */
        ctx.setLineDash([]);
        const hs = 8 / this._zoom; /* handle visual size */
        const half = hs / 2;
        const corners = [
            [x - half,     y - half],         /* top-left */
            [x + w - half, y - half],         /* top-right */
            [x - half,     y + h - half],     /* bottom-left */
            [x + w - half, y + h - half],     /* bottom-right */
        ];
        for (const [cx, cy] of corners) {
            ctx.fillStyle = "#ffffff";
            ctx.fillRect(cx, cy, hs, hs);
            ctx.strokeStyle = "#000000";
            ctx.lineWidth = 1 / this._zoom;
            ctx.strokeRect(cx, cy, hs, hs);
        }

        ctx.restore();
    }

    /* ------------------------------------------------------------------
     *  Selection & mouse interaction
     * ------------------------------------------------------------------ */

    /**
     * Bind mousedown, mousemove, and mouseup listeners for selection
     * and dragging of canvas items.
     *
     * Mousedown performs a hit-test (topmost first) and selects the
     * item under the cursor.  Holding the left button down and moving
     * the mouse drags the selected image.  Mouseup finishes the drag
     * and persists the new position to the database.
     * @private
     */
    _bindMouseEvents() {
        this.canvas.addEventListener("mousedown", (e) => this._onMouseDown(e));

        /* Bind mousemove and mouseup on the window so dragging continues
           even when the cursor leaves the canvas boundaries. */
        window.addEventListener("mousemove", (e) => this._onMouseMove(e));
        window.addEventListener("mouseup", (e) => this._onMouseUp(e));
    }

    /**
     * Bind wheel zoom around the current cursor position.
     *
     * @private
     */
    _bindWheelEvent() {
        this.canvas.addEventListener("wheel", (e) => this._onWheel(e), {
            passive: false,
        });
    }

    /**
     * Handle mousedown: select the topmost image under the cursor.
     *
     * Iterates items in reverse order (last = topmost) and selects the
     * first one whose bounding box contains the click position.  If no
     * item is hit the selection is cleared.  Only fully loaded images
     * are selectable (placeholders are ignored).
     *
     * @param {MouseEvent} event - The native mousedown event.
     * @private
     */
    _onMouseDown(event) {
        if (event.button !== 0) {
            return;
        }

        const canvasPoint = this._canvasPoint(event);
        const { x, y } = this._canvasToWorld(canvasPoint.x, canvasPoint.y);

        /* Check if a resize handle of the currently selected item was clicked. */
        const handleHit = this._hitTestHandle(x, y);
        if (handleHit) {
            event.preventDefault();
            const item = this._selectedItem;
            this._resizing = true;
            this._resizeCorner = handleHit;
            this._resizeStartX = x;
            this._resizeStartY = y;
            this._resizeStartWidth = item.width;
            this._resizeStartHeight = item.height;
            this._resizeStartItemX = item.x;
            this._resizeStartItemY = item.y;
            return;
        }

        const hit = this._hitTest(x, y);

        this._selectedItem = hit;
        this._notifySelectionChange();
        this._scheduleRender();

        if (hit) {
            /* Prevent the browser from starting a native drag or text
               selection — without this, mousemove events get swallowed. */
            event.preventDefault();

            this._dragging = true;
            this._dragOffsetX = x - hit.x;
            this._dragOffsetY = y - hit.y;
            this.canvas.style.cursor = "grabbing";
        } else {
            event.preventDefault();
            this._panning = true;
            this._lastPanX = canvasPoint.x;
            this._lastPanY = canvasPoint.y;
            this.canvas.style.cursor = "grabbing";
        }
    }

    /**
     * Handle mousemove: reposition the selected item while dragging.
     *
     * @param {MouseEvent} event - The native mousemove event.
     * @private
     */
    _onMouseMove(event) {
        /* Handle active resize operation. */
        if (this._resizing && this._selectedItem) {
            const point = this._canvasPoint(event);
            const { x, y } = this._canvasToWorld(point.x, point.y);
            this._applyResize(x, y);
            this._scheduleRender();
            return;
        }

        if (this._panning) {
            const point = this._canvasPoint(event);
            this._panX += point.x - this._lastPanX;
            this._panY += point.y - this._lastPanY;
            this._lastPanX = point.x;
            this._lastPanY = point.y;
            this._scheduleRender();
            return;
        }

        if (!this._dragging || !this._selectedItem) {
            /* Update cursor style based on hover — only when the event
               target is actually the canvas (listener is on window). */
            if (event.target === this.canvas) {
                const point = this._canvasPoint(event);
                const { x, y } = this._canvasToWorld(point.x, point.y);

                /* Resize handle cursors take priority over grab cursor. */
                const handle = this._hitTestHandle(x, y);
                if (handle) {
                    this.canvas.style.cursor =
                        (handle === "tl" || handle === "br") ? "nwse-resize" : "nesw-resize";
                } else {
                    const hover = this._hitTest(x, y);
                    this.canvas.style.cursor = hover ? "grab" : "grab";
                }
            }
            return;
        }

        const point = this._canvasPoint(event);
        const { x, y } = this._canvasToWorld(point.x, point.y);
        this._selectedItem.x = x - this._dragOffsetX;
        this._selectedItem.y = y - this._dragOffsetY;
        this._scheduleRender();
    }

    /**
     * Apply resize logic based on the current mouse position.
     *
     * Computes a new width from the mouse delta relative to the drag start,
     * derives height from the aspect ratio, clamps to a minimum of 8px in
     * either dimension, and repositions the image so the opposite corner
     * stays anchored.
     *
     * @param {number} x - Current mouse X in canvas coordinates.
     * @param {number} y - Current mouse Y in canvas coordinates.
     * @private
     */
    _applyResize(x, y) {
        const item = this._selectedItem;
        const dx = x - this._resizeStartX;
        const dy = y - this._resizeStartY;
        const aspect = this._resizeStartHeight / this._resizeStartWidth;
        const minDim = 8;

        let newWidth, newHeight;

        switch (this._resizeCorner) {
            case "br":
                /* Bottom-right: expand rightward and downward. */
                newWidth = this._resizeStartWidth + dx;
                break;
            case "bl":
                /* Bottom-left: expand leftward (negative dx = bigger). */
                newWidth = this._resizeStartWidth - dx;
                break;
            case "tr":
                /* Top-right: expand rightward and upward. */
                newWidth = this._resizeStartWidth + dx;
                break;
            case "tl":
                /* Top-left: expand leftward and upward. */
                newWidth = this._resizeStartWidth - dx;
                break;
        }

        /* Derive height from aspect ratio. */
        newHeight = newWidth * aspect;

        /* Clamp to minimum size. */
        if (newWidth < minDim || newHeight < minDim) {
            if (aspect >= 1) {
                /* Taller than wide — height is the binding constraint. */
                newHeight = minDim;
                newWidth = minDim / aspect;
            } else {
                newWidth = minDim;
                newHeight = minDim * aspect;
            }
        }

        /* Anchor the opposite corner by adjusting position. */
        switch (this._resizeCorner) {
            case "br":
                /* Top-left stays fixed — position unchanged. */
                break;
            case "bl":
                /* Top-right stays fixed — shift X. */
                item.x = this._resizeStartItemX + this._resizeStartWidth - newWidth;
                break;
            case "tr":
                /* Bottom-left stays fixed — shift Y. */
                item.y = this._resizeStartItemY + this._resizeStartHeight - newHeight;
                break;
            case "tl":
                /* Bottom-right stays fixed — shift both X and Y. */
                item.x = this._resizeStartItemX + this._resizeStartWidth - newWidth;
                item.y = this._resizeStartItemY + this._resizeStartHeight - newHeight;
                break;
        }

        item.width = newWidth;
        item.height = newHeight;
    }

    /**
     * Handle mouseup: finish dragging and persist the new position.
     *
     * @param {MouseEvent} event - The native mouseup event.
     * @private
     */
    _onMouseUp(event) {
        if (event.button !== 0) {
            return;
        }

        /* Finish a resize operation. */
        if (this._resizing) {
            const item = this._selectedItem;
            this._resizing = false;
            this._resizeCorner = null;
            this.canvas.style.cursor = "default";

            if (item && item.imageRecord && item.img) {
                const newScale = item.width / item.img.naturalWidth;
                this.api.updateImage(item.imageRecord.id, {
                    pos_x: item.x,
                    pos_y: item.y,
                    scale: newScale,
                }).catch((err) => {
                    console.error("Failed to persist image resize:", err);
                });
            }
            /* Re-render so the action panel reappears after resize. */
            this._notifySelectionChange();
            this._scheduleRender();
            return;
        }

        if (this._panning) {
            this._panning = false;
            this.canvas.style.cursor = "grab";
            return;
        }

        if (!this._dragging) {
            return;
        }

        const item = this._selectedItem;
        this._dragging = false;
        this.canvas.style.cursor = item ? "grab" : "default";

        /* Persist the new position if the item has a database record. */
        if (item && item.imageRecord) {
            this.api.updateImage(item.imageRecord.id, {
                pos_x: item.x,
                pos_y: item.y,
            }).catch((err) => {
                console.error("Failed to persist image position:", err);
            });
        }

        /* Re-render so the action panel reappears after drag. */
        this._notifySelectionChange();
        this._scheduleRender();
    }

    /**
     * Convert a mouse event to canvas-relative coordinates.
     *
     * @param {MouseEvent} event - The mouse event.
     * @returns {{ x: number, y: number }} Canvas-relative position.
     * @private
     */
    _canvasCoords(event) {
        const point = this._canvasPoint(event);
        return this._canvasToWorld(point.x, point.y);
    }

    /**
     * Convert a mouse event to canvas-buffer coordinates.
     *
     * @param {MouseEvent} event - The mouse event.
     * @returns {{ x: number, y: number }} Canvas-buffer position.
     * @private
     */
    _canvasPoint(event) {
        const rect = this.canvas.getBoundingClientRect();
        /* Scale from CSS pixels to canvas buffer coordinates.  The
           canvas buffer dimensions may differ from the CSS layout size
           (e.g. after the sidebar changes the flex layout). */
        return {
            x: (event.clientX - rect.left) * (this.canvas.width / rect.width),
            y: (event.clientY - rect.top) * (this.canvas.height / rect.height),
        };
    }

    /**
     * Convert canvas-buffer coordinates to world coordinates.
     *
     * @param {number} x - Canvas-buffer X coordinate.
     * @param {number} y - Canvas-buffer Y coordinate.
     * @returns {{ x: number, y: number }} World-space position.
     * @private
     */
    _canvasToWorld(x, y) {
        return {
            x: (x - this._panX) / this._zoom,
            y: (y - this._panY) / this._zoom,
        };
    }

    /**
     * Convert world coordinates to canvas-buffer coordinates.
     *
     * @param {number} x - World X coordinate.
     * @param {number} y - World Y coordinate.
     * @returns {{ x: number, y: number }} Canvas-buffer position.
     * @private
     */
    _worldToCanvas(x, y) {
        return {
            x: x * this._zoom + this._panX,
            y: y * this._zoom + this._panY,
        };
    }

    /**
     * Convert world coordinates to CSS pixels relative to the canvas.
     *
     * @param {number} x - World X coordinate.
     * @param {number} y - World Y coordinate.
     * @returns {{ x: number, y: number }} CSS pixel position.
     * @private
     */
    _worldToCss(x, y) {
        const rect = this.canvas.getBoundingClientRect();
        const point = this._worldToCanvas(x, y);
        return {
            x: point.x * (rect.width / this.canvas.width),
            y: point.y * (rect.height / this.canvas.height),
        };
    }

    /**
     * Zoom around the mouse cursor.
     *
     * @param {WheelEvent} event - The native wheel event.
     * @private
     */
    _onWheel(event) {
        event.preventDefault();
        const point = this._canvasPoint(event);
        const before = this._canvasToWorld(point.x, point.y);
        const factor = Math.exp(-event.deltaY * 0.001);
        this._zoom = Math.max(
            this._minZoom,
            Math.min(this._maxZoom, this._zoom * factor)
        );
        this._panX = point.x - before.x * this._zoom;
        this._panY = point.y - before.y * this._zoom;
        this._scheduleRender();
    }

    /**
     * Centre the camera on the world origin.
     *
     * @private
     */
    _centerView() {
        this._panX = this.canvas.width / 2;
        this._panY = this.canvas.height / 2;
    }

    /**
     * Find the topmost loaded image at the given canvas coordinates.
     *
     * Iterates the items array in reverse (last item = topmost) and
     * returns the first image-type item whose bounding box contains
     * the point.  Placeholders are not selectable.
     *
     * @param {number} x - The X coordinate to test.
     * @param {number} y - The Y coordinate to test.
     * @returns {Object|null} The hit item, or null if nothing was hit.
     * @private
     */
    _hitTest(x, y) {
        for (let i = this._items.length - 1; i >= 0; i--) {
            const item = this._items[i];
            if (item.type !== "image") {
                continue;
            }
            if (
                x >= item.x &&
                x <= item.x + item.width &&
                y >= item.y &&
                y <= item.y + item.height
            ) {
                return item;
            }
        }
        return null;
    }

    /**
     * Check if a point falls on one of the four corner resize handles
     * of the currently selected item.
     *
     * The hit area is slightly larger than the visual handle (12×12 vs
     * 8×8 px) to make grabbing easier.  Returns the corner identifier
     * string or null if no handle was hit.
     *
     * @param {number} x - The X coordinate to test.
     * @param {number} y - The Y coordinate to test.
     * @returns {string|null} "tl", "tr", "bl", "br", or null.
     * @private
     */
    _hitTestHandle(x, y) {
        const item = this._selectedItem;
        if (!item) {
            return null;
        }

        const pad = 2; /* same padding used by the selection outline */
        const bx = item.x - pad;
        const by = item.y - pad;
        const bw = item.width + pad * 2;
        const bh = item.height + pad * 2;

        const hitSize = 12 / this._zoom;
        const half = hitSize / 2;

        const corners = [
            { id: "tl", cx: bx,      cy: by },
            { id: "tr", cx: bx + bw, cy: by },
            { id: "bl", cx: bx,      cy: by + bh },
            { id: "br", cx: bx + bw, cy: by + bh },
        ];

        for (const corner of corners) {
            if (
                x >= corner.cx - half &&
                x <= corner.cx + half &&
                y >= corner.cy - half &&
                y <= corner.cy + half
            ) {
                return corner.id;
            }
        }
        return null;
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

        const point = this._canvasPoint(event);
        const drop = this._canvasToWorld(point.x, point.y);

        for (const file of files) {
            this._uploadAndDisplay(file, drop.x, drop.y);
        }
    }

    /**
     * Upload files at the centre of the current viewport.
     *
     * @param {FileList|Array<File>} files - Files chosen through the upload button.
     */
    uploadFiles(files) {
        const images = Array.from(files).filter((f) => f.type.startsWith("image/"));
        if (images.length === 0) {
            return;
        }

        const center = this._canvasToWorld(this.canvas.width / 2, this.canvas.height / 2);
        images.forEach((file, index) => {
            const offset = index * (24 / this._zoom);
            this._uploadAndDisplay(file, center.x + offset, center.y + offset);
        });
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
        const placeholderW = (this.canvas.width / this._zoom) / 3;
        const placeholderH = (this.canvas.height / this._zoom) / 3;
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
     *  Action panel (z-order & delete)
     * ------------------------------------------------------------------ */

    /**
     * Build the floating action panel DOM and append it to the canvas container.
     *
     * Creates a hidden div with five buttons: move-to-top, move-up,
     * move-down, move-to-bottom, and delete.  The panel is positioned
     * absolutely within #canvas-container and shown/hidden dynamically
     * based on the current selection state.
     * @private
     */
    _buildActionPanel() {
        this._actionPanel = document.createElement("div");
        this._actionPanel.className = "canvas-actions canvas-actions--hidden";

        const buttons = [
            { label: "\u21C8",  title: "Move to top",    action: () => this._moveToTop() },
            { label: "\u2191",  title: "Move up",        action: () => this._moveUp() },
            { label: "\u2193",  title: "Move down",      action: () => this._moveDown() },
            { label: "\u21CA",  title: "Move to bottom", action: () => this._moveToBottom() },
        ];

        for (const def of buttons) {
            const btn = document.createElement("button");
            btn.className = "canvas-actions__btn";
            btn.textContent = def.label;
            btn.title = def.title;
            btn.addEventListener("click", (e) => {
                e.stopPropagation();
                def.action();
            });
            this._actionPanel.appendChild(btn);
        }

        /* Visual separator before the delete button. */
        const sep = document.createElement("div");
        sep.className = "canvas-actions__separator";
        this._actionPanel.appendChild(sep);

        const deleteBtn = document.createElement("button");
        deleteBtn.className = "canvas-actions__btn canvas-actions__btn--delete";
        deleteBtn.textContent = "\uD83D\uDDD1";  /* 🗑 */
        deleteBtn.title = "Delete image";
        deleteBtn.addEventListener("click", (e) => {
            e.stopPropagation();
            this._deleteSelected();
        });
        this._actionPanel.appendChild(deleteBtn);

        this.canvas.parentElement.appendChild(this._actionPanel);
    }

    /**
     * Position the action panel above the selected item.
     *
     * Converts the item's canvas-buffer coordinates to CSS pixels
     * (accounting for any scaling between the buffer and CSS layout),
     * then places the panel centred above the item with a small gap.
     * Hides the panel if nothing is selected or an interaction is active.
     * @private
     */
    _updateActionPanelPosition() {
        if (!this._selectedItem || this._dragging || this._resizing) {
            this._actionPanel.classList.add("canvas-actions--hidden");
            return;
        }

        this._actionPanel.classList.remove("canvas-actions--hidden");

        const item = this._selectedItem;
        const topLeft = this._worldToCss(item.x, item.y);
        const bottomRight = this._worldToCss(item.x + item.width, item.y + item.height);
        const itemCenterCss = (topLeft.x + bottomRight.x) / 2;
        const itemTopCss = topLeft.y;
        const rect = this.canvas.getBoundingClientRect();

        /* Measure panel so we can centre it. */
        const panelW = this._actionPanel.offsetWidth;
        const panelH = this._actionPanel.offsetHeight;
        const gap = 6;

        let left = itemCenterCss - panelW / 2;
        let top = itemTopCss - panelH - gap;

        /* Clamp to stay within the container. */
        left = Math.max(0, Math.min(left, rect.width - panelW));
        top = Math.max(0, top);

        this._actionPanel.style.left = left + "px";
        this._actionPanel.style.top = top + "px";
    }

    /**
     * Build the canvas toolbar with upload and zoom controls.
     *
     * @private
     */
    _buildCanvasToolbar() {
        this._toolbar = document.createElement("div");
        this._toolbar.className = "canvas-toolbar";

        this._fileInput = document.createElement("input");
        this._fileInput.type = "file";
        this._fileInput.accept = "image/png,image/jpeg,image/gif,image/webp";
        this._fileInput.multiple = true;
        this._fileInput.className = "canvas-toolbar__file";

        const uploadBtn = this._createToolbarButton("\u2191", "Upload images", () => {
            this._fileInput.click();
        });
        const zoomOutBtn = this._createToolbarButton("-", "Zoom out", () => {
            this._zoomAtCanvasCenter(1 / 1.2);
        });
        const resetBtn = this._createToolbarButton("100%", "Reset view", () => {
            this._zoom = 1;
            this._centerView();
            this._scheduleRender();
        });
        resetBtn.classList.add("canvas-toolbar__zoom-label");
        this._zoomLabel = resetBtn;
        const zoomInBtn = this._createToolbarButton("+", "Zoom in", () => {
            this._zoomAtCanvasCenter(1.2);
        });

        this._fileInput.addEventListener("change", () => {
            this.uploadFiles(this._fileInput.files);
            this._fileInput.value = "";
        });

        this._toolbar.appendChild(uploadBtn);
        this._toolbar.appendChild(zoomOutBtn);
        this._toolbar.appendChild(resetBtn);
        this._toolbar.appendChild(zoomInBtn);
        this._toolbar.appendChild(this._fileInput);
        this.canvas.parentElement.appendChild(this._toolbar);
    }

    /**
     * Create a toolbar button.
     *
     * @param {string} label - Button text.
     * @param {string} title - Tooltip text.
     * @param {Function} action - Click handler.
     * @returns {HTMLButtonElement} Configured button.
     * @private
     */
    _createToolbarButton(label, title, action) {
        const button = document.createElement("button");
        button.type = "button";
        button.className = "canvas-toolbar__btn";
        button.textContent = label;
        button.title = title;
        button.addEventListener("click", (event) => {
            event.stopPropagation();
            action();
        });
        return button;
    }

    /**
     * Update toolbar state after rendering.
     *
     * @private
     */
    _updateCanvasToolbar() {
        if (this._zoomLabel) {
            this._zoomLabel.textContent = `${Math.round(this._zoom * 100)}%`;
        }
    }

    /**
     * Zoom around the centre of the canvas.
     *
     * @param {number} factor - Multiplicative zoom factor.
     * @private
     */
    _zoomAtCanvasCenter(factor) {
        const point = { x: this.canvas.width / 2, y: this.canvas.height / 2 };
        const before = this._canvasToWorld(point.x, point.y);
        this._zoom = Math.max(
            this._minZoom,
            Math.min(this._maxZoom, this._zoom * factor)
        );
        this._panX = point.x - before.x * this._zoom;
        this._panY = point.y - before.y * this._zoom;
        this._scheduleRender();
    }

    /**
     * Move the selected item to the top of the draw order.
     *
     * Moves the item to the end of the _items array and reassigns
     * sequential z_index values to all items, then persists the
     * changes to the backend.
     * @private
     */
    _moveToTop() {
        const item = this._selectedItem;
        if (!item) return;

        const idx = this._items.indexOf(item);
        if (idx === -1 || idx === this._items.length - 1) return;

        this._items.splice(idx, 1);
        this._items.push(item);
        this._reassignZIndices();
        this._scheduleRender();
    }

    /**
     * Move the selected item one step up in the draw order.
     *
     * Swaps the item with the one above it in the _items array and
     * persists both z_index values.
     * @private
     */
    _moveUp() {
        const item = this._selectedItem;
        if (!item) return;

        const idx = this._items.indexOf(item);
        if (idx === -1 || idx === this._items.length - 1) return;

        /* Swap with the item above (next in array = drawn later). */
        [this._items[idx], this._items[idx + 1]] =
            [this._items[idx + 1], this._items[idx]];
        this._reassignZIndices();
        this._scheduleRender();
    }

    /**
     * Move the selected item one step down in the draw order.
     *
     * Swaps the item with the one below it in the _items array and
     * persists both z_index values.
     * @private
     */
    _moveDown() {
        const item = this._selectedItem;
        if (!item) return;

        const idx = this._items.indexOf(item);
        if (idx <= 0) return;

        /* Swap with the item below (previous in array = drawn earlier). */
        [this._items[idx], this._items[idx - 1]] =
            [this._items[idx - 1], this._items[idx]];
        this._reassignZIndices();
        this._scheduleRender();
    }

    /**
     * Move the selected item to the bottom of the draw order.
     *
     * Moves the item to the start of the _items array and reassigns
     * sequential z_index values to all items.
     * @private
     */
    _moveToBottom() {
        const item = this._selectedItem;
        if (!item) return;

        const idx = this._items.indexOf(item);
        if (idx <= 0) return;

        this._items.splice(idx, 1);
        this._items.unshift(item);
        this._reassignZIndices();
        this._scheduleRender();
    }

    /**
     * Reassign sequential z_index values (0, 1, 2, ...) to all items.
     *
     * Persists each updated z_index to the backend and triggers the
     * onChange callback so the sidebar can refresh its image list.
     * @private
     */
    _reassignZIndices() {
        for (let i = 0; i < this._items.length; i++) {
            const it = this._items[i];
            if (it.imageRecord) {
                it.imageRecord.z_index = i;
                this.api.updateImage(it.imageRecord.id, { z_index: i })
                    .catch((err) => {
                        console.error("Failed to update z_index:", err);
                    });
            }
        }
        if (this._onChange) {
            this._onChange();
        }
    }

    /**
     * Delete the currently selected image from the canvas and backend.
     *
     * Removes the item from the _items array, calls the delete API,
     * clears the selection, and notifies listeners.
     * @private
     */
    _deleteSelected() {
        const item = this._selectedItem;
        if (!item || !item.imageRecord) return;

        const idx = this._items.indexOf(item);
        if (idx !== -1) {
            this._items.splice(idx, 1);
        }
        this._selectedItem = null;
        this._notifySelectionChange();

        this.api.deleteImage(item.imageRecord.id)
            .catch((err) => {
                console.error("Failed to delete image:", err);
            });

        this._scheduleRender();
        if (this._onChange) {
            this._onChange();
        }
    }

    /* ------------------------------------------------------------------
     *  Selection notification & query helpers
     * ------------------------------------------------------------------ */

    /**
     * Build a plain info object from the currently selected item and
     * invoke the onSelectionChange callback.
     *
     * Called whenever the selection changes (select, deselect) or the
     * selected item's position/size is modified (drag, resize).
     * @private
     */
    _notifySelectionChange() {
        if (!this._onSelectionChange) {
            return;
        }
        const item = this._selectedItem;
        if (!item || !item.imageRecord) {
            this._onSelectionChange(null);
            return;
        }
        this._onSelectionChange({
            id: item.imageRecord.id,
            x: Math.round(item.x),
            y: Math.round(item.y),
            width: Math.round(item.width),
            height: Math.round(item.height),
            naturalWidth: item.img ? item.img.naturalWidth : 0,
            naturalHeight: item.img ? item.img.naturalHeight : 0,
        });
    }

    /**
     * Return a Map of image ID to info object for all loaded canvas items.
     *
     * Used by the sidebar to enrich the image table with position and
     * scaled dimensions for each image.
     *
     * @returns {Map<number, Object>} Map keyed by image record ID.
     */
    getItemsInfo() {
        const map = new Map();
        for (const item of this._items) {
            if (item.type === "image" && item.imageRecord) {
                map.set(item.imageRecord.id, {
                    id: item.imageRecord.id,
                    x: Math.round(item.x),
                    y: Math.round(item.y),
                    width: Math.round(item.width),
                    height: Math.round(item.height),
                    naturalWidth: item.img ? item.img.naturalWidth : 0,
                    naturalHeight: item.img ? item.img.naturalHeight : 0,
                });
            }
        }
        return map;
    }

    /**
     * Return the database record ID of the currently selected image,
     * or null if nothing is selected.
     *
     * @returns {number|null} The selected image's record ID.
     */
    getSelectedImageId() {
        if (this._selectedItem && this._selectedItem.imageRecord) {
            return this._selectedItem.imageRecord.id;
        }
        return null;
    }

    /**
     * Select an image on the canvas by its database record ID.
     *
     * Looks up the canvas item whose imageRecord.id matches the given ID,
     * selects it (showing the outline and action panel), and updates the
     * sidebar highlight. If no matching item is found the selection is cleared.
     *
     * @param {number} id - The database record ID of the image to select.
     */
    selectImageById(id) {
        const item = this._items.find(
            (it) => it.imageRecord && it.imageRecord.id === id
        ) || null;
        this._selectedItem = item;
        this._notifySelectionChange();
        this._scheduleRender();
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
        this._selectedItem = null;
        this._dragging = false;
        this._panning = false;
        this._resizing = false;
        this._resizeCorner = null;
        this._actionPanel.classList.add("canvas-actions--hidden");
        this._notifySelectionChange();
        this._syncCanvasSize();
        this._centerView();
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
                item.width = 100 / this._zoom;
                item.height = 100 / this._zoom;
            } else {
                item.width = (this.canvas.width / this._zoom) / 3;
                item.height = (this.canvas.height / this._zoom) / 3;
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
                            (this.canvas.width / this._zoom) / 3,
                            (this.canvas.height / this._zoom) / 3
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
