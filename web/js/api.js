/**
 * ApiClient — handles all HTTP communication with the mood board backend.
 *
 * Each method maps to a single API endpoint and returns the parsed JSON
 * response.  Errors are thrown as plain Error objects with the server's
 * message when the response status is not OK.
 */
class ApiClient {

    /**
     * Fetch the current project from the backend.
     *
     * If no projects exist yet the backend automatically creates a
     * default "Untitled Project" and returns it.
     *
     * @returns {Promise<Object>} The current project object.
     */
    async getCurrentProject() {
        const response = await fetch("/api/current-project");
        return this._handleResponse(response);
    }

    /**
     * Fetch all projects from the backend.
     *
     * @returns {Promise<Array<Object>>} An array of project objects
     *     ordered alphabetically by name.
     */
    async listProjects() {
        const response = await fetch("/api/projects");
        return this._handleResponse(response);
    }

    /**
     * Set a project as the current (active) project.
     *
     * @param {number} projectId - The ID of the project to open.
     * @returns {Promise<Object>} The opened project object.
     */
    async openProject(projectId) {
        const response = await fetch("/api/projects/open", {
            method: "POST",
            headers: { "Content-Type": "application/json" },
            body: JSON.stringify({ project_id: projectId }),
        });
        return this._handleResponse(response);
    }

    /**
     * Create a new project and set it as current.
     *
     * @param {string} name - The project name.
     * @returns {Promise<Object>} The newly created project object.
     */
    async createProject(name) {
        const response = await fetch("/api/projects", {
            method: "POST",
            headers: { "Content-Type": "application/json" },
            body: JSON.stringify({ name }),
        });
        return this._handleResponse(response);
    }

    /**
     * Upload an image file to the current project.
     *
     * Reads the file as base64 and sends it to the backend as a JSON
     * payload.  The backend saves the file to disk and records it in
     * the database.
     *
     * @param {File} file - A File object (e.g. from a drop event).
     * @returns {Promise<Object>} The created image record.
     */
    async uploadImage(file) {
        const base64Data = await this._readFileAsBase64(file);
        const response = await fetch("/api/images/upload", {
            method: "POST",
            headers: { "Content-Type": "application/json" },
            body: JSON.stringify({ filename: file.name, data: base64Data }),
        });
        return this._handleResponse(response);
    }

    /**
     * Fetch all images for the current project.
     *
     * @returns {Promise<Array<Object>>} An array of image objects ordered
     *     by z_index then id.
     */
    async listImages() {
        const response = await fetch("/api/images");
        return this._handleResponse(response);
    }

    /**
     * Update fields on an existing image record.
     *
     * Sends the provided fields (pos_x, pos_y, scale, rotation, z_index)
     * to the backend which persists them in the database.
     *
     * @param {number} imageId - The image record ID.
     * @param {Object} fields - An object with one or more updatable keys.
     * @returns {Promise<Object>} The updated image record.
     */
    async updateImage(imageId, fields) {
        const response = await fetch("/api/images/update", {
            method: "POST",
            headers: { "Content-Type": "application/json" },
            body: JSON.stringify({ image_id: imageId, ...fields }),
        });
        return this._handleResponse(response);
    }

    /**
     * Read a File object as a base64-encoded string (data portion only).
     *
     * Uses FileReader to convert the file contents to a base64 string,
     * stripping the ``data:...;base64,`` prefix so the backend receives
     * pure base64.
     *
     * @param {File} file - The file to read.
     * @returns {Promise<string>} The base64-encoded file content.
     * @private
     */
    _readFileAsBase64(file) {
        return new Promise((resolve, reject) => {
            const reader = new FileReader();
            reader.onload = () => {
                /* Strip the "data:<mime>;base64," prefix. */
                const result = reader.result;
                const base64 = result.substring(result.indexOf(",") + 1);
                resolve(base64);
            };
            reader.onerror = () => reject(reader.error);
            reader.readAsDataURL(file);
        });
    }

    /**
     * Parse a fetch response and throw on non-OK status codes.
     *
     * @param {Response} response - The fetch Response object.
     * @returns {Promise<Object|Array>} The parsed JSON body.
     * @throws {Error} If the response status is not OK.
     * @private
     */
    async _handleResponse(response) {
        const data = await response.json();
        if (!response.ok) {
            throw new Error(data.error || `Request failed (${response.status})`);
        }
        return data;
    }
}
