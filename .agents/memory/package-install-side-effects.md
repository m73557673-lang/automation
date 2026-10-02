---
name: Package installation side effects
description: Replit-managed package installs can rewrite dependency files even when the intended dependency set is unchanged.
---

After installing project dependencies, inspect manifest and lockfile changes. Replit-managed installs may rewrite dependency metadata, and Python installs also reapply `requirements.txt`, potentially upgrading floating FastAPI/Starlette ranges. Keep only required dependency edits and check whether test-only packages live in `requirements-dev.txt`.

**Why:** A dependency setup run changed requirements and lockfile metadata unrelated to the requested feature; applying runtime requirements also upgraded the test client stack while its needed `httpx2` dependency was only declared for development.

**How to apply:** After package installs, compare dependency files to the requested changes, remove incidental churn, and install the development requirements before running the full test suite.