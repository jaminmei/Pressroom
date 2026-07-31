---
title: Core concepts
description: Learn how workspaces, workflows, nodes, Providers, runs, Databases, Ground Truth, and published APIs relate in PressRoom.
---

# Core concepts

PressRoom uses a small set of resource boundaries to keep authoring, execution, evaluation, and external access understandable. The most important boundary is the active workspace: nearly every resource and permission is evaluated within it.

## Workspace

A **workspace** is the collaboration and isolation boundary for:

- members and roles;
- workflows and versions;
- Databases, documents, Ground Truth, and evaluation runs;
- workspace model Providers;
- workflow API keys and usage traces.

The workspace switcher determines the active scope. Switching workspaces changes which resources the application can resolve; it is not a visual filter over a global list.

### Roles at a glance

| Role | Intended use |
| --- | --- |
| `Owner` | Full control, including workspace deletion and ownership transfer. |
| `Admin` | Daily administration, publishing, Providers, members, API keys, and workspace settings. |
| `Editor` | Build workflows, manage Databases and documents, edit Ground Truth, and run evaluations. |
| `Runner` | Run workflows and evaluations and view results without editing resources. |
| `Viewer` | Read-only access to resources and results. |

The backend enforces capabilities. A disabled or hidden control in the UI is only a presentation of that same authorization decision, not the security boundary itself.

## Workflow and version

A **workflow** is a saved, named DAG. Its definition contains nodes, connections, and node configuration.

PressRoom distinguishes three states:

- An **unsaved draft** is current editor work and is not the shared source of truth.
- A **saved version** is available to the workspace and can be selected for evaluation.
- A **published version** records the version most recently published and unlocks public API access.

Saving and publishing solve different problems. Save while iterating with teammates; publish only after you are ready to expose the workflow to workflow-scoped API callers. In the current release, that publication state is an access gate: new public runs resolve the workflow's current saved definition rather than loading an immutable published snapshot.

## Node and connection

A **node** performs one typed step. Node definitions come from the backend registry, which supplies input/output types, connection rules, and schema-backed configuration.

The standard families are:

| Family | Examples | Role in the graph |
| --- | --- | --- |
| Input | PDF Input, Image Input | Binds the run's source file. |
| Processor | Document to Image, enhancement, rotation | Transforms data before an engine. |
| Engine | OCR, Model, Text, MarkItDown, Docling, layout detection | Produces document intelligence or conversion output. |
| End | End | Collects the final workflow result. |

A **connection** routes a node's output to a compatible input port. The validator rejects cycles, missing nodes, excessive port connections, incompatible types, and graphs without exactly one final node.

## Engine and Provider

An **engine service** implements PressRoom's `/process`, `/health`, and `/config` service contract. Built-in Compose engines cover OCR, the local VLM adapter, Text, MarkItDown, Docling, layout detection, image enhancement, and image rotation.

A **Provider** tells a node where and how to invoke a capability:

- `engine_service` Providers are invoked directly through the engine `/process` contract.
- `openai_compatible` Providers are invoked through the local VLM adapter, which selects standard OpenAI-compatible or Azure OpenAI request behavior for that invocation.

Workspace Provider credentials are encrypted at rest. The credential is resolved at invocation time and must not be copied into node configuration, workflow definitions, traces, or logs.

## Task run and result

A **task run** is one execution of a workflow with a specific set of inputs and a workflow snapshot. It tracks node progress, events, terminal state, timing, and produced results.

The editor uses WebSocket updates for the active task and persists run snapshots for later access. Node-level output helps diagnose the pipeline; the `End` node is the final result entry point.

Public API calls also create task runs. The API calls the task ID a `workflow_run_id`, but it refers to the same persisted execution identity.

## Database and document

A **Database** is an evaluation collection (the backend retains the historical `test-set` naming in some internal routes). It owns:

- uploaded source documents;
- evaluation runs over selected documents;
- per-document run history;
- Ground Truth versions.

It is separate from the PostgreSQL infrastructure service.

## Ground Truth and comparison

**Ground Truth** is the expected content for one document. Versions are append-only: a manual JSON upload or an accepted evaluation result creates a new version instead of overwriting history.

During an evaluation, each result can be:

- matched with the current Ground Truth;
- different from it;
- not compared because Ground Truth is missing or unavailable;
- failed or skipped during execution.

Reviewing a result is explicit. **Accept as Ground Truth** promotes that output into a new version; **Reject** records the review without replacing existing Ground Truth.

## Published API and API key

A **published workflow API** becomes callable after the workflow has a published version. In the current release it executes the current saved definition, and supports a remote URL input and a multipart file upload.

An **API key**:

- is bound to exactly one workflow;
- is returned in full only when it is issued;
- is stored as a hash by the API-key service;
- can be revoked immediately;
- does not grant browser-session administration access.

The public `/api/v1` runtime and the session-authenticated `/api` administration surface are deliberately separate.

## The lifecycle

```text
Workspace
  ├─ Provider ───────────────┐
  ├─ Workflow → saved version → run → result
  │                    └──────→ publication gate → scoped API key → API run
  └─ Database → document → Ground Truth versions
                    └────→ evaluation run → compare → accept/reject
```

## Verify your mental model

Before building a production flow, confirm that you can answer:

1. Which workspace owns the workflow and Provider?
2. Which saved version is being evaluated?
3. Which version is currently published?
4. Which document and Ground Truth version produced a comparison?
5. Which workflow owns the API key and resulting run?

These identifiers are the fastest way to diagnose unexpected access or output.

## Troubleshooting concepts

- If a resource appears missing after a workspace switch, verify the active workspace before recreating it.
- If editing is disabled, compare the operation with the active member role.
- If a model node has no selection, verify enabled models and the Provider default.
- If API output differs from the editor, confirm which workflow version is published.
- If evaluation says `No GT`, add or accept Ground Truth for that specific document.

## Next steps

- [Use Workflow Studio and templates](/workflows/studio-and-templates)
- [Build with editor nodes](/workflows/editor-and-nodes)
- [Set up evaluation Databases](/evaluation/databases)
