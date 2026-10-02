# Autonomous AI-Powered Incident Commander

A local full-stack incident response prototype for exploring simulated SRE scenarios. It provides an incident overview, evidence trails, reference runbooks, human-approved simulated remediation, simulated recovery checks, and synthetic postmortems.

## Safety and scope

- All seeded incidents, service metrics, histories, and generated postmortems are explicitly labeled synthetic.
- No production telemetry or infrastructure is connected.
- Remediation only records a simulated operator decision and a simulated recovery result. It does not execute infrastructure changes.
- AI-provider integration and RAG document ingestion are intentionally left as future modules; current investigation text is scenario data and deterministic guidance, not AI output.

## Requirements

- Node.js 20 or newer
- Python 3.12

## Run in Replit

The `Start application` workflow runs Vite on port 5000 and FastAPI on port 8000. Vite proxies `/api` requests to FastAPI. Replit installs the project packages from `package.json` and `requirements.txt`.

```bash
npm run dev
```

The frontend is served on port 5000; the API is available through the frontend proxy at `/api`.

For local development outside Replit, use Node.js 20+ and a standard Python 3.12 installation:

```bash
npm install
python -m pip install -r requirements.txt
npm run dev
```

## Configuration and data

Copy `.env.example` to `.env` to override optional settings. `INCIDENT_DATABASE_URL` defaults to a local SQLite file at `backend/data/incident_commander.db`; tables are created and synthetic demonstration records are seeded on first startup. Keep `.env` private; it is excluded from version control.

The backend exposes `/api/health`, `/api/dashboard`, incident creation and investigation endpoints, service summaries, runbook search, approval/rejection and recovery simulation endpoints, and synthetic postmortem generation. Interactive API documentation is available at `/docs` on the FastAPI server.

## Checks

```bash
npm run typecheck
npm run build
python -m py_compile backend/app/*.py backend/app/services/*.py
```