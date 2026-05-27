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
import hashlib
import hmac
import os
import re
import secrets
import shutil
import sqlite3
import time
from collections.abc import Generator
from typing import Any

# SQL schema -----------------------------------------------------------------

_SCHEMA_PROJECTS = """\
CREATE TABLE IF NOT EXISTS projects (
    id         INTEGER PRIMARY KEY AUTOINCREMENT,
    user_id    INTEGER,
    name       TEXT    NOT NULL UNIQUE,
    created_at TEXT    NOT NULL DEFAULT (datetime('now')),
    updated_at TEXT    NOT NULL DEFAULT (datetime('now')),
    FOREIGN KEY (user_id) REFERENCES users(id) ON DELETE CASCADE
);
"""

_SCHEMA_USERS = """\
CREATE TABLE IF NOT EXISTS users (
    id            INTEGER PRIMARY KEY AUTOINCREMENT,
    username      TEXT    NOT NULL UNIQUE,
    password_hash TEXT    NOT NULL,
    created_at    TEXT    NOT NULL DEFAULT (datetime('now')),
    updated_at    TEXT    NOT NULL DEFAULT (datetime('now'))
);
"""

_SCHEMA_SESSIONS = """\
CREATE TABLE IF NOT EXISTS sessions (
    token_hash TEXT PRIMARY KEY,
    user_id    INTEGER NOT NULL,
    created_at INTEGER NOT NULL,
    expires_at INTEGER NOT NULL,
    FOREIGN KEY (user_id) REFERENCES users(id) ON DELETE CASCADE
);
"""

_SCHEMA_SETTINGS = """\
CREATE TABLE IF NOT EXISTS settings (
    key   TEXT PRIMARY KEY,
    value TEXT NOT NULL
);
"""

_SCHEMA_USER_SETTINGS = """\
CREATE TABLE IF NOT EXISTS user_settings (
    user_id INTEGER NOT NULL,
    key     TEXT    NOT NULL,
    value   TEXT    NOT NULL,
    PRIMARY KEY (user_id, key),
    FOREIGN KEY (user_id) REFERENCES users(id) ON DELETE CASCADE
);
"""

_SCHEMA_IMAGES = """\
CREATE TABLE IF NOT EXISTS images (
    id            INTEGER PRIMARY KEY AUTOINCREMENT,
    project_id    INTEGER NOT NULL,
    filename      TEXT    NOT NULL,
    pos_x         REAL    NOT NULL DEFAULT 0.0,
    pos_y         REAL    NOT NULL DEFAULT 0.0,
    scale         REAL    NOT NULL DEFAULT 1.0,
    rotation      REAL    NOT NULL DEFAULT 0.0,
    z_index       INTEGER NOT NULL DEFAULT 0,
    native_width  INTEGER NOT NULL DEFAULT 0,
    native_height INTEGER NOT NULL DEFAULT 0,
    loop_enabled  INTEGER NOT NULL DEFAULT 1,
    created_at    TEXT    NOT NULL DEFAULT (datetime('now')),
    updated_at    TEXT    NOT NULL DEFAULT (datetime('now')),
    FOREIGN KEY (project_id) REFERENCES projects(id) ON DELETE CASCADE
);
"""

# Whitelist of columns that callers may update via update_image().
_IMAGE_UPDATABLE_FIELDS: set[str] = {
    "pos_x",
    "pos_y",
    "scale",
    "rotation",
    "z_index",
    "loop_enabled",
}

# Pattern for valid project names (alphanumeric, hyphens, underscores, spaces).
_SAFE_NAME_RE = re.compile(r"^[\w\- ]+$")

_PASSWORD_ITERATIONS = 600_000
_SESSION_TOKEN_BYTES = 32


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
        Also migrates existing databases by adding any missing columns.  Should
        be called once at application startup before authentication bootstrap
        users or sessions are created.
        """
        with self.connect() as conn:
            conn.execute(_SCHEMA_USERS)
            conn.execute(_SCHEMA_SESSIONS)
            conn.execute(_SCHEMA_PROJECTS)
            conn.execute(_SCHEMA_SETTINGS)
            conn.execute(_SCHEMA_USER_SETTINGS)
            conn.execute(_SCHEMA_IMAGES)

            # Migrate existing databases: add native dimension columns if
            # they don't already exist.  SQLite raises OperationalError when
            # the column is already present, which we silently ignore.
            migrations = (
                "ALTER TABLE images ADD COLUMN native_width INTEGER NOT NULL DEFAULT 0",
                "ALTER TABLE images ADD COLUMN native_height INTEGER NOT NULL DEFAULT 0",
                "ALTER TABLE images ADD COLUMN loop_enabled INTEGER NOT NULL DEFAULT 1",
                "ALTER TABLE projects ADD COLUMN user_id INTEGER",
            )
            for statement in migrations:
                try:
                    conn.execute(statement)
                except sqlite3.OperationalError:
                    pass

    # -- authentication -----------------------------------------------------

    def create_or_update_user(self, username: str, password: str) -> dict[str, Any]:
        """Create a user or update its password if it already exists.

        Passwords are stored as PBKDF2-SHA256 hashes with a per-password
        random salt.  This method is intended for initial admin bootstrap from
        environment variables and for later credential rotation.

        Args:
            username: Login name for the user.
            password: Plain-text password to hash before storage.

        Returns:
            The created or updated user row without the password hash.

        Raises:
            ValueError: If the username or password is empty.
        """
        username = username.strip()
        if not username:
            raise ValueError("Username must not be empty.")
        if not password:
            raise ValueError("Password must not be empty.")

        password_hash = self._hash_password(password)
        with self.connect() as conn:
            existing = conn.execute(
                "SELECT id FROM users WHERE username = ?", (username,)
            ).fetchone()
            if existing:
                conn.execute(
                    "UPDATE users SET password_hash = ?, updated_at = datetime('now') "
                    "WHERE id = ?",
                    (password_hash, existing["id"]),
                )
                user_id = existing["id"]
            else:
                cursor = conn.execute(
                    "INSERT INTO users (username, password_hash) VALUES (?, ?)",
                    (username, password_hash),
                )
                user_id = cursor.lastrowid

            row = conn.execute(
                "SELECT id, username, created_at, updated_at FROM users WHERE id = ?",
                (user_id,),
            ).fetchone()
        return dict(row)

    def authenticate_user(
        self, username: str, password: str
    ) -> dict[str, Any] | None:
        """Validate a username/password pair.

        Args:
            username: Login name supplied by the browser.
            password: Plain-text password supplied by the browser.

        Returns:
            The matching user row without the password hash, or ``None`` if
            the credentials are invalid.
        """
        with self.connect() as conn:
            row = conn.execute(
                "SELECT * FROM users WHERE username = ?", (username.strip(),)
            ).fetchone()

        if row is None or not self._verify_password(password, row["password_hash"]):
            return None

        return {
            "id": row["id"],
            "username": row["username"],
            "created_at": row["created_at"],
            "updated_at": row["updated_at"],
        }

    def count_users(self) -> int:
        """Return the number of configured users.

        Returns:
            The total row count from the ``users`` table.
        """
        with self.connect() as conn:
            row = conn.execute("SELECT COUNT(*) AS count FROM users").fetchone()
        return int(row["count"])

    def create_session(self, user_id: int, lifetime_seconds: int) -> str:
        """Create a persistent login session for a user.

        The raw token is returned to the caller for the browser cookie, while
        only a SHA-256 hash of the token is stored in SQLite.

        Args:
            user_id: The authenticated user's primary key.
            lifetime_seconds: Number of seconds before the session expires.

        Returns:
            A URL-safe random session token.
        """
        token = secrets.token_urlsafe(_SESSION_TOKEN_BYTES)
        now = int(time.time())
        with self.connect() as conn:
            conn.execute(
                "INSERT INTO sessions (token_hash, user_id, created_at, expires_at) "
                "VALUES (?, ?, ?, ?)",
                (self._hash_session_token(token), user_id, now, now + lifetime_seconds),
            )
        return token

    def get_user_by_session(self, token: str) -> dict[str, Any] | None:
        """Fetch the user linked to an unexpired session token.

        Expired sessions are removed opportunistically before lookup.

        Args:
            token: Raw session token from the browser cookie.

        Returns:
            The authenticated user row without password data, or ``None``.
        """
        self.delete_expired_sessions()
        token_hash = self._hash_session_token(token)
        now = int(time.time())
        with self.connect() as conn:
            row = conn.execute(
                "SELECT users.id, users.username, users.created_at, users.updated_at "
                "FROM sessions "
                "JOIN users ON users.id = sessions.user_id "
                "WHERE sessions.token_hash = ? AND sessions.expires_at > ?",
                (token_hash, now),
            ).fetchone()
        return dict(row) if row else None

    def delete_session(self, token: str) -> None:
        """Delete one session by its raw token.

        Args:
            token: Raw session token from the browser cookie.
        """
        with self.connect() as conn:
            conn.execute(
                "DELETE FROM sessions WHERE token_hash = ?",
                (self._hash_session_token(token),),
            )

    def delete_expired_sessions(self) -> None:
        """Remove sessions whose expiry timestamp is in the past."""
        with self.connect() as conn:
            conn.execute(
                "DELETE FROM sessions WHERE expires_at <= ?",
                (int(time.time()),),
            )

    def assign_unowned_projects(self, user_id: int) -> None:
        """Attach legacy projects without an owner to a user.

        Args:
            user_id: User ID that should own existing cloned or migrated
                project rows where ``user_id`` is currently ``NULL``.
        """
        with self.connect() as conn:
            conn.execute(
                "UPDATE projects SET user_id = ? WHERE user_id IS NULL",
                (user_id,),
            )

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

    def get_user_setting(self, user_id: int, key: str) -> str | None:
        """Fetch a per-user setting value.

        Args:
            user_id: Owner of the setting.
            key: The setting key.

        Returns:
            The setting value as a string, or ``None`` if not set.
        """
        with self.connect() as conn:
            row = conn.execute(
                "SELECT value FROM user_settings WHERE user_id = ? AND key = ?",
                (user_id, key),
            ).fetchone()
        return row["value"] if row else None

    def set_user_setting(self, user_id: int, key: str, value: str) -> None:
        """Insert or update a per-user setting.

        Args:
            user_id: Owner of the setting.
            key: The setting key.
            value: The setting value.
        """
        with self.connect() as conn:
            conn.execute(
                "INSERT OR REPLACE INTO user_settings (user_id, key, value) "
                "VALUES (?, ?, ?)",
                (user_id, key, value),
            )

    def get_or_create_current_project(self, user_id: int) -> dict[str, Any]:
        """Return the current project, creating one if necessary.

        Resolution order:

        1. Read ``current_project_id`` from user settings — if the referenced
           project still exists, return it.
        2. Fall back to the first project alphabetically.
        3. If no projects exist for the user, create *Untitled Project* and set
           it as the current project.

        Args:
            user_id: Owner of the current project.

        Returns:
            A dict of the current project's column values.
        """
        # Try the stored current project.
        raw_id = self.get_user_setting(user_id, "current_project_id")
        if raw_id is not None:
            project = self.get_project(int(raw_id), user_id=user_id)
            if project is not None:
                return project

        # Fall back to the first existing project.
        projects = self.list_projects(user_id=user_id)
        if projects:
            self.set_user_setting(user_id, "current_project_id", str(projects[0]["id"]))
            return projects[0]

        # No projects exist — create a default one.
        project = self.create_project("Untitled Project", user_id=user_id)
        self.set_user_setting(user_id, "current_project_id", str(project["id"]))
        return project

    # -- project CRUD --------------------------------------------------------

    def create_project(self, name: str, user_id: int) -> dict[str, Any]:
        """Create a new project and its image directory on disk.

        Inserts a row into the ``projects`` table and creates the directory
        ``projects/<name>/`` on the filesystem.

        Args:
            name: The project name.  Must be unique and contain only
                alphanumeric characters, hyphens, underscores, or spaces.
            user_id: The user who owns the project.

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
                "INSERT INTO projects (user_id, name) VALUES (?, ?)",
                (user_id, name),
            )
            row = conn.execute(
                "SELECT * FROM projects WHERE id = ?", (cursor.lastrowid,)
            ).fetchone()

        os.makedirs(self._image_dir(name), exist_ok=True)
        return dict(row)

    def get_project(
        self, project_id: int, user_id: int | None = None
    ) -> dict[str, Any] | None:
        """Fetch a single project by its primary key.

        Args:
            project_id: The project ID.
            user_id: Optional owner ID used to enforce project isolation.

        Returns:
            A dict of column values, or ``None`` if not found.
        """
        with self.connect() as conn:
            if user_id is None:
                row = conn.execute(
                    "SELECT * FROM projects WHERE id = ?", (project_id,)
                ).fetchone()
            else:
                row = conn.execute(
                    "SELECT * FROM projects WHERE id = ? AND user_id = ?",
                    (project_id, user_id),
                ).fetchone()
        return dict(row) if row else None

    def get_project_by_name(
        self, name: str, user_id: int | None = None
    ) -> dict[str, Any] | None:
        """Fetch a single project by its name.

        Args:
            name: The project name.
            user_id: Optional owner ID used to enforce project isolation.

        Returns:
            A dict of column values, or ``None`` if not found.
        """
        with self.connect() as conn:
            if user_id is None:
                row = conn.execute(
                    "SELECT * FROM projects WHERE name = ?", (name,)
                ).fetchone()
            else:
                row = conn.execute(
                    "SELECT * FROM projects WHERE name = ? AND user_id = ?",
                    (name, user_id),
                ).fetchone()
        return dict(row) if row else None

    def list_projects(self, user_id: int | None = None) -> list[dict[str, Any]]:
        """Return all projects ordered alphabetically by name.

        Args:
            user_id: Optional owner whose projects should be listed.  When
                omitted, all projects are returned for maintenance scripts.

        Returns:
            A list of dicts, one per project.
        """
        with self.connect() as conn:
            if user_id is None:
                rows = conn.execute("SELECT * FROM projects ORDER BY name").fetchall()
            else:
                rows = conn.execute(
                    "SELECT * FROM projects WHERE user_id = ? ORDER BY name",
                    (user_id,),
                ).fetchall()
        return [dict(r) for r in rows]

    def rename_project(self, project_id: int, new_name: str, user_id: int) -> bool:
        """Rename a project and move its image directory on disk.

        Updates the ``updated_at`` timestamp.  If the project's directory
        exists on disk it is moved to match the new name.

        Args:
            project_id: The project's primary key.
            new_name: The new unique name.
            user_id: Owner ID used to enforce project isolation.

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
        old = self.get_project(project_id, user_id=user_id)
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
        automatically.  The project's ``projects/<name>/`` directory tree is
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
        native_width: int = 0,
        native_height: int = 0,
        loop_enabled: int = 1,
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
            native_width: The image's original pixel width.
            native_height: The image's original pixel height.
            loop_enabled: Whether animated media should loop by default.

        Returns:
            A dict of the newly created image row.
        """
        with self.connect() as conn:
            cursor = conn.execute(
                "INSERT INTO images "
                "(project_id, filename, pos_x, pos_y, scale, rotation, "
                "z_index, native_width, native_height, loop_enabled) "
                "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
                (project_id, filename, pos_x, pos_y, scale, rotation,
                 z_index, native_width, native_height, loop_enabled),
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

    def get_image_for_user(
        self, image_id: int, user_id: int
    ) -> dict[str, Any] | None:
        """Fetch an image only if it belongs to a user's project.

        Args:
            image_id: The image ID.
            user_id: Owner ID used to enforce project isolation.

        Returns:
            A dict of image column values, or ``None`` if not found for the
            user.
        """
        with self.connect() as conn:
            row = conn.execute(
                "SELECT images.* FROM images "
                "JOIN projects ON projects.id = images.project_id "
                "WHERE images.id = ? AND projects.user_id = ?",
                (image_id, user_id),
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

    @staticmethod
    def _hash_password(password: str) -> str:
        """Hash a plain-text password for storage.

        Args:
            password: Plain-text password.

        Returns:
            Encoded PBKDF2-SHA256 password hash string.
        """
        salt = secrets.token_bytes(16)
        digest = hashlib.pbkdf2_hmac(
            "sha256", password.encode("utf-8"), salt, _PASSWORD_ITERATIONS
        )
        return (
            f"pbkdf2_sha256${_PASSWORD_ITERATIONS}$"
            f"{salt.hex()}${digest.hex()}"
        )

    @staticmethod
    def _verify_password(password: str, stored_hash: str) -> bool:
        """Verify a password against a stored PBKDF2 hash.

        Args:
            password: Plain-text password supplied by the user.
            stored_hash: Encoded hash from the database.

        Returns:
            ``True`` when the password is valid, otherwise ``False``.
        """
        try:
            algorithm, iterations, salt_hex, digest_hex = stored_hash.split("$", 3)
            if algorithm != "pbkdf2_sha256":
                return False
            expected = bytes.fromhex(digest_hex)
            actual = hashlib.pbkdf2_hmac(
                "sha256",
                password.encode("utf-8"),
                bytes.fromhex(salt_hex),
                int(iterations),
            )
        except (ValueError, TypeError):
            return False
        return hmac.compare_digest(actual, expected)

    @staticmethod
    def _hash_session_token(token: str) -> str:
        """Hash a session token before database storage or lookup.

        Args:
            token: Raw session token.

        Returns:
            SHA-256 hex digest of the token.
        """
        return hashlib.sha256(token.encode("utf-8")).hexdigest()
