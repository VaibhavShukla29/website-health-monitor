# =============================================================================
# Dockerfile — Website Health Monitoring System  (Phase 6)
# =============================================================================
#
# Concepts demonstrated:
#   • Base image selection  (why slim?)
#   • Layer caching optimisation  (COPY requirements before code)
#   • Non-root user security
#   • Environment variable injection
#   • Docker HEALTHCHECK integration
#   • EXPOSE documentation
#
# Build:
#   docker build -t website-health-monitor .
#   docker build -t website-health-monitor:1.0.0 .
#
# Run:
#   docker run -p 5000:5000 website-health-monitor
#   docker run -p 5000:5000 -e MONITOR_INTERVAL=30 website-health-monitor
#   docker run -p 5000:5000 -v $(pwd)/websites.txt:/app/websites.txt website-health-monitor
#
# Test:
#   curl http://localhost:5000/health
#   curl http://localhost:5000/metrics
#   curl http://localhost:5000/websites
# =============================================================================


# ── Stage: Base image ────────────────────────────────────────────────────────
# python:3.11-slim  =  official Python image based on Debian, with docs/tests
#                      stripped out.  ~50MB vs ~300MB for the full image.
# Always pin a specific version (3.11-slim not 3-slim or latest) to ensure
# reproducible builds — "latest" can break your build unexpectedly.
FROM python:3.11-slim


# ── Metadata labels ──────────────────────────────────────────────────────────
# OCI-standard labels visible in 'docker inspect' and container registries.
# Good practice for operational visibility in production environments.
LABEL maintainer="your-email@example.com"
LABEL version="1.0.0"
LABEL description="Website Health Monitoring System — Python + Flask"
LABEL org.opencontainers.image.source="https://github.com/yourusername/website-health-monitor"


# ── Working directory ────────────────────────────────────────────────────────
# All subsequent COPY, RUN, CMD commands use /app as their base directory.
# Convention: use /app for Python web applications.
WORKDIR /app


# ── Layer caching optimisation ───────────────────────────────────────────────
# Docker builds images as a stack of layers.  Each instruction is one layer.
# A layer is ONLY rebuilt if:
#   a) The instruction itself changed, OR
#   b) Any preceding layer was rebuilt
#
# Strategy: copy files that change RARELY before files that change OFTEN.
#
# requirements.txt changes: when you add/remove/update a dependency (~weekly)
# Application code changes: every development iteration (~many times per day)
#
# By placing COPY requirements.txt and RUN pip install BEFORE COPY . .
# we ensure pip install is only re-run when dependencies change, not on
# every code change.  This makes iterative builds 5–10× faster.
COPY requirements.txt .

RUN pip install --no-cache-dir -r requirements.txt
#   --no-cache-dir : discard pip's download cache after install
#                   reduces final image size by ~50–100MB


# ── Copy application code ─────────────────────────────────────────────────────
# This layer rebuilds on any code change — comes AFTER pip install intentionally
COPY . .


# ── Initialise log file ───────────────────────────────────────────────────────
# Ensure logs.txt exists before the app starts.
# The logging module opens it in append mode, but the file must exist.
RUN touch logs.txt


# ── Security: run as a non-root user ─────────────────────────────────────────
# By default, Docker containers run as root (uid 0).
# If an attacker exploits a vulnerability in the app, they get root inside
# the container — a significant security risk.
# Best practice: create a dedicated user with the minimum required permissions.
#
# --disabled-password : no login password (service account, not interactive)
# --gecos ""          : skip the GECOS info field (name, phone, etc.)
RUN adduser --disabled-password --gecos "" appuser \
    && chown -R appuser:appuser /app

USER appuser


# ── Expose port ──────────────────────────────────────────────────────────────
# Documents which port the container listens on.
# EXPOSE alone does NOT publish the port — that happens at 'docker run -p'.
# It is documentation for operators and for orchestrators (k8s, Swarm).
EXPOSE 5000


# ── Environment variable defaults ─────────────────────────────────────────────
# These defaults can be overridden at runtime:
#   docker run -e MONITOR_INTERVAL=30 -e FLASK_DEBUG=true ...
ENV MONITOR_INTERVAL=60
ENV WEBSITES_FILE=websites.txt
ENV FLASK_DEBUG=false
ENV PORT=5000


# ── Container health check ────────────────────────────────────────────────────
# Docker periodically runs this command.  If it fails 3 times in a row,
# Docker marks the container "unhealthy".
#
# --interval=30s     : run every 30 seconds
# --timeout=10s      : give up if the command takes > 10 seconds
# --start-period=15s : don't count failures in the first 15s (startup grace)
# --retries=3        : mark unhealthy after 3 consecutive failures
#
# Integration points:
#   • Docker Swarm:  auto-restart unhealthy containers
#   • Kubernetes:    readiness/liveness probes use similar logic
#   • AWS ECS:       deregister unhealthy tasks from load balancers
HEALTHCHECK --interval=30s --timeout=10s --start-period=15s --retries=3 \
    CMD python -c "\
import urllib.request; \
urllib.request.urlopen('http://localhost:${PORT}/health', timeout=5)" \
    || exit 1


# ── Start command ─────────────────────────────────────────────────────────────
# CMD specifies what to run when the container starts.
# Using array form ["python", "app.py"] is preferred over shell form
# "python app.py" because it avoids spawning an intermediate shell process,
# which means signals (SIGTERM from 'docker stop') reach Python directly.
CMD ["python", "app.py"]
