# Frontend agent instructions

This directory is the active Next.js interface for the financial Skill platform. The repository-root `AGENTS.md` and `CONTEXT.md` define the product boundary and outrank this file.

## Before changing code

- Read `../CONTEXT.md` and the relevant current document under `../docs/`.
- Treat `src/features/platform-api/` as the platform boundary. Update the OpenAPI contract first when an API shape changes, then regenerate the client with `pnpm contracts:generate`.
- Use Clerk only to prove login identity. Platform roles, resource isolation, approvals, audit, and execution permissions come from the FastAPI backend.

## Current interface

The supported dashboard areas are workbench, Skill center, runs, files, AI assistant, workflows, profile, user management, Skill governance, and Skill reviews. Add product behavior inside the matching `src/features/` module and keep route files thin.

Use server components by default. Add `use client` only for browser APIs or React hooks. Use the shared `Icons` registry and `PageContainer` for page headers. Existing shadcn components under `src/components/ui/` are infrastructure; extend them in feature code.

## Completion

Run the affected Node tests, `pnpm typecheck`, and `pnpm build`. A frontend change is complete when no deleted route is referenced, the platform navigation tests pass, and the production build succeeds.
