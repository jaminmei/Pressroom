---
title: Run workflows and inspect results
description: Validate and execute a workflow, monitor node progress, inspect outputs, compare runs, and diagnose failures.
---

# Run workflows and inspect results

An editor run validates the current graph, binds staged input files, executes a workflow snapshot, and persists task status and results. Live WebSocket updates improve the active experience; persisted snapshots let you return after a disconnect.

## Prerequisites

- A valid workflow with at least one input and exactly one End node
- Required files staged on input nodes
- Healthy engines and configured Providers
- A workspace role with `workflow.run`

## 1. Validate the graph

Select **Validation** (the check-circle button) to inspect local structure and configuration findings. Fix every blocking issue before running.

Warnings such as an orphaned node or engine-health advisory do not produce a **Run Anyway** dialog in the current toolbar. Review them before deciding to continue.

Select **Run** once. If the local graph is executable, **Name this Run** opens immediately; after **Execute**, server-side validation can still return structure, port, Provider/model, or engine findings before a task starts.

## 2. Name and execute the run

In **Name this Run**, add a label that will be meaningful in Compare and History, such as:

```text
Invoice sample — OCR baseline
```

The name is optional; a task ID is used when it is empty. Select **Execute**.

The monitor shows:

- task ID and elapsed time;
- the current node and overall progress;
- per-node timeline and terminal status;
- connection state and cancellation controls.

Do not switch workspaces while the task is being created or while results are loading.

## 3. Inspect node output

Select a completed non-End node and open its **Result** tab. This is the most direct way to locate where content changed or disappeared.

Work from left to right:

1. Confirm input metadata identifies the expected file.
2. Confirm preprocessing produced the expected representation or page images.
3. Review engine output and metadata.
4. Confirm the final engine output reaches End.

Uploaded source files are not rendered in API trace mode.

## 4. Inspect the final result

Select the **End** node. Its current tabs are:

- **Configuration** for the terminal contract;
- **Run** for task status and control;
- **Compare** for prior-run selection, **Diff**, **Sync**, and **Download**;
- **History** for persisted task and workflow-version context.

For ordinary nodes, PDF and image-producing results can show a visual preview and raw data. Current engine outputs are generally displayed as structured raw JSON with metadata and any binary previews. Use downloads from **Compare** instead of copying large stored results from the browser.

## 5. Compare and reopen runs

Open **Compare** and select prior runs. The first two panes support diff and synchronized scrolling; additional panes remain independently scrollable.

Use **History** or **Recent Runs** to:

- reopen a completed task;
- restore its result context;
- inspect published workflow versions;
- restore an eligible version into the editor.

Restoring a version changes the graph shown in the editor; save or reconcile unsaved work first.

## Node-level iteration

Use **Run node** after a complete baseline run when you want focused feedback. A node can run only when its required predecessors and input are available. End nodes cannot run individually.

For a failed task, **Rerun node** may retry the failed scope. Always recheck the final workflow after a node-level retry.

## Verify success

- The task reaches a terminal completed state.
- Every expected node reports completed, or an intentional branch is clearly skipped.
- The selected input metadata matches your staged document.
- Node-level output is present before End.
- The final output format and content match the workflow's contract.
- The run is available from Recent Runs or History after reloading the page.

## Troubleshooting

### Execution fails on one node

Select that node and read its error and configuration. Check the corresponding service under **Settings** or Provider under **Workspace Settings → Providers**. Fix the dependency before retrying.

### Live progress disconnects

Use **Reconnect manually**. If the reconnect limit is reached, reload the page and reopen the task from **Recent Runs**. A WebSocket failure does not by itself mean server-side execution stopped.

### Result loading fails after completion

Refresh, confirm the same workspace remains active, and reopen the task. Workspace changes while a result request is in flight are intentionally rejected.

### Model output is unstructured

Review the node prompt and **Output Schema**, confirm the selected model supports the requested capability, and inspect the node's **Result** JSON for upstream validation details.

### The result differs from a previous run

Confirm the input file, saved workflow version, Provider and model, node parameters, and engine health. Name runs with those variables so Compare remains useful.

## Next steps

- [Evaluate a saved workflow over a Database](/evaluation/databases)
- [Maintain versioned Ground Truth](/evaluation/ground-truth)
- [Publish the workflow API](/publish/api-access)
