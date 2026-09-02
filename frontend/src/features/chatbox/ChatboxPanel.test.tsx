import "@testing-library/jest-dom/vitest";
import { act, fireEvent, render, screen } from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

const renderMarkdown = vi.hoisted(() => vi.fn());
const useChatboxSessionOptions = vi.hoisted(() => vi.fn());
const listToolApprovals = vi.hoisted(() => vi.fn());
const decideToolApproval = vi.hoisted(() => vi.fn());

vi.mock("@/services/chatboxApi", () => ({
  listToolApprovals,
  decideToolApproval,
}));

vi.mock("react-markdown", () => ({
  default: (props: {
    readonly children: string;
    readonly rehypePlugins?: readonly unknown[];
    readonly remarkPlugins?: readonly unknown[];
  }) => {
    renderMarkdown(props);
    return <>{props.children}</>;
  },
}));

const chatboxSession = vi.hoisted(() => ({
  messages: [
    {
      id: "assistant-1",
      role: "assistant",
      content: [{ type: "thinking", thinking: "private thought" }],
    },
  ] as Array<{
    id: string;
    role: string;
    content: Array<Record<string, unknown>>;
  }>,
  runningState: "idle" as const,
  toolExecutions: {} as Record<string, {
    toolCallId: string;
    toolName: string;
    args?: unknown;
    result?: unknown;
    isError?: boolean;
  }>,
  compactionNotes: [],
  connected: true,
  runtimeStatus: "ready" as const,
  requiresRefresh: false,
  accessUnavailable: false,
  send: vi.fn(() => true),
  abort: vi.fn(() => true),
}));

vi.mock("@/features/chatbox/useChatboxSession", () => ({
  useChatboxSession: (options: unknown) => {
    useChatboxSessionOptions(options);
    return chatboxSession;
  },
}));

import { ChatboxPanel } from "@/features/chatbox/ChatboxPanel";

function renderPanel() {
  return render(
    <ChatboxPanel
      onClose={vi.fn()}
      onArchive={vi.fn()}
      onRefresh={vi.fn()}
      onRetry={vi.fn()}
      onSelectSession={vi.fn()}
      open
      refreshError={false}
      restarting={false}
      runtimeEnabled
      sessionId="session-1"
      sessions={[]}
      sessionStatus="ready"
    />,
  );
}

describe("ChatboxPanel", () => {
  beforeEach(() => {
    chatboxSession.messages = [{
      id: "assistant-1",
      role: "assistant",
      content: [{ type: "thinking", thinking: "private thought" }],
    }];
    chatboxSession.send.mockReset();
    chatboxSession.send.mockReturnValue(true);
    chatboxSession.requiresRefresh = false;
    chatboxSession.accessUnavailable = false;
    chatboxSession.toolExecutions = {};
    useChatboxSessionOptions.mockClear();
    renderMarkdown.mockClear();
    listToolApprovals.mockReset();
    listToolApprovals.mockReturnValue(new Promise(() => undefined));
    decideToolApproval.mockReset();
    decideToolApproval.mockResolvedValue({});
    document.body.style.cursor = "";
    document.body.style.userSelect = "";
  });

  afterEach(() => {
    vi.restoreAllMocks();
  });

  it("keeps message renderer state while the composer rerenders", () => {
    renderPanel();

    fireEvent.click(screen.getByRole("button", { name: "Show thinking" }));
    expect(screen.getByText("private thought")).toBeInTheDocument();

    fireEvent.change(screen.getByRole("textbox", { name: "Message the workspace assistant" }), {
      target: { value: "next prompt" },
    });
    expect(screen.getByText("private thought")).toBeInTheDocument();
  });

  it("does not send during IME composition or clear a prompt that was not sent", () => {
    renderPanel();
    const composer = screen.getByRole("textbox", { name: "Message the workspace assistant" });
    fireEvent.change(composer, { target: { value: "unfinished" } });

    fireEvent.keyDown(composer, { key: "Enter", code: "Enter", keyCode: 13, isComposing: true });
    expect(chatboxSession.send).not.toHaveBeenCalled();
    expect(composer).toHaveValue("unfinished");

    chatboxSession.send.mockReturnValueOnce(false);
    fireEvent.keyDown(composer, { key: "Enter", code: "Enter", keyCode: 13 });
    expect(chatboxSession.send).toHaveBeenCalledWith("unfinished");
    expect(composer).toHaveValue("unfinished");

    fireEvent.keyDown(composer, { key: "Enter", code: "Enter", keyCode: 13 });
    expect(composer).toHaveValue("");
  });

  it("keeps restored history visible and distinguishes a runtime restore failure", () => {
    chatboxSession.messages = [{
      id: "user-legacy",
      role: "user",
      content: [{ type: "text", text: "existing conversation" }],
    }];
    chatboxSession.requiresRefresh = true;

    renderPanel();

    expect(screen.getByText("existing conversation")).toBeInTheDocument();
    expect(screen.getByText(/Conversation history is loaded/)).toBeInTheDocument();
    expect(screen.queryByText("This runtime has ended. Start a new conversation or reopen another one."))
      .not.toBeInTheDocument();
  });

  it("renders model Markdown with the shared safety plugins", () => {
    chatboxSession.messages = [{
      id: "assistant-markdown",
      role: "assistant",
      content: [{ type: "text", text: "| A |\n| - |\n| B |" }],
    }];

    renderPanel();

    expect(renderMarkdown).toHaveBeenCalledWith(expect.objectContaining({
      rehypePlugins: expect.arrayContaining([expect.any(Function)]),
      remarkPlugins: expect.arrayContaining([expect.any(Function)]),
    }));
  });

  it("renders linked tool results once as a card and hides the global toggle otherwise", () => {
    const rawEnvelope = '{"schema_version":"pressroom-envelope.v1","ok":true}';
    chatboxSession.messages = [
      {
        id: "assistant-tool-call",
        role: "assistant",
        content: [{
          type: "toolCall",
          toolCallId: "tool-1",
          toolName: "workflow_list",
          input: {},
        }],
      },
      {
        id: "tool-result",
        role: "toolResult",
        toolCallId: "tool-1",
        content: [{ type: "text", text: rawEnvelope }],
      } as never,
    ];
    chatboxSession.toolExecutions = {
      "tool-1": {
        toolCallId: "tool-1",
        toolName: "workflow_list",
        args: {},
        result: {
          content: [],
          details: {
            schema_version: "pressroom-envelope.v1",
            ok: true,
            data: {
              data: [{ id: "workflow-1", name: "Invoice OCR", latest_version: 2 }],
            },
            error: null,
          },
        },
        isError: false,
      },
    };

    const rendered = renderPanel();

    expect(screen.getByTestId("chatbox-tool-card")).toHaveTextContent("List workflows");
    expect(screen.queryByText(rawEnvelope)).not.toBeInTheDocument();
    expect(screen.getByTestId("chatbox-expand-toggle")).toBeInTheDocument();

    chatboxSession.messages = [{
      id: "assistant-only",
      role: "assistant",
      content: [{ type: "text", text: "No tools here" }],
    }];
    chatboxSession.toolExecutions = {};
    rendered.rerender(
      <ChatboxPanel
        onClose={vi.fn()}
        onArchive={vi.fn()}
        onRefresh={vi.fn()}
        onRetry={vi.fn()}
        onSelectSession={vi.fn()}
        open
        refreshError={false}
        restarting={false}
        runtimeEnabled
        sessionId="session-1"
        sessions={[]}
        sessionStatus="ready"
      />,
    );
    expect(screen.queryByTestId("chatbox-expand-toggle")).not.toBeInTheDocument();
  });

  it("keeps unmatched legacy tool results readable", () => {
    chatboxSession.messages = [{
      id: "legacy-tool-result",
      role: "toolResult",
      toolCallId: "missing-tool-call",
      content: [{ type: "text", text: "legacy result" }],
    } as never];

    renderPanel();

    expect(screen.getByText("legacy result")).toBeInTheDocument();
    expect(screen.queryByTestId("chatbox-expand-toggle")).not.toBeInTheDocument();
  });

  it("tells the user to Refresh after the durable session ends", () => {
    chatboxSession.messages = [];
    chatboxSession.requiresRefresh = true;

    renderPanel();

    expect(screen.getByText(
      "This runtime has ended. Start a new conversation or reopen another one.",
    )).toBeInTheDocument();
  });

  it("shows an access error without offering Refresh after a policy close", () => {
    chatboxSession.messages = [];
    chatboxSession.accessUnavailable = true;

    renderPanel();

    expect(screen.getByText(
      "Access to this Chatbox session is no longer available. Check your sign-in and workspace access.",
    )).toBeInTheDocument();
    expect(screen.queryByRole("button", { name: "Refresh" })).not.toBeInTheDocument();
  });

  it("cleans up resize state when the pointer is cancelled", () => {
    renderPanel();

    fireEvent.pointerDown(screen.getByRole("button", { name: "Resize chatbox" }), {
      clientX: 200,
      clientY: 200,
    });
    expect(document.body.style.cursor).toBe("nwse-resize");
    expect(document.body.style.userSelect).toBe("none");

    fireEvent.pointerCancel(window);
    expect(document.body.style.cursor).toBe("");
    expect(document.body.style.userSelect).toBe("");
  });

  it("coalesces resize updates into animation frames", () => {
    renderPanel();
    const callbacks: FrameRequestCallback[] = [];
    const requestFrame = vi.spyOn(window, "requestAnimationFrame")
      .mockImplementation((callback) => {
        callbacks.push(callback);
        return callbacks.length;
      });

    fireEvent.pointerDown(screen.getByRole("button", { name: "Resize chatbox" }), {
      clientX: 200,
      clientY: 200,
    });
    fireEvent.pointerMove(window, { clientX: 180, clientY: 180 });
    fireEvent.pointerMove(window, { clientX: 160, clientY: 160 });
    expect(requestFrame).toHaveBeenCalledTimes(1);

    act(() => callbacks[0]?.(0));
    fireEvent.pointerMove(window, { clientX: 140, clientY: 140 });
    expect(requestFrame).toHaveBeenCalledTimes(2);
  });

  it("disables the session transport while the window is closed", () => {
    const view = renderPanel();
    expect(useChatboxSessionOptions).toHaveBeenLastCalledWith({
      enabled: true,
      initialSession: undefined,
      sessionId: "session-1",
    });

    view.rerender(
      <ChatboxPanel
        onClose={vi.fn()}
        onArchive={vi.fn()}
        onRefresh={vi.fn()}
        onRetry={vi.fn()}
        onSelectSession={vi.fn()}
        open={false}
        refreshError={false}
        restarting={false}
        runtimeEnabled
        sessionId="session-1"
        sessions={[]}
        sessionStatus="ready"
      />,
    );

    expect(useChatboxSessionOptions).toHaveBeenLastCalledWith({
      enabled: false,
      initialSession: undefined,
      sessionId: "session-1",
    });
  });

  it("keeps optimistic history visible without enabling transport before activation", () => {
    render(
      <ChatboxPanel
        onClose={vi.fn()}
        onArchive={vi.fn()}
        onRefresh={vi.fn()}
        onRetry={vi.fn()}
        onSelectSession={vi.fn()}
        open
        refreshError={false}
        restarting
        runtimeEnabled={false}
        sessionId="session-1"
        sessions={[{
          session_id: "session-1",
          messages: [{ id: "history-1", role: "assistant", content: [{ type: "text", text: "Saved history" }] }],
        } as never]}
        sessionStatus="ready"
      />,
    );

    expect(useChatboxSessionOptions).toHaveBeenLastCalledWith(expect.objectContaining({
      enabled: false,
      sessionId: "session-1",
    }));
  });

  it("renders Admission decisions as durable conversation messages", () => {
    chatboxSession.messages = [{
      id: "admission-platform-1",
      role: "platform",
      content: [{
        type: "admission",
        status: "reject_out_of_scope",
        reasonCode: "not_pressroom_scope",
      }],
    }];

    renderPanel();

    expect(screen.getByTestId("chatbox-admission-message"))
      .toHaveTextContent("outside the PressRoom workspace assistant scope");
  });

  it("follows streaming output unless the user has scrolled up", () => {
    const scrollCallbacks: FrameRequestCallback[] = [];
    vi.spyOn(window, "requestAnimationFrame").mockImplementation((callback) => {
      scrollCallbacks.push(callback);
      return scrollCallbacks.length;
    });
    const view = renderPanel();
    const messageList = screen.getByTestId("chatbox-message-list");
    let scrollHeight = 500;
    Object.defineProperties(messageList, {
      clientHeight: { configurable: true, value: 100 },
      scrollHeight: { configurable: true, get: () => scrollHeight },
    });
    act(() => scrollCallbacks.shift()?.(0));
    messageList.scrollTop = 0;

    chatboxSession.messages = [...chatboxSession.messages, {
      id: "assistant-2",
      role: "assistant",
      content: [{ type: "text", text: "latest" }],
    }];
    view.rerender(
      <ChatboxPanel
        onClose={vi.fn()}
        onArchive={vi.fn()}
        onRefresh={vi.fn()}
        onRetry={vi.fn()}
        onSelectSession={vi.fn()}
        open
        refreshError={false}
        restarting={false}
        runtimeEnabled
        sessionId="session-1"
        sessions={[]}
        sessionStatus="ready"
      />,
    );
    expect(messageList.scrollTop).toBe(0);
    act(() => scrollCallbacks.shift()?.(0));
    expect(messageList.scrollTop).toBe(500);

    messageList.scrollTop = 120;
    fireEvent.scroll(messageList);
    scrollHeight = 700;
    chatboxSession.messages = [...chatboxSession.messages, {
      id: "assistant-3",
      role: "assistant",
      content: [{ type: "text", text: "more" }],
    }];
    view.rerender(
      <ChatboxPanel
        onClose={vi.fn()}
        onArchive={vi.fn()}
        onRefresh={vi.fn()}
        onRetry={vi.fn()}
        onSelectSession={vi.fn()}
        open
        refreshError={false}
        restarting={false}
        runtimeEnabled
        sessionId="session-1"
        sessions={[]}
        sessionStatus="ready"
      />,
    );
    expect(messageList.scrollTop).toBe(120);
  });

  it("shows an argument-bound approval and submits the user's decision", async () => {
    listToolApprovals.mockResolvedValueOnce([{
      id: "approval-1",
      operation: "workflow.execute",
      argument_summary: '{"workflow_id":"workflow-1"}',
      expires_at: "2099-01-01T00:00:00Z",
    }]);

    renderPanel();

    const approval = await screen.findByTestId("chatbox-tool-approval");
    const tray = screen.getByTestId("chatbox-approval-tray");
    const composer = screen.getByRole("textbox", { name: "Message the workspace assistant" });
    expect(approval).toHaveTextContent("workflow.execute");
    expect(approval).toHaveTextContent(/Expires in \d+s/);
    expect(screen.getByTestId("chatbox-message-list")).not.toContainElement(approval);
    expect(tray.compareDocumentPosition(composer) & Node.DOCUMENT_POSITION_FOLLOWING).toBeTruthy();
    await act(async () => {
      fireEvent.click(screen.getByRole("button", { name: "Approve" }));
    });
    expect(decideToolApproval).toHaveBeenCalledWith("session-1", "approval-1", true);
  });

  it("keeps the confirmation tray visible and reports a failed decision", async () => {
    listToolApprovals.mockResolvedValueOnce([{
      id: "approval-1",
      operation: "workflow.create",
      argument_summary: '{"name":"Agent OCR test"}',
      expires_at: "2099-01-01T00:00:00Z",
    }]);
    decideToolApproval.mockRejectedValueOnce(new Error("expired"));
    listToolApprovals.mockResolvedValueOnce([]);

    renderPanel();
    await screen.findByTestId("chatbox-tool-approval");
    await act(async () => {
      fireEvent.click(screen.getByRole("button", { name: "Approve" }));
    });

    expect(screen.getByText(/approval could not be submitted/i)).toBeInTheDocument();
  });
});
