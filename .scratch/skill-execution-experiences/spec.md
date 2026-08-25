Status: ready-for-agent

## Problem Statement

Employees currently see almost every published business Skill through the same file upload and parameter form. The form repeats information already shown on the Skill detail page, includes a task-description field that many handlers never consume, mixes future progress stages into task creation, and uses one confirmation message regardless of actual risk. It does not explain the relationship between business files, show reliable input checks, or present results in the language of the selected workflow. Only the 应收核销日清 Skill currently has a purpose-built execution experience.

The generic fallback also hides configuration errors: a new or republished business Skill can appear runnable even though nobody has designed its creation, checkpoints, recovery, and result experience.

## Solution

Give every non-foundation Skill a platform-owned execution experience selected through a controlled registry. Each business experience presents the files, parameters, review information, action wording, progress, recovery guidance, and outputs that belong to that Skill. Shared components may provide uploads, task creation, status, cancellation, and output downloads, but they must not contain business terminology or decide business workflow.

Foundation file Skills keep a compact generic file-processing experience. Supporting Skills use diagnostic or conversational experiences. A business Skill that has no registered experience is visibly unavailable and cannot silently fall back to the generic form. Skill detail, workbench, file, and AI-draft entry points all converge on the same canonical Skill-scoped routes with their existing input context preserved.

## User Stories

1. As an employee, I want the selected Skill page to use its own business terminology, so that I know I opened the correct workflow.
2. As an employee, I want each required workbook to have a clear business role, so that I do not confuse source, reference, mapping, and output files.
3. As an employee, I want parameters grouped in the order I make the business decision, so that I can complete the form without interpreting a JSON schema.
4. As an employee, I want dates, periods, choices, numbers, and switches to use appropriate controls, so that invalid values are harder to enter.
5. As an employee, I want uploaded files from an AI draft or file workbench to appear in the same experience, so that I do not have to upload them again.
6. As an employee, I want a truthful readiness review before task creation, so that detectable file and parameter problems are found early.
7. As an employee, I want the review to distinguish checks performed before submission from checks performed by the Worker, so that I do not mistake an unchecked condition for a successful validation.
8. As an employee, I want the primary button to describe the actual action, so that I know whether I am reconciling, merging, splitting, renaming, comparing, allocating, or generating a report.
9. As an employee, I want confirmation only when the Skill's configured risk requires it, so that routine read-only tasks are not interrupted by a misleading warning.
10. As an employee, I want write-producing workflows to state what will be created or changed before I confirm, so that I can judge the effect.
11. As an employee, I want progress to appear after task creation in business stages, so that creation pages stay focused and running tasks remain understandable.
12. As an employee, I want failure guidance specific to the stage and Skill, so that I know whether to replace a file, change a parameter, retry, or contact an administrator.
13. As an employee, I want successful tasks to summarize business results before technical details, so that I can act on the outcome quickly.
14. As an employee, I want outputs labelled by business purpose, so that I download the right workbook or report.
15. As an employee, I want historical run links to keep working, so that bookmarks and task-center records do not break during migration.
16. As an employee, I want bank reconciliation and labor-invoice checking to emphasize comparison inputs and discrepancy outputs, so that read-only checking is clear.
17. As an employee, I want project-detail supplementation, receivables merging, and expense allocation to distinguish source workbooks from generated or modified workbooks, so that originals remain protected.
18. As an employee, I want sales splitting and withholding-report renaming to preview naming or grouping rules, so that batch outputs are predictable.
19. As an employee, I want AR progress comparison to identify the two periods or versions being compared, so that the difference report is meaningful.
20. As an employee, I want daily order summaries to foreground date and aggregation scope, so that I do not generate a report for the wrong period.
21. As an employee, I want compliance spot checks to explain sampling parameters and advisory output, so that recommendations are not mistaken for a compliance approval.
22. As an administrator, I want an unregistered business experience to block execution, so that incomplete Skill publication is visible before employees create tasks.
23. As an administrator, I want external manifests to reference only reviewed experience keys, so that Skill packages cannot inject executable frontend code.
24. As a Skill maintainer, I want semantic-free shared task infrastructure, so that I can reuse uploads, status, cancellation, and downloads without inheriting another Skill's rules.
25. As a Skill maintainer, I want draft and disabled business Skills to require a bespoke experience before publication, so that generic fallback does not return later.
26. As a platform operator, I want ordinary business Skills to remain on the existing Run and Worker model, so that a custom screen does not force an unnecessary runtime migration.
27. As a platform operator, I want workflows reserved for human checkpoints, sequential batches, versioned materials, or recovery semantics, so that runtime complexity follows business need.
28. As an auditor, I want task identity, ownership, inputs, confirmation, state, and outputs to remain governed by backend records, so that presentation changes do not weaken auditability.
29. As an accessibility user, I want labels, error messages, focus order, and status announcements to remain usable with keyboard and assistive technology, so that every execution experience is operable.
30. As a mobile or narrow-screen user, I want forms and task summaries to remain readable without horizontal scrolling, so that I can review a task away from a desktop monitor.

## Implementation Decisions

- Classify Skills as foundation file, supporting, or business Skills. The current foundation file Skills are xlsx, docx, pdf, and pptx.
- Add a controlled execution-experience registry owned by the platform. Manifests may declare a key, but the key can resolve only to reviewed platform code.
- Give each published business Skill an explicit registered experience. Missing registration produces an unavailable state and never invokes the generic form.
- Keep shared components semantic-free: page shell, role-based file picker, parameter controls, readiness panel, risk confirmation, task-created summary, business-stage progress, cancellation, failure panel, and output list.
- Keep business composition, wording, file relationships, parameter grouping, readiness facts, stage mapping, result metrics, and recovery guidance in the individual Skill experience definition or component.
- Use the existing Run model for ordinary Skills. Continue using the workflow model only for Skills that require human checkpoints, sequential multi-date processing, versioned materials, or workflow-specific recovery.
- Treat 应收核销日清 as the reference for workflow mechanics, not as a template for reconciliation dates, 智云 credentials, AR/SO/SOD files, daily writes, or other AR-only semantics.
- Use canonical Skill-scoped routes for creation and task detail. Preserve legacy run and workflow URLs through redirects or compatible links.
- Route Skill detail, workbench, file actions, and AI task drafts into the same registered experience while preserving draft parameters and file identifiers.
- Remove the generic task-description field unless a handler explicitly consumes it. Do not show progress stages in the creation form. Do not repeat file and parameter descriptions above and inside the same form.
- Use each Skill's configured action label. Apply a confirmation step only when backend risk configuration requires it.
- Show preflight facts only when the platform can compute them reliably. Label remaining checks as Worker-time checks rather than claiming they passed.
- Do not allow externally supplied component paths or arbitrary dynamic frontend imports.
- Migrate in batches: registry and AR compatibility; read-only reconciliation; workbook-producing workflows; split/rename/comparison workflows; statistics and compliance advice; then draft/disabled publication gates and full entry-point verification.

## Testing Decisions

- Test at the highest stable seam: entering a Skill from its public platform entry point, supplying valid or invalid inputs, creating the task, and observing the correct canonical destination and business presentation.
- Registry tests cover every published business Skill, foundation/support classification, unknown keys, and the no-fallback rule.
- Experience tests assert externally visible labels, file roles, parameter controls, readiness wording, confirmation behavior, action label, and created-task link. They do not assert internal component structure.
- Entry consistency tests cover direct Skill detail, workbench draft, file action, and AI draft paths with preserved files and parameters.
- Existing run-access, workflow, navigation, and task-center tests remain regression coverage for permissions and historical links.
- Contract tests are added before frontend consumption if a backend preflight or experience field is introduced.
- Type checking and production build are required after each migration batch; the final verification runs the affected frontend suite and backend contract tests.

## Out of Scope

- Changing the business calculations or workbook mutation rules inside Skill handlers.
- Converting every Skill to the workflow runtime.
- Loading UI code from third-party Skill packages.
- Publishing currently draft or disabled business Skills solely as part of this visual migration.
- Replacing the existing authorization, file ownership, audit, queue, or Worker models.
- Claiming workbook-content validation when the backend has not performed it.

## Further Notes

The work must preserve unrelated changes already present in the repository. Production AR safety gates and source/vendor separation remain unchanged. Each migration batch must be independently demonstrable before the next batch begins.
