# Agent instructions

## Agent skills

### Issue tracker

Issues and specifications for this repository live as Markdown files under `.scratch/`. See `docs/agents/issue-tracker.md`.

### Triage labels

Use the repository's configured five triage labels: `needs-triage`, `needs-info`, `ready-for-agent`, `ready-for-human`, and `wontfix`. See `docs/agents/triage-labels.md`.

### Domain docs

This is a single-context repository. Read `CONTEXT.md` and relevant decisions under `docs/adr/` before exploring the codebase. See `docs/agents/domain.md`.

### Verification

After modifying files in this repository, do not run any tests. Review the diff only, and state that tests were not run.
