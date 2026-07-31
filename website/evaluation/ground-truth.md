---
title: Ground Truth
description: Add expected content to evaluation documents, inspect append-only versions, compare results, and accept or reject reviewed output.
---

# Ground Truth

Ground Truth is the expected content for one Database document. PressRoom keeps it per document and append-only: manual upload and accepted results create a new version instead of changing an older record.

## Prerequisites

- A Database with at least one uploaded document
- `ground_truth.view` to inspect Ground Truth
- `Owner`, `Admin`, or `Editor` to upload or review Ground Truth
- A `.json` file; the current UI reads and stores its contents as text and does not validate JSON syntax

## Add Ground Truth manually

1. Open the Database.
2. Select **Ground Truth**.
3. Select the document using the radio control.
4. Select **Upload GT**.
5. Choose a `.json` file containing the expected output.

The current UI accepts the `.json` extension, reads the file as text, and creates a new Ground Truth version with `json` format and `manual` source. Neither the UI nor this endpoint currently rejects invalid JSON syntax, so validate the file separately when structured display matters.

Use the same output shape you expect from the workflow. For example:

```json
{
  "invoice_number": "<expected-number>",
  "currency": "<expected-currency>",
  "total": "<expected-total>"
}
```

Use placeholders in public examples and synthetic data in shared fixtures. Ground Truth is application data and may contain sensitive document content.

## Inspect document versions

You can inspect Ground Truth from two places:

- **Ground Truth** summarizes approved, pending, and missing documents.
- Selecting a document under **Documents** opens its Ground Truth tab with the current version, source, format, timestamp, notes, content, and version history.

Selecting a historical version is read-only. The current marker identifies the newest version used for future comparisons.

## Compare an evaluation result

1. Run a saved workflow over documents in the Database.
2. Open **Runs** and select the completed run.
3. Select a document result.
4. Review **Original / Ground Truth** beside **OCR Output**. The actual-output column currently keeps that label even for a non-OCR workflow.

PressRoom records whether comparable content matched or mismatched. If Ground Truth is absent, the result is `No GT`; it is not treated as a failure or a pass.

## Accept output as a new version

Select **Accept as Ground Truth** when the actual result is correct and should become the new expected content.

PressRoom:

1. creates a new Ground Truth version from the result's output content and format;
2. links it to the source task run;
3. marks the evaluation result accepted;
4. records the comparison as matched for that reviewed result.

The previous Ground Truth remains in version history.

## Reject output

Select **Reject** when the actual result should not become Ground Truth. The current UI records the rejected review status without asking for a reason, and it does not delete or replace the current Ground Truth.

Fix the workflow or Provider configuration, run again, and compare the new result.

## Versioning practices

- Treat manual Ground Truth as reviewed data, not an arbitrary expected string.
- Keep output formats consistent across versions of a document.
- Review the full actual content before accepting it.
- Name evaluation runs so the source of an accepted version is understandable.
- Preserve a deterministic document set while comparing model or workflow changes.
- Export or back up application data according to your retention policy; version history is not a substitute for infrastructure backup.

## Verify success

- After a successful upload, reload or re-enter the Database because the current Ground Truth view does not refresh itself automatically; the document should then change from missing to approved.
- The document panel shows a current version and the stored content; valid JSON is formatted for readability.
- A new manual upload increments the version rather than overwriting history.
- An evaluation result with Ground Truth shows matched or mismatched content.
- Accepting a reviewed output adds a version linked to the run.
- Rejecting leaves the current Ground Truth unchanged.

## Troubleshooting

### Upload GT asks you to select a document

Choose one document in the Ground Truth table before selecting **Upload GT**.

### JSON is displayed as a single line or plain text

The upload path does not validate JSON syntax. Validate the file before upload if structured content is required. The document panel pretty-prints content only when the stored format includes `json` and parsing succeeds; otherwise it displays the stored text.

### A comparison is unavailable

Confirm the workflow result completed and both expected and actual content are present. A failed/skipped execution or missing Ground Truth cannot produce a content comparison.

### Accept and Reject are unavailable

Your role needs `ground_truth.accept_reject`. Owners, Admins, and Editors have this capability; Runners and Viewers do not.

### The current version looks unexpected

Open version history and inspect source and timestamp. A manual upload and every accepted run append a version; the newest version becomes current.

## Next steps

- [Run another Database baseline](/evaluation/databases)
- [Tune workflow execution and results](/workflows/run-and-results)
- [Review workspace roles and security](/administration/security-and-troubleshooting)
