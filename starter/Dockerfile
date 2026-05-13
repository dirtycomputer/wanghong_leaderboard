# Starter Dockerfile for a Wang Hong leaderboard harness.
#
# Build:
#   docker build -t my-harness:dev .
# Validate locally before submitting:
#   kakeya-lb validate .
#
# The official runner invokes this image with strict resource limits
# and only the leaderboard proxy reachable from the container network.
# Do NOT install anything that opens listening sockets or that requires
# outbound network access at runtime.

FROM python:3.11-slim AS base

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_DISABLE_PIP_VERSION_CHECK=1 \
    PIP_NO_CACHE_DIR=1

WORKDIR /opt/harness

COPY requirements.txt ./
RUN pip install --no-cache-dir -r requirements.txt

COPY src ./src
COPY run.sh ./run.sh
COPY harness.yaml ./harness.yaml
RUN chmod +x ./run.sh

ENTRYPOINT ["./run.sh"]
