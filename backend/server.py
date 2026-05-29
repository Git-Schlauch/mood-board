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
import ipaddress
import json
import mimetypes
import os
import sqlite3
import sys
import secrets
import socket
import urllib.parse
import urllib.error
import urllib.request
from http.server import HTTPServer, SimpleHTTPRequestHandler
from typing import Any

from backend.database import Database


SESSION_COOKIE_NAME = "mood_board_session"
SESSION_LIFETIME_SECONDS = 60 * 60 * 24 * 7
URL_IMPORT_MAX_BYTES = int(
    os.environ.get("MOODBOARD_URL_IMPORT_MAX_BYTES", str(50 * 1024 * 1024))
)
URL_IMPORT_MAX_REDIRECTS = 5


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
        request_path = urllib.parse.urlsplit(self.path).path
        if request_path == "/api/session":
            self._handle_session()
        elif request_path.startswith("/api/") and not self._require_authentication():
            return
        elif request_path.startswith("/projects/") and not self._require_authentication():
            return
        elif request_path == "/api/current-project":
            self._handle_current_project()
        elif request_path == "/api/projects":
            self._handle_list_projects()
        elif request_path == "/api/images":
            self._handle_list_images()
        elif request_path == "/api/layers":
            self._handle_list_layers()
        elif request_path == "/api/users":
            self._handle_list_users()
        elif request_path.startswith("/projects/"):
            self._handle_serve_image()
        else:
            super().do_GET()

    def do_POST(self) -> None:
        """Route POST requests to the appropriate API handler."""
        request_path = urllib.parse.urlsplit(self.path).path
        if request_path == "/api/login":
            self._handle_login()
        elif request_path == "/api/logout":
            self._handle_logout()
        elif request_path.startswith("/api/") and not self._require_authentication():
            return
        elif request_path == "/api/projects/open":
            self._handle_open_project()
        elif request_path == "/api/projects":
            self._handle_create_project()
        elif request_path == "/api/layers":
            self._handle_create_layer()
        elif request_path == "/api/images/upload":
            self._handle_image_upload()
        elif request_path == "/api/images/import-url":
            self._handle_image_url_import()
        elif request_path == "/api/images/update":
            self._handle_image_update()
        elif request_path == "/api/images/delete":
            self._handle_image_delete()
        elif request_path == "/api/projects/rename":
            self._handle_rename_project()
        elif request_path == "/api/users":
            self._handle_create_user()
        elif request_path == "/api/users/password":
            self._handle_change_password()
        elif request_path == "/api/users/reset-password":
            self._handle_reset_user_password()
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

    def _handle_list_users(self) -> None:
        """Return public user records for administrators.

        ``GET /api/users``
        """
        if not self._require_admin():
            return
        self._send_json(self.db.list_users())

    def _handle_create_user(self) -> None:
        """Create a new user as an administrator.

        ``POST /api/users``

        Expects ``{"username": "<name>", "password": "<password>",
        "is_admin": false}``.
        """
        if not self._require_admin():
            return

        body = self._read_json_body()
        if body is None:
            return

        username = str(body.get("username", ""))
        password = str(body.get("password", ""))
        is_admin = bool(body.get("is_admin", False))

        try:
            user = self.db.create_user(username, password, is_admin=is_admin)
        except ValueError as exc:
            self._send_json({"error": str(exc)}, status=400)
            return
        except sqlite3.IntegrityError:
            self._send_json({"error": "Username already exists"}, status=409)
            return

        self._send_json(self._public_user(user), status=201)

    def _handle_change_password(self) -> None:
        """Change the authenticated user's password.

        ``POST /api/users/password``

        Expects ``{"current_password": "<password>",
        "new_password": "<password>"}``.
        """
        body = self._read_json_body()
        if body is None:
            return

        current_password = str(body.get("current_password", ""))
        new_password = str(body.get("new_password", ""))
        user_id = int(self.current_user["id"])

        if not self.db.verify_user_password(user_id, current_password):
            self._send_json({"error": "Current password is incorrect"}, status=403)
            return

        try:
            self.db.set_user_password(user_id, new_password)
        except ValueError as exc:
            self._send_json({"error": str(exc)}, status=400)
            return

        self._send_json({"success": True})

    def _handle_reset_user_password(self) -> None:
        """Reset another user's password as an administrator.

        ``POST /api/users/reset-password``

        Expects ``{"user_id": <int>, "new_password": "<password>"}``.
        """
        if not self._require_admin():
            return

        body = self._read_json_body()
        if body is None:
            return

        user_id = body.get("user_id")
        new_password = str(body.get("new_password", ""))
        if user_id is None:
            self._send_json({"error": "Missing user_id"}, status=400)
            return

        try:
            updated = self.db.set_user_password(int(user_id), new_password)
        except ValueError as exc:
            self._send_json({"error": str(exc)}, status=400)
            return

        if not updated:
            self._send_json({"error": "User not found"}, status=404)
            return

        self._send_json({"success": True})

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
        self.db.list_layers(project["id"])
        images = self.db.list_images(project["id"])
        self._send_json(images)

    def _handle_list_layers(self) -> None:
        """Return all layers for the current project.

        ``GET /api/layers``

        Layers are ordered from bottom to top.  A default layer is created
        automatically for legacy projects.
        """
        project = self.db.get_or_create_current_project(self.current_user["id"])
        layers = self.db.list_layers(project["id"])
        self._send_json(layers)

    def _handle_create_layer(self) -> None:
        """Create a new layer in the current project.

        ``POST /api/layers``

        Expects ``{"name": "<layer name>"}``.
        """
        body = self._read_json_body()
        if body is None:
            return

        name = str(body.get("name", ""))
        project = self.db.get_or_create_current_project(self.current_user["id"])
        try:
            layer = self.db.create_layer(project["id"], name)
        except ValueError as exc:
            self._send_json({"error": str(exc)}, status=400)
            return
        except sqlite3.IntegrityError:
            self._send_json({"error": "Layer name already exists"}, status=409)
            return

        self._send_json(layer, status=201)

    def _handle_image_upload(self) -> None:
        """Accept an image upload and save it to disk.

        ``POST /api/images/upload``

        Preferred requests send the raw image bytes as the body with
        ``filename``, ``native_width``, and ``native_height`` query parameters.
        The legacy JSON/base64 format remains accepted for compatibility.  The
        file is saved into the current project's directory.  Filename conflicts
        are resolved by appending a numeric suffix (e.g. ``photo_1.png``).

        Returns the created image database record on success.
        """
        content_type = self.headers.get("Content-Type", "")
        if content_type.startswith("application/json"):
            self._handle_json_image_upload()
            return

        parsed = urllib.parse.urlsplit(self.path)
        query = urllib.parse.parse_qs(parsed.query)
        filename = query.get("filename", [""])[0]
        native_width = query.get("native_width", ["0"])[0]
        native_height = query.get("native_height", ["0"])[0]
        file_bytes = self._read_binary_body()
        if file_bytes is None:
            return

        self._save_uploaded_image(
            filename, file_bytes, native_width=native_width, native_height=native_height
        )

    def _handle_json_image_upload(self) -> None:
        """Accept a legacy base64-encoded JSON image upload.

        ``POST /api/images/upload``

        Expects a JSON body with ``{"filename": "<string>", "data": "<base64>"}``.
        This exists for compatibility with older clients; the browser now uses
        binary uploads to reduce memory pressure.
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

        self._save_uploaded_image(
            filename,
            file_bytes,
            native_width=body.get("native_width", 0),
            native_height=body.get("native_height", 0),
        )

    def _handle_image_url_import(self) -> None:
        """Import an image, WebM, or MP4 file from a remote HTTP(S) URL.

        ``POST /api/images/import-url``

        Expects ``{"url": "<https-url>"}``.  The feature is disabled unless
        ``MOODBOARD_ALLOW_URL_IMPORT=1`` is set because it intentionally makes
        outbound network requests from the server.
        """
        if os.environ.get("MOODBOARD_ALLOW_URL_IMPORT") != "1":
            self._send_json(
                {"error": "URL import is disabled on this server"}, status=403
            )
            return

        body = self._read_json_body()
        if body is None:
            return

        url = str(body.get("url", "")).strip()
        if not url:
            self._send_json({"error": "Missing URL"}, status=400)
            return

        try:
            final_url, content_type, file_bytes = self._download_import_url(url)
        except ValueError as exc:
            self._send_json({"error": str(exc)}, status=400)
            return
        except urllib.error.URLError as exc:
            self._send_json({"error": f"Could not download URL: {exc.reason}"}, status=400)
            return
        except TimeoutError:
            self._send_json({"error": "URL download timed out"}, status=400)
            return

        filename = self._filename_for_import_url(final_url, content_type, file_bytes)
        self._save_uploaded_image(filename, file_bytes)

    def _download_import_url(self, url: str) -> tuple[str, str, bytes]:
        """Download a remote import URL with redirect and size checks.

        Args:
            url: HTTP(S) URL supplied by the browser.

        Returns:
            Tuple of final URL, response Content-Type, and downloaded bytes.

        Raises:
            ValueError: If the URL, redirect, host, response type, or size is
                not acceptable.
            urllib.error.URLError: If the remote request fails.
        """
        current_url = url
        opener = urllib.request.build_opener(_NoRedirectHandler)

        for _ in range(URL_IMPORT_MAX_REDIRECTS + 1):
            self._validate_import_url(current_url)
            request = urllib.request.Request(
                current_url,
                headers={"User-Agent": "MoodBoardUrlImport/1.0"},
                method="GET",
            )

            try:
                with opener.open(request, timeout=15) as response:
                    status = response.getcode()
                    content_type = response.headers.get("Content-Type", "")
                    content_length = response.headers.get("Content-Length")
                    if content_length:
                        try:
                            if int(content_length) > URL_IMPORT_MAX_BYTES:
                                raise ValueError("Remote file is too large")
                        except ValueError as exc:
                            if str(exc) == "Remote file is too large":
                                raise
                            raise ValueError("Remote file size is invalid") from exc
                    if status < 200 or status >= 300:
                        raise ValueError(f"Remote server returned HTTP {status}")

                    file_bytes = response.read(URL_IMPORT_MAX_BYTES + 1)
                    if len(file_bytes) > URL_IMPORT_MAX_BYTES:
                        raise ValueError("Remote file is too large")
                    return response.geturl(), content_type, file_bytes
            except urllib.error.HTTPError as exc:
                if exc.code in (301, 302, 303, 307, 308):
                    location = exc.headers.get("Location")
                    if not location:
                        raise ValueError("Remote redirect did not include a location")
                    current_url = urllib.parse.urljoin(current_url, location)
                    continue
                raise

        raise ValueError("Remote URL redirected too many times")

    def _validate_import_url(self, url: str) -> None:
        """Validate that a URL is safe to request from the server.

        Args:
            url: Candidate HTTP(S) URL.

        Raises:
            ValueError: If the URL is invalid or resolves to a non-public host.
        """
        parsed = urllib.parse.urlsplit(url)
        if parsed.scheme not in ("http", "https"):
            raise ValueError("Only http and https URLs are supported")
        if not parsed.hostname:
            raise ValueError("URL must include a hostname")
        if parsed.username or parsed.password:
            raise ValueError("URLs with embedded credentials are not allowed")

        port = parsed.port or (443 if parsed.scheme == "https" else 80)
        try:
            addresses = socket.getaddrinfo(parsed.hostname, port, type=socket.SOCK_STREAM)
        except socket.gaierror as exc:
            raise ValueError(f"Could not resolve URL host: {exc}") from exc

        for address in addresses:
            ip = ipaddress.ip_address(address[4][0])
            if not ip.is_global:
                raise ValueError("URL host resolves to a private or local address")

    def _filename_for_import_url(
        self, url: str, content_type: str, file_bytes: bytes
    ) -> str:
        """Choose a safe filename for an imported remote media file.

        Args:
            url: Final URL after redirects.
            content_type: Remote response Content-Type header.
            file_bytes: Downloaded file bytes.

        Returns:
            Basename with an extension compatible with the detected media type.
        """
        parsed = urllib.parse.urlsplit(url)
        filename = os.path.basename(urllib.parse.unquote(parsed.path))
        filename = filename or "imported-media"
        base, ext = os.path.splitext(filename)
        detected_ext = self._detect_media_extension(content_type, file_bytes)
        if detected_ext is None:
            return filename
        if ext.lower() != detected_ext:
            filename = f"{base or 'imported-media'}{detected_ext}"
        return filename

    @staticmethod
    def _detect_media_extension(content_type: str, file_bytes: bytes) -> str | None:
        """Detect a supported media extension from headers and signatures.

        Args:
            content_type: Remote response Content-Type header.
            file_bytes: Downloaded file bytes.

        Returns:
            File extension including the leading dot, or ``None`` if unknown.
        """
        content_type = content_type.split(";", 1)[0].strip().lower()
        content_type_map = {
            "image/png": ".png",
            "image/jpeg": ".jpg",
            "image/gif": ".gif",
            "image/webp": ".webp",
            "video/webm": ".webm",
            "video/mp4": ".mp4",
        }
        if content_type in content_type_map:
            return content_type_map[content_type]
        if file_bytes.startswith(b"\x89PNG\r\n\x1a\n"):
            return ".png"
        if file_bytes.startswith(b"\xff\xd8\xff"):
            return ".jpg"
        if file_bytes.startswith((b"GIF87a", b"GIF89a")):
            return ".gif"
        if file_bytes.startswith(b"RIFF") and file_bytes[8:12] == b"WEBP":
            return ".webp"
        if file_bytes.startswith(b"\x1a\x45\xdf\xa3"):
            return ".webm"
        if MoodBoardRequestHandler._looks_like_mp4(file_bytes):
            return ".mp4"
        return None

    def _save_uploaded_image(
        self,
        filename: str,
        file_bytes: bytes,
        native_width: int | str = 0,
        native_height: int | str = 0,
    ) -> None:
        """Validate, persist, and record an uploaded image.

        Args:
            filename: Original filename from the client.
            file_bytes: Raw decoded image payload.
            native_width: Optional original image width.
            native_height: Optional original image height.
        """
        filename = os.path.basename(filename)
        if not filename:
            self._send_json({"error": "Invalid filename"}, status=400)
            return
        if not self._is_supported_image_upload(filename, file_bytes):
            self._send_json(
                {"error": "Only PNG, JPEG, GIF, WebP, WebM, and MP4 files are supported"},
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
        try:
            native_width = int(native_width or 0)
            native_height = int(native_height or 0)
        except (TypeError, ValueError):
            self._send_json({"error": "Invalid native dimensions"}, status=400)
            return

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
        ``scale``, ``rotation``, ``z_index``, ``loop_enabled``, ``locked``,
        or ``layer_id``.  Returns the updated image record on success, or 404
        if the image does not exist.
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
            if k in (
                "pos_x",
                "pos_y",
                "scale",
                "rotation",
                "z_index",
                "loop_enabled",
                "locked",
                "layer_id",
            )
        }
        if not fields:
            self._send_json({"error": "No updatable fields provided"}, status=400)
            return

        image = self.db.get_image_for_user(int(image_id), self.current_user["id"])
        if image is None:
            self._send_json({"error": "Image not found"}, status=404)
            return

        if "layer_id" in fields:
            layer = self.db.get_layer_for_user(
                int(fields["layer_id"]), self.current_user["id"]
            )
            if layer is None or layer["project_id"] != image["project_id"]:
                self._send_json({"error": "Layer not found"}, status=404)
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
            if filename.lower().endswith(".webm"):
                content_type = "video/webm"
            elif filename.lower().endswith(".mp4"):
                content_type = "video/mp4"
            else:
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

    def _read_binary_body(self) -> bytes | None:
        """Read the request body as raw bytes.

        Sends a 400 error and returns ``None`` if the request body is empty.

        Returns:
            The request body bytes, or ``None`` on failure.
        """
        content_length = int(self.headers.get("Content-Length", 0))
        if content_length == 0:
            self._send_json({"error": "Empty upload body"}, status=400)
            return None
        return self.rfile.read(content_length)

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

    def _require_admin(self) -> bool:
        """Require the authenticated user to be an administrator.

        Returns:
            ``True`` when the current user is an administrator, otherwise sends
            a 403 JSON response and returns ``False``.
        """
        if not self.current_user or not self.current_user.get("is_admin"):
            self._send_json({"error": "Administrator access required"}, status=403)
            return False
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
        return {
            "id": user["id"],
            "username": user["username"],
            "is_admin": bool(user.get("is_admin", False)),
        }

    @staticmethod
    def _is_supported_image_upload(filename: str, file_bytes: bytes) -> bool:
        """Validate that an upload is a supported raster image.

        Args:
            filename: Sanitized upload filename.
            file_bytes: Decoded file content.

        Returns:
            ``True`` for PNG, JPEG, GIF, WebP, WebM, or MP4 uploads.
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
        if ext == ".webm":
            return file_bytes.startswith(b"\x1a\x45\xdf\xa3")
        if ext == ".mp4":
            return MoodBoardRequestHandler._looks_like_mp4(file_bytes)
        return any(file_bytes.startswith(signature) for signature in signatures.get(ext, ()))

    @staticmethod
    def _looks_like_mp4(file_bytes: bytes) -> bool:
        """Return whether bytes look like an MP4/ISO-BMFF container.

        Args:
            file_bytes: Candidate media bytes.

        Returns:
            ``True`` when an ``ftyp`` box is present with a common MP4 brand.
        """
        if len(file_bytes) < 12 or file_bytes[4:8] != b"ftyp":
            return False
        brand = file_bytes[8:12]
        compatible = file_bytes[16:64]
        brands = (
            b"isom", b"iso2", b"iso4", b"iso5", b"iso6",
            b"mp41", b"mp42", b"avc1", b"M4V ", b"MSNV",
        )
        return brand in brands or any(candidate in compatible for candidate in brands)


class _NoRedirectHandler(urllib.request.HTTPRedirectHandler):
    """Prevent urllib from following redirects without validation."""

    def redirect_request(
        self,
        req: urllib.request.Request,
        fp: Any,
        code: int,
        msg: str,
        headers: Any,
        newurl: str,
    ) -> None:
        """Return ``None`` so redirects are surfaced as HTTPError objects.

        Args:
            req: Original request.
            fp: Remote response file object.
            code: HTTP status code.
            msg: HTTP status message.
            headers: Response headers.
            newurl: Redirect target.

        Returns:
            Always ``None`` to disable automatic redirect following.
        """
        return None


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

    If ``MOODBOARD_ADMIN_PASSWORD`` is set, the named admin user is created
    when missing and promoted when present.  Existing passwords are left alone
    so changes made in the browser survive container restarts.  If the database
    has no users and no password was provided, a random one-time admin password
    is generated and printed so local development remains usable without
    shipping default credentials.

    Args:
        db: Initialised database instance.
    """
    username = os.environ.get("MOODBOARD_ADMIN_USERNAME", "admin")
    password = os.environ.get("MOODBOARD_ADMIN_PASSWORD")

    if password:
        user = db.get_public_user_by_username(username)
        if user is None:
            user = db.create_user(username, password, is_admin=True)
        elif not user.get("is_admin"):
            db.set_user_admin(int(user["id"]), True)
            user = db.get_public_user(int(user["id"])) or user
        db.assign_unowned_projects(user["id"])
        print(f"Authentication ready for user '{username}'.")
        return

    if db.count_users() == 0:
        generated_password = secrets.token_urlsafe(18)
        user = db.create_or_update_user(username, generated_password, is_admin=True)
        db.assign_unowned_projects(user["id"])
        print("No MOODBOARD_ADMIN_PASSWORD was set.")
        print(f"Created initial user '{username}' with password: {generated_password}")
        print("Set MOODBOARD_ADMIN_PASSWORD to control this credential explicitly.")
        return

    if db.count_admin_users() == 0:
        promoted = db.promote_first_user_to_admin()
        if promoted:
            print(f"Promoted '{promoted['username']}' to administrator.")
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
