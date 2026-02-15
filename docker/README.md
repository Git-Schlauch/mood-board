# Mood Board — Docker Usage

## Building the image

From the project root (not this folder):

```bash
docker build -f docker/Dockerfile -t mood-board .
```

## Running the container

Basic usage (ephemeral storage):

```bash
docker run -p 8031:8031 mood-board
```

## Persistent storage

The container stores the SQLite database (`mood_board.db`) and all uploaded
images inside `/app/projects`. To keep this data across container restarts,
mount a host directory to that path:

```bash
docker run -p 8031:8031 -v /path/on/host:/app/projects mood-board
```

Replace `/path/on/host` with an absolute path on your machine, e.g.:

```bash
docker run -p 8031:8031 -v "$HOME/mood-board-data":/app/projects mood-board
```

Everything — the database and every project's uploaded images — will be
written to that host folder and survive container rebuilds.

## Changing the port

The server listens on port 8031 by default. To change it, set the
`MOODBOARD_PORT` environment variable and update the port mapping to match:

```bash
docker run -e MOODBOARD_PORT=9000 -p 9000:9000 mood-board
```

The `-p` flag maps `host-port:container-port`. Both sides must agree with the
value of `MOODBOARD_PORT` so that traffic reaches the server.

You can also combine persistent storage with a custom port:

```bash
docker run -e MOODBOARD_PORT=9000 \
           -p 9000:9000 \
           -v "$HOME/mood-board-data":/app/projects \
           mood-board
```

## Stopping the container

List running containers and stop by name or ID:

```bash
docker ps
docker stop <container-id>
```
