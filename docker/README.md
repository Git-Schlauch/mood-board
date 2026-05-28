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

The application now requires a login. Set the initial admin credentials when
starting the container:

```bash
docker run -p 8031:8031 \
           -e MOODBOARD_ADMIN_USERNAME=admin \
           -e MOODBOARD_ADMIN_PASSWORD='choose-a-long-password' \
           mood-board
```

## Docker Compose / Dockge

The repository includes a `compose.yaml` file suitable for Dockge. Before
starting the stack set `MOODBOARD_ADMIN_PASSWORD` in Dockge's environment
variables. Optionally set `MOODBOARD_ADMIN_USERNAME`; it defaults to `admin`.

```yaml
MOODBOARD_ADMIN_USERNAME=admin
MOODBOARD_ADMIN_PASSWORD=choose-a-long-password
MOODBOARD_ALLOW_URL_IMPORT=0
MOODBOARD_URL_IMPORT_MAX_BYTES=52428800
PUID=1000
PGID=1000
```

The Compose stack bind-mounts `./projects` to `/app/projects`. Keep `PUID` and
`PGID` aligned with the Linux user that owns the copied project folder so the
container can write the SQLite database and uploaded images.

Set `MOODBOARD_ALLOW_URL_IMPORT=1` only if the container is allowed to download
direct media URLs. The server blocks private/local IP targets and enforces the
`MOODBOARD_URL_IMPORT_MAX_BYTES` download limit.

## Persistent storage

The container stores the SQLite database (`mood_board.db`) and all uploaded
images inside `/app/projects`. With the included Compose file this maps to
`./projects` beside `compose.yaml`. To do the same with `docker run`, mount a
host directory to that path:

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

If you simply want the server to listen on a different port on the host system
set the host port accordingly in the `docker run` command. For example to
set the port to 8080 use a command like:

```bash
docker run -p 8080:8031 mood-board
```

If you need to change the port inside the docker container you can do so by
setting the `MOODBOARD_PORT` inside the docker iamge. To change it, set the
`MOODBOARD_PORT` environment variable and update the port mapping to match:

```bash
docker run -e MOODBOARD_PORT=9000 -p 8080:9000 mood-board
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
