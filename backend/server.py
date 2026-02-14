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
import functools
import json
import os
import sqlite3
import sys
from http.server import HTTPServer, SimpleHTTPRequestHandler
from typing import Any

from backend.database import Database


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
        super().__init__(*args, directory=directory, **kwargs)

    # -- HTTP verb overrides -------------------------------------------------

    def do_GET(self) -> None:
        """Route GET requests to API handlers or static file serving."""
        if self.path == "/api/current-project":
            self._handle_current_project()
        elif self.path == "/api/projects":
            self._handle_list_projects()
        else:
            super().do_GET()

    def do_POST(self) -> None:
        """Route POST requests to the appropriate API handler."""
        if self.path == "/api/projects/open":
            self._handle_open_project()
        elif self.path == "/api/projects":
            self._handle_create_project()
        else:
            self.send_error(404)

    # -- API handlers --------------------------------------------------------

    def _handle_current_project(self) -> None:
        """Return the current project, auto-creating one if none exist.

        ``GET /api/current-project``
        """
        project = self.db.get_or_create_current_project()
        self._send_json(project)

    def _handle_list_projects(self) -> None:
        """Return all projects as a JSON array.

        ``GET /api/projects``
        """
        projects = self.db.list_projects()
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

        project = self.db.get_project(int(project_id))
        if project is None:
            self._send_json({"error": "Project not found"}, status=404)
            return

        self.db.set_setting("current_project_id", str(project["id"]))
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
            project = self.db.create_project(name)
        except ValueError as exc:
            self._send_json({"error": str(exc)}, status=400)
            return
        except sqlite3.IntegrityError:
            self._send_json(
                {"error": f"Project '{name}' already exists"}, status=409
            )
            return

        self.db.set_setting("current_project_id", str(project["id"]))
        self._send_json(project, status=201)

    # -- JSON helpers --------------------------------------------------------

    def _send_json(self, data: Any, status: int = 200) -> None:
        """Serialise *data* as JSON and send it as the HTTP response.

        Args:
            data: Any JSON-serialisable value (dict, list, etc.).
            status: The HTTP status code (default 200).
        """
        payload = json.dumps(data).encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(payload)))
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


def run_server(port: int = 8031) -> None:
    """Start the HTTP server and serve forever.

    Initialises the database, resolves the ``web/`` directory relative to
    this file's location, and begins serving requests.

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
