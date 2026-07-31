---
title: Databases and batch evaluation
description: Create a reusable document Database, upload fixtures, run a saved workflow across selected files, and review per-document results.
---

# Databases and batch evaluation

A PressRoom **Database** is a workspace-scoped evaluation collection. It keeps documents, evaluation runs, result comparisons, and Ground Truth together so that workflow changes can be measured against a stable set.

## Prerequisites

- An active workspace
- A saved workflow in that workspace
- `Owner`, `Admin`, or `Editor` to create a Database and upload documents
- `Owner`, `Admin`, `Editor`, or `Runner` to start a run
- Representative, non-sensitive PDF, PNG, JPEG, or WebP files

Database uploads use the backend's `MAX_FILE_SIZE_MB` setting, which defaults to 50 MiB per document. Stock Compose does not map that name from `.env`; changing only the `.env` value has no effect unless the deployment also passes it into the backend environment.

## 1. Create a Database

1. Select **Database** in the top product navigation.
2. Select **Create Database**.
3. Enter a task-oriented name, such as `Synthetic invoices — regression`.
4. Add a description that records document source, intended workflow, and review purpose.
5. Select **Create**.

The new Database opens in its workspace. The product may retain `test-set` terminology in internal API routes; the user-facing resource is **Database**.

## 2. Upload documents

1. Open the **Documents** section.
2. Select **Upload**.
3. Choose one or more supported files.
4. Confirm each file appears with type, size, upload time, and Ground Truth status.

Use deterministic fixtures when comparing workflow versions. Avoid mixing unrelated document families in one Database; a stable, well-described set makes pass rates meaningful.

![Database documents and Ground Truth workflow](/images/guides/database-ground-truth.webp)

Select a document row to open its preview and details. Browser preview availability depends on file type, but the source remains available to the evaluation runtime.

## 3. Choose documents for a run

Select document rows, then choose **Run Workflow**. You can also open the **Runs** section and select **New Run**.

On the run configuration page:

1. Choose a saved **Workflow** from the active workspace.
2. Enter an optional **Run Name**, such as `OCR v3 — July baseline`.
3. Search and select one or more documents.
4. Review the selected count and workflow summary.
5. Select the dynamic **Run _N_ documents** button, where _N_ is the selected count.

The backend snapshots the current workflow definition for the evaluation. If the workflow has a published version, that version number is associated with the run; otherwise the latest saved version is used. In the current release, the associated published number can therefore predate the saved definition in the snapshot. Treat the snapshot as the execution source of truth. Later workflow edits do not rewrite an existing run.

Only one active evaluation run is allowed for a Database at a time. Wait for the current run to become terminal before starting another.

## 4. Monitor progress

After creation, PressRoom returns to the Database and shows live progress. Per-document states include queued, running, completed, failed, and skipped.

The `standard` profile schedules serial/background evaluation execution in the application runtime. The `full` profile can send evaluation work through Redis and Celery when queue mode is enabled.

You can leave the active view and reopen the run from **Runs**. Status and results are persisted.

## 5. Review results

Open a completed run to inspect:

- workflow name and run timing;
- document count and execution summary;
- pass rate for documents that could be compared;
- each document's execution, Ground Truth, comparison, and review status.

Select a result row to compare the UI's **Original / Ground Truth** column with **OCR Output**. The second label is currently used even when the selected workflow is not OCR-based. A result without Ground Truth is labeled `No GT` rather than counted as a match.

Use **Accept as Ground Truth** only after reviewing the actual content. This creates a new Ground Truth version. **Reject** records that the output should not become Ground Truth.

## Build a useful evaluation set

- Keep source documents fixed while comparing workflow versions.
- Include clean, noisy, rotated, table-heavy, and mixed-layout examples relevant to your use case.
- Name runs with the workflow version, Provider/model, and important parameters.
- Add Ground Truth before relying on pass rate.
- Review failures separately from content differences; an execution failure is not a comparison mismatch.

## Verify success

- The Database is visible only in its owning workspace.
- Uploaded documents show the expected filename, MIME type, and size.
- The run records the chosen workflow and selected document count.
- Progress reaches a terminal state for every document.
- Completed results are visible from **Runs** after a page reload.
- Documents with Ground Truth show `Pass` or `Differs`; missing Ground Truth shows `No GT`.

## Troubleshooting

### Upload partially succeeds

The backend can return successful files and per-file errors together, but the current UI does not display that error array and its success message reflects the number selected. If fewer documents appear than expected, check unsupported MIME type, empty content, and the file-size limit, then retry uncertain files one at a time.

### No workflow appears

Save a workflow in the same active workspace. Clear the workflow search and verify workspace selection. Evaluation cannot bind a workflow owned by another workspace.

### A new run returns a conflict

Another evaluation is active for this Database. Open **Runs**, wait for it to complete or fail, then create the next run.

### Pass rate is missing

Pass rate is calculated from matched and mismatched comparisons. Add Ground Truth to the relevant documents and run the workflow again.

### A run remains queued in the full profile

Confirm Redis and `celery-worker` are healthy, `ORCHESTRATOR_MODE=queue`, `ENABLE_QUEUE_MODE=true`, and backend/worker runtime configuration matches.

## Next steps

- [Create and review Ground Truth versions](/evaluation/ground-truth)
- [Compare editor runs](/workflows/run-and-results)
- [Choose standard or queue execution](/deployment/compose)
