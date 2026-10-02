---
name: Incident commander phase boundaries
description: Current project constraints for the incident commander prototype.
---

The incident commander prototype may use optional AI for evidence-grounded investigations, with a deterministic no-credential fallback. AI output must not execute remediation; human actions and recovery checks remain simulation-only.

**Why:** The user requested modular investigation agents while retaining the existing deterministic demonstration and simulated-only operator controls.

**How to apply:** Gather facts and citations before model calls, validate structured output against stored evidence, use a documented evidence-support score rather than model confidence, and preserve existing SQLite records during schema changes.