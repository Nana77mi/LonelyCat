#!/usr/bin/env bash
# Build LonelyCat sandbox image (lonelycat-sandbox:py312). See docs/spec/sandbox.md.
# Run from repo root: ./scripts/build_sandbox_image.sh
# Requires Docker (WSL2 or Linux).

set -e
REPO_ROOT="$(cd "$(dirname "$0")/.." && pwd)"
DOCKERFILE="$REPO_ROOT/docker/sandbox/Dockerfile"
if [ ! -f "$DOCKERFILE" ]; then
  echo "Dockerfile not found at $DOCKERFILE. Run from repo root." >&2
  exit 1
fi
cd "$REPO_ROOT"

echo "Building lonelycat-sandbox:py312 from docker/sandbox/Dockerfile ..."
docker build -f docker/sandbox/Dockerfile -t lonelycat-sandbox:py312 .
echo "Done. Verify with: docker run --rm lonelycat-sandbox:py312 python -c \"print(1)\""
