---
title: Workflow Editor and nodes
description: Build a valid typed workflow, configure nodes, understand connection rules, and save or publish versions safely.
---

# Workflow Editor and nodes

The Workflow Editor is a typed DAG canvas. The graph is executable configuration: node type, port compatibility, edges, and schema-backed settings determine what PressRoom will run.

## Prerequisites

- An active workspace
- Permission to create or edit workflows
- Healthy built-in engines for the node types you intend to use
- A configured Provider for Model nodes

Start with [Quick Convert](/getting-started/first-workflow) if this is your first graph.

## Understand the canvas

The main surfaces are:

- the **canvas**, where nodes and connections define data flow;
- the floating toolbar, with **Run**, **Validation**, clear, template, version, publish, and restore actions;
- the **Inspector**, which shows configuration or result for the selected node;
- **Monitor**, **Compare**, and **History** panels for execution and review.

Select a node to make its current configuration and compatible data types visible.

## Add a node

You can add nodes in three ways:

1. Select **Add node** and search the registry.
2. Use an endpoint's add action to choose a compatible upstream or downstream node.
3. Insert a compatible node on an existing connection; the editor rewires that edge.

Endpoint-aware menus filter out incompatible choices. If no option appears, the current port may be at its connection limit or no registered node accepts that type.

## Connect the graph

Drag from a source endpoint to a target endpoint, or use the endpoint picker. The editor validates:

- a node cannot connect to itself;
- duplicate edges are rejected;
- output and input types must be compatible;
- a port cannot exceed its maximum connections;
- the graph cannot contain a cycle;
- `End` cannot have downstream connections.

Type-incompatible connections are rejected rather than retained as warning edges. An orphaned node can remain on the canvas and is reported as a non-blocking warning, but it does not contribute to execution.

## Configure common node families

### Input nodes

Select the input and stage a file in **Node Configuration**. Supported type and size checks happen before execution. A workflow requires at least one input node.

Templates use a file placeholder in the saved definition; the actual uploaded path belongs to the run, not the reusable workflow.

### Processor nodes

Processors change the representation before inference. Common uses include:

- turning PDF pages into images;
- detecting layout regions;
- enhancing low-quality scans;
- correcting image orientation.

Place processors in the order in which their output types satisfy the next node.

### Engine nodes

Engine configuration is supplied by the node registry and Provider schema. Built-in OCR and conversion engines use system-managed service Providers. A Model node requires a workspace `openai_compatible` Provider and enabled model.

If more than one enabled model is available, choose explicitly. If exactly one is available, a new workflow may select it automatically; with zero or multiple candidates, do not assume a selection.

### End node

A valid workflow has exactly one `end/final` node. Multiple upstream branches may connect to it; the final result view becomes the entry point for their terminal outputs.

`End` cannot be run by itself.

## Validate before execution

Select **Validation** (the check-circle button) to inspect the current graph. Fix blocking findings such as:

- missing input or final node;
- multiple final nodes;
- missing required configuration;
- a Model node without a Provider;
- incompatible connection types;
- a cycle.

Orphaned nodes and engine health can appear as advisory warnings. The current toolbar does not show a **Run Anyway** confirmation for warnings; **Run** opens the naming dialog whenever the local graph has no blocking issue, while server-side validation can still reject **Execute**.

## Run one node

For focused iteration, select an eligible node and choose **Run node**. Its predecessors must already be complete and required input must be staged. Input, output, and End nodes have restrictions; a complete workflow run is still the authoritative end-to-end check.

You can rerun failed nodes when the persisted task context supports it. The monitor identifies the retry scope.

## Save and publish

- **Save Draft**, available from the header **Search** command palette (<kbd>Ctrl</kbd>/<kbd>Cmd</kbd> + <kbd>K</kbd>), writes a new shared saved version.
- **Publish** selects a version for public invocation and requires Owner or Admin permission.
- **Publish As** creates and publishes a separate workflow when appropriate.

Publishing an unchanged DAG may report that no structural changes exist since the current published version.

## Verify success

Before treating a graph as ready:

1. Validation reports no blocking issues.
2. Every branch begins at a typed input and terminates at the single End node.
3. Provider and model selections are explicit where required.
4. A representative file completes successfully.
5. Node output and final output have the expected format.
6. The intended saved version is visible in Workflow Studio.

## Troubleshooting

### Connection is rejected

Read the reason shown by the editor. Check direction, source output type, target input type, and port capacity. Adding a converter or processor between two nodes may resolve a type mismatch.

### A node type is unknown

The saved definition references a type absent from the current node registry. Confirm the corresponding engine or optional registry module is installed and healthy; otherwise replace that node with a supported type.

### Model configuration is empty

Open **Workspace Settings → Providers**, enable at least one model, and test it. Return to the Model node and select both Provider and Model.

### Save reports a newer version

Do not overwrite blindly. **Refresh latest** loads the shared version; **Keep local draft** postpones the choice. For Owner or Admin, **Save As new name** currently invokes **Publish As**, so it creates and publishes a separate workflow rather than saving another draft.

### Final output is empty

Inspect the last engine node first. If it produced data, verify its output is connected to End. If not, work backward through the node results to find the first empty or failed step.

## Next steps

- [Configure Model Providers](/workflows/providers)
- [Monitor runs and inspect results](/workflows/run-and-results)
- [Create a Database evaluation](/evaluation/databases)
