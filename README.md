# Mood Board

A browser-based image arrangement tool for creating mood boards. Drag images onto
an HTML canvas and arrange them freely — move, resize, reorder, and organise images
across multiple projects. All state is persisted in an SQLite database with
zero external dependencies.

## Features

- **Drag-and-drop upload** — drop images onto the canvas to add them to a project
- **Upload button** — add images and WebM clips through a file picker when drag-and-drop is awkward
- **Animated media** — GIF and WebM playback loops by default and can be toggled per item
- **Free arrangement** — move and resize images anywhere on an infinite pannable canvas
- **Pan and zoom** — drag the empty canvas to move around and use the mouse wheel to zoom
- **Z-order controls** — bring images forward or send them back with a floating action panel
- **Multiple projects** — create, switch between, and rename projects
- **Login sessions** — users sign in before project and image data is served
- **Browser user management** — admins can create users and reset passwords from the sidebar
- **Sidebar** — browse uploaded images, view metadata, and click to select on canvas
- **Persistent state** — positions, sizes, and z-order are saved automatically

## Requirements

- Python 3.12 or newer
- [uv](https://docs.astral.sh/uv/) (for dependency management)

No third-party Python packages are required. The frontend uses plain HTML, CSS, and
JavaScript with no frameworks or build tools.

## Getting Started

1. **Clone the repository and set up the virtual environment:**

   ```bash
   uv venv
   uv sync
   ```

2. **Start the server:**

   ```bash
   export MOODBOARD_ADMIN_PASSWORD='choose-a-long-password'
   .venv/bin/python -m backend.server
   ```

   The server starts on port 8031 by default. Use `--port` to change it:

   ```bash
   .venv/bin/python -m backend.server --port 9000
   ```

3. **Open the app** at [http://localhost:8031](http://localhost:8031).

   Sign in with `admin` unless `MOODBOARD_ADMIN_USERNAME` was set before
   startup. If no users exist and no admin password is provided, the server
   prints a random first-run password to the terminal.

   Use the sidebar's **Users** button as an admin to change your own password,
   create users, and reset passwords. If `MOODBOARD_ADMIN_PASSWORD` is set,
   it only creates the admin when missing; password changes made in the browser
   are not overwritten on restart.

### Docker Compose

For Dockge or Docker Compose, copy `.env.example` to `.env`, set
`MOODBOARD_ADMIN_PASSWORD`, and keep `PUID`/`PGID` aligned with the Linux user
that owns the copied project folder. Then start the stack:

```bash
docker compose up -d
```

Compose stores the SQLite database and uploaded images in `./projects`, so you
can copy or back up that folder directly.

## Project Structure

```
mood_board/
├── web/                    # Frontend files
│   ├── index.html          # Main HTML page
│   ├── css/
│   │   └── style.css       # All styles
│   └── js/
│       ├── api.js          # Backend API client
│       ├── auth.js         # Login screen and session bootstrap
│       ├── canvas.js       # Canvas rendering & interaction
│       └── sidebar.js      # Sidebar UI & project dialog
├── backend/                # Backend Python code
│   ├── server.py           # HTTP server & API routes
│   └── database.py         # SQLite database layer
├── docs/                   # Project documentation (markdown)
│   ├── frontend/
│   └── backend/
├── projects/               # Runtime data (created automatically)
│   ├── mood_board.db       # SQLite database
│   └── <project-name>/    # Uploaded images per project
└── pyproject.toml          # Python project metadata
```

## Architecture

### Frontend

Built with plain HTML, CSS, and JavaScript — no frameworks, no build step. The UI
has three main components:

- **Canvas** (`web/js/canvas.js`) — renders static images on an HTML5 canvas and
  uses a DOM media layer for live GIF/WebM playback, pan/zoom, drag-to-move,
  resize handles, and selection.
- **Sidebar** (`web/js/sidebar.js`) — collapsible overlay listing uploaded images with
  metadata, a project name field, and a project-switching dialog.
- **API client** (`web/js/api.js`) — thin wrapper around `fetch` for backend calls.

### Backend

A zero-dependency Python HTTP server using the stdlib `http.server` module. It serves
static files from `web/` and exposes a JSON API for project CRUD and image
upload/storage. Metadata (positions, z-order, dimensions) is stored in SQLite via a
thin database layer (`backend/database.py`).

## Documentation

Additional documentation is available in the [`docs/`](docs/) folder.

## Licence

This project is not currently published under an open-source licence. All rights reserved.
