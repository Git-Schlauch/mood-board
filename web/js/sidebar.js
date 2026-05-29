/**
 * Sidebar — collapsible right-hand panel for project management.
 *
 * Builds all DOM elements programmatically and manages the sidebar's
 * expanded/collapsed state, the current project display, and the
 * "Open Project" dialog (which also allows creating new projects).
 */
class Sidebar {

    /**
     * Create the sidebar and attach it to the page.
     *
     * Immediately fetches the current project from the backend and
     * displays its name in the sidebar header.
     *
     * @param {ApiClient} api - The API client for backend communication.
     * @param {Object} [options] - Configuration options.
     * @param {Function} [options.onProjectChange] - Callback invoked
     *     whenever the active project changes (open, create, or initial
     *     load).  Receives no arguments — the caller should read
     *     ``sidebar.currentProject`` for the new project.
     * @param {Function} [options.onLogout] - Callback invoked when the user
     *     clicks the logout button.
     * @param {Object} [options.user] - Authenticated public user record.
     * @param {CanvasController} [options.canvas] - Reference to the
     *     canvas controller, used to query item positions and selection.
     */
    constructor(api, options = {}) {
        /** @type {ApiClient} */
        this.api = api;

        /** @type {boolean} Whether the sidebar is currently expanded. */
        this.isOpen = true;

        /** @type {Object|null} The currently loaded project. */
        this.currentProject = null;

        /** @type {Array<Object>} Current project's layers. */
        this._layers = [];

        /** @type {HTMLElement|null} The dialog overlay element. */
        this._dialogOverlay = null;

        /** @type {HTMLElement|null} The user dialog overlay element. */
        this._userDialogOverlay = null;

        /** @type {Function|null} */
        this._onProjectChange = options.onProjectChange || null;

        /** @type {Function|null} */
        this._onLogout = options.onLogout || null;

        /** @type {Object|null} */
        this._user = options.user || null;

        /** @type {CanvasController|null} */
        this._canvas = options.canvas || null;

        this._buildDOM();
        this._bindEvents();
        this._loadCurrentProject();
    }

    /* ------------------------------------------------------------------
     *  DOM construction
     * ------------------------------------------------------------------ */

    /**
     * Build the sidebar DOM tree and append it to document.body.
     *
     * Creates the aside element with a header (toggle button + project
     * name) and a content area (Open Project button).  The sidebar
     * starts in the expanded state.
     * @private
     */
    _buildDOM() {
        /* Sidebar root */
        this._el = document.createElement("aside");
        this._el.id = "sidebar";
        this._el.className = "sidebar sidebar--open";

        /* Header row: toggle button + project name */
        this._header = document.createElement("div");
        this._header.className = "sidebar__header";

        this._toggleBtn = document.createElement("button");
        this._toggleBtn.className = "sidebar__toggle";
        this._toggleBtn.title = "Minimise sidebar";
        this._toggleBtn.textContent = "\u25B6"; /* ▶ */

        this._projectName = document.createElement("span");
        this._projectName.className = "sidebar__project-name";
        this._projectName.textContent = "\u2026"; /* … placeholder */

        this._header.appendChild(this._toggleBtn);
        this._header.appendChild(this._projectName);

        /* Content area */
        this._content = document.createElement("div");
        this._content.className = "sidebar__content";

        this._openBtn = document.createElement("button");
        this._openBtn.className = "sidebar__open-btn";
        this._openBtn.textContent = "Open Project";

        this._content.appendChild(this._openBtn);

        this._usersBtn = document.createElement("button");
        this._usersBtn.className = "sidebar__users-btn";
        this._usersBtn.textContent = this._user && this._user.is_admin
            ? "Users"
            : "Account";
        this._content.appendChild(this._usersBtn);

        this._logoutBtn = document.createElement("button");
        this._logoutBtn.className = "sidebar__logout-btn";
        this._logoutBtn.textContent = "Log out";
        this._content.appendChild(this._logoutBtn);

        this._layerHeading = document.createElement("h3");
        this._layerHeading.className = "sidebar__image-heading";
        this._layerHeading.textContent = "Layers";
        this._content.appendChild(this._layerHeading);

        this._layerList = document.createElement("div");
        this._layerList.className = "sidebar__layer-list";
        this._content.appendChild(this._layerList);

        this._newLayerRow = document.createElement("div");
        this._newLayerRow.className = "sidebar__layer-create";
        this._newLayerInput = document.createElement("input");
        this._newLayerInput.type = "text";
        this._newLayerInput.className = "sidebar__layer-input";
        this._newLayerInput.placeholder = "New layer";
        this._newLayerBtn = document.createElement("button");
        this._newLayerBtn.className = "sidebar__layer-add";
        this._newLayerBtn.textContent = "+";
        this._newLayerRow.appendChild(this._newLayerInput);
        this._newLayerRow.appendChild(this._newLayerBtn);
        this._content.appendChild(this._newLayerRow);

        /* Image list heading */
        this._imageHeading = document.createElement("h3");
        this._imageHeading.className = "sidebar__image-heading";
        this._imageHeading.textContent = "Images";
        this._content.appendChild(this._imageHeading);

        /* Image table */
        this._imageTable = document.createElement("table");
        this._imageTable.className = "sidebar__image-table";
        this._imageTableBody = document.createElement("tbody");
        this._imageTable.appendChild(this._imageTableBody);
        this._content.appendChild(this._imageTable);

        /* Assemble */
        this._el.appendChild(this._header);
        this._el.appendChild(this._content);
        document.body.appendChild(this._el);
    }

    /* ------------------------------------------------------------------
     *  Event binding
     * ------------------------------------------------------------------ */

    /**
     * Bind click handlers for the toggle button, Open Project button,
     * and double-click to rename the project name.
     * @private
     */
    _bindEvents() {
        this._toggleBtn.addEventListener("click", () => this.toggle());
        this._openBtn.addEventListener("click", () => this.openProjectDialog());
        if (this._usersBtn) {
            this._usersBtn.addEventListener("click", () => this.openUserDialog());
        }
        this._newLayerBtn.addEventListener("click", () => this._createLayer());
        this._newLayerInput.addEventListener("keydown", (event) => {
            if (event.key === "Enter") {
                event.preventDefault();
                this._createLayer();
            }
        });
        this._logoutBtn.addEventListener("click", () => {
            if (this._onLogout) {
                this._onLogout();
            }
        });
        this._projectName.addEventListener("dblclick", () => this._startRename());
    }

    /* ------------------------------------------------------------------
     *  User management dialog
     * ------------------------------------------------------------------ */

    /**
     * Open the user management dialog.
     *
     * Every user can change their own password.  Administrators can also
     * create users and reset passwords from the same dialog.
     */
    async openUserDialog() {
        if (this._userDialogOverlay) {
            return;
        }

        this._userDialogOverlay = document.createElement("div");
        this._userDialogOverlay.className = "dialog-overlay";

        const dialog = document.createElement("div");
        dialog.className = "dialog dialog--wide";

        const title = document.createElement("h2");
        title.textContent = this._user && this._user.is_admin ? "Users" : "Account";
        dialog.appendChild(title);

        this._buildPasswordSection(dialog);

        if (this._user && this._user.is_admin) {
            const hr = document.createElement("hr");
            dialog.appendChild(hr);
            await this._buildAdminUserSection(dialog);
        }

        const actions = document.createElement("div");
        actions.className = "dialog__actions";

        const closeBtn = document.createElement("button");
        closeBtn.className = "dialog__cancel-btn";
        closeBtn.textContent = "Close";
        closeBtn.addEventListener("click", () => this.closeUserDialog());

        actions.appendChild(closeBtn);
        dialog.appendChild(actions);

        this._userDialogOverlay.appendChild(dialog);
        document.body.appendChild(this._userDialogOverlay);
    }

    /**
     * Close and remove the user management dialog from the DOM.
     */
    closeUserDialog() {
        if (this._userDialogOverlay) {
            this._userDialogOverlay.remove();
            this._userDialogOverlay = null;
        }
    }

    /**
     * Build the password-change form.
     *
     * @param {HTMLElement} dialog - Dialog element to append into.
     * @private
     */
    _buildPasswordSection(dialog) {
        const heading = document.createElement("h3");
        heading.textContent = "Change Password";
        dialog.appendChild(heading);

        const row = document.createElement("div");
        row.className = "dialog__stack";

        const current = this._buildDialogInput(
            "password", "Current password", "current-password"
        );
        const next = this._buildDialogInput("password", "New password", "new-password");
        const save = document.createElement("button");
        save.className = "dialog__create-btn";
        save.textContent = "Save";
        const status = this._buildDialogStatus();

        save.addEventListener("click", async () => {
            status.textContent = "";
            try {
                await this.api.changePassword(current.value, next.value);
                current.value = "";
                next.value = "";
                status.textContent = "Password updated.";
            } catch (err) {
                status.textContent = err.message || "Could not update password.";
            }
        });

        row.appendChild(current);
        row.appendChild(next);
        row.appendChild(save);
        row.appendChild(status);
        dialog.appendChild(row);
    }

    /**
     * Build administrator-only user management controls.
     *
     * @param {HTMLElement} dialog - Dialog element to append into.
     * @returns {Promise<void>} Resolves after users are loaded.
     * @private
     */
    async _buildAdminUserSection(dialog) {
        const heading = document.createElement("h3");
        heading.textContent = "Manage Users";
        dialog.appendChild(heading);

        const createRow = document.createElement("div");
        createRow.className = "dialog__user-create";
        const username = this._buildDialogInput("text", "Username", "username");
        const password = this._buildDialogInput(
            "password", "Initial password", "new-password"
        );

        const adminLabel = document.createElement("label");
        adminLabel.className = "dialog__checkbox";
        const admin = document.createElement("input");
        admin.type = "checkbox";
        adminLabel.appendChild(admin);
        adminLabel.appendChild(document.createTextNode("Admin"));

        const createBtn = document.createElement("button");
        createBtn.className = "dialog__create-btn";
        createBtn.textContent = "Create";
        const status = this._buildDialogStatus();
        const list = document.createElement("div");
        list.className = "dialog__user-list";

        const refresh = async () => {
            list.innerHTML = "";
            const users = await this.api.listUsers();
            for (const user of users) {
                list.appendChild(this._buildUserRow(user, status));
            }
        };

        createBtn.addEventListener("click", async () => {
            status.textContent = "";
            try {
                await this.api.createUser(
                    username.value.trim(),
                    password.value,
                    admin.checked
                );
                username.value = "";
                password.value = "";
                admin.checked = false;
                status.textContent = "User created.";
                await refresh();
            } catch (err) {
                status.textContent = err.message || "Could not create user.";
            }
        });

        createRow.appendChild(username);
        createRow.appendChild(password);
        createRow.appendChild(adminLabel);
        createRow.appendChild(createBtn);
        dialog.appendChild(createRow);
        dialog.appendChild(status);
        dialog.appendChild(list);

        try {
            await refresh();
        } catch (err) {
            status.textContent = err.message || "Could not load users.";
        }
    }

    /**
     * Build one row in the administrator user list.
     *
     * @param {Object} user - Public user record.
     * @param {HTMLElement} status - Shared status element.
     * @returns {HTMLElement} User row element.
     * @private
     */
    _buildUserRow(user, status) {
        const row = document.createElement("div");
        row.className = "dialog__user-row";

        const name = document.createElement("span");
        name.textContent = user.is_admin ? `${user.username} (admin)` : user.username;

        const password = this._buildDialogInput(
            "password", "New password", "new-password"
        );
        const reset = document.createElement("button");
        reset.className = "dialog__create-btn";
        reset.textContent = "Reset";
        reset.addEventListener("click", async () => {
            status.textContent = "";
            try {
                await this.api.resetUserPassword(user.id, password.value);
                password.value = "";
                status.textContent = `Password reset for ${user.username}.`;
            } catch (err) {
                status.textContent = err.message || "Could not reset password.";
            }
        });

        row.appendChild(name);
        row.appendChild(password);
        row.appendChild(reset);
        return row;
    }

    /**
     * Create a dialog input element.
     *
     * @param {string} type - Input type.
     * @param {string} placeholder - Placeholder text.
     * @param {string} autocomplete - Browser autocomplete token.
     * @returns {HTMLInputElement} Configured input element.
     * @private
     */
    _buildDialogInput(type, placeholder, autocomplete) {
        const input = document.createElement("input");
        input.type = type;
        input.className = "dialog__text-input";
        input.placeholder = placeholder;
        input.autocomplete = autocomplete;
        return input;
    }

    /**
     * Create a dialog status text element.
     *
     * @returns {HTMLElement} Status element.
     * @private
     */
    _buildDialogStatus() {
        const status = document.createElement("p");
        status.className = "dialog__status";
        status.setAttribute("role", "status");
        return status;
    }

    /* ------------------------------------------------------------------
     *  Inline project rename
     * ------------------------------------------------------------------ */

    /**
     * Replace the project name span with an editable input field.
     *
     * The input is pre-filled with the current project name and auto-selected.
     * Pressing Enter or blurring the input commits the rename; pressing Escape
     * cancels and reverts to the original name.
     * @private
     */
    _startRename() {
        if (!this.currentProject || this._renameInput) {
            return;
        }

        const originalName = this.currentProject.name;

        /* Create the input element. */
        this._renameInput = document.createElement("input");
        this._renameInput.type = "text";
        this._renameInput.className = "sidebar__project-name-input";
        this._renameInput.value = originalName;

        /* Hide the span and insert the input beside it. */
        this._projectName.style.display = "none";
        this._header.appendChild(this._renameInput);

        /* Focus and select all text. */
        this._renameInput.focus();
        this._renameInput.select();

        /** Commit the rename with the current input value. */
        const commit = () => {
            const newName = this._renameInput.value.trim();
            if (newName && newName !== originalName) {
                this._commitRename(newName, originalName);
            } else {
                this._endRename(originalName);
            }
        };

        /** Cancel the rename and revert to the original name. */
        const cancel = () => {
            this._endRename(originalName);
        };

        this._renameInput.addEventListener("keydown", (e) => {
            if (e.key === "Enter") {
                e.preventDefault();
                commit();
            } else if (e.key === "Escape") {
                e.preventDefault();
                cancel();
            }
        });

        this._renameInput.addEventListener("blur", () => {
            /* Guard: if _renameInput is already gone, do nothing. */
            if (!this._renameInput) {
                return;
            }
            commit();
        });
    }

    /**
     * Send the rename request to the backend and finish editing.
     *
     * On success the sidebar and page title are updated with the new name.
     * On failure the original name is restored.
     *
     * @param {string} newName - The desired new project name.
     * @param {string} originalName - The name to revert to on failure.
     * @private
     */
    async _commitRename(newName, originalName) {
        try {
            const updated = await this.api.renameProject(
                this.currentProject.id,
                newName
            );
            this.currentProject = updated;
            this._endRename(updated.name);
        } catch (err) {
            console.error("Failed to rename project:", err);
            this._endRename(originalName);
        }
    }

    /**
     * Remove the rename input, restore the project name span, and update
     * its text content to the given name.
     *
     * @param {string} displayName - The name to display in the span.
     * @private
     */
    _endRename(displayName) {
        if (this._renameInput) {
            this._renameInput.remove();
            this._renameInput = null;
        }
        this._projectName.style.display = "";
        this._projectName.textContent = displayName;
    }

    /* ------------------------------------------------------------------
     *  Sidebar toggle
     * ------------------------------------------------------------------ */

    /**
     * Toggle the sidebar between expanded (~280 px) and collapsed (~60 px).
     *
     * When collapsed the content area is hidden and only the toggle
     * button is visible.  A CSS transition animates the width change.
     */
    toggle() {
        this.isOpen = !this.isOpen;

        if (this.isOpen) {
            this._el.classList.remove("sidebar--collapsed");
            this._el.classList.add("sidebar--open");
            this._toggleBtn.textContent = "\u25B6"; /* ▶ */
            this._toggleBtn.title = "Minimise sidebar";
        } else {
            this._el.classList.remove("sidebar--open");
            this._el.classList.add("sidebar--collapsed");
            this._toggleBtn.textContent = "\u25C0"; /* ◀ */
            this._toggleBtn.title = "Expand sidebar";
        }
    }

    /* ------------------------------------------------------------------
     *  Current project
     * ------------------------------------------------------------------ */

    /**
     * Fetch the current project from the backend and update the display.
     * @private
     */
    async _loadCurrentProject() {
        try {
            this.currentProject = await this.api.getCurrentProject();
            this._projectName.textContent = this.currentProject.name;
            await this.refreshLayerList();
            this.refreshImageList();
            if (this._onProjectChange) {
                this._onProjectChange();
            }
        } catch (err) {
            console.error("Failed to load current project:", err);
            this._projectName.textContent = "(error)";
        }
    }

    /* ------------------------------------------------------------------
     *  Layer list
     * ------------------------------------------------------------------ */

    /**
     * Refresh the layer list shown in the sidebar.
     */
    async refreshLayerList() {
        try {
            this._layers = await this.api.listLayers();
            this._renderLayerList();
        } catch (err) {
            console.error("Failed to load layer list:", err);
        }
    }

    /**
     * Create a layer from the sidebar input.
     *
     * @private
     */
    async _createLayer() {
        const name = this._newLayerInput.value.trim();
        if (!name) {
            return;
        }

        this._newLayerBtn.disabled = true;
        try {
            await this.api.createLayer(name);
            this._newLayerInput.value = "";
            await this.refreshLayerList();
            if (this._canvas) {
                await this._canvas.refreshLayers();
            }
            await this.refreshImageList();
        } catch (err) {
            console.error("Failed to create layer:", err);
        } finally {
            this._newLayerBtn.disabled = false;
        }
    }

    /**
     * Render the current layer list.
     *
     * @private
     */
    _renderLayerList() {
        this._layerList.innerHTML = "";
        for (const layer of this._layers) {
            const row = document.createElement("div");
            row.className = "sidebar__layer-row";
            const name = document.createElement("span");
            name.textContent = layer.name;
            const order = document.createElement("span");
            order.className = "sidebar__layer-order";
            order.textContent = `#${layer.sort_order + 1}`;
            row.appendChild(name);
            row.appendChild(order);
            this._layerList.appendChild(row);
        }
    }

    /* ------------------------------------------------------------------
     *  Image list
     * ------------------------------------------------------------------ */

    /**
     * Fetch images for the current project and rebuild the sidebar table.
     *
     * Clears the existing table body and populates it with two rows per
     * image: a name row and a collapsible detail row showing position,
     * scaled size, and native dimensions.  If the image is currently
     * selected on the canvas, the detail row is shown and the name row
     * is highlighted.  Safe to call at any time — if the API call fails
     * the table is left empty with an error logged to the console.
     */
    async refreshImageList() {
        this._imageTableBody.innerHTML = "";

        try {
            const images = await this.api.listImages();
            if (images.length === 0) {
                const row = document.createElement("tr");
                const cell = document.createElement("td");
                cell.className = "sidebar__image-empty";
                cell.textContent = "No images yet";
                row.appendChild(cell);
                this._imageTableBody.appendChild(row);
                return;
            }

            /* Gather canvas-side data for position/scaled size. */
            const itemsInfo = this._canvas ? this._canvas.getItemsInfo() : new Map();
            const selectedId = this._canvas ? this._canvas.getSelectedImageId() : null;

            for (const img of images) {
                const info = itemsInfo.get(img.id);
                const isSelected = img.id === selectedId;

                /* Name row */
                const nameRow = document.createElement("tr");
                nameRow.dataset.imageId = img.id;
                if (isSelected) {
                    nameRow.className = "sidebar__image-row--selected";
                }
                const nameCell = document.createElement("td");
                nameCell.textContent = img.filename;
                nameCell.title = img.filename;
                nameRow.appendChild(nameCell);
                nameRow.addEventListener("click", () => {
                    if (this._canvas) {
                        this._canvas.selectImageById(parseInt(nameRow.dataset.imageId, 10));
                    }
                });
                this._imageTableBody.appendChild(nameRow);

                /* Detail row (hidden by default) */
                const detailRow = document.createElement("tr");
                detailRow.className = "sidebar__image-detail";
                detailRow.dataset.detailForId = img.id;
                if (isSelected) {
                    detailRow.classList.add("sidebar__image-detail--visible");
                }
                const detailCell = document.createElement("td");
                detailCell.innerHTML = this._buildDetailHtml(info, img);
                detailRow.appendChild(detailCell);
                this._imageTableBody.appendChild(detailRow);
            }
        } catch (err) {
            console.error("Failed to load image list:", err);
        }
    }

    /**
     * Build the HTML string for a detail cell.
     *
     * Combines canvas-side data (position, scaled size) with database
     * record data (native dimensions) into a compact multi-line string.
     *
     * @param {Object|undefined} info - Canvas item info (may be undefined
     *     if the image hasn't loaded yet).
     * @param {Object} record - The image database record.
     * @returns {string} HTML string for the detail cell content.
     * @private
     */
    _buildDetailHtml(info, record) {
        const x = info ? info.x : "?";
        const y = info ? info.y : "?";
        const w = info ? info.width : "?";
        const h = info ? info.height : "?";
        const nw = record.native_width || (info ? info.naturalWidth : 0);
        const nh = record.native_height || (info ? info.naturalHeight : 0);
        const layer = this._escapeHtml(info ? info.layerName : this._layerName(record.layer_id));
        const locked = (info ? info.locked : Boolean(record.locked)) ? "yes" : "no";
        return `Position: ${x}, ${y}<br>` +
               `Size: ${w} &times; ${h}<br>` +
               `Native: ${nw} &times; ${nh}<br>` +
               `Layer: ${layer}<br>` +
               `Locked: ${locked}`;
    }

    /**
     * Return a layer name for display.
     *
     * @param {number|null} layerId - Layer ID.
     * @returns {string} Layer name or fallback text.
     * @private
     */
    _layerName(layerId) {
        const layer = this._layers.find((entry) => entry.id === layerId);
        return layer ? layer.name : "Layer";
    }

    /**
     * Highlight the sidebar row matching the given selection info.
     *
     * Called by the canvas's onSelectionChange callback.  Clears all
     * existing highlights first, then — if info is not null — finds
     * the matching name row and detail row by data attribute and
     * applies the highlight class / updates the detail values.
     *
     * @param {Object|null} info - Selection info object with id, x, y,
     *     width, height, naturalWidth, naturalHeight — or null when
     *     the selection is cleared.
     */
    highlightImage(info) {
        /* Clear all existing highlights. */
        const selected = this._imageTableBody.querySelectorAll(
            ".sidebar__image-row--selected"
        );
        for (const el of selected) {
            el.classList.remove("sidebar__image-row--selected");
        }
        const visibleDetails = this._imageTableBody.querySelectorAll(
            ".sidebar__image-detail--visible"
        );
        for (const el of visibleDetails) {
            el.classList.remove("sidebar__image-detail--visible");
        }

        if (!info) {
            return;
        }

        /* Find the matching name row and detail row. */
        const nameRow = this._imageTableBody.querySelector(
            `tr[data-image-id="${info.id}"]`
        );
        const detailRow = this._imageTableBody.querySelector(
            `tr[data-detail-for-id="${info.id}"]`
        );

        if (nameRow) {
            nameRow.classList.add("sidebar__image-row--selected");
        }
        if (detailRow) {
            detailRow.classList.add("sidebar__image-detail--visible");
            /* Update detail values from the live info. */
            const cell = detailRow.querySelector("td");
            if (cell) {
                const nw = info.naturalWidth || 0;
                const nh = info.naturalHeight || 0;
                cell.innerHTML =
                    `Position: ${info.x}, ${info.y}<br>` +
                    `Size: ${info.width} &times; ${info.height}<br>` +
                    `Native: ${nw} &times; ${nh}<br>` +
                    `Layer: ${this._escapeHtml(info.layerName)}<br>` +
                    `Locked: ${info.locked ? "yes" : "no"}`;
            }
        }
    }

    /**
     * Escape a string before inserting it into a detail row.
     *
     * @param {string} value - Raw display string.
     * @returns {string} HTML-safe text.
     * @private
     */
    _escapeHtml(value) {
        return String(value).replace(/[&<>"']/g, (char) => ({
            "&": "&amp;",
            "<": "&lt;",
            ">": "&gt;",
            "\"": "&quot;",
            "'": "&#39;",
        }[char]));
    }

    /* ------------------------------------------------------------------
     *  Open Project dialog
     * ------------------------------------------------------------------ */

    /**
     * Open the project selection dialog.
     *
     * Fetches the full project list from the backend and builds a modal
     * overlay with a dropdown selector, Open/Cancel buttons, and a
     * "New Project" section with a text input and Create button.
     */
    async openProjectDialog() {
        /* Prevent duplicate dialogs. */
        if (this._dialogOverlay) {
            return;
        }

        let projects;
        try {
            projects = await this.api.listProjects();
        } catch (err) {
            console.error("Failed to list projects:", err);
            return;
        }

        /* Overlay */
        this._dialogOverlay = document.createElement("div");
        this._dialogOverlay.className = "dialog-overlay";

        /* Dialog box */
        const dialog = document.createElement("div");
        dialog.className = "dialog";

        /* Title */
        const title = document.createElement("h2");
        title.textContent = "Open Project";
        dialog.appendChild(title);

        /* Project dropdown */
        const select = document.createElement("select");
        select.className = "dialog__project-list";
        for (const proj of projects) {
            const opt = document.createElement("option");
            opt.value = proj.id;
            opt.textContent = proj.name;
            if (this.currentProject && proj.id === this.currentProject.id) {
                opt.selected = true;
            }
            select.appendChild(opt);
        }
        dialog.appendChild(select);

        /* Action buttons */
        const actions = document.createElement("div");
        actions.className = "dialog__actions";

        const openBtn = document.createElement("button");
        openBtn.className = "dialog__open-btn";
        openBtn.textContent = "Open";
        openBtn.addEventListener("click", () => {
            this._onOpenProject(Number(select.value));
        });

        const cancelBtn = document.createElement("button");
        cancelBtn.className = "dialog__cancel-btn";
        cancelBtn.textContent = "Cancel";
        cancelBtn.addEventListener("click", () => this.closeProjectDialog());

        actions.appendChild(openBtn);
        actions.appendChild(cancelBtn);
        dialog.appendChild(actions);

        /* Divider */
        const hr = document.createElement("hr");
        dialog.appendChild(hr);

        /* New project section */
        const newTitle = document.createElement("h3");
        newTitle.textContent = "New Project";
        dialog.appendChild(newTitle);

        const newRow = document.createElement("div");
        newRow.className = "dialog__new-row";

        const nameInput = document.createElement("input");
        nameInput.type = "text";
        nameInput.className = "dialog__new-name";
        nameInput.placeholder = "Project name";

        const createBtn = document.createElement("button");
        createBtn.className = "dialog__create-btn";
        createBtn.textContent = "Create";
        createBtn.addEventListener("click", () => {
            const name = nameInput.value.trim();
            if (name) {
                this._onCreateProject(name);
            }
        });

        /* Allow Enter key in the input to trigger create. */
        nameInput.addEventListener("keydown", (e) => {
            if (e.key === "Enter") {
                const name = nameInput.value.trim();
                if (name) {
                    this._onCreateProject(name);
                }
            }
        });

        newRow.appendChild(nameInput);
        newRow.appendChild(createBtn);
        dialog.appendChild(newRow);

        /* Assemble and show */
        this._dialogOverlay.appendChild(dialog);
        document.body.appendChild(this._dialogOverlay);
    }

    /**
     * Close and remove the project dialog from the DOM.
     */
    closeProjectDialog() {
        if (this._dialogOverlay) {
            this._dialogOverlay.remove();
            this._dialogOverlay = null;
        }
    }

    /**
     * Handle opening an existing project selected from the dropdown.
     *
     * Sends the request to the backend, updates the sidebar display,
     * and closes the dialog.
     *
     * @param {number} projectId - The ID of the project to open.
     * @private
     */
    async _onOpenProject(projectId) {
        try {
            this.currentProject = await this.api.openProject(projectId);
            this._projectName.textContent = this.currentProject.name;
            this.closeProjectDialog();
            await this.refreshLayerList();
            this.refreshImageList();
            if (this._onProjectChange) {
                this._onProjectChange();
            }
        } catch (err) {
            console.error("Failed to open project:", err);
            alert("Could not open project: " + err.message);
        }
    }

    /**
     * Handle creating a new project from the dialog input.
     *
     * Sends the create request to the backend, updates the sidebar
     * display, and closes the dialog.
     *
     * @param {string} name - The name for the new project.
     * @private
     */
    async _onCreateProject(name) {
        try {
            this.currentProject = await this.api.createProject(name);
            this._projectName.textContent = this.currentProject.name;
            this.closeProjectDialog();
            await this.refreshLayerList();
            this.refreshImageList();
            if (this._onProjectChange) {
                this._onProjectChange();
            }
        } catch (err) {
            console.error("Failed to create project:", err);
            alert("Could not create project: " + err.message);
        }
    }
}
