---
name: Package installation side effects
description: Replit-managed package installs can rewrite dependency files even when the intended dependency set is unchanged.
---

After installing project dependencies, inspect manifest and lockfile changes. Keep only the dependency edits needed for the requested work; restore incidental duplicate declarations or lockfile metadata changes.

**Why:** A dependency setup run changed requirements and lockfile metadata unrelated to the requested feature.

**How to apply:** Before delivering work that needed package installation, compare dependency-file diffs with the requested dependency changes and remove incidental churn.