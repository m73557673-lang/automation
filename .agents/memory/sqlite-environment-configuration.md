---
name: SQLite environment configuration
description: Keep this incident-response prototype on SQLite without accidentally using Replit's platform database variable.
---

Use `INCIDENT_DATABASE_URL` for this app's database override and keep the local SQLite file as the default. Do not read the generic `DATABASE_URL` implicitly.

**Why:** Replit supplies a `DATABASE_URL` that can select PostgreSQL, conflicting with the requested SQLite prototype and requiring a driver that is not part of this app.

**How to apply:** Preserve the app-specific SQLite setting unless the user explicitly asks to change the database. If a different database is introduced later, add its driver and choose the app-specific configuration deliberately.