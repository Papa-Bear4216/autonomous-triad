# AGENTS.md — Autonomous Multi-Agent Triad

## Project Overview
Python CLI + HTTP server framework for multi-agent AI collaboration. The web entry point is `triad/server.py`, a stdlib `ThreadingHTTPServer` serving JSON endpoints (`/health`, `/telemetry`, `/auto`, `/review`).

## Running in Base44
- `docker compose -f docker-compose.base44.yml up -d` starts the server on port 3000.
- The container installs `psutil` and `watchdog` at startup, then runs the server via `watchmedo auto-restart` for live reload on `.py` file changes.
- `TRIAD_HOST=0.0.0.0` and `TRIAD_PORT=3000` are set via compose environment.

## Dependencies
- **psutil** — only third-party package; used in `advisor_manager.py` for process tree management.
- All other imports are Python standard library.

## Key Architecture Notes
- Advisors (Claude, Codex, Nous, Ollama) are **local binaries** invoked as subprocesses via `advisors.json` config. They have Windows paths baked in and won't exist in the container — the server starts fine without them; queries auto-failover to the `mock` advisor.
- `fcntl`/`msvcrt` imports in `triad_engine.py` are platform-conditional (try/except).
- No external API credentials or secrets are needed to boot the server.
- No database, no frontend — pure JSON API.

## Verification
- `curl http://localhost:3000/health` — returns status, advisor list, subsystem connectivity.
- `curl http://localhost:3000/telemetry` — returns council session metrics.
- `POST /auto` with `{"prompt": "..."}` — classifies intent and routes to advisor.
- `POST /review` with `{"diff": "..."}` — runs diff review.
