"""Mood Board — lightweight development web server.

Serves static files from the ``web/`` directory using Python's built-in
:mod:`http.server` module.  No third-party dependencies are required.

Usage::

    python backend/server.py [--port PORT]

The default port is **8031**.
"""

from __future__ import annotations

import argparse
import functools
import os
import sys
from http.server import HTTPServer, SimpleHTTPRequestHandler


class MoodBoardRequestHandler(SimpleHTTPRequestHandler):
    """HTTP request handler that serves files from the *web/* directory.

    Inherits from :class:`SimpleHTTPRequestHandler` and overrides the
    default directory so that the document root points at ``web/``
    regardless of where the process is started from.
    """

    def __init__(self, *args, directory: str | None = None, **kwargs) -> None:
        """Initialise the handler with a custom document root.

        Args:
            directory: Absolute path to the directory to serve.  When
                ``None`` the handler falls back to the current working
                directory (standard library default).
            *args: Positional arguments forwarded to the parent class.
            **kwargs: Keyword arguments forwarded to the parent class.
        """
        super().__init__(*args, directory=directory, **kwargs)


def build_handler(web_root: str) -> type[MoodBoardRequestHandler]:
    """Return a handler class bound to *web_root*.

    This uses :func:`functools.partial` so that every incoming request
    is served from the correct directory without relying on ``os.chdir``.

    Args:
        web_root: Absolute path to the ``web/`` directory.

    Returns:
        A partially-applied :class:`MoodBoardRequestHandler` class.
    """
    return functools.partial(MoodBoardRequestHandler, directory=web_root)  # type: ignore[return-value]


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

    Resolves the ``web/`` directory relative to this file's location so
    the server works regardless of the caller's working directory.

    Args:
        port: TCP port to bind to.
    """
    project_root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    web_root = os.path.join(project_root, "web")

    if not os.path.isdir(web_root):
        print(f"Error: web directory not found at {web_root}", file=sys.stderr)
        sys.exit(1)

    handler = build_handler(web_root)
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
