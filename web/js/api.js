/**
 * ApiClient — handles all HTTP communication with the mood board backend.
 *
 * Each method maps to a single API endpoint and returns the parsed JSON
 * response.  Errors are thrown as plain Error objects with the server's
 * message when the response status is not OK.
 */
class ApiClient {

    /**
     * Fetch the current login session from the backend.
     *
     * The backend reads the HTTP-only session cookie and returns a small
     * public user object when the browser is already authenticated.
     *
     * @returns {Promise<Object>} Session state with authenticated and user keys.
     */
    async getSession() {
        const response = await fetch("/api/session");
        return this._handleResponse(response);
    }

    /**
     * Log in with a username and password.
     *
     * On success the backend sets an HTTP-only session cookie.  JavaScript
     * never receives or stores the raw session token.
     *
     * @param {string} username - The login username.
     * @param {string} password - The login password.
     * @returns {Promise<Object>} Session state with authenticated and user keys.
     */
    async login(username, password) {
        const response = await fetch("/api/login", {
            method: "POST",
            headers: { "Content-Type": "application/json" },
            body: JSON.stringify({ username, password }),
        });
        return this._handleResponse(response);
    }

    /**
     * Log out the current browser session.
     *
     * The backend deletes the session record and clears the HTTP-only cookie.
     *
     * @returns {Promise<Object>} A success confirmation object.
     */
    async logout() {
        const response = await fetch("/api/logout", { method: "POST" });
        return this._handleResponse(response);
    }

    /**
     * Fetch all users for the administrator user-management view.
     *
     * @returns {Promise<Array<Object>>} Public user records.
     */
    async listUsers() {
        const response = await fetch("/api/users");
        return this._handleResponse(response);
    }

    /**
     * Create a new user.
     *
     * @param {string} username - New user's login name.
     * @param {string} password - New user's initial password.
     * @param {boolean} isAdmin - Whether the new user is an administrator.
     * @returns {Promise<Object>} Created public user record.
     */
    async createUser(username, password, isAdmin = false) {
        const response = await fetch("/api/users", {
            method: "POST",
            headers: { "Content-Type": "application/json" },
            body: JSON.stringify({
                username,
                password,
                is_admin: isAdmin,
            }),
        });
        return this._handleResponse(response);
    }

    /**
     * Change the current user's password.
     *
     * @param {string} currentPassword - Current password for verification.
     * @param {string} newPassword - New password to store.
     * @returns {Promise<Object>} Success confirmation.
     */
    async changePassword(currentPassword, newPassword) {
        const response = await fetch("/api/users/password", {
            method: "POST",
            headers: { "Content-Type": "application/json" },
            body: JSON.stringify({
                current_password: currentPassword,
                new_password: newPassword,
            }),
        });
        return this._handleResponse(response);
    }

    /**
     * Reset a user's password as an administrator.
     *
     * @param {number} userId - User ID to update.
     * @param {string} newPassword - Replacement password.
     * @returns {Promise<Object>} Success confirmation.
     */
    async resetUserPassword(userId, newPassword) {
        const response = await fetch("/api/users/reset-password", {
            method: "POST",
            headers: { "Content-Type": "application/json" },
            body: JSON.stringify({
                user_id: userId,
                new_password: newPassword,
            }),
        });
        return this._handleResponse(response);
    }

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
     * Rename an existing project.
     *
     * Sends the project ID and new name to the backend which updates the
     * database record and moves the project directory on disk.
     *
     * @param {number} projectId - The ID of the project to rename.
     * @param {string} newName - The desired new name.
     * @returns {Promise<Object>} The updated project object.
     */
    async renameProject(projectId, newName) {
        const response = await fetch("/api/projects/rename", {
            method: "POST",
            headers: { "Content-Type": "application/json" },
            body: JSON.stringify({ project_id: projectId, new_name: newName }),
        });
        return this._handleResponse(response);
    }

    /**
     * Upload an image or WebM file to the current project.
     *
     * Extracts the native pixel dimensions by loading the file into a
     * temporary Image element, then streams the original binary file to the
     * backend.  Sending the file directly avoids base64 expansion and keeps
     * large uploads much lighter for browsers such as Firefox.
     *
     * @param {File} file - A File object (e.g. from a drop event).
     * @returns {Promise<Object>} The created image record.
     */
    async uploadImage(file) {
        const dims = await this._getNativeMediaDimensions(file);
        const params = new URLSearchParams({
            filename: file.name,
            native_width: String(dims.width),
            native_height: String(dims.height),
        });
        const response = await fetch(`/api/images/upload?${params.toString()}`, {
            method: "POST",
            headers: {
                "Content-Type": file.type || "application/octet-stream",
            },
            body: file,
        });
        return this._handleResponse(response);
    }

    /**
     * Import an image or WebM file from a remote URL.
     *
     * The backend downloads and validates the URL server-side, then stores the
     * resulting media file in the current project just like a normal upload.
     *
     * @param {string} url - Remote HTTP(S) media URL.
     * @returns {Promise<Object>} The created image record.
     */
    async importImageUrl(url) {
        const response = await fetch("/api/images/import-url", {
            method: "POST",
            headers: { "Content-Type": "application/json" },
            body: JSON.stringify({ url }),
        });
        return this._handleResponse(response);
    }

    /**
     * Load a File into temporary media to read its native dimensions.
     *
     * Creates an object URL from the file, waits for an image or video to load
     * enough metadata, reads its natural dimensions, then revokes the URL to
     * free memory.
     *
     * @param {File} file - The image or WebM file.
     * @returns {Promise<{width: number, height: number}>} Native pixel dimensions.
     * @private
     */
    _getNativeMediaDimensions(file) {
        if (file.type === "video/webm" || file.name.toLowerCase().endsWith(".webm")) {
            return this._getNativeVideoDimensions(file);
        }
        return this._getNativeImageDimensions(file);
    }

    /**
     * Load an image File to read its native dimensions.
     *
     * @param {File} file - The image file.
     * @returns {Promise<{width: number, height: number}>} Native pixel dimensions.
     * @private
     */
    _getNativeImageDimensions(file) {
        return new Promise((resolve) => {
            const url = URL.createObjectURL(file);
            const img = new Image();
            img.onload = () => {
                const width = img.naturalWidth;
                const height = img.naturalHeight;
                URL.revokeObjectURL(url);
                resolve({ width, height });
            };
            img.onerror = () => {
                URL.revokeObjectURL(url);
                resolve({ width: 0, height: 0 });
            };
            img.src = url;
        });
    }

    /**
     * Load a WebM File to read its native video dimensions.
     *
     * @param {File} file - The WebM file.
     * @returns {Promise<{width: number, height: number}>} Native pixel dimensions.
     * @private
     */
    _getNativeVideoDimensions(file) {
        return new Promise((resolve) => {
            const url = URL.createObjectURL(file);
            const video = document.createElement("video");
            video.preload = "metadata";
            video.onloadedmetadata = () => {
                const width = video.videoWidth;
                const height = video.videoHeight;
                URL.revokeObjectURL(url);
                resolve({ width, height });
            };
            video.onerror = () => {
                URL.revokeObjectURL(url);
                resolve({ width: 0, height: 0 });
            };
            video.src = url;
        });
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
     * Sends the provided fields (pos_x, pos_y, scale, rotation, z_index, or
     * loop_enabled) to the backend which persists them in the database.
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
     * Delete an image from the current project.
     *
     * Sends the image ID to the backend which removes the database record
     * and deletes the file from disk.
     *
     * @param {number} imageId - The image record ID.
     * @returns {Promise<Object>} A success confirmation object.
     */
    async deleteImage(imageId) {
        const response = await fetch("/api/images/delete", {
            method: "POST",
            headers: { "Content-Type": "application/json" },
            body: JSON.stringify({ image_id: imageId }),
        });
        return this._handleResponse(response);
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
