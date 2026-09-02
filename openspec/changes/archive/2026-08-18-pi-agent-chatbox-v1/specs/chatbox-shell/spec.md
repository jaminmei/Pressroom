# Spec: chatbox-shell

Capability: workspace-scoped bottom-right launcher and conversation panel for the Pi Agent chatbox.

Source: [proposal](../../proposal.md); accepted decision `wiki/decisions/2026-08-14/pi-agent-chatbox-v1-boundaries.md` §1, §4.

## ADDED Requirements

### Requirement: Fixed bottom-right launcher on authenticated workspace pages
The chatbox SHALL be opened from a fixed launcher at the bottom-right of authenticated application pages where the chatbot is available. The launcher SHALL NOT appear on pages that lack an authenticated workspace session.

#### Scenario: Launcher visible to authenticated workspace user
- **WHEN** an authenticated user with an active workspace opens a chatbot-enabled page
- **THEN** the bottom-right launcher is visible and activates the chatbox panel on click

#### Scenario: Launcher hidden without workspace session
- **WHEN** a visitor without an authenticated workspace session opens a page
- **THEN** the bottom-right launcher is not rendered

### Requirement: Compact conversation panel with narrow-screen adaptation
Activating the launcher SHALL open a compact conversation panel. On narrow screens the panel MAY become a drawer or full-height surface.

#### Scenario: Compact panel opens on activation
- **WHEN** the user activates the launcher on a wide viewport
- **THEN** a compact conversation panel opens over the application without leaving the document-conversion UI

#### Scenario: Narrow viewport uses full-height surface
- **WHEN** the user activates the launcher on a narrow viewport
- **THEN** the panel renders as a drawer or full-height surface so the conversation remains usable

### Requirement: Active workspace and Pi session preserved across open/close
Opening and closing the panel SHALL preserve the active workspace identity and the active Pi session.

#### Scenario: Session survives open/close
- **WHEN** the user opens the panel, observes an in-flight Pi session, closes the panel, and reopens it
- **THEN** the same workspace identity and the same Pi session are restored, including the in-flight state

### Requirement: Single workspace-default model with no per-message picker
V1 SHALL use one workspace default model shared by Pi Agent and Pi Coding Agent. The chatbox SHALL NOT expose a per-message model picker.

#### Scenario: Default model is the only model used
- **WHEN** the user sends a message in the chatbox
- **THEN** the request is dispatched to the workspace default `llm_api` Provider only, with no in-panel model selector

### Requirement: React, TypeScript, and Ant Design foundation with swappable Pi renderers
The chatbox SHALL be built on the existing React, TypeScript, and Ant Design stack and SHALL permit custom Pi message and tool renderers. A third-party chat shell is permitted only if it allows custom Pi message and tool renderers.

#### Scenario: Renderers are pluggable
- **WHEN** a Pi event arrives that requires a custom tool or message renderer
- **THEN** the chatbox delegates rendering to the registered React renderer for that Pi event/tool type instead of falling back when a renderer exists

### Requirement: Production bundle respects debug-store and console-diagnostics rules
The production frontend bundle SHALL NOT expose debug stores or unconditional console diagnostics, consistent with the repository's existing frontend rules.

#### Scenario: Production build is clean
- **WHEN** the production frontend bundle is built
- **THEN** it contains no debug store and no unconditional console diagnostic output
