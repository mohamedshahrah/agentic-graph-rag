#!/bin/sh
# Fix ownership of the writable paths, then drop to the unprivileged user.
#
# The container starts as root only so this can run. `data/` is a host bind
# mount, so its ownership comes from the host, not the image — the chown in the
# Dockerfile can't reach it, and a non-root server can't write to it. Chowning
# here, at start, is what lets uploads and the per-user DuckDB files be written
# while the server itself still runs as `app`.
set -e

# Only meaningful when we're root (the normal case). If an operator pins a
# --user, skip straight to the command.
if [ "$(id -u)" = "0" ]; then
  mkdir -p /app/data/uploads /app/data/downloads /app/data/vectors /app/.cache/huggingface
  # Best-effort: a read-only mount would make this fail, and that's the
  # operator's choice to surface, not ours to crash on.
  chown -R app:app /app/data /app/.cache 2>/dev/null || true
  exec gosu app "$@"
fi

exec "$@"
