import "@testing-library/jest-dom/vitest";
import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import { beforeEach, describe, expect, it, vi } from "vitest";

const api = vi.hoisted(() => ({
  activate: vi.fn(), archive: vi.fn(), create: vi.fn(), deleteArchived: vi.fn(),
  get: vi.fn(), getCurrent: vi.fn(), list: vi.fn(), pause: vi.fn(),
  suspend: vi.fn(), unarchive: vi.fn(),
}));
const preference = vi.hoisted(() => ({ enabled: true }));
const scope = vi.hoisted(() => ({
  authStatus: "authenticated", userId: "user-1" as string | null,
  workspaceId: "workspace-1" as string | null,
}));

vi.mock("@/services/chatboxApi", () => ({
  activateChatboxSession: api.activate,
  archiveChatboxSession: api.archive,
  createChatboxSession: api.create,
  deleteArchivedChatboxSession: api.deleteArchived,
  getChatboxSession: api.get,
  getCurrentChatboxSession: api.getCurrent,
  listChatboxSessions: api.list,
  pauseChatboxSession: api.pause,
  suspendChatboxSession: api.suspend,
  unarchiveChatboxSession: api.unarchive,
}));
vi.mock("@/features/chatbox/chatboxPreferenceStore", () => ({ useExperimentalChatboxEnabled: () => preference.enabled }));
vi.mock("@/stores/authStore", () => ({
  useAuthStore: (selector: (state: unknown) => unknown) => selector({
    status: scope.authStatus,
    currentUser: scope.userId === null ? null : { id: scope.userId },
  }),
}));
vi.mock("@/stores/workspaceStore", () => ({
  useWorkspaceStore: (selector: (state: unknown) => unknown) => selector({
    currentWorkspace: scope.workspaceId === null ? null : { id: scope.workspaceId },
  }),
}));
vi.mock("@/features/chatbox/ChatboxLauncher", () => ({
  ChatboxLauncher: ({ onOpen }: { readonly onOpen: () => void }) => <button onClick={onOpen}>Open chatbox</button>,
}));
vi.mock("@/features/chatbox/ChatboxPanel", () => ({
  ChatboxPanel: (props: {
    readonly archivedSessions: readonly { readonly session_id: string }[];
    readonly onArchive: () => void;
    readonly onDeleteArchived: (sessionId: string) => void;
    readonly onNewConversation: () => void;
    readonly onSelectSession: (sessionId: string) => void;
    readonly onStartConversation: (prompt: string) => void;
    readonly onUnarchive: (sessionId: string, open: boolean) => void;
    readonly open: boolean;
    readonly refreshError: boolean;
    readonly runtimeEnabled: boolean;
    readonly sessionId: string | null;
    readonly sessions: readonly { readonly session_id: string }[];
    readonly sessionStatus: string;
  }) => props.open ? (
    <div data-testid="panel">
      <span data-testid="status">{props.sessionStatus}</span>
      <span data-testid="session">{props.sessionId}</span>
      <span data-testid="runtime-enabled">{String(props.runtimeEnabled)}</span>
      <span data-testid="refresh-error">{String(props.refreshError)}</span>
      <button onClick={() => props.onStartConversation("list workflows")}>Send first</button>
      <button onClick={props.onNewConversation}>New</button>
      <button onClick={props.onArchive}>Archive</button>
      <button onClick={() => props.onSelectSession("session-other")}>Select</button>
      <button onClick={() => props.onUnarchive("session-archived", true)}>Unarchive</button>
      <button onClick={() => props.onDeleteArchived("session-archived")}>Delete</button>
    </div>
  ) : null,
}));

import { ChatboxShell } from "@/features/chatbox/ChatboxShell";

const session = (id: string, state = "active") => ({
  session_id: id, session_state: state, runtime_generation: 1,
});

function deferred<T>() {
  let resolve!: (value: T) => void;
  let reject!: (reason?: unknown) => void;
  const promise = new Promise<T>((promiseResolve, promiseReject) => {
    resolve = promiseResolve;
    reject = promiseReject;
  });
  return { promise, reject, resolve };
}

describe("ChatboxShell", () => {
  beforeEach(() => {
    vi.clearAllMocks();
    window.sessionStorage.clear();
    preference.enabled = true;
    scope.authStatus = "authenticated";
    scope.userId = "user-1";
    scope.workspaceId = "workspace-1";
    api.getCurrent.mockResolvedValue(null);
    api.list.mockResolvedValue({ items: [], total: 0, current_session_id: null });
    api.pause.mockResolvedValue(session("paused", "paused"));
    api.suspend.mockResolvedValue(session("suspended", "paused"));
    api.archive.mockResolvedValue(session("archived", "archived"));
    api.deleteArchived.mockResolvedValue({ success: true });
  });

  it("does not render while the experiment is disabled", () => {
    preference.enabled = false;
    render(<ChatboxShell />);
    expect(screen.queryByRole("button", { name: "Open chatbox" })).not.toBeInTheDocument();
  });

  it("opens an ephemeral blank conversation without creating a database Session", async () => {
    render(<ChatboxShell />);
    fireEvent.click(screen.getByRole("button", { name: "Open chatbox" }));
    await waitFor(() => expect(screen.getByTestId("status")).toHaveTextContent("ready"));
    expect(screen.getByTestId("session")).toBeEmptyDOMElement();
    expect(api.create).not.toHaveBeenCalled();
    expect(api.list).toHaveBeenCalledWith("conversations");
    expect(api.list).toHaveBeenCalledWith("archived");
  });

  it("creates the durable Session on the first send", async () => {
    api.create.mockResolvedValue(session("session-created"));
    render(<ChatboxShell />);
    fireEvent.click(screen.getByRole("button", { name: "Open chatbox" }));
    await waitFor(() => expect(screen.getByTestId("status")).toHaveTextContent("ready"));
    fireEvent.click(screen.getByRole("button", { name: "Send first" }));
    await waitFor(() => expect(screen.getByTestId("session")).toHaveTextContent("session-created"));
    expect(api.create).toHaveBeenCalledTimes(1);
  });

  it("restores and activates the server-selected paused Session", async () => {
    api.getCurrent.mockResolvedValue(session("session-paused", "paused"));
    api.activate.mockResolvedValue(session("session-paused"));
    render(<ChatboxShell />);
    fireEvent.click(screen.getByRole("button", { name: "Open chatbox" }));
    await waitFor(() => expect(api.activate).toHaveBeenCalledWith("session-paused"));
    expect(screen.getByTestId("session")).toHaveTextContent("session-paused");
    expect(api.create).not.toHaveBeenCalled();
  });

  it("renders the target history before activation without enabling its Runtime", async () => {
    const activation = deferred<ReturnType<typeof session>>();
    api.getCurrent.mockResolvedValue(session("session-current"));
    api.list.mockImplementation((view: string) => Promise.resolve({
      items: view === "conversations"
        ? [session("session-current"), session("session-other", "paused")]
        : [],
      total: view === "conversations" ? 2 : 0,
      current_session_id: "session-current",
    }));
    api.activate.mockReturnValue(activation.promise);
    render(<ChatboxShell />);
    fireEvent.click(screen.getByRole("button", { name: "Open chatbox" }));
    await waitFor(() => expect(screen.getByTestId("session")).toHaveTextContent("session-current"));
    expect(screen.getByTestId("runtime-enabled")).toHaveTextContent("true");

    fireEvent.click(screen.getByRole("button", { name: "Select" }));

    await waitFor(() => expect(screen.getByTestId("session")).toHaveTextContent("session-other"));
    expect(screen.getByTestId("runtime-enabled")).toHaveTextContent("false");
    activation.resolve(session("session-other"));
    await waitFor(() => expect(screen.getByTestId("runtime-enabled")).toHaveTextContent("true"));
  });

  it("restores the previous Session transport when activation fails", async () => {
    api.getCurrent.mockResolvedValue(session("session-current"));
    api.list.mockImplementation((view: string) => Promise.resolve({
      items: view === "conversations"
        ? [session("session-current"), session("session-other", "paused")]
        : [],
      total: view === "conversations" ? 2 : 0,
      current_session_id: "session-current",
    }));
    api.activate.mockRejectedValue(new Error("activation failed"));
    render(<ChatboxShell />);
    fireEvent.click(screen.getByRole("button", { name: "Open chatbox" }));
    await waitFor(() => expect(screen.getByTestId("session")).toHaveTextContent("session-current"));

    fireEvent.click(screen.getByRole("button", { name: "Select" }));

    await waitFor(() => expect(screen.getByTestId("refresh-error")).toHaveTextContent("true"));
    expect(screen.getByTestId("session")).toHaveTextContent("session-current");
    expect(screen.getByTestId("runtime-enabled")).toHaveTextContent("true");
  });

  it("keeps the activated Session transport when only list refresh fails", async () => {
    let listCalls = 0;
    api.getCurrent.mockResolvedValue(session("session-current"));
    api.list.mockImplementation((view: string) => {
      listCalls += 1;
      if (listCalls > 2) return Promise.reject(new Error("list refresh failed"));
      return Promise.resolve({
        items: view === "conversations"
          ? [session("session-current"), session("session-other", "paused")]
          : [],
        total: view === "conversations" ? 2 : 0,
        current_session_id: "session-current",
      });
    });
    api.activate.mockResolvedValue(session("session-other"));
    render(<ChatboxShell />);
    fireEvent.click(screen.getByRole("button", { name: "Open chatbox" }));
    await waitFor(() => expect(screen.getByTestId("session")).toHaveTextContent("session-current"));

    fireEvent.click(screen.getByRole("button", { name: "Select" }));

    await waitFor(() => expect(screen.getByTestId("refresh-error")).toHaveTextContent("true"));
    expect(screen.getByTestId("session")).toHaveTextContent("session-other");
    expect(screen.getByTestId("runtime-enabled")).toHaveTextContent("true");
  });

  it("pauses the current Session and returns to blank for New Conversation", async () => {
    api.getCurrent.mockResolvedValue(session("session-current"));
    render(<ChatboxShell />);
    fireEvent.click(screen.getByRole("button", { name: "Open chatbox" }));
    await waitFor(() => expect(screen.getByTestId("session")).toHaveTextContent("session-current"));
    fireEvent.click(screen.getByRole("button", { name: "New" }));
    await waitFor(() => expect(api.pause).toHaveBeenCalledWith("session-current"));
    expect(screen.getByTestId("session")).toBeEmptyDOMElement();
    expect(api.create).not.toHaveBeenCalled();
  });

  it("archives without creating a replacement Session", async () => {
    api.getCurrent.mockResolvedValue(session("session-current"));
    render(<ChatboxShell />);
    fireEvent.click(screen.getByRole("button", { name: "Open chatbox" }));
    await waitFor(() => expect(screen.getByTestId("session")).toHaveTextContent("session-current"));
    fireEvent.click(screen.getByRole("button", { name: "Archive" }));
    await waitFor(() => expect(api.archive).toHaveBeenCalledWith("session-current"));
    expect(screen.getByTestId("session")).toBeEmptyDOMElement();
    expect(api.create).not.toHaveBeenCalled();
  });

  it("delegates Unarchive-and-open and permanent Delete", async () => {
    api.unarchive.mockResolvedValue(session("session-archived"));
    render(<ChatboxShell />);
    fireEvent.click(screen.getByRole("button", { name: "Open chatbox" }));
    await waitFor(() => expect(screen.getByTestId("status")).toHaveTextContent("ready"));
    fireEvent.click(screen.getByRole("button", { name: "Unarchive" }));
    await waitFor(() => expect(api.unarchive).toHaveBeenCalledWith("session-archived", true));
    expect(screen.getByTestId("session")).toHaveTextContent("session-archived");
    fireEvent.click(screen.getByRole("button", { name: "Delete" }));
    await waitFor(() => expect(api.deleteArchived).toHaveBeenCalledWith("session-archived"));
  });

  it("suspends the old workspace Session when the workspace changes", async () => {
    api.getCurrent.mockResolvedValue(session("session-current"));
    const view = render(<ChatboxShell />);
    fireEvent.click(screen.getByRole("button", { name: "Open chatbox" }));
    await waitFor(() => expect(screen.getByTestId("session")).toHaveTextContent("session-current"));
    scope.workspaceId = "workspace-2";
    api.getCurrent.mockResolvedValue(null);
    view.rerender(<ChatboxShell />);
    await waitFor(() => expect(api.suspend).toHaveBeenCalledWith("session-current", "workspace-1"));
  });
});
