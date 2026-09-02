import { useCallback, useEffect, useReducer, useRef, useState } from "react";

import { generateChatboxId } from "@/features/chatbox/chatboxId";
import { assemblePiEvent, initialPiAssemblerState, parsePiEvent, resetPiAssembler, type PiAssemblerState, type PiEvent } from "@/features/chatbox/piEventAssembler";
import {
  chatboxSessionWebSocketPath,
  getChatboxSession,
  type ChatboxSession,
  type ChatboxLifecycleState,
} from "@/services/chatboxApi";
import { buildWorkspaceScopedUrl } from "@/services/workspaceTransport";

interface UseChatboxSessionOptions {
  readonly sessionId: string;
  readonly enabled: boolean;
  readonly initialSession?: ChatboxSession;
}
type Action = { readonly kind: "event"; readonly event: PiEvent } | { readonly kind: "reset"; readonly state: PiAssemblerState };
export type ChatboxRuntimeStatus = "loading-history" | "restoring-runtime" | "ready" | "restore-failed";
const reconnectDelays = [1000, 2000, 5000] as const;
const MAX_RECONNECT_ATTEMPTS = 5;
const RECONNECT_STABILITY_MS = 30_000;

function reducer(state: PiAssemblerState, action: Action): PiAssemblerState {
  return action.kind === "event" ? assemblePiEvent(state, action.event) : action.state;
}

function runningStateFromLifecycle(state: ChatboxLifecycleState): PiAssemblerState["runningState"] {
  return state === "active" ? "working" : "idle";
}

function stateFromSession(session: ChatboxSession): PiAssemblerState {
  return resetPiAssembler(
    session.messages,
    runningStateFromLifecycle(session.state),
    session.tool_executions,
    session.compaction_notes,
    session.live_message_id,
  );
}

export function useChatboxSession({ sessionId, enabled, initialSession }: UseChatboxSessionOptions) {
  const [state, dispatch] = useReducer(reducer, initialPiAssemblerState);
  const [connected, setConnected] = useState(false);
  const [runtimeStatus, setRuntimeStatus] = useState<ChatboxRuntimeStatus>("loading-history");
  const [requiresRefresh, setRequiresRefresh] = useState(false);
  const [accessUnavailable, setAccessUnavailable] = useState(false);
  const socketRef = useRef<WebSocket | null>(null);
  const runtimeReadyRef = useRef(false);
  const initialSessionRef = useRef(initialSession);
  if (initialSession?.session_id === sessionId) initialSessionRef.current = initialSession;

  useEffect(() => {
    setConnected(false);
    runtimeReadyRef.current = false;
    setRuntimeStatus("loading-history");
    setRequiresRefresh(false);
    setAccessUnavailable(false);
    const initialSnapshot = initialSessionRef.current;
    if (initialSnapshot?.session_id === sessionId) {
      dispatch({ kind: "reset", state: stateFromSession(initialSnapshot) });
      setRuntimeStatus("restoring-runtime");
    }
    if (!enabled) return;
    let disposed = false;
    let reconnectTimer: number | null = null;
    let stabilityTimer: number | null = null;
    let reconnectAttempts = 0;
    let activeSocket: WebSocket | null = null;

    function clearReconnect(): void {
      if (reconnectTimer === null) return;
      window.clearTimeout(reconnectTimer);
      reconnectTimer = null;
    }

    function clearStabilityTimer(): void {
      if (stabilityTimer === null) return;
      window.clearTimeout(stabilityTimer);
      stabilityTimer = null;
    }

    function closeSocket(): void {
      const socket = activeSocket;
      activeSocket = null;
      clearStabilityTimer();
      if (socket === null) return;
      socket.onclose = null;
      socket.close();
      if (socketRef.current === socket) socketRef.current = null;
    }

    function scheduleReconnect(): void {
      if (
        disposed
        || reconnectTimer !== null
        || reconnectAttempts >= MAX_RECONNECT_ATTEMPTS
      ) return;
      const delay = reconnectDelays[Math.min(reconnectAttempts, reconnectDelays.length - 1)];
      reconnectAttempts += 1;
      reconnectTimer = window.setTimeout(() => {
        reconnectTimer = null;
        void reloadAndConnect();
      }, delay);
    }

    function connect(snapshotRevision: number): void {
      if (disposed) return;
      try {
        const protocol = window.location.protocol === "https:" ? "wss:" : "ws:";
        const path = buildWorkspaceScopedUrl(chatboxSessionWebSocketPath(sessionId));
        const url = new URL(path, window.location.origin);
        url.protocol = protocol;
        url.searchParams.set("after_revision", String(snapshotRevision));
        const socket = new WebSocket(url);
        activeSocket = socket;
        socketRef.current = socket;
        socket.onopen = () => {
          if (disposed || activeSocket !== socket) return;
          setRuntimeStatus("restoring-runtime");
          clearStabilityTimer();
          stabilityTimer = window.setTimeout(() => {
            stabilityTimer = null;
            if (!disposed && activeSocket === socket) reconnectAttempts = 0;
          }, RECONNECT_STABILITY_MS);
        };
        // Frames can contain user prompts or model output. Malformed and
        // forward-compatible event types are intentionally dropped without
        // writing their raw payloads to production browser logs.
        socket.onmessage = (message) => {
          if (disposed || typeof message.data !== "string") return;
          try {
            const parsed: unknown = JSON.parse(message.data);
            if (
              typeof parsed === "object"
              && parsed !== null
              && "type" in parsed
              && parsed.type === "runtime_status"
              && "status" in parsed
            ) {
              if (parsed.status === "ready") {
                runtimeReadyRef.current = true;
                setConnected(true);
                setRuntimeStatus("ready");
              } else if (parsed.status === "restoring") {
                runtimeReadyRef.current = false;
                setConnected(false);
                setRuntimeStatus("restoring-runtime");
              } else if (parsed.status === "failed") {
                runtimeReadyRef.current = false;
                setConnected(false);
                setRuntimeStatus("restore-failed");
              }
              return;
            }
            const event = parsePiEvent(parsed);
            if (event !== null) dispatch({ kind: "event", event });
          } catch {
            return;
          }
        };
        socket.onclose = (event) => {
          clearStabilityTimer();
          if (activeSocket === socket) {
            activeSocket = null;
            socketRef.current = null;
            runtimeReadyRef.current = false;
            setConnected(false);
            setRuntimeStatus("restore-failed");
          }
          if (disposed) return;
          if (event.code === 1000) {
            setRequiresRefresh(true);
            clearReconnect();
            return;
          }
          if (event.code === 1008) {
            // Authentication and workspace-policy changes are owned by the
            // surrounding app shell; Refresh cannot repair them.
            setAccessUnavailable(true);
            clearReconnect();
            return;
          }
          scheduleReconnect();
        };
      } catch {
        setConnected(false);
        scheduleReconnect();
      }
    }

    async function reloadAndConnect(): Promise<void> {
      try {
        const session = await getChatboxSession(sessionId);
        if (disposed) return;
        // The server snapshot is authoritative. The client never creates local Pi
        // events while disconnected, so replacing state cannot drop unsent work.
        dispatch({
          kind: "reset",
          state: stateFromSession(session),
        });
        setRuntimeStatus("restoring-runtime");
        if (session.state === "dead") {
          setConnected(false);
          setRuntimeStatus("restore-failed");
          setRequiresRefresh(true);
          clearReconnect();
          closeSocket();
          return;
        }
        setRequiresRefresh(false);
        setAccessUnavailable(false);
        connect(session.snapshot_revision ?? 0);
      } catch {
        if (!disposed) {
          setRuntimeStatus("restore-failed");
          scheduleReconnect();
        }
      }
    }

    void reloadAndConnect();
    return () => {
      disposed = true;
      clearReconnect();
      clearStabilityTimer();
      closeSocket();
    };
  }, [enabled, sessionId]);

  const send = useCallback((promptText: string): boolean => {
    const socket = socketRef.current;
    if (socket?.readyState !== WebSocket.OPEN || !runtimeReadyRef.current || !promptText.trim()) return false;
    try {
      socket.send(JSON.stringify({
        type: "prompt",
        id: generateChatboxId("prompt"),
        message: promptText,
      }));
      return true;
    } catch {
      return false;
    }
  }, []);
  const abort = useCallback((): boolean => {
    const socket = socketRef.current;
    if (socket?.readyState !== WebSocket.OPEN) return false;
    try {
      socket.send(JSON.stringify({ type: "abort", id: generateChatboxId("abort") }));
      return true;
    } catch {
      return false;
    }
  }, []);
  return {
    messages: state.messages,
    runningState: state.runningState,
    toolExecutions: state.toolExecutions,
    compactionNotes: state.compactionNotes,
    connected,
    runtimeStatus,
    requiresRefresh,
    accessUnavailable,
    send,
    abort,
  };
}
