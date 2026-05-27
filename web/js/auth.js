/**
 * AuthController — manages the login screen and authenticated app startup.
 *
 * The controller checks the existing server session on page load.  If the
 * browser is authenticated it calls the supplied startup callback; otherwise
 * it renders a compact login form that posts credentials to the backend.
 */
class AuthController {

    /**
     * Create the controller and check the current session.
     *
     * @param {ApiClient} api - The API client used for auth requests.
     * @param {Object} options - Configuration options.
     * @param {Function} options.onAuthenticated - Callback invoked with the
     *     public user object after a valid login or existing session.
     */
    constructor(api, options) {
        /** @type {ApiClient} */
        this.api = api;

        /** @type {Function} */
        this._onAuthenticated = options.onAuthenticated;

        /** @type {HTMLElement|null} */
        this._overlay = null;

        /** @type {HTMLFormElement|null} */
        this._form = null;

        /** @type {HTMLElement|null} */
        this._error = null;

        this._checkSession();
    }

    /**
     * Log out and reload the app into its unauthenticated state.
     *
     * @returns {Promise<void>} Resolves after the logout request has finished.
     */
    async logout() {
        try {
            await this.api.logout();
        } finally {
            window.location.reload();
        }
    }

    /**
     * Ask the backend whether this browser already has a valid session.
     *
     * Existing sessions skip the login screen and start the application
     * immediately.  Failed checks fall back to showing the login form.
     *
     * @private
     */
    async _checkSession() {
        try {
            const session = await this.api.getSession();
            if (session.authenticated) {
                this._onAuthenticated(session.user);
                return;
            }
        } catch (err) {
            console.error("Failed to check session:", err);
        }
        this._showLogin();
    }

    /**
     * Build and display the login overlay.
     *
     * The form is created with DOM APIs to keep credentials out of the URL and
     * posts JSON credentials to the login endpoint.
     *
     * @private
     */
    _showLogin() {
        if (this._overlay) {
            return;
        }

        this._overlay = document.createElement("section");
        this._overlay.className = "auth";

        const panel = document.createElement("div");
        panel.className = "auth__panel";

        const title = document.createElement("h1");
        title.textContent = "Mood Board";

        const subtitle = document.createElement("p");
        subtitle.textContent = "Sign in to open your canvas.";

        this._form = document.createElement("form");
        this._form.className = "auth__form";

        const username = this._buildInput("text", "Username", "username");
        const password = this._buildInput("password", "Password", "current-password");

        const submit = document.createElement("button");
        submit.type = "submit";
        submit.textContent = "Sign in";

        this._error = document.createElement("p");
        this._error.className = "auth__error";
        this._error.setAttribute("role", "alert");

        this._form.appendChild(username);
        this._form.appendChild(password);
        this._form.appendChild(submit);
        this._form.appendChild(this._error);
        this._form.addEventListener("submit", (event) => this._onSubmit(event));

        panel.appendChild(title);
        panel.appendChild(subtitle);
        panel.appendChild(this._form);
        this._overlay.appendChild(panel);
        document.body.appendChild(this._overlay);

        username.focus();
    }

    /**
     * Create a styled form input for the login panel.
     *
     * @param {string} type - Input type, such as text or password.
     * @param {string} placeholder - Placeholder shown inside the input.
     * @param {string} autocomplete - Browser autocomplete token.
     * @returns {HTMLInputElement} Configured input element.
     * @private
     */
    _buildInput(type, placeholder, autocomplete) {
        const input = document.createElement("input");
        input.type = type;
        input.placeholder = placeholder;
        input.autocomplete = autocomplete;
        input.required = true;
        return input;
    }

    /**
     * Submit credentials to the backend and start the app on success.
     *
     * @param {SubmitEvent} event - Native form submit event.
     * @private
     */
    async _onSubmit(event) {
        event.preventDefault();
        const usernameInput = this._form.querySelector('input[type="text"]');
        const passwordInput = this._form.querySelector('input[type="password"]');
        const submit = this._form.querySelector('button[type="submit"]');
        submit.disabled = true;
        this._setError("");

        try {
            const session = await this.api.login(
                usernameInput.value.trim(),
                passwordInput.value
            );
            this._overlay.remove();
            this._overlay = null;
            this._onAuthenticated(session.user);
        } catch (err) {
            this._setError(err.message || "Sign in failed.");
        } finally {
            submit.disabled = false;
        }
    }

    /**
     * Update the login error message.
     *
     * @param {string} message - Error text to display, or empty to clear it.
     * @private
     */
    _setError(message) {
        if (this._error) {
            this._error.textContent = message;
        }
    }
}
