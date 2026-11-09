#!/usr/bin/env bash
# Start Shelf. The Python environment lives on local disk because the NAS share
# (CIFS) can't hold the symlinks a virtual environment needs.
set -euo pipefail
cd "$(dirname "$0")"
export UV_PROJECT_ENVIRONMENT="${UV_PROJECT_ENVIRONMENT:-$HOME/.local/share/shelf/venv}"
export UV_LINK_MODE=copy
exec uv run shelf "$@"
