---
name: Incident commander phase boundaries
description: Current project constraints for the incident commander prototype.
---

For the incident commander prototype, do not implement AI or real remediation in this phase. Preserve existing SQLite records when normalizing the schema.

**Why:** The user explicitly limited this phase to database, API, and frontend integration while excluding AI and real remediation; existing local records must survive the schema transition.

**How to apply:** Keep recommendations deterministic and operator actions or recovery checks simulation-only. Perform schema changes without dropping existing records.