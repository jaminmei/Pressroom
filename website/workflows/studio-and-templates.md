---
title: Workflow Studio and templates
description: Start from curated workflow templates, import a definition, and manage saved workflows in Workflow Studio.
---

# Workflow Studio and templates

**Template Center** is the fastest path to a valid graph. **Workflow Studio** is the library for saved workflows. Use them together: begin from a proven topology, tune it in the editor, then save it into the active workspace.

## Prerequisites

- A signed-in user with an active workspace
- `workflow.create` and `workflow.edit_draft` capabilities to create and modify workflows
- A Provider with an enabled vision model if you plan to use a Model template

## Choose a built-in template

Open **Template Center** from the sidebar. PressRoom ships three starters:

| Card | Topology | Best for |
| --- | --- | --- |
| **Quick Convert** | PDF → page image → OCR → End | A model-free first run and text-heavy documents. |
| **Custom Workflow** | PDF → page image → Model → End | Complex layouts, tables, or structured vision-model extraction. |
| **Multi-Engine Compare** | PDF → page image → OCR and Model → End | Comparing two approaches on the same source. |

Select **Apply now** on a card. The template is localized, copied into the editor store, and opened as an editable draft. It is not saved automatically.

Applying a template replaces every node on the current canvas immediately, without an unsaved-work confirmation in the current Template Center flow. Save important work first.

## Tune the starter

After applying a template:

1. Select each node and review **Node Configuration**.
2. Confirm the document page selection and preprocessing options.
3. For a Model node, choose a workspace Provider and an enabled, vision-capable model.
4. Add, remove, or reconnect nodes while preserving one terminal `End` node.
5. Upload a safe sample and run validation before saving.

The built-in templates are baselines, not locked product recipes.

## Import workflow JSON

Use **Import** in Template Center when you already have a workflow definition.

The importer expects JSON with `nodes` and `connections` arrays. It repairs the final-node shape where possible and opens the result in the editor. Import does not bypass node registry or connection validation.

Before importing a definition from another party:

- review Provider references and prompts;
- remove local file paths and environment-specific values;
- confirm every node type is registered in this deployment;
- treat embedded content as untrusted configuration.

An invalid JSON document, missing arrays, or an empty node list is rejected without replacing the current graph.

## Export a template definition

Select **Export** on a template card to download its name, nodes, and connections as JSON. Exported definitions do not contain Provider secrets. Still review the file before publishing it because node prompts and workflow structure may be sensitive to your use case.

## Save into Workflow Studio

From the editor:

1. Open the header **Search** command palette, or press <kbd>Ctrl</kbd>/<kbd>Cmd</kbd> + <kbd>K</kbd>.
2. Choose **Save Draft**.
3. Open **Workflow Studio**. Use **Rename** to set or refine the workflow name and description.
4. Search for the saved name and confirm the latest version.

Workflow Studio lets authorized members open saved workflows, rename them, review latest and published version indicators, and delete them. Deletion is permanent and is restricted more tightly than editing.

## Manage version conflicts

Saved workflow versions are shared. If another member saves while your local draft is based on an older version, the editor reports a conflict instead of silently overwriting the new version.

Choose deliberately:

- **Refresh latest** replaces the editor with the newest shared version.
- **Keep local draft** postpones the decision without changing the server version.
- For an Owner or Admin, **Save As new name** currently opens **Publish As** and creates and publishes a separate workflow. It is not a draft-only save action.

Do not use publishing as a conflict-resolution mechanism.

## Verify success

- Applying a template opens a connected graph in the editor.
- Model templates clearly show a Provider/model selection requirement when none is available.
- Saving makes the workflow visible in Workflow Studio.
- Reopening the workflow restores its saved nodes and connections.
- The published badge remains absent until an authorized member publishes a version.

## Troubleshooting

### A template opens with a Provider warning

The OCR template uses a built-in engine. Model templates require a configured, enabled model. Follow [Model Providers](/workflows/providers), then return to the node and make an explicit selection.

### Import reports an invalid schema

Confirm the top-level object, or its workflow definition, contains non-empty `nodes` and a `connections` array. Import only node types supported by the current registry.

### A saved workflow is not visible

Check the active workspace and clear the Workflow Studio search. Workflows are isolated by workspace.

### Rename or delete is unavailable

Editors can rename saved workflows. Deletion requires an Owner or Admin under the current capability matrix. Publishing is performed from the Workflow Editor, not from the Workflow Studio list, and also requires an Owner or Admin.

## Next steps

- [Learn node configuration and connection rules](/workflows/editor-and-nodes)
- [Run and inspect a workflow](/workflows/run-and-results)
- [Publish API access](/publish/api-access)
