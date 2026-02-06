# Sandbox image for LonelyCat (Phase 1). See docs/spec/sandbox.md.
# Base: python:3.12-slim; user sandbox uid 1000; --user=1000:1000, --workdir=/workspace/work.
FROM python:3.12-slim

# Install bash, coreutils, findutils, jq, git (optional). Slim may lack some.
RUN apt-get update && apt-get install -y --no-install-recommends \
    bash \
    coreutils \
    findutils \
    jq \
    git \
    && rm -rf /var/lib/apt/lists/*

# Create user sandbox (uid 1000) for non-root execution.
RUN groupadd -g 1000 sandbox && useradd -u 1000 -g sandbox -m -s /bin/bash sandbox

# Workspace layout: mount points for inputs (ro), work (rw), artifacts (rw).
RUN mkdir -p /workspace/inputs /workspace/work /workspace/artifacts \
    && chown -R sandbox:sandbox /workspace

WORKDIR /workspace/work

# Default: run as sandbox. Runner overrides with --user=1000:1000.
USER sandbox

# Default entrypoint for shell.run; python.run uses python. Override per exec.
ENTRYPOINT ["bash"]
