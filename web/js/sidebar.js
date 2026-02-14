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
     */
    constructor(api) {
        /** @type {ApiClient} */
        this.api = api;

        /** @type {boolean} Whether the sidebar is currently expanded. */
        this.isOpen = true;

        /** @type {Object|null} The currently loaded project. */
        this.currentProject = null;

        /** @type {HTMLElement|null} The dialog overlay element. */
        this._dialogOverlay = null;

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

        /* Assemble */
        this._el.appendChild(this._header);
        this._el.appendChild(this._content);
        document.body.appendChild(this._el);
    }

    /* ------------------------------------------------------------------
     *  Event binding
     * ------------------------------------------------------------------ */

    /**
     * Bind click handlers for the toggle button and Open Project button.
     * @private
     */
    _bindEvents() {
        this._toggleBtn.addEventListener("click", () => this.toggle());
        this._openBtn.addEventListener("click", () => this.openProjectDialog());
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
        } catch (err) {
            console.error("Failed to load current project:", err);
            this._projectName.textContent = "(error)";
        }
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
        } catch (err) {
            console.error("Failed to create project:", err);
            alert("Could not create project: " + err.message);
        }
    }
}
