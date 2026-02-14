"""Mood Board — SQLite database layer.

Manages all persistent storage for the mood board application using Python's
built-in :mod:`sqlite3` module.  Provides CRUD operations for projects and
images, handles schema creation, and manages the ``projects/`` directory tree
where uploaded images are stored on the filesystem.

The database file lives at ``projects/mood_board.db`` by default.  Each project
gets its own subdirectory under ``projects/<project-name>/`` for uploaded
image files.
"""

from __future__ import annotations

import contextlib
import os
import re
import shutil
import sqlite3
from collections.abc import Generator
from typing import Any

# SQL schema -----------------------------------------------------------------

_SCHEMA_PROJECTS = """\
CREATE TABLE IF NOT EXISTS projects (
    id         INTEGER PRIMARY KEY AUTOINCREMENT,
    name       TEXT    NOT NULL UNIQUE,
    created_at TEXT    NOT NULL DEFAULT (datetime('now')),
    updated_at TEXT    NOT NULL DEFAULT (datetime('now'))
);
"""

_SCHEMA_SETTINGS = """\
CREATE TABLE IF NOT EXISTS settings (
    key   TEXT PRIMARY KEY,
    value TEXT NOT NULL
);
"""

_SCHEMA_IMAGES = """\
CREATE TABLE IF NOT EXISTS images (
    id         INTEGER PRIMARY KEY AUTOINCREMENT,
    project_id INTEGER NOT NULL,
    filename   TEXT    NOT NULL,
    pos_x      REAL    NOT NULL DEFAULT 0.0,
    pos_y      REAL    NOT NULL DEFAULT 0.0,
    scale      REAL    NOT NULL DEFAULT 1.0,
    rotation   REAL    NOT NULL DEFAULT 0.0,
    z_index    INTEGER NOT NULL DEFAULT 0,
    created_at TEXT    NOT NULL DEFAULT (datetime('now')),
    updated_at TEXT    NOT NULL DEFAULT (datetime('now')),
    FOREIGN KEY (project_id) REFERENCES projects(id) ON DELETE CASCADE
);
"""

# Whitelist of columns that callers may update via update_image().
_IMAGE_UPDATABLE_FIELDS: set[str] = {"pos_x", "pos_y", "scale", "rotation", "z_index"}

# Pattern for valid project names (alphanumeric, hyphens, underscores, spaces).
_SAFE_NAME_RE = re.compile(r"^[\w\- ]+$")


class Database:
    """Manages the SQLite database for mood board projects and images.

    Handles connection lifecycle, schema creation, and all CRUD operations.
    The database file is stored at ``projects/mood_board.db`` relative to the
    project root.  Project image directories live under
    ``projects/<project>/``.

    The constructor accepts an optional *db_path* override so that tests can
    pass ``\":memory:\"`` or a temporary file path without touching the real
    data directory.
    """

    def __init__(self, db_path: str | None = None) -> None:
        """Initialise the database manager.

        When *db_path* is ``None`` the default location
        ``projects/mood_board.db`` (relative to the project root) is used and
        the ``projects/`` directory is created if it does not already exist.

        Args:
            db_path: Optional override for the database file path.
        """
        project_root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
        self._data_dir: str = os.path.join(project_root, "projects")

        if db_path is None:
            os.makedirs(self._data_dir, exist_ok=True)
            self._db_path: str = os.path.join(self._data_dir, "mood_board.db")
        else:
            self._db_path = db_path

        # For in-memory databases we keep a single persistent connection so
        # that all operations see the same schema and data.  File-backed
        # databases create a fresh connection per ``connect()`` call.
        self._persistent_conn: sqlite3.Connection | None = None
        if self._db_path == ":memory:":
            self._persistent_conn = sqlite3.connect(":memory:")
            self._persistent_conn.row_factory = sqlite3.Row
            self._persistent_conn.execute("PRAGMA foreign_keys = ON")

    # -- connection management -----------------------------------------------

    @contextlib.contextmanager
    def connect(self) -> Generator[sqlite3.Connection, None, None]:
        """Yield a database connection with foreign keys enabled.

        The connection uses :attr:`sqlite3.Row` as its row factory so that
        result rows behave like dictionaries.  On clean exit the transaction
        is committed; on exception it is rolled back.

        For file-backed databases a new connection is created and closed each
        time.  For in-memory databases a single persistent connection is
        reused so that all operations share the same schema and data.

        Yields:
            An open :class:`sqlite3.Connection`.
        """
        if self._persistent_conn is not None:
            conn = self._persistent_conn
        else:
            conn = sqlite3.connect(self._db_path)
            conn.row_factory = sqlite3.Row
            conn.execute("PRAGMA foreign_keys = ON")

        try:
            yield conn
            conn.commit()
        except Exception:
            conn.rollback()
            raise
        finally:
            # Only close transient (file-backed) connections.
            if self._persistent_conn is None:
                conn.close()

    # -- schema --------------------------------------------------------------

    def initialize(self) -> None:
        """Create the database tables if they do not already exist.

        Safe to call multiple times thanks to ``CREATE TABLE IF NOT EXISTS``.
        Should be called once at application startup.
        """
        with self.connect() as conn:
            conn.execute(_SCHEMA_PROJECTS)
            conn.execute(_SCHEMA_SETTINGS)
            conn.execute(_SCHEMA_IMAGES)

    # -- settings ------------------------------------------------------------

    def get_setting(self, key: str) -> str | None:
        """Fetch a setting value by its key.

        Args:
            key: The setting key.

        Returns:
            The setting value as a string, or ``None`` if not set.
        """
        with self.connect() as conn:
            row = conn.execute(
                "SELECT value FROM settings WHERE key = ?", (key,)
            ).fetchone()
        return row["value"] if row else None

    def set_setting(self, key: str, value: str) -> None:
        """Insert or update a setting.

        Uses ``INSERT OR REPLACE`` so the row is created if missing or
        updated if it already exists.

        Args:
            key: The setting key.
            value: The setting value.
        """
        with self.connect() as conn:
            conn.execute(
                "INSERT OR REPLACE INTO settings (key, value) VALUES (?, ?)",
                (key, value),
            )

    def get_or_create_current_project(self) -> dict[str, Any]:
        """Return the current project, creating one if necessary.

        Resolution order:

        1. Read ``current_project_id`` from settings — if the referenced
           project still exists, return it.
        2. Fall back to the first project alphabetically.
        3. If no projects exist at all, create *Untitled Project* and set
           it as the current project.

        Returns:
            A dict of the current project's column values.
        """
        # Try the stored current project.
        raw_id = self.get_setting("current_project_id")
        if raw_id is not None:
            project = self.get_project(int(raw_id))
            if project is not None:
                return project

        # Fall back to the first existing project.
        projects = self.list_projects()
        if projects:
            self.set_setting("current_project_id", str(projects[0]["id"]))
            return projects[0]

        # No projects exist — create a default one.
        project = self.create_project("Untitled Project")
        self.set_setting("current_project_id", str(project["id"]))
        return project

    # -- project CRUD --------------------------------------------------------

    def create_project(self, name: str) -> dict[str, Any]:
        """Create a new project and its image directory on disk.

        Inserts a row into the ``projects`` table and creates the directory
        ``projects/<name>/`` on the filesystem.

        Args:
            name: The project name.  Must be unique and contain only
                alphanumeric characters, hyphens, underscores, or spaces.

        Returns:
            A dict with keys ``id``, ``name``, ``created_at``,
            ``updated_at``.

        Raises:
            ValueError: If *name* is empty or contains unsafe characters.
            sqlite3.IntegrityError: If a project with that name already
                exists.
        """
        name = self._sanitize_name(name)
        with self.connect() as conn:
            cursor = conn.execute(
                "INSERT INTO projects (name) VALUES (?)", (name,)
            )
            row = conn.execute(
                "SELECT * FROM projects WHERE id = ?", (cursor.lastrowid,)
            ).fetchone()

        os.makedirs(self._image_dir(name), exist_ok=True)
        return dict(row)

    def get_project(self, project_id: int) -> dict[str, Any] | None:
        """Fetch a single project by its primary key.

        Args:
            project_id: The project ID.

        Returns:
            A dict of column values, or ``None`` if not found.
        """
        with self.connect() as conn:
            row = conn.execute(
                "SELECT * FROM projects WHERE id = ?", (project_id,)
            ).fetchone()
        return dict(row) if row else None

    def get_project_by_name(self, name: str) -> dict[str, Any] | None:
        """Fetch a single project by its name.

        Args:
            name: The project name.

        Returns:
            A dict of column values, or ``None`` if not found.
        """
        with self.connect() as conn:
            row = conn.execute(
                "SELECT * FROM projects WHERE name = ?", (name,)
            ).fetchone()
        return dict(row) if row else None

    def list_projects(self) -> list[dict[str, Any]]:
        """Return all projects ordered alphabetically by name.

        Returns:
            A list of dicts, one per project.
        """
        with self.connect() as conn:
            rows = conn.execute(
                "SELECT * FROM projects ORDER BY name"
            ).fetchall()
        return [dict(r) for r in rows]

    def rename_project(self, project_id: int, new_name: str) -> bool:
        """Rename a project and move its image directory on disk.

        Updates the ``updated_at`` timestamp.  If the project's directory
        exists on disk it is moved to match the new name.

        Args:
            project_id: The project's primary key.
            new_name: The new unique name.

        Returns:
            ``True`` if the project was found and renamed, ``False``
            otherwise.

        Raises:
            ValueError: If *new_name* is empty or contains unsafe characters.
            sqlite3.IntegrityError: If *new_name* is already taken.
            OSError: If the directory rename fails.
        """
        new_name = self._sanitize_name(new_name)

        # Fetch the old name so we can move the directory.
        old = self.get_project(project_id)
        if old is None:
            return False

        old_name: str = old["name"]

        with self.connect() as conn:
            cursor = conn.execute(
                "UPDATE projects SET name = ?, updated_at = datetime('now') "
                "WHERE id = ?",
                (new_name, project_id),
            )
            if cursor.rowcount == 0:
                return False

        # Move the filesystem directory if it exists.
        old_dir = self._image_dir(old_name)
        new_dir = self._image_dir(new_name)
        if os.path.isdir(old_dir):
            os.rename(old_dir, new_dir)
        else:
            # No existing directory — just create the new one.
            os.makedirs(new_dir, exist_ok=True)

        return True

    def delete_project(self, project_id: int) -> bool:
        """Delete a project, its image rows (via cascade), and its directory.

        The ``ON DELETE CASCADE`` foreign key removes associated image rows
        automatically.  The project's ``data/<name>/`` directory tree is
        removed with :func:`shutil.rmtree`.

        Args:
            project_id: The project's primary key.

        Returns:
            ``True`` if the project existed and was deleted, ``False``
            otherwise.
        """
        project = self.get_project(project_id)
        if project is None:
            return False

        with self.connect() as conn:
            conn.execute("DELETE FROM projects WHERE id = ?", (project_id,))

        # Remove the entire project directory tree from disk.
        project_dir = os.path.join(self._data_dir, project["name"])
        if os.path.isdir(project_dir):
            shutil.rmtree(project_dir)

        return True

    # -- image CRUD ----------------------------------------------------------

    def add_image(
        self,
        project_id: int,
        filename: str,
        pos_x: float = 0.0,
        pos_y: float = 0.0,
        scale: float = 1.0,
        rotation: float = 0.0,
        z_index: int = 0,
    ) -> dict[str, Any]:
        """Insert a new image record for a project.

        Does **not** handle the file upload itself — the caller is
        responsible for saving the image file to disk before calling this
        method.

        Args:
            project_id: The owning project's primary key.
            filename: The image filename (basename only).
            pos_x: Horizontal position on the canvas.
            pos_y: Vertical position on the canvas.
            scale: Scale factor (1.0 = original size).
            rotation: Rotation in degrees.
            z_index: Draw order (higher values are drawn on top).

        Returns:
            A dict of the newly created image row.
        """
        with self.connect() as conn:
            cursor = conn.execute(
                "INSERT INTO images "
                "(project_id, filename, pos_x, pos_y, scale, rotation, z_index) "
                "VALUES (?, ?, ?, ?, ?, ?, ?)",
                (project_id, filename, pos_x, pos_y, scale, rotation, z_index),
            )
            row = conn.execute(
                "SELECT * FROM images WHERE id = ?", (cursor.lastrowid,)
            ).fetchone()
        return dict(row)

    def get_image(self, image_id: int) -> dict[str, Any] | None:
        """Fetch a single image by its primary key.

        Args:
            image_id: The image ID.

        Returns:
            A dict of column values, or ``None`` if not found.
        """
        with self.connect() as conn:
            row = conn.execute(
                "SELECT * FROM images WHERE id = ?", (image_id,)
            ).fetchone()
        return dict(row) if row else None

    def list_images(self, project_id: int) -> list[dict[str, Any]]:
        """Return all images for a project, ordered by draw layer.

        Results are sorted by ``z_index`` ascending, then by ``id``
        ascending as a tiebreaker.

        Args:
            project_id: The owning project's primary key.

        Returns:
            A list of dicts, one per image.
        """
        with self.connect() as conn:
            rows = conn.execute(
                "SELECT * FROM images WHERE project_id = ? "
                "ORDER BY z_index ASC, id ASC",
                (project_id,),
            ).fetchall()
        return [dict(r) for r in rows]

    def update_image(self, image_id: int, **kwargs: Any) -> bool:
        """Update one or more fields on an image record.

        Only the fields listed in :data:`_IMAGE_UPDATABLE_FIELDS` are
        accepted (``pos_x``, ``pos_y``, ``scale``, ``rotation``,
        ``z_index``).  Unknown keys are silently ignored.  The
        ``updated_at`` timestamp is refreshed automatically.

        Args:
            image_id: The image's primary key.
            **kwargs: Column names and their new values.

        Returns:
            ``True`` if the image was found and updated, ``False``
            otherwise.
        """
        fields = {k: v for k, v in kwargs.items() if k in _IMAGE_UPDATABLE_FIELDS}
        if not fields:
            return False

        set_clause = ", ".join(f"{col} = ?" for col in fields)
        sql = (
            f"UPDATE images SET {set_clause}, updated_at = datetime('now') "
            f"WHERE id = ?"
        )
        params: list[Any] = list(fields.values()) + [image_id]

        with self.connect() as conn:
            cursor = conn.execute(sql, params)
        return cursor.rowcount > 0

    def delete_image(self, image_id: int) -> bool:
        """Delete an image record from the database.

        Does **not** remove the image file from disk — the caller should
        handle file deletion separately so that DB and filesystem operations
        remain cleanly separable.

        Args:
            image_id: The image's primary key.

        Returns:
            ``True`` if the image existed and was deleted, ``False``
            otherwise.
        """
        with self.connect() as conn:
            cursor = conn.execute(
                "DELETE FROM images WHERE id = ?", (image_id,)
            )
        return cursor.rowcount > 0

    # -- path helpers --------------------------------------------------------

    def _image_dir(self, project_name: str) -> str:
        """Return the absolute path to a project's image directory.

        Args:
            project_name: The project name.

        Returns:
            Absolute path, e.g. ``/path/to/projects/my-project``.
        """
        return os.path.join(self._data_dir, project_name)

    def get_image_path(self, project_name: str, filename: str) -> str:
        """Return the full filesystem path for an image file.

        Args:
            project_name: The project name.
            filename: The image filename (basename only).

        Returns:
            Absolute path, e.g.
            ``/path/to/projects/my-project/photo.png``.
        """
        return os.path.join(self._image_dir(project_name), filename)

    # -- validation ----------------------------------------------------------

    @staticmethod
    def _sanitize_name(name: str) -> str:
        """Validate and clean a project name for filesystem safety.

        Strips leading/trailing whitespace and ensures the name contains
        only alphanumeric characters, hyphens, underscores, or spaces.

        Args:
            name: The raw project name.

        Returns:
            The stripped project name.

        Raises:
            ValueError: If the name is empty or contains unsafe characters.
        """
        name = name.strip()
        if not name:
            raise ValueError("Project name must not be empty.")
        if not _SAFE_NAME_RE.match(name):
            raise ValueError(
                f"Project name contains unsafe characters: {name!r}. "
                "Only alphanumeric characters, hyphens, underscores, "
                "and spaces are allowed."
            )
        return name
