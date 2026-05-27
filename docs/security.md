# Security Notes

## External network traffic

The frontend only calls same-origin paths under `/api/...` and `/projects/...`.
There are no CDN scripts, analytics beacons, third-party image URLs, WebSocket
connections, or hard-coded external HTTP endpoints in the current source tree.
The backend uses Python standard library modules only and does not make outbound
network requests.

## Authentication

Mood Board requires login before project data, images, or API routes can be
used. Sessions are stored in SQLite and referenced by an HTTP-only cookie named
`mood_board_session`. Passwords are stored as PBKDF2-SHA256 hashes with a
per-password random salt.

Projects are owned by users. Project lists, the active project setting, canvas
state, uploaded images, image updates, and image file serving are filtered by
the authenticated user so one user only sees their own canvas data.

## First user

Set `MOODBOARD_ADMIN_USERNAME` and `MOODBOARD_ADMIN_PASSWORD` before starting
the server or Docker Compose stack. If no users exist and no admin password is
provided, the local development server creates an `admin` user with a random
password and prints it to the server log.

## Uploads

Uploads are accepted only for PNG, JPEG, GIF, WebP, and WebM media payloads.
SVG and HTML uploads are rejected to avoid serving active content from the
projects directory.
