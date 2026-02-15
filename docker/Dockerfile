FROM python:3.12-alpine

LABEL maintainer="Mood Board"
LABEL description="Lightweight container for the Mood Board web server"

# Create a non-root user to run the application.
RUN addgroup -S moodboard && adduser -S moodboard -G moodboard

WORKDIR /app

# Copy only the files needed at runtime.
COPY backend/ backend/
COPY web/ web/

# The projects directory holds the SQLite database and uploaded images.
# Mount a host volume here for persistent storage.
RUN mkdir -p projects && chown moodboard:moodboard projects
VOLUME /app/projects

# Switch to non-root user.
USER moodboard

# Default port — override with MOODBOARD_PORT env var or --port flag.
ENV MOODBOARD_PORT=8031
EXPOSE 8031

CMD python -m backend.server --port "${MOODBOARD_PORT}"
