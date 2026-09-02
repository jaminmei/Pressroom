import "@testing-library/jest-dom/vitest";
import { fireEvent, render, screen } from "@testing-library/react";
import { describe, expect, it } from "vitest";

import { BashToolRenderer } from "@/features/chatbox/toolRenderers/BashToolRenderer";
import { EditToolRenderer, ReadToolRenderer, WriteToolRenderer } from "@/features/chatbox/toolRenderers/FileToolRenderers";
import { PressroomToolRenderer } from "@/features/chatbox/toolRenderers/PressroomToolRenderer";
import { QueryToolRenderer } from "@/features/chatbox/toolRenderers/QueryToolRenderers";
import { UnknownToolRenderer } from "@/features/chatbox/toolRenderers/UnknownToolRenderer";
import { getToolRenderer, toolRendererRegistry } from "@/features/chatbox/toolRenderers/registry";
import { ToolCard } from "@/features/chatbox/toolRenderers/ToolCard";
import type { ToolExecution } from "@/features/chatbox/piEventAssembler";
import type { ToolExecutionView } from "@/features/chatbox/toolRenderers/types";
import {
  payloadText,
  payloadTruncation,
  toToolExecutionView,
  truncateToolPreview,
} from "@/features/chatbox/toolRenderers/types";

function view(exec: ToolExecution): ToolExecutionView {
  return toToolExecutionView(exec);
}

const pendingExec: ToolExecution = { toolCallId: "t1", toolName: "bash", args: { command: "npm test" } };
const successExec: ToolExecution = {
  toolCallId: "t2",
  toolName: "bash",
  args: { command: "ls -la" },
  result: { content: [{ type: "text", text: "total 0" }] },
  isError: false
};
const errorExec: ToolExecution = {
  toolCallId: "t3",
  toolName: "bash",
  args: { command: "exit 1" },
  result: { content: [{ type: "text", text: "Command exited with code 1" }] },
  isError: true
};

describe("ToolCard", () => {
  it("collapses the body by default and expands on toggle", () => {
    render(<ToolCard forceExpand={false} status="success" title="bash ls">body</ToolCard>);
    expect(screen.queryByTestId("chatbox-tool-body")).not.toBeInTheDocument();
    fireEvent.click(screen.getByRole("button", { name: "Toggle tool result" }));
    expect(screen.getByTestId("chatbox-tool-body")).toBeInTheDocument();
  });

  it("shows the body when forceExpand is set", () => {
    render(<ToolCard forceExpand status="pending" title="bash npm test">body</ToolCard>);
    expect(screen.getByTestId("chatbox-tool-body")).toBeInTheDocument();
  });
});

describe("BashToolRenderer", () => {
  it("renders command and collapsed result with status", () => {
    render(<BashToolRenderer exec={view(successExec)} forceExpand={false} />);
    expect(screen.getByText(/Bash ls -la/)).toBeInTheDocument();
    expect(screen.getByText("Done")).toBeInTheDocument();
    expect(screen.queryByTestId("chatbox-tool-body")).not.toBeInTheDocument();
  });

  it("shows live output while pending", () => {
    const pending = { ...pendingExec, partialResult: { content: [{ type: "text", text: "building..." }] } };
    render(<BashToolRenderer exec={view(pending)} forceExpand />);
    expect(screen.getByTestId("chatbox-bash-live")).toHaveTextContent("building...");
    expect(screen.queryByTestId("chatbox-bash-output")).not.toBeInTheDocument();
    expect(screen.getAllByText("building...")).toHaveLength(1);
    expect(screen.getByText("Running")).toBeInTheDocument();
  });

  it("shares truncation metadata, including the full output path", () => {
    const exec: ToolExecution = {
      ...successExec,
      result: {
        content: [{ type: "text", text: "partial" }],
        details: {
          truncation: { truncated: true },
          fullOutputPath: "artifacts/bash-output.txt",
        },
      },
    };

    render(<BashToolRenderer exec={view(exec)} forceExpand={false} />);
    expect(screen.getByText("Truncated")).toBeInTheDocument();
    expect(screen.getByText("artifacts/bash-output.txt")).toBeInTheDocument();
  });

  it("marks error results", () => {
    render(<BashToolRenderer exec={view(errorExec)} forceExpand />);
    expect(screen.getByText("Error")).toBeInTheDocument();
    expect(screen.getByTestId("chatbox-bash-output")).toHaveTextContent("Command exited with code 1");
  });

  it("normalizes and truncates multiline commands in the title", () => {
    const exec: ToolExecution = {
      ...pendingExec,
      args: { command: `npm test\n${"x".repeat(80)}` },
    };
    render(<BashToolRenderer exec={view(exec)} forceExpand={false} />);

    const title = document.querySelector(".chatbox-tool-card-title");
    expect(title).toHaveTextContent(/^Bash npm test x+\.\.\.$/);
    expect(title?.textContent).not.toContain("\n");
    expect(title?.textContent?.length).toBeLessThanOrEqual(68);
  });
});

describe("ReadToolRenderer", () => {
  it("renders path, range, content, and truncation tag", () => {
    const exec: ToolExecution = {
      toolCallId: "r1",
      toolName: "read",
      args: { path: "src/app.ts", offset: 10, limit: 20 },
      result: {
        content: [{ type: "text", text: "export {}" }],
        details: { truncation: { truncated: true, truncatedBy: "lines" }, fullOutputPath: "/tmp/full" }
      },
      isError: false
    };
    render(<ReadToolRenderer exec={view(exec)} forceExpand />);
    expect(screen.getByText(/Read src\/app\.ts/)).toBeInTheDocument();
    expect(screen.getByText("Truncated")).toBeInTheDocument();
    expect(screen.getByTestId("chatbox-tool-body")).toHaveTextContent("export {}");
  });

  it("localizes open-ended read ranges without inventing a zero offset", () => {
    const onlyLimit = view({
      toolCallId: "r-limit",
      toolName: "read",
      args: { path: "src/app.ts", limit: 20 },
    });
    const rendered = render(<ReadToolRenderer exec={onlyLimit} forceExpand={false} />);
    expect(document.querySelector(".chatbox-tool-card-title")).toHaveTextContent(
      "(up to 20 lines)",
    );

    rendered.rerender(<ReadToolRenderer exec={view({
      toolCallId: "r-offset",
      toolName: "read",
      args: { path: "src/app.ts", offset: 10 },
    })} forceExpand={false} />);
    expect(document.querySelector(".chatbox-tool-card-title")).toHaveTextContent(
      "(from line 10)",
    );
  });
});

describe("EditToolRenderer", () => {
  it("renders the unified diff with add and del lines", () => {
    const exec: ToolExecution = {
      toolCallId: "e1",
      toolName: "edit",
      args: { path: "a.ts" },
      result: { content: [], details: { diff: "-old\n+new\n ctx" } },
      isError: false
    };
    render(<EditToolRenderer exec={view(exec)} forceExpand />);
    expect(screen.getByTestId("chatbox-edit-diff")).toHaveTextContent("+new");
    expect(document.querySelector(".chatbox-diff-add")).not.toBeNull();
    expect(document.querySelector(".chatbox-diff-del")).not.toBeNull();
    expect(document.querySelector(".chatbox-diff-add")).toHaveTextContent(/^\+new$/);
  });

  it("bounds large diff previews before creating line nodes", () => {
    const exec: ToolExecution = {
      toolCallId: "e-large",
      toolName: "edit",
      args: { path: "large.ts" },
      result: {
        content: [],
        details: { diff: `-old\n+${"a".repeat(16_000)}TAIL` },
      },
      isError: false,
    };

    render(<EditToolRenderer exec={view(exec)} forceExpand />);
    expect(screen.getByTestId("chatbox-edit-diff")).not.toHaveTextContent("TAIL");
    expect(screen.getByTestId("chatbox-edit-diff")).toHaveTextContent(/more characters/);
  });
});

describe("WriteToolRenderer", () => {
  it("renders path and content preview", () => {
    const exec: ToolExecution = {
      toolCallId: "w1",
      toolName: "write",
      args: { path: "out.md", content: "# hello" },
      result: { content: [{ type: "text", text: "ok" }] },
      isError: false
    };
    render(<WriteToolRenderer exec={view(exec)} forceExpand />);
    expect(screen.getByText(/Write out\.md/)).toBeInTheDocument();
    expect(screen.getByTestId("chatbox-tool-body")).toHaveTextContent("# hello");
  });

  it("preserves an intentionally empty content preview", () => {
    const exec: ToolExecution = {
      toolCallId: "w2",
      toolName: "write",
      args: { path: "empty.txt", content: "" },
      result: { content: [{ type: "text", text: "ok" }] },
      isError: false,
    };
    render(<WriteToolRenderer exec={view(exec)} forceExpand />);
    expect(screen.getByTestId("chatbox-tool-body")).not.toHaveTextContent("ok");
  });

  it("bounds large write previews", () => {
    const exec: ToolExecution = {
      toolCallId: "w-large",
      toolName: "write",
      args: { path: "large.txt", content: `${"a".repeat(16_000)}TAIL` },
    };

    render(<WriteToolRenderer exec={view(exec)} forceExpand />);
    expect(screen.getByTestId("chatbox-tool-body")).not.toHaveTextContent("TAIL");
    expect(screen.getByTestId("chatbox-tool-body")).toHaveTextContent("4 more characters");
  });
});

describe("QueryToolRenderers (grep/find/ls)", () => {
  it("renders query and result with truncation", () => {
    const exec: ToolExecution = {
      toolCallId: "q1",
      toolName: "grep",
      args: { pattern: "TODO", path: "src" },
      result: {
        content: [{ type: "text", text: "src/a.ts:1:TODO fix" }],
        details: { truncation: { truncated: true, truncatedBy: "lines" } }
      },
      isError: false
    };
    render(<QueryToolRenderer exec={view(exec)} forceExpand toolLabel="Grep" />);
    expect(screen.getByText(/Grep TODO/)).toBeInTheDocument();
    expect(screen.getByText("Truncated")).toBeInTheDocument();
    expect(screen.getByTestId("chatbox-tool-body")).toHaveTextContent("TODO fix");
  });

  it("does not treat an explicit false result limit as truncation", () => {
    const exec: ToolExecution = {
      toolCallId: "q2",
      toolName: "find",
      args: { pattern: "*.ts" },
      result: {
        content: [{ type: "text", text: "src/a.ts" }],
        details: { resultLimitReached: false },
      },
      isError: false,
    };
    render(<QueryToolRenderer exec={view(exec)} forceExpand toolLabel="Find" />);
    expect(screen.queryByText("Truncated")).not.toBeInTheDocument();
  });

  it("does not add trailing whitespace when a query is empty", () => {
    const exec: ToolExecution = {
      toolCallId: "q3",
      toolName: "ls",
      args: {},
    };
    render(<QueryToolRenderer exec={view(exec)} forceExpand={false} toolLabel="Ls" />);

    expect(document.querySelector(".chatbox-tool-card-title")).toHaveTextContent(/^Ls$/);
  });

  it("bounds large query-result previews", () => {
    render(<QueryToolRenderer exec={view({
      toolCallId: "q-large",
      toolName: "grep",
      args: { pattern: "needle" },
      result: {
        content: [{ type: "text", text: `${"a".repeat(16_000)}TAIL` }],
      },
      isError: false,
    })} forceExpand toolLabel="Grep" />);

    expect(screen.getByTestId("chatbox-tool-body")).not.toHaveTextContent("TAIL");
    expect(screen.getByTestId("chatbox-tool-body")).toHaveTextContent("4 more characters");
  });

  it("uses shared truncation metadata from partial query results", () => {
    render(<QueryToolRenderer exec={view({
      toolCallId: "q-partial",
      toolName: "find",
      args: { pattern: "*.ts" },
      partialResult: {
        content: [{ type: "text", text: "src/a.ts" }],
        details: {
          fullOutputPath: "/tmp/full-output.txt",
          resultLimitReached: 1,
        },
      },
    })} forceExpand toolLabel="Find" />);

    expect(screen.getByText("Truncated")).toBeInTheDocument();
    expect(screen.getByText("/tmp/full-output.txt")).toBeInTheDocument();
  });
});

describe("tool result parsing", () => {
  it("does not treat array arguments as a record", () => {
    expect(view({ toolCallId: "array-args", toolName: "read", args: [] }).args).toBeNull();
  });

  it("does not split a Unicode surrogate pair at the preview boundary", () => {
    const prefix = "a".repeat(15_999);
    const preview = truncateToolPreview(`${prefix}😀TAIL`);

    expect(preview.text).toBe(prefix);
    expect(preview.omittedCharacters).toBe(6);
  });

  it("keeps only validated truncation fields", () => {
    const result = view({
      toolCallId: "r2",
      toolName: "read",
      result: {
        content: [],
        details: {
          fullOutputPath: "safe.txt",
          truncation: { truncated: true, truncatedBy: 42, totalLines: "many", maxBytes: 1024 },
        },
      },
      isError: false,
    }).result;

    expect(payloadTruncation(result)).toEqual({
      truncated: true,
      fullOutputPath: "safe.txt",
      maxBytes: 1024,
    });
  });

  it("does not report malformed terminal payloads as successful", () => {
    expect(view({
      toolCallId: "bad-result",
      toolName: "bash",
      result: null,
      isError: false,
    }).status).toBe("pending");
    expect(view({
      toolCallId: "failed-result",
      toolName: "bash",
      result: null,
      isError: true,
    }).status).toBe("error");
  });

  it("separates multiple text blocks", () => {
    expect(payloadText({
      content: [
        { type: "text", text: "first" },
        { type: "text", text: "second" },
      ],
    })).toBe("first\nsecond");
  });

  it("renders only allowlisted tool-result image MIME types", () => {
    const unsafe: ToolExecution = {
      toolCallId: "unsafe-image",
      toolName: "read",
      args: { path: "output" },
      result: {
        content: [{ type: "image", data: "PHNjcmlwdD4=", mimeType: "image/svg+xml" }],
      },
      isError: false,
    };
    const rendered = render(<ReadToolRenderer exec={view(unsafe)} forceExpand />);
    expect(document.querySelector(".chatbox-tool-image")).toBeNull();

    rendered.rerender(<ReadToolRenderer exec={view({
      ...unsafe,
      result: {
        content: [{ type: "image", data: "iVBORw0KGgo=", mimeType: "image/png" }],
      },
    })} forceExpand />);
    expect(document.querySelector(".chatbox-tool-image")).not.toBeNull();
  });

  it("rejects oversized base64 tool-result images", () => {
    const oversized: ToolExecution = {
      toolCallId: "oversized-image",
      toolName: "read",
      args: { path: "output" },
      result: {
        content: [{ type: "image", data: "a".repeat(10_000_001), mimeType: "image/png" }],
      },
      isError: false,
    };

    render(<ReadToolRenderer exec={view(oversized)} forceExpand />);

    expect(document.querySelector(".chatbox-tool-image")).toBeNull();
  });
});

describe("UnknownToolRenderer", () => {
  it("renders tool name, JSON arguments, and text result without executing components", () => {
    const exec: ToolExecution = {
      toolCallId: "u1",
      toolName: "deploy",
      args: { target: "prod" },
      result: { content: [{ type: "text", text: "deployed" }] },
      isError: false
    };
    render(<UnknownToolRenderer exec={view(exec)} forceExpand />);
    expect(screen.getByText(/Tool deploy/)).toBeInTheDocument();
    expect(screen.getByTestId("chatbox-unknown-args")).toHaveTextContent('"target": "prod"');
    expect(screen.getByTestId("chatbox-tool-body")).toHaveTextContent("deployed");
  });

  it("handles absent, cyclic, and oversized arguments safely", () => {
    const noArgs = render(<UnknownToolRenderer exec={view({
      toolCallId: "u-none",
      toolName: "extension",
    })} forceExpand />);
    expect(screen.getByTestId("chatbox-unknown-args")).toHaveTextContent("No arguments");

    const cyclic: Record<string, unknown> = {};
    cyclic.self = cyclic;
    noArgs.rerender(<UnknownToolRenderer exec={view({
      toolCallId: "u-cycle",
      toolName: "extension",
      args: cyclic,
    })} forceExpand />);
    expect(screen.getByTestId("chatbox-unknown-args")).toHaveTextContent("Arguments could not be displayed");

    noArgs.rerender(<UnknownToolRenderer exec={view({
      toolCallId: "u-large",
      toolName: "extension",
      args: { content: `${"a".repeat(16_000)}TAIL` },
    })} forceExpand />);
    expect(screen.getByTestId("chatbox-unknown-args")).not.toHaveTextContent("TAIL");
    expect(screen.getByTestId("chatbox-unknown-args")).toHaveTextContent(/more characters/);
  });

  it("bounds unknown-tool result previews", () => {
    render(<UnknownToolRenderer exec={view({
      toolCallId: "u-result",
      toolName: "extension",
      result: { content: [{ type: "text", text: `${"a".repeat(16_000)}TAIL` }] },
      isError: false,
    })} forceExpand />);

    expect(screen.getByTestId("chatbox-unknown-result")).not.toHaveTextContent("TAIL");
    expect(screen.getByTestId("chatbox-unknown-result")).toHaveTextContent("4 more characters");
  });
});

describe("PressroomToolRenderer", () => {
  it("renders workflow list envelopes as a structured table", () => {
    const exec: ToolExecution = {
      toolCallId: "workflow-list-1",
      toolName: "workflow_list",
      args: { page: 1 },
      result: {
        content: [],
        details: {
          schema_version: "pressroom-envelope.v1",
          ok: true,
          data: {
            data: [{
              id: "workflow-1",
              name: "Invoice OCR",
              latest_version: 3,
              updated_at: "2026-08-27T00:00:00Z",
            }],
            meta: { total: 1 },
          },
          error: null,
        },
      },
      isError: false,
    };

    render(<PressroomToolRenderer exec={view(exec)} forceExpand />);

    expect(document.querySelector(".chatbox-tool-card-title")).toHaveTextContent("List workflows");
    expect(screen.getByTestId("chatbox-pressroom-result")).toHaveTextContent("Invoice OCR");
    expect(screen.getByTestId("chatbox-pressroom-result")).toHaveTextContent("workflow-1");
    expect(screen.getByTestId("chatbox-pressroom-result")).toHaveTextContent("3");
    expect(screen.queryByText(/pressroom-envelope\.v1/)).not.toBeInTheDocument();
  });

  it("renders PressRoom errors without dumping their envelope", () => {
    render(<PressroomToolRenderer exec={view({
      toolCallId: "workflow-get-1",
      toolName: "workflow_get",
      args: { workflow_id: "workflow-missing" },
      result: {
        content: [],
        details: {
          schema_version: "pressroom-envelope.v1",
          ok: false,
          data: null,
          error: { code: "NOT_FOUND", message: "Workflow not found" },
        },
      },
      isError: true,
    })} forceExpand />);

    expect(screen.getByTestId("chatbox-pressroom-result")).toHaveTextContent("NOT_FOUND");
    expect(screen.getByTestId("chatbox-pressroom-result")).toHaveTextContent("Workflow not found");
  });
});

describe("toolRendererRegistry", () => {
  it("registers all built-in coding tools", () => {
    expect(Object.keys(toolRendererRegistry).sort()).toEqual(["bash", "edit", "find", "grep", "ls", "read", "write"]);
  });

  it("falls back to the unknown-tool renderer", () => {
    expect(getToolRenderer("read")).toBe(ReadToolRenderer);
    expect(getToolRenderer("workflow_list")).toBe(PressroomToolRenderer);
    expect(getToolRenderer("some-extension-tool")).toBe(UnknownToolRenderer);
  });
});
