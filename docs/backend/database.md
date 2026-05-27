# Database Module

## Overview

The `backend/database.py` module provides all persistent storage for the mood board application. It uses Python's built-in `sqlite3` module with a single database file at `projects/mood_board.db`. Uploaded images are stored on the filesystem under `projects/<project-name>/`; only metadata (position, scale, rotation, draw order, native dimensions, and ownership) is kept in the database.

## Schema

### `projects` table

| Column       | Type    | Notes                          |
|--------------|---------|--------------------------------|
| `id`         | INTEGER | Primary key, autoincrement     |
| `user_id`    | INTEGER | FK -> `users.id`, project owner |
| `name`       | TEXT    | Unique, used as directory name |
| `created_at` | TEXT    | ISO 8601 timestamp             |
| `updated_at` | TEXT    | ISO 8601 timestamp             |

### `users` table

| Column          | Type    | Notes                              |
|-----------------|---------|------------------------------------|
| `id`            | INTEGER | Primary key, autoincrement         |
| `username`      | TEXT    | Unique login name                  |
| `password_hash` | TEXT    | PBKDF2-SHA256 password hash        |
| `created_at`    | TEXT    | ISO 8601 timestamp                 |
| `updated_at`    | TEXT    | ISO 8601 timestamp                 |

### `sessions` table

| Column       | Type    | Notes                          |
|--------------|---------|--------------------------------|
| `token_hash` | TEXT    | SHA-256 hash of session token  |
| `user_id`    | INTEGER | FK -> `users.id`               |
| `created_at` | INTEGER | Unix timestamp                 |
| `expires_at` | INTEGER | Unix timestamp                 |

### `user_settings` table

| Column    | Type    | Notes                         |
|-----------|---------|-------------------------------|
| `user_id` | INTEGER | FK -> `users.id`              |
| `key`     | TEXT    | Setting key                   |
| `value`   | TEXT    | Setting value                 |

### `images` table

| Column       | Type    | Notes                                    |
|--------------|---------|------------------------------------------|
| `id`         | INTEGER | Primary key, autoincrement               |
| `project_id` | INTEGER | FK → `projects.id`, cascade delete       |
| `filename`   | TEXT    | Basename only (e.g. `photo.png`)         |
| `pos_x`      | REAL    | Horizontal canvas position               |
| `pos_y`      | REAL    | Vertical canvas position                 |
| `scale`      | REAL    | Scale factor (1.0 = original)            |
| `rotation`   | REAL    | Rotation in degrees                      |
| `z_index`    | INTEGER | Draw order (higher = on top)             |
| `native_width` | INTEGER | Original image width                   |
| `native_height` | INTEGER | Original image height                 |
| `loop_enabled` | INTEGER | Animated GIF/WebM playback flag       |
| `created_at` | TEXT    | ISO 8601 timestamp                       |
| `updated_at` | TEXT    | ISO 8601 timestamp                       |

## Usage

```python
from backend.database import Database

# Production - uses projects/mood_board.db
db = Database()
db.initialize()

# Testing — in-memory database
db = Database(":memory:")
db.initialize()

# Create or update a user
user = db.create_or_update_user("admin", "long-password")

# Create a project
project = db.create_project("my-mood-board", user_id=user["id"])

# Add an image
image = db.add_image(project["id"], "photo.png", pos_x=100, pos_y=200)

# Update image position
db.update_image(image["id"], pos_x=150, pos_y=250, rotation=45.0)

# List all images for a project
images = db.list_images(project["id"])

# Delete a project (cascades to images, removes directory)
db.delete_project(project["id"])
```

## Filesystem Layout

```
projects/
├── mood_board.db
├── project-alpha/
│   ├── photo1.png
│   └── sketch.jpg
└── project-beta/
    └── reference.png
```

## Design Notes

- **No third-party dependencies** — uses only `sqlite3`, `os`, `shutil`, and other stdlib modules.
- **Thread safety** — each `connect()` call creates a fresh connection, making it safe for concurrent access.
- **JSON-friendly** — all methods return plain `dict` objects (converted from `sqlite3.Row`).
- **Foreign keys** — `PRAGMA foreign_keys = ON` is set on every connection to enforce cascade deletes.
- **User isolation** — server routes pass a user ID into project lookups so users only see their own canvas data.
- **Name validation** — project names are restricted to alphanumeric characters, hyphens, underscores, and spaces.
