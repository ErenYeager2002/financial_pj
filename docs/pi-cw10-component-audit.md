# CW10 DeerFlow component adaptation audit

Observed: 2026-10-08. Status: preparatory source audit; no UI cutover, dependency installation or production code change.

## Pinned provenance

Repository: https://github.com/bytedance/deer-flow/tree/d3a9c123ff7ce37d6f6af3c7b065ef501fe16cb0

The Git tree was retrieved at the construction plan's exact commit. Thirteen selected files were fetched read-only and checked against their Git blob SHA-1; independent SHA-256 values are in the adjacent source manifest. Local reference copies remain outside the production source. The license is MIT; any later copied/substantially adapted source must retain the complete copyright and permission notice. No upstream install/build script was executed.

This is a selected-component audit, not a complete transitive dependency or performance certification. Declared package ranges below are not resolved lockfile versions.

## Dependency comparison

| Package | Platform declaration | Pinned upstream declaration |
|---|---|---|
| next | 16.2.12 | ^16.3.3 |
| react | 19.2.4 | ^19.0.0 |
| react-dom | 19.2.4 | ^19.0.0 |
| tailwindcss | ^4.2.2 | ^4.0.15 |
| @base-ui/react | ^1.6.0 | not declared |
| @radix-ui/react-slot | not declared | ^1.2.4 |
| lucide-react | not declared | ^0.562.0 |
| @tabler/icons-react | ^3.40.0 | not declared |
| ai | ^7.0.44 | ^6.0.33 |
| @langchain/langgraph-sdk | not declared | ^1.5.3 |
| @tanstack/react-virtual | not declared | ^3.13.23 |
| use-stick-to-bottom | not declared | ^1.1.1 |
| streamdown | not declared | 2.5.0 |
| shiki | not declared | 3.23.0 |
| react-resizable-panels | not declared | ^4.4.1 |

Do not replace the platform package.json/lockfile or migrate its Next/React versions just to copy a display component. The platform uses Base UI and Tabler while upstream display controls use Radix and Lucide. Adapt each control to the existing platform primitives. AI SDK types also differ in major version; define display props from the existing Pi view model rather than importing upstream message/run types.

## Concrete component decisions

| Component | Evidence and required adaptation | Disposition |
|---|---|---|
| ai-elements/conversation.tsx | Presentational layout and scroll-to-bottom; depends on use-stick-to-bottom and Lucide. Preserve user scroll and accessible log semantics. Reuse existing platform scroll behavior or separately approve/add a locked dependency. | First extraction candidate |
| ai-elements/message.tsx | Imports AI SDK UIMessage and upstream streamdown. Replace with Pi visible-message props and existing safe Markdown rendering; copy presentation only. | Adapt shell, not message protocol |
| workspace/messages/tool-call-details.tsx | Imports LangGraph ToolCall type, clipboard/i18n/tool preview helpers. Map existing stable Pi tool IDs/status/results to a platform-owned display type. | Adapt after plain messages |
| workspace/messages/virtual-message-list.tsx | Uses react-virtual, stick-to-bottom and upstream message grouping. Group stable Pi message IDs without recreating cursor state. | Optional measured optimization; new dependency cost unmeasured |
| workspace/chats/chat-box.tsx | Reads upstream thread context and artifact/browser/sidecar contexts. Keep layout composition, replace state with existing Pi view model/actions and platform artifact panel. | Do not copy as a ready-made page |
| ai-elements/prompt-input.tsx | Has upstream upload imports, object/data handling and fetch(url). Use only input visual structure; retain platform upload commit/version/scope and current draft/delivery controller. | Do not copy upload/submit behavior |
| workspace/input-box.tsx | Over 100 KB of source; references auth, thread creation, models, projects, skills, suggestions, voice and backend fetch paths. | Not a reusable isolated input component |
| workspace/chats/use-thread-chat.ts | Own thread identity/reset/router semantics. | Excluded; platform session ownership and routing stay authoritative |
| workspace/artifacts/artifact-file-preview.tsx | HTML iframe permits scripts/forms; uses upstream artifact URL, citation and message bridge helpers. This is not accepted as the platform preview policy. | Retain safe platform downloads; preview requires separate origin/resource/security verification |
| ai-elements/code-block.tsx | Shiki-generated HTML and clipboard helper. | Lazy-load only after sanitization/provenance and bundle tests; no new raw-HTML path now |

## Integration seam and order

1. Keep one existing usePiSession controller per owned session. The feature flag changes only renderer selection, never mounts both controllers. Pass the same state/actions to old and adapted renderers.
2. Extract conversation layout and message shells first, preserving Pi stable IDs, unknown states, extension display filtering and accessibility. Record source commit/license beside copied files.
3. Add tool-result cards using actual Pi events. Background jobs and finance tasks keep distinct lifecycle/status/cancel actions.
4. Bind composer, queue retrieval, upload, models, dialogs and artifacts to existing controller actions and capability projection. Do not add raw RPC or upstream fetch fallbacks.
5. Features without real backend data (goal/todos/subagents/long-term memory/history branching/regeneration) stay absent. No LangGraph, Redis, Gateway, second Next process or independent auth layer.
6. Validate old/new renderer with the same real session: no duplicate prompt or observers; unload only cancels observation; unknown delivery never resends. UI rollback switches rendering only and preserves session, receipts, financial tasks and safety fixes.

## Gates and measurable acceptance still outstanding

- G4 real browser matrix remains incomplete; browser inventory was empty and both Chrome and in-app browser creation were unavailable during this audit.
- Before G5: inventory the selected components' full import closure, resolve exact lockfile additions, compare production route assets and build/runtime memory against current UI, and verify license notices.
- Exercise long histories, active token streaming, large downloads/previews and approved peak concurrency; record measured values. Source-file size is not bundle size, and no memory-saving claim is made here.
- Confirm keyboard/IME/multiline input, focus after dialog/queue actions, theme, narrow screens and error/unknown states in the real browser.
- Production UI switching remains conditional on the plan's G1-G5 requirements and UI cutover approval. This audit prepares a reviewable integration, not permission to skip those gates.
