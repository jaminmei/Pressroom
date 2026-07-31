---
title: Run your first PDF → OCR workflow
description: Apply the built-in Quick Convert template, upload a PDF, execute OCR, inspect the result, and save the workflow.
---

# Run your first PDF → OCR workflow

This guide uses the built-in **Quick Convert** template. It creates a `PDF Input → Document to Image → OCR → End` graph and does not require an external model Provider.

## Prerequisites

- A healthy `standard` or `full` PressRoom deployment
- An app-local account with an active workspace
- A small, non-sensitive PDF that contains selectable or visible text
- A workspace role allowed to create, edit, and run workflows (`Owner`, `Admin`, or `Editor`)

## 1. Apply the starter

1. Sign in to PressRoom.
2. Select **Template Center** in the left navigation.
3. Find the **Quick Convert** card. Its description identifies it as the PDF-to-image OCR path.
4. Select **Apply now**.

PressRoom opens the Workflow Editor with four connected nodes:

```text
PDF Input → Document to Image → OCR → End
```

![Template Center with the Quick Convert PDF to OCR starter](/images/guides/template-center-ocr.webp)

Applying a template replaces the current canvas immediately. The current Template Center flow does not show an unsaved-work confirmation, so save important work before selecting **Apply now**.

## 2. Inspect the graph

Select each node and review its configuration in the **Inspector**:

- **PDF Input** owns the file binding.
- **Document to Image** converts page 1 by default.
- **OCR** uses the bundled OCR engine and starts with Chinese language recognition and angle classification enabled.
- **End** is the terminal result entry point.

The connection lines represent typed data flow. A document enters the processor, page images enter OCR, and recognized output reaches the final node.

## 3. Upload a PDF

1. Select **PDF Input**.
2. In **Node Configuration**, select **Choose file** or use the upload drop area.
3. Choose your local PDF.
4. Confirm that the editor reports the document as staged for the run.

The uploaded file is submitted with the execution; selecting it in the browser does not publish it or make it part of a template.

## 4. Validate and run

1. Select **Validation** (the check-circle button) in the floating toolbar and fix any blocking issue it lists.
2. Select **Run**. When the local graph is executable, the run-name dialog opens immediately.
3. In **Name this Run**, enter an optional label such as `OCR baseline`, or leave it blank to use the task ID.
4. Select **Execute**. Server-side validation can still return a blocking error before execution starts.

The execution monitor receives live task and node state over WebSocket. Keep the workspace selected until the task finishes.

## 5. Inspect the result

When the run completes:

1. Select the **OCR** node and open its **Result** tab. Current engine output is normally shown as structured raw JSON with metadata.
2. Select **End** to open its **Run**, **Compare**, and **History** tabs.
3. Use **Compare** after you have more than one run; its toolbar provides **Diff**, **Sync**, and **Download**.
4. Use **History** to reload a previous task context.

For a text-heavy PDF, the final output should contain recognizable document text. OCR quality depends on page resolution, language, rotation, and source quality.

## 6. Save the workflow

1. Open the header **Search** command palette, or press <kbd>Ctrl</kbd>/<kbd>Cmd</kbd> + <kbd>K</kbd>.
2. Choose **Save Draft**.
3. Open **Workflow Studio**. If the new record is untitled, choose **Rename** and give it a meaningful name such as `Invoice OCR baseline`.
4. Confirm that the saved workflow appears with its latest version.

Saving creates a shared workflow record for the active workspace. It does not make the workflow callable through the public API; that requires a separate **Publish** action.

## Verify success

You have completed the guide when all of the following are true:

- the graph contains one input and one `End` node;
- validation reports no blocking issue;
- the run reaches a completed state;
- OCR content is visible in the result view;
- the workflow appears in **Workflow Studio**.

## Troubleshooting

### Run is disabled

Select the PDF input and confirm a file is staged. Then check that all nodes are connected and exactly one `End` node exists.

### Validation reports an offline engine

Open **Settings** and inspect the OCR engine health. At the host, run:

```bash
docker compose --profile standard ps ocr-engine backend
```

If needed, inspect the affected service logs without sharing document content publicly.

### The run completes but OCR text is poor

Try a higher-resolution source, enable the appropriate OCR language, or add image enhancement and rotation processors before OCR. For complex tables and mixed layouts, compare OCR with a vision model after configuring a Provider.

### A newer workflow version is reported

Another saved version exists. **Refresh latest** loads it; **Keep local draft** postpones the decision. For an Owner or Admin, the banner's **Save As new name** action currently opens **Publish As**, which creates and publishes a separate workflow—use it only when that is the intended outcome.

### The task loses live updates

Use the manual reconnect action or reopen the run from **Recent Runs**. Completed task snapshots and results are persisted even when the browser's WebSocket disconnects.

## Next steps

- [Learn the editor and node rules](/workflows/editor-and-nodes)
- [Configure an OpenAI-compatible model Provider](/workflows/providers)
- [Create a Database for batch evaluation](/evaluation/databases)
