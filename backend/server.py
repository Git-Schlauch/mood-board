"""Mood Board — lightweight development web server.

Serves static files from the ``web/`` directory and exposes a small JSON
API for project management.  Uses Python's built-in :mod:`http.server`
module — no third-party dependencies are required.

Usage::

    python backend/server.py [--port PORT]

The default port is **8031**.
"""

from __future__ import annotations

import argparse
import base64
from http.cookies import SimpleCookie
import functools
import json
import mimetypes
import os
import sqlite3
import sys
import secrets
import urllib.parse
from http.server import HTTPServer, SimpleHTTPRequestHandler
from typing import Any

from backend.database import Database


SESSION_COOKIE_NAME = "mood_board_session"
SESSION_LIFETIME_SECONDS = 60 * 60 * 24 * 7


class MoodBoardRequestHandler(SimpleHTTPRequestHandler):
    """HTTP request handler serving static files and a project management API.

    Static files are served from the ``web/`` directory.  Paths starting
    with ``/api/`` are routed to handler methods that interact with the
    :class:`Database` instance.
    """

    def __init__(
        self,
        *args: Any,
        directory: str | None = None,
        db: Database | None = None,
        **kwargs: Any,
    ) -> None:
        """Initialise the handler with a document root and database.

        ``self.db`` is assigned **before** calling the parent constructor
        because :class:`SimpleHTTPRequestHandler.__init__` immediately
        processes the incoming request (calls ``handle()``).

        Args:
            directory: Absolute path to the directory to serve.
            db: The shared :class:`Database` instance.
            *args: Positional arguments forwarded to the parent class.
            **kwargs: Keyword arguments forwarded to the parent class.
        """
        self.db: Database | None = db
        self.current_user: dict[str, Any] | None = None
        super().__init__(*args, directory=directory, **kwargs)

    # -- HTTP verb overrides -------------------------------------------------

    def do_GET(self) -> None:
        """Route GET requests to API handlers or static file serving."""
        if self.path == "/api/session":
            self._handle_session()
        elif self.path.startswith("/api/") and not self._require_authentication():
            return
        elif self.path.startswith("/projects/") and not self._require_authentication():
            return
        elif self.path == "/api/current-project":
            self._handle_current_project()
        elif self.path == "/api/projects":
            self._handle_list_projects()
        elif self.path == "/api/images":
            self._handle_list_images()
        elif self.path.startswith("/projects/"):
            self._handle_serve_image()
        else:
            super().do_GET()

    def do_POST(self) -> None:
        """Route POST requests to the appropriate API handler."""
        if self.path == "/api/login":
            self._handle_login()
        elif self.path == "/api/logout":
            self._handle_logout()
        elif self.path.startswith("/api/") and not self._require_authentication():
            return
        elif self.path == "/api/projects/open":
            self._handle_open_project()
        elif self.path == "/api/projects":
            self._handle_create_project()
        elif self.path == "/api/images/upload":
            self._handle_image_upload()
        elif self.path == "/api/images/update":
            self._handle_image_update()
        elif self.path == "/api/images/delete":
            self._handle_image_delete()
        elif self.path == "/api/projects/rename":
            self._handle_rename_project()
        else:
            self.send_error(404)

    # -- API handlers --------------------------------------------------------

    def _handle_session(self) -> None:
        """Return the current authentication state for the browser.

        ``GET /api/session``
        """
        user = self._get_authenticated_user()
        if user is None:
            self._send_json({"authenticated": False, "user": None})
            return

        self._send_json({"authenticated": True, "user": self._public_user(user)})

    def _handle_login(self) -> None:
        """Authenticate a user and set an HTTP-only session cookie.

        ``POST /api/login``

        Expects ``{"username": "<name>", "password": "<password>"}``.
        Returns the public user record on success, or 401 for invalid
        credentials.
        """
        body = self._read_json_body()
        if body is None:
            return

        username = str(body.get("username", ""))
        password = str(body.get("password", ""))
        user = self.db.authenticate_user(username, password)
        if user is None:
            self._send_json({"error": "Invalid username or password"}, status=401)
            return

        token = self.db.create_session(user["id"], SESSION_LIFETIME_SECONDS)
        self._send_json(
            {"authenticated": True, "user": self._public_user(user)},
            headers={"Set-Cookie": self._build_session_cookie(token)},
        )

    def _handle_logout(self) -> None:
        """Clear the browser session and remove it from the database.

        ``POST /api/logout``
        """
        token = self._read_session_cookie()
        if token:
            self.db.delete_session(token)
        self._send_json(
            {"success": True},
            headers={"Set-Cookie": self._build_clear_session_cookie()},
        )

    def _handle_current_project(self) -> None:
        """Return the current project, auto-creating one if none exist.

        ``GET /api/current-project``
        """
        project = self.db.get_or_create_current_project(self.current_user["id"])
        self._send_json(project)

    def _handle_list_projects(self) -> None:
        """Return all projects as a JSON array.

        ``GET /api/projects``
        """
        projects = self.db.list_projects(self.current_user["id"])
        self._send_json(projects)

    def _handle_open_project(self) -> None:
        """Set a project as the current project.

        ``POST /api/projects/open``

        Expects a JSON body with ``{"project_id": <int>}``.  Returns the
        opened project on success, or a 404 if the project does not exist.
        """
        body = self._read_json_body()
        if body is None:
            return

        project_id = body.get("project_id")
        if project_id is None:
            self._send_json({"error": "Missing project_id"}, status=400)
            return

        project = self.db.get_project(int(project_id), user_id=self.current_user["id"])
        if project is None:
            self._send_json({"error": "Project not found"}, status=404)
            return

        self.db.set_user_setting(
            self.current_user["id"], "current_project_id", str(project["id"])
        )
        self._send_json(project)

    def _handle_create_project(self) -> None:
        """Create a new project and set it as current.

        ``POST /api/projects``

        Expects a JSON body with ``{"name": "<string>"}``.  Returns the
        newly created project on success, 400 on validation error, or
        409 if the name is already taken.
        """
        body = self._read_json_body()
        if body is None:
            return

        name = body.get("name")
        if not name:
            self._send_json({"error": "Missing project name"}, status=400)
            return

        try:
            project = self.db.create_project(name, user_id=self.current_user["id"])
        except ValueError as exc:
            self._send_json({"error": str(exc)}, status=400)
            return
        except sqlite3.IntegrityError:
            self._send_json(
                {"error": f"Project '{name}' already exists"}, status=409
            )
            return

        self.db.set_user_setting(
            self.current_user["id"], "current_project_id", str(project["id"])
        )
        self._send_json(project, status=201)

    def _handle_rename_project(self) -> None:
        """Rename an existing project.

        ``POST /api/projects/rename``

        Expects a JSON body with ``{"project_id": <int>, "new_name": "<string>"}``.
        Delegates to :meth:`Database.rename_project` which updates the database
        and moves the project directory on disk.  Returns the updated project
        dict on success, 400 on validation error, 404 if the project is not
        found, or 409 if the new name is already taken.
        """
        body = self._read_json_body()
        if body is None:
            return

        project_id = body.get("project_id")
        new_name = body.get("new_name")

        if project_id is None or not new_name:
            self._send_json(
                {"error": "Missing project_id or new_name"}, status=400
            )
            return

        try:
            success = self.db.rename_project(
                int(project_id), new_name, user_id=self.current_user["id"]
            )
        except ValueError as exc:
            self._send_json({"error": str(exc)}, status=400)
            return
        except sqlite3.IntegrityError:
            self._send_json(
                {"error": f"Project '{new_name}' already exists"}, status=409
            )
            return

        if not success:
            self._send_json({"error": "Project not found"}, status=404)
            return

        project = self.db.get_project(int(project_id), user_id=self.current_user["id"])
        self._send_json(project)

    # -- image handlers ------------------------------------------------------

    def _handle_list_images(self) -> None:
        """Return all images for the current project as a JSON array.

        ``GET /api/images``

        Fetches the current project and returns its image records ordered
        by z_index then id.
        """
        project = self.db.get_or_create_current_project(self.current_user["id"])
        images = self.db.list_images(project["id"])
        self._send_json(images)

    def _handle_image_upload(self) -> None:
        """Accept a base64-encoded image upload and save it to disk.

        ``POST /api/images/upload``

        Expects a JSON body with ``{"filename": "<string>", "data": "<base64>"}``
        where *data* is the raw file content encoded as base64.  The file is
        saved into the current project's directory.  Filename conflicts are
        resolved by appending a numeric suffix (e.g. ``photo_1.png``).

        Returns the created image database record on success.
        """
        body = self._read_json_body()
        if body is None:
            return

        filename = body.get("filename")
        data_b64 = body.get("data")

        if not filename or not data_b64:
            self._send_json(
                {"error": "Missing 'filename' or 'data' field"}, status=400
            )
            return

        # Decode base64 payload.
        try:
            file_bytes = base64.b64decode(data_b64)
        except Exception:
            self._send_json({"error": "Invalid base64 data"}, status=400)
            return

        filename = os.path.basename(filename)
        if not filename:
            self._send_json({"error": "Invalid filename"}, status=400)
            return
        if not self._is_supported_image_upload(filename, file_bytes):
            self._send_json(
                {"error": "Only PNG, JPEG, GIF, and WebP images are supported"},
                status=400,
            )
            return

        project = self.db.get_or_create_current_project(self.current_user["id"])
        project_name: str = project["name"]

        # Resolve filename conflicts by appending a numeric suffix.
        save_name = self._unique_filename(project_name, filename)

        # Ensure the project directory exists and write the file.
        dest = self.db.get_image_path(project_name, save_name)
        os.makedirs(os.path.dirname(dest), exist_ok=True)
        with open(dest, "wb") as fh:
            fh.write(file_bytes)

        # Extract optional native dimensions sent by the frontend.
        native_width = int(body.get("native_width", 0))
        native_height = int(body.get("native_height", 0))

        # Record in the database.
        image = self.db.add_image(
            project["id"], save_name,
            native_width=native_width,
            native_height=native_height,
        )
        self._send_json(image, status=201)

    def _unique_filename(self, project_name: str, filename: str) -> str:
        """Return a filename that does not collide with existing files.

        If *filename* already exists in the project directory a numeric
        suffix is appended before the extension (e.g. ``photo_1.png``,
        ``photo_2.png``) until an unused name is found.

        Args:
            project_name: The project name (used to resolve the directory).
            filename: The desired filename.

        Returns:
            A filename guaranteed not to exist in the project directory.
        """
        dest = self.db.get_image_path(project_name, filename)
        if not os.path.exists(dest):
            return filename

        base, ext = os.path.splitext(filename)
        counter = 1
        while True:
            candidate = f"{base}_{counter}{ext}"
            if not os.path.exists(self.db.get_image_path(project_name, candidate)):
                return candidate
            counter += 1

    def _handle_image_update(self) -> None:
        """Update position, scale, or other fields on an image record.

        ``POST /api/images/update``

        Expects a JSON body with ``{"image_id": <int>, ...fields}`` where
        the additional fields are any subset of ``pos_x``, ``pos_y``,
        ``scale``, ``rotation``, ``z_index``.  Returns the updated image
        record on success, or 404 if the image does not exist.
        """
        body = self._read_json_body()
        if body is None:
            return

        image_id = body.get("image_id")
        if image_id is None:
            self._send_json({"error": "Missing image_id"}, status=400)
            return

        # Extract only the updatable fields from the body.
        fields = {
            k: v for k, v in body.items()
            if k in ("pos_x", "pos_y", "scale", "rotation", "z_index")
        }
        if not fields:
            self._send_json({"error": "No updatable fields provided"}, status=400)
            return

        image = self.db.get_image_for_user(int(image_id), self.current_user["id"])
        if image is None:
            self._send_json({"error": "Image not found"}, status=404)
            return

        updated = self.db.update_image(int(image_id), **fields)
        if not updated:
            self._send_json({"error": "Image not found"}, status=404)
            return

        image = self.db.get_image_for_user(int(image_id), self.current_user["id"])
        self._send_json(image)

    def _handle_image_delete(self) -> None:
        """Delete an image record and its file from disk.

        ``POST /api/images/delete``

        Expects a JSON body with ``{"image_id": <int>}``.  Removes the
        database record first, then attempts to delete the corresponding
        file from disk.  Returns a success message on success, or 404 if
        the image does not exist.
        """
        body = self._read_json_body()
        if body is None:
            return

        image_id = body.get("image_id")
        if image_id is None:
            self._send_json({"error": "Missing image_id"}, status=400)
            return

        # Fetch the image record before deleting so we know the filename.
        image = self.db.get_image_for_user(int(image_id), self.current_user["id"])
        if image is None:
            self._send_json({"error": "Image not found"}, status=404)
            return

        # Delete from database.
        self.db.delete_image(int(image_id))

        # Delete file from disk.
        project = self.db.get_project(image["project_id"])
        if project:
            file_path = self.db.get_image_path(project["name"], image["filename"])
            if os.path.isfile(file_path):
                try:
                    os.remove(file_path)
                except OSError as exc:
                    # Log but don't fail — the DB record is already gone.
                    sys.stderr.write(
                        f"Warning: could not delete file {file_path}: {exc}\n"
                    )

        self._send_json({"success": True})

    def _handle_serve_image(self) -> None:
        """Serve an uploaded image file from the projects directory.

        ``GET /projects/<project-name>/<filename>``

        Decodes the URL path, validates against path traversal attacks,
        and sends the file with the appropriate Content-Type header.
        """
        # Decode URL-encoded path (e.g. spaces as %20).
        decoded_path = urllib.parse.unquote(self.path)

        # Strip the leading "/projects/" prefix and split into parts.
        relative = decoded_path[len("/projects/"):]
        parts = relative.split("/")

        # We expect exactly two segments: project name and filename.
        if len(parts) != 2 or ".." in parts or not all(parts):
            self.send_error(400, "Invalid image path")
            return

        project_name, filename = parts
        project = self.db.get_project_by_name(
            project_name, user_id=self.current_user["id"]
        )
        if project is None:
            self.send_error(404, "Image not found")
            return

        file_path = self.db.get_image_path(project_name, filename)

        if not os.path.isfile(file_path):
            self.send_error(404, "Image not found")
            return

        # Determine content type from file extension.
        content_type, _ = mimetypes.guess_type(filename)
        if content_type is None:
            content_type = "application/octet-stream"

        try:
            with open(file_path, "rb") as fh:
                data = fh.read()
        except OSError:
            self.send_error(500, "Failed to read image file")
            return

        self.send_response(200)
        self.send_header("Content-Type", content_type)
        self.send_header("Content-Length", str(len(data)))
        self.end_headers()
        self.wfile.write(data)

    # -- JSON helpers --------------------------------------------------------

    def _send_json(
        self, data: Any, status: int = 200, headers: dict[str, str] | None = None
    ) -> None:
        """Serialise *data* as JSON and send it as the HTTP response.

        Args:
            data: Any JSON-serialisable value (dict, list, etc.).
            status: The HTTP status code (default 200).
            headers: Optional extra response headers.
        """
        payload = json.dumps(data).encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(payload)))
        if headers:
            for key, value in headers.items():
                self.send_header(key, value)
        self.end_headers()
        self.wfile.write(payload)

    def _read_json_body(self) -> dict[str, Any] | None:
        """Read and parse the request body as JSON.

        Sends a 400 error and returns ``None`` if the body is missing or
        is not valid JSON.

        Returns:
            The parsed JSON object, or ``None`` on failure.
        """
        content_length = int(self.headers.get("Content-Length", 0))
        if content_length == 0:
            self._send_json({"error": "Empty request body"}, status=400)
            return None

        raw = self.rfile.read(content_length)
        try:
            return json.loads(raw)
        except json.JSONDecodeError:
            self._send_json({"error": "Invalid JSON"}, status=400)
            return None

    def log_message(self, format: str, *args: Any) -> None:
        """Write log messages to stderr with a cleaner format."""
        sys.stderr.write(f"[{self.log_date_time_string()}] {format % args}\n")

    # -- authentication helpers --------------------------------------------

    def _require_authentication(self) -> bool:
        """Require a valid session for the current request.

        Returns:
            ``True`` when a user is authenticated, otherwise sends a 401 JSON
            response and returns ``False``.
        """
        user = self._get_authenticated_user()
        if user is None:
            self._send_json({"error": "Authentication required"}, status=401)
            return False
        self.current_user = user
        return True

    def _get_authenticated_user(self) -> dict[str, Any] | None:
        """Resolve the current user from the session cookie.

        Returns:
            A public user dict, or ``None`` when no valid session exists.
        """
        token = self._read_session_cookie()
        if not token:
            return None
        return self.db.get_user_by_session(token)

    def _read_session_cookie(self) -> str | None:
        """Read the raw session token from the Cookie header.

        Returns:
            The session token string, or ``None`` if it is absent.
        """
        cookie_header = self.headers.get("Cookie")
        if not cookie_header:
            return None
        cookies = SimpleCookie()
        cookies.load(cookie_header)
        morsel = cookies.get(SESSION_COOKIE_NAME)
        return morsel.value if morsel else None

    def _build_session_cookie(self, token: str) -> str:
        """Build a Set-Cookie header for a new session.

        Args:
            token: Raw session token to store in the browser.

        Returns:
            A complete Set-Cookie header value.
        """
        parts = [
            f"{SESSION_COOKIE_NAME}={token}",
            "Path=/",
            "HttpOnly",
            "SameSite=Lax",
            f"Max-Age={SESSION_LIFETIME_SECONDS}",
        ]
        if os.environ.get("MOODBOARD_COOKIE_SECURE") == "1":
            parts.append("Secure")
        return "; ".join(parts)

    def _build_clear_session_cookie(self) -> str:
        """Build a Set-Cookie header that removes the browser session.

        Returns:
            A complete Set-Cookie header value with an expired cookie.
        """
        parts = [
            f"{SESSION_COOKIE_NAME}=",
            "Path=/",
            "HttpOnly",
            "SameSite=Lax",
            "Max-Age=0",
        ]
        if os.environ.get("MOODBOARD_COOKIE_SECURE") == "1":
            parts.append("Secure")
        return "; ".join(parts)

    @staticmethod
    def _public_user(user: dict[str, Any]) -> dict[str, Any]:
        """Return the safe browser-facing user fields.

        Args:
            user: Internal user row.

        Returns:
            Dict containing only non-sensitive user fields.
        """
        return {"id": user["id"], "username": user["username"]}

    @staticmethod
    def _is_supported_image_upload(filename: str, file_bytes: bytes) -> bool:
        """Validate that an upload is a supported raster image.

        Args:
            filename: Sanitized upload filename.
            file_bytes: Decoded file content.

        Returns:
            ``True`` for PNG, JPEG, GIF, or WebP uploads.
        """
        ext = os.path.splitext(filename)[1].lower()
        signatures = {
            ".png": (b"\x89PNG\r\n\x1a\n",),
            ".jpg": (b"\xff\xd8\xff",),
            ".jpeg": (b"\xff\xd8\xff",),
            ".gif": (b"GIF87a", b"GIF89a"),
        }
        if ext == ".webp":
            return file_bytes.startswith(b"RIFF") and file_bytes[8:12] == b"WEBP"
        return any(file_bytes.startswith(signature) for signature in signatures.get(ext, ()))


def build_handler(
    web_root: str, db: Database
) -> type[MoodBoardRequestHandler]:
    """Return a handler class bound to *web_root* and *db*.

    Uses :func:`functools.partial` so that every incoming request is
    served from the correct directory and has access to the shared
    database instance.

    Args:
        web_root: Absolute path to the ``web/`` directory.
        db: The shared :class:`Database` instance.

    Returns:
        A partially-applied :class:`MoodBoardRequestHandler` class.
    """
    return functools.partial(  # type: ignore[return-value]
        MoodBoardRequestHandler, directory=web_root, db=db
    )


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    """Parse command-line arguments.

    Args:
        argv: Argument list.  Defaults to ``sys.argv[1:]`` when ``None``.

    Returns:
        Parsed :class:`argparse.Namespace` with a ``port`` attribute.
    """
    parser = argparse.ArgumentParser(
        description="Mood Board development server"
    )
    parser.add_argument(
        "--port",
        type=int,
        default=8031,
        help="Port to listen on (default: 8031)",
    )
    return parser.parse_args(argv)


def bootstrap_authentication(db: Database) -> None:
    """Ensure at least one login exists before serving requests.

    If ``MOODBOARD_ADMIN_PASSWORD`` is set, the named admin user is created or
    updated on every startup.  If the database has no users and no password
    was provided, a random one-time admin password is generated and printed so
    local development remains usable without shipping default credentials.

    Args:
        db: Initialised database instance.
    """
    username = os.environ.get("MOODBOARD_ADMIN_USERNAME", "admin")
    password = os.environ.get("MOODBOARD_ADMIN_PASSWORD")

    if password:
        user = db.create_or_update_user(username, password)
        db.assign_unowned_projects(user["id"])
        print(f"Authentication ready for user '{username}'.")
        return

    if db.count_users() == 0:
        generated_password = secrets.token_urlsafe(18)
        user = db.create_or_update_user(username, generated_password)
        db.assign_unowned_projects(user["id"])
        print("No MOODBOARD_ADMIN_PASSWORD was set.")
        print(f"Created initial user '{username}' with password: {generated_password}")
        print("Set MOODBOARD_ADMIN_PASSWORD to control this credential explicitly.")
        return

    print("Authentication ready.")


def run_server(port: int = 8031) -> None:
    """Start the HTTP server and serve forever.

    Initialises the database, resolves the ``web/`` directory relative to
    this file's location, bootstraps authentication, and begins serving
    requests.

    Args:
        port: TCP port to bind to.
    """
    project_root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    web_root = os.path.join(project_root, "web")

    if not os.path.isdir(web_root):
        print(f"Error: web directory not found at {web_root}", file=sys.stderr)
        sys.exit(1)

    db = Database()
    db.initialize()
    bootstrap_authentication(db)

    handler = build_handler(web_root, db)
    server = HTTPServer(("0.0.0.0", port), handler)

    print(f"Serving mood board on http://localhost:{port}")
    print(f"Document root: {web_root}")
    print("Press Ctrl+C to stop.")

    try:
        server.serve_forever()
    except KeyboardInterrupt:
        print("\nShutting down.")
        server.server_close()


if __name__ == "__main__":
    args = parse_args()
    run_server(port=args.port)
