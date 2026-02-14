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
