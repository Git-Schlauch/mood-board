# Database Module

## Overview

The `backend/database.py` module provides all persistent storage for the mood board application. It uses Python's built-in `sqlite3` module with a single database file at `data/mood_board.db`. Uploaded images are stored on the filesystem under `data/<project-name>/images/`; only metadata (position, scale, rotation, draw order) is kept in the database.

## Schema

### `projects` table

| Column       | Type    | Notes                          |
|--------------|---------|--------------------------------|
| `id`         | INTEGER | Primary key, autoincrement     |
| `name`       | TEXT    | Unique, used as directory name |
| `created_at` | TEXT    | ISO 8601 timestamp             |
| `updated_at` | TEXT    | ISO 8601 timestamp             |

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
| `created_at` | TEXT    | ISO 8601 timestamp                       |
| `updated_at` | TEXT    | ISO 8601 timestamp                       |

## Usage

```python
from backend.database import Database

# Production — uses data/mood_board.db
db = Database()
db.initialize()

# Testing — in-memory database
db = Database(":memory:")
db.initialize()

# Create a project
project = db.create_project("my-mood-board")

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
data/
├── mood_board.db
├── project-alpha/
│   └── images/
│       ├── photo1.png
│       └── sketch.jpg
└── project-beta/
    └── images/
        └── reference.png
```

## Design Notes

- **No third-party dependencies** — uses only `sqlite3`, `os`, `shutil`, and other stdlib modules.
- **Thread safety** — each `connect()` call creates a fresh connection, making it safe for concurrent access.
- **JSON-friendly** — all methods return plain `dict` objects (converted from `sqlite3.Row`).
- **Foreign keys** — `PRAGMA foreign_keys = ON` is set on every connection to enforce cascade deletes.
- **Name validation** — project names are restricted to alphanumeric characters, hyphens, underscores, and spaces.
