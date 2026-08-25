# 02 — Migrate 应收核销日清 through the registry

**What to build:** Employees continue using the existing 应收核销日清 workflow through the new registered experience without changes to its safety gates, material versions, checkpoints, batches, or recovery behavior.

**Blocked by:** 01 — Controlled registry and canonical execution routes.

**Status:** ready-for-human

- [x] The AR experience is selected through the controlled registry.
- [x] Existing single-date and multi-date launch behavior remains unchanged.
- [x] Existing task, batch, material, cancel, retry, and result links remain valid.
- [x] AR workflow tests pass without weakening execution policy.
