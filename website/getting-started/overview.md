---
title: PressRoom overview
description: Understand what PressRoom does, how its main product areas fit together, and which deployment profile to choose.
---

# PressRoom overview

PressRoom is a self-hosted workspace for designing, running, evaluating, and publishing document-processing workflows. It combines a visual, typed DAG editor with built-in conversion engines, workspace-scoped model Providers, reusable evaluation data, and a workflow-scoped public API.

## What you can do

### Build document workflows

The **Workflow Editor** connects four kinds of building blocks:

1. **Inputs** stage a PDF, image, or other supported file.
2. **Processors** transform input before inference, such as converting a document to page images, enhancing an image, or correcting rotation.
3. **Engines** perform OCR, layout detection, Text or HTML processing, MarkItDown conversion, Docling conversion, or model inference.
4. **End** is the single terminal node that exposes the final workflow result.

Connections are validated against node and port types. Cycles, orphaned nodes, incompatible data types, and multiple final nodes are reported before execution.

### Evaluate repeatably

A **Database** is a reusable document set, not the PostgreSQL server itself. Within a Database you can:

- upload documents;
- select a saved workflow and a subset of documents;
- monitor batch progress and per-document status;
- compare output with the current Ground Truth;
- accept a reviewed output as a new Ground Truth version.

![Evaluation run comparing a synthetic invoice with versioned Ground Truth](/images/product/evaluation-compare.webp)

### Publish an integration

Saving and publishing are separate actions. A saved workflow can be edited and used for evaluation. Publishing records publication state and unlocks public API access; in the current release, new public runs execute the workflow's current saved definition.

From the workflow's **API Access** page, an Owner or Admin can issue and revoke workflow-scoped keys, copy URL and upload examples, and review public invocation usage. A key for one workflow cannot call another workflow.

## How the system fits together

```text
Browser
  └─ React application
       └─ FastAPI backend
            ├─ PostgreSQL: workspaces, workflows, runs, evaluation data
            ├─ SQLite Provider store: encrypted workspace Provider records
            ├─ Shared storage: uploaded documents and generated results
            └─ Engine services: OCR, VLM adapter, Text, MarkItDown, Docling,
                                layout detection, enhancement, and rotation
```

The standard profile executes workflows serially in the application runtime. The full profile adds Redis and a Celery worker for queued execution. Both profiles use the same workflow and engine contracts.

## Before you begin

You need:

- Docker Engine with Docker Compose v2;
- at least 16 GB of RAM for the `standard` or `full` profile;
- enough additional memory and disk for model-heavy engines and retained files;
- permission to build images locally, because the project does not publish prebuilt application images.

You do **not** need an external model Provider for the first OCR workflow.

## Product navigation

| Area | Purpose |
| --- | --- |
| **Workflow Editor** | Create or modify the current workflow and inspect execution. |
| **Workflow Studio** | Search, open, rename, reach API Access, and delete saved workflows. Publishing is performed in the editor. |
| **Template Center** | Apply a built-in starter or import workflow JSON. |
| **Database** | Manage document sets, batch runs, comparisons, and Ground Truth. |
| **Settings** | Inspect built-in engine services and their health. |
| **Workspace Settings → Providers** | Manage workspace model Providers and models. |
| **API Access** | Configure external invocation for a publication-enabled workflow. |

The product UI supports English and Traditional Chinese. These docs are available in English and Simplified Chinese; UI names remain in English when precision matters.

## Verify your understanding

You are ready to install when these distinctions are clear:

- a **workflow draft** is editable, while publication state gates external API access to the current saved definition;
- a **Database** owns evaluation documents and Ground Truth, while a **workspace** owns access to all product resources;
- a built-in **engine service** follows the `/process`, `/health`, and `/config` contract, while an `openai_compatible` **Provider** supplies request-time model access through the local VLM adapter.

## Troubleshooting orientation

| Symptom | Where to start |
| --- | --- |
| The application does not start | [Installation troubleshooting](/getting-started/installation#troubleshooting) |
| A node is unavailable or unhealthy | [Model Providers](/workflows/providers) and [Run and results](/workflows/run-and-results) |
| A batch has no comparable result | [Ground Truth](/evaluation/ground-truth) |
| API Access is locked | [Publish and configure API Access](/publish/api-access) |
| A deployment needs hardening | [Security and troubleshooting](/administration/security-and-troubleshooting) |

## Next steps

- [Install the standard profile](/getting-started/installation)
- [Run the first PDF → OCR workflow](/getting-started/first-workflow)
- [Learn the core concepts](/concepts/core-concepts)
