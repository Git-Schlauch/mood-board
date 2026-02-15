# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Project Overview

Mood Board is a browser-based image arrangement tool with a Python backend. Users can
create projects, drag images onto an HTML canvas, and arrange them freely — moving,
resizing, and reordering images. All state is persisted per-project in an SQLite database.

### Frontend

Built with plain HTML, CSS, and JavaScript (no frameworks). The UI consists of:

- **Canvas** (`web/js/canvas.js`) — renders images, handles pan/zoom, drag-to-move,
  resize handles, and selection.
- **Sidebar** (`web/js/sidebar.js`) — collapsible overlay listing uploaded images,
  a project name field, and a "load project" dialog.
- **API client** (`web/js/api.js`) — thin wrapper around `fetch` for backend calls.
- **Action panel** — floating controls for z-order (bring forward / send back) and
  delete, shown when an image is selected.

### Backend

A zero-dependency Python HTTP server (`backend/server.py`) using the stdlib
`http.server` module. It serves static files from `web/` and exposes a JSON API for
project CRUD and image upload/storage. Data lives under `data/<project-name>/` on disk;
metadata (positions, z-order, dimensions) is kept in `data/mood_board.db` via a thin
SQLite layer (`backend/database.py`).

### Running the server

```bash
.venv/bin/python -m backend.server [--port PORT]   # default port: 8031
```

Then open `http://localhost:8031` in a browser.

## Project Structure

```
mood_board/
├── web/                    # Frontend files
│   ├── index.html          # Main HTML page
│   ├── css/
│   │   └── style.css       # All styles
│   └── js/
│       ├── api.js           # Backend API client
│       ├── canvas.js        # Canvas rendering & interaction
│       └── sidebar.js       # Sidebar UI & project dialog
├── backend/                # Backend Python code
│   ├── server.py           # HTTP server & API routes
│   └── database.py         # SQLite database layer
├── docs/                   # Project documentation (markdown)
│   ├── frontend/
│   └── backend/
│       └── database.md
├── projects
│   ├── mood_board.db       # SQLite database
│   └── <project-name>/     # Uploaded images per project
├── claude-log/             # Timestamped edit logs
├── pyproject.toml          # Python project metadata (uv)
└── CLAUDE.md               # This file
```

## Development Workflow

All changes should be:
1. Made to the appropriate file (`web/index.html`, `web/css/style.css`, or `web/js/*.js`)
2. Logged in a new timestamped file in `claude-log/` folder
3. Committed to the `dev-claude` branch with descriptive commit messages

## Agent Rules

Rules for the agent when executing prompts.

### Conversation

Use casual British english when talking. When finished, end the conversation with "Oi mate. I'm done here.".
When acknowledging a mistake use British phrases like "Bollocks", or "That was pants" - be creative with your choise of words.
Any code (e.g. javascript, python, ...) should be written using American english.

### Logging edits

Any code changes should be logged in log files. The filename has the format YYYY-MM-DD__HH-MM-SS.log (ISO timestamp - year-month-day and time of day - hour-minutes-seconds).
In this file a compact list of changes should be written down, including which files were created/deleted/modified and what the changes aim to achive.
At the end of the log file I want an empty line, followed by "Agent: " + the name of the current model used, e.g. "Sonnet 4.5" or "Opus 4.0".
For every prompt a new file should be created. log files are to be placed in the "./claude-log" folder.

### Documentation

Project documentation should be placed in the "./docs" folder and written in markdown format. All code should contain in-code documentation, including arguments and return values where applicable.
Try to add a short paragraph of 2-5 sentences explaining what the function does to each function. if the function contains only a few lines of code this can be shortened to a single sentence.

### Languages

This project is split into frontend and backend.

The frontend uses HTML, CSS, and Javascript. No other languages should be used unless explicitly told otherwise. If the task requires a different language ask first before generating any code.
HTML file(s) are to be placed in the 'web' folder. CSS file(s) should be placed in the 'web/css' folder, javascript files should be placed in the 'web/js' folder. Keep javascript or CSS
in HTML files to a minimum - we prefer to put CSS and javascript in dedicated files.

The backend uses Python 3.12 or newer. We keep usage of third-party modules to a minimum and prefer native modules where applicable. Current dependencies are managed via uv.
Use type annotations whenever you can. Use docstring comments for in-code documentation for every function and class.

We prefer an object oriented approach in both javascript and python.


### Third party code and external sources

This project avoids third-party libraries. If possible no third party libraries should be used and all code should be written locally. Similar to that don't use external images without
asking first. avoid external sources, but use external documentation where needed. if graphics are needed consider creating them live using javascript or css.

### Git

We are using git for version control. The active developer branch is "dev-claude". Every accepted prompt should have the changes commited to the active developer branch.
The commit message should start with a single line of text summarizing the changes, followed by an empty line, followed by a short paragraph providing more detailed information.
If needed more paragraphs can be added but in general these commit messages should be kept brief.

