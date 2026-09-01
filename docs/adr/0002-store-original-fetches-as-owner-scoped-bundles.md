---
status: accepted
---

# Store original fetches as owner-scoped immutable bundles

Original read-only fetches will be stored as immutable, owner-scoped Fetched Bundles with a database-controlled lifecycle, rather than treating workflow context or a task workspace as the authoritative source. Persisted Fetched Data Previews remain derived views that can outlive raw-file retention, Skill Snapshots continue to pin executable capability, and Workflow Material Sets remain the authority for business workbooks; keeping these lifecycles separate costs an additional model and storage boundary but prevents a historical preview from being mistaken for replayable raw data and allows privacy-driven cleanup without changing a completed financial task.
