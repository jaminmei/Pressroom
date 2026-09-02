import axios from "axios";
import { useCallback, useEffect, useRef, useState } from "react";

import { ChatboxLauncher } from "@/features/chatbox/ChatboxLauncher";
import { ChatboxPanel } from "@/features/chatbox/ChatboxPanel";
import { shouldRenderChatbox } from "@/features/chatbox/chatboxAvailability";
import { useExperimentalChatboxEnabled } from "@/features/chatbox/chatboxPreferenceStore";
import {
  clearStoredChatboxSession,
  readStoredChatboxSession,
  storeChatboxSession,
} from "@/features/chatbox/chatboxSessionStore";
import {
  activateChatboxSession,
  archiveChatboxSession,
  createChatboxSession,
  deleteArchivedChatboxSession,
  getCurrentChatboxSession,
  getChatboxSession,
  listChatboxSessions,
  pauseChatboxSession,
  suspendChatboxSession,
  unarchiveChatboxSession,
  type ChatboxSession,
} from "@/services/chatboxApi";
import { useAuthStore } from "@/stores/authStore";
import { useWorkspaceStore } from "@/stores/workspaceStore";

const CHATBOX_SESSION_NOT_FOUND_STATUS = 404;
const AGENT_LLM_NOT_CONFIGURED_STATUS = 409;

interface ChatboxScope {
  readonly userId: string;
  readonly workspaceId: string;
}

export function ChatboxShell() {
  const authStatus = useAuthStore((state) => state.status);
  const userId = useAuthStore((state) => state.currentUser?.id ?? null);
  const chatboxEnabled = useExperimentalChatboxEnabled(userId);
  const workspaceId = useWorkspaceStore((state) => state.currentWorkspace?.id ?? null);
  const [sessionId, setSessionId] = useState<string | null>(null);
  const [sessions, setSessions] = useState<readonly ChatboxSession[]>([]);
  const [archivedSessions, setArchivedSessions] = useState<readonly ChatboxSession[]>([]);
  const [initialPrompt, setInitialPrompt] = useState<string | null>(null);
  const [sessionStatus, setSessionStatus] = useState<"loading" | "ready" | "unconfigured" | "unavailable">("loading");
  const [open, setOpen] = useState(false);
  const [restarting, setRestarting] = useState(false);
  const [refreshError, setRefreshError] = useState(false);
  const [runtimeSessionId, setRuntimeSessionId] = useState<string | null>(null);
  const requestGeneration = useRef(0);
  const sessionIdRef = useRef<string | null>(null);
  const sessionRequestGeneration = useRef<number | null>(null);
  const activeScope = useRef<ChatboxScope | null>(null);
  const pageUnloading = useRef(false);
  const available = chatboxEnabled && shouldRenderChatbox(authStatus, workspaceId);

  const destroyActiveSession = useCallback((updateState: boolean, preserveSelection = false): void => {
    requestGeneration.current += 1;
    sessionRequestGeneration.current = null;
    const cleanupScope = activeScope.current;
    const cleanupSessionId = sessionIdRef.current;
    activeScope.current = null;
    sessionIdRef.current = null;
    if (updateState) {
      setRuntimeSessionId(null);
      setOpen(false);
      setSessionId(null);
      setSessions([]);
      setArchivedSessions([]);
      setInitialPrompt(null);
      setSessionStatus("loading");
      setRestarting(false);
      setRefreshError(false);
    }
    if (pageUnloading.current || cleanupScope === null) return;
    if (cleanupSessionId !== null) {
      if (preserveSelection) {
        void suspendChatboxSession(cleanupSessionId, cleanupScope.workspaceId).catch(() => undefined);
      } else {
        clearStoredChatboxSession(cleanupScope.userId, cleanupScope.workspaceId);
        void pauseChatboxSession(cleanupSessionId).catch(() => undefined);
      }
    }
  }, []);

  const refreshSessionList = useCallback(async (): Promise<void> => {
    const [conversations, archived] = await Promise.all([
      listChatboxSessions("conversations"),
      listChatboxSessions("archived"),
    ]);
    setSessions(conversations.items);
    setArchivedSessions(archived.items);
  }, []);

  const applySession = useCallback((generation: number, session: ChatboxSession): boolean => {
    if (requestGeneration.current !== generation) {
      void pauseChatboxSession(session.session_id).catch(() => undefined);
      return false;
    }
    sessionIdRef.current = session.session_id;
    storeChatboxSession(userId, workspaceId, session.session_id);
    setSessionId(session.session_id);
    setSessionStatus("ready");
    return true;
  }, [userId, workspaceId]);

  const loadSession = useCallback(async (): Promise<void> => {
    // The loading UI has no Retry action. Coalescing duplicate calls here also
    // gives the first request sole ownership of sessionRequestGeneration.
    if (sessionRequestGeneration.current !== null) return;
    const generation = ++requestGeneration.current;
    sessionRequestGeneration.current = generation;
    sessionIdRef.current = null;
    setRuntimeSessionId(null);
    setSessionId(null);
    setSessionStatus("loading");
    setRestarting(false);
    setRefreshError(false);
    try {
      const storedSessionId = readStoredChatboxSession(userId, workspaceId);
      let session: ChatboxSession | null = null;
      const current = await getCurrentChatboxSession();
      if (current !== null) {
        session = current.session_state === "paused"
          ? await activateChatboxSession(current.session_id)
          : current;
      } else if (storedSessionId !== null) {
        try {
          session = await getChatboxSession(storedSessionId);
          session = await activateChatboxSession(session.session_id);
        } catch (error: unknown) {
          if (!axios.isAxiosError(error) || error.response?.status !== CHATBOX_SESSION_NOT_FOUND_STATUS) throw error;
          clearStoredChatboxSession(userId, workspaceId);
        }
      }
      if (session !== null) {
        if (applySession(generation, session)) {
          setRuntimeSessionId(session.session_id);
          await refreshSessionList();
        }
      } else if (requestGeneration.current === generation) {
        sessionIdRef.current = null;
        setSessionId(null);
        setSessionStatus("ready");
        await refreshSessionList();
      }
    } catch (error: unknown) {
      if (requestGeneration.current !== generation) return;
      setSessionStatus(
        axios.isAxiosError(error) && error.response?.status === AGENT_LLM_NOT_CONFIGURED_STATUS
          ? "unconfigured"
          : "unavailable",
      );
    } finally {
      if (sessionRequestGeneration.current === generation) {
        sessionRequestGeneration.current = null;
      }
    }
  }, [applySession, refreshSessionList, userId, workspaceId]);

  useEffect(() => {
    const markPageUnloading = () => { pageUnloading.current = true; };
    window.addEventListener("beforeunload", markPageUnloading);
    window.addEventListener("pagehide", markPageUnloading);
    return () => {
      window.removeEventListener("beforeunload", markPageUnloading);
      window.removeEventListener("pagehide", markPageUnloading);
    };
  }, []);

  useEffect(() => {
    const nextScope = available && userId !== null && workspaceId !== null
      ? { userId, workspaceId }
      : null;
    const previousScope = activeScope.current;
    if (
      previousScope !== null
      && nextScope !== null
      && previousScope.userId === nextScope.userId
      && previousScope.workspaceId === nextScope.workspaceId
    ) return;

    const workspaceTemporarilyUnavailable = previousScope !== null
      && nextScope === null
      && authStatus === "authenticated"
      && chatboxEnabled
      && userId === previousScope.userId
      && workspaceId === null;
    if (workspaceTemporarilyUnavailable) {
      setOpen(false);
      return;
    }

    if (previousScope !== null) {
      destroyActiveSession(
        true,
        nextScope !== null && previousScope.userId === nextScope.userId,
      );
    }
    if (nextScope !== null) activeScope.current = nextScope;
  }, [authStatus, available, chatboxEnabled, destroyActiveSession, userId, workspaceId]);

  useEffect(() => () => destroyActiveSession(false, true), [destroyActiveSession]);

  useEffect(() => {
    if (!open || sessionId === null || sessionStatus !== "ready") return;
    const timer = window.setInterval(() => {
      void refreshSessionList().catch(() => undefined);
    }, 3_000);
    return () => window.clearInterval(timer);
  }, [open, refreshSessionList, sessionId, sessionStatus]);

  if (!available) return null;
  const handleOpen = () => {
    setOpen(true);
    if (sessionId === null) void loadSession();
  };
  const handleNewConversation = async (): Promise<void> => {
    if (sessionId === null || restarting) return;
    const generation = ++requestGeneration.current;
    const previousRuntimeSessionId = runtimeSessionId;
    setRuntimeSessionId(null);
    setRestarting(true);
    setRefreshError(false);
    try {
      await pauseChatboxSession(sessionId);
    } catch (error: unknown) {
      if (requestGeneration.current !== generation) return;
      if (
        axios.isAxiosError(error)
        && error.response?.status === CHATBOX_SESSION_NOT_FOUND_STATUS
      ) {
        clearStoredChatboxSession(userId, workspaceId);
        sessionIdRef.current = null;
        setSessionId(null);
        setSessionStatus("unavailable");
      } else {
        setRuntimeSessionId(previousRuntimeSessionId);
        setRefreshError(true);
      }
      setRestarting(false);
      return;
    }
    if (requestGeneration.current !== generation) return;
    clearStoredChatboxSession(userId, workspaceId);
    sessionIdRef.current = null;
    setSessionId(null);
    setInitialPrompt(null);
    setSessionStatus("ready");
    try {
      await refreshSessionList();
    } catch {
      if (requestGeneration.current === generation) setRefreshError(true);
    } finally {
      if (requestGeneration.current === generation) setRestarting(false);
    }
  };
  const handleSelectSession = async (nextSessionId: string): Promise<void> => {
    if (nextSessionId === sessionId || restarting) return;
    const generation = ++requestGeneration.current;
    const previousRuntimeSessionId = runtimeSessionId;
    const previousSession = sessions.find((session) => session.session_id === sessionId);
    const optimisticSession = sessions.find((session) => session.session_id === nextSessionId);
    setRuntimeSessionId(null);
    setRestarting(true);
    setRefreshError(false);
    try {
      if (optimisticSession !== undefined && !applySession(generation, optimisticSession)) return;
      const activatedSession = await activateChatboxSession(nextSessionId);
      if (!applySession(generation, activatedSession)) return;
      setRuntimeSessionId(activatedSession.session_id);
    } catch {
      if (requestGeneration.current === generation) {
        if (previousSession !== undefined) applySession(generation, previousSession);
        setRuntimeSessionId(previousRuntimeSessionId);
        setRefreshError(true);
        setRestarting(false);
      }
      return;
    }
    try {
      await refreshSessionList();
    } catch {
      if (requestGeneration.current === generation) setRefreshError(true);
    } finally {
      if (requestGeneration.current === generation) setRestarting(false);
    }
  };
  const handleArchive = async (): Promise<void> => {
    if (sessionId === null || restarting) return;
    const generation = ++requestGeneration.current;
    const previousRuntimeSessionId = runtimeSessionId;
    setRuntimeSessionId(null);
    setRestarting(true);
    try {
      await archiveChatboxSession(sessionId);
    } catch {
      if (requestGeneration.current === generation) {
        setRuntimeSessionId(previousRuntimeSessionId);
        setRefreshError(true);
        setRestarting(false);
      }
      return;
    }
    if (requestGeneration.current !== generation) return;
    clearStoredChatboxSession(userId, workspaceId);
    sessionIdRef.current = null;
    setSessionId(null);
    setInitialPrompt(null);
    setSessionStatus("ready");
    try {
      await refreshSessionList();
    } catch {
      if (requestGeneration.current === generation) setRefreshError(true);
    } finally {
      if (requestGeneration.current === generation) setRestarting(false);
    }
  };
  const handleStartConversation = async (prompt: string): Promise<boolean> => {
    if (sessionId !== null || restarting || !prompt.trim()) return false;
    const generation = ++requestGeneration.current;
    setRestarting(true);
    setRefreshError(false);
    let created: ChatboxSession;
    try {
      created = await createChatboxSession();
    } catch (error: unknown) {
      if (requestGeneration.current === generation) {
        setSessionStatus(
          axios.isAxiosError(error) && error.response?.status === AGENT_LLM_NOT_CONFIGURED_STATUS
            ? "unconfigured"
            : "ready",
        );
        setRefreshError(true);
        setRestarting(false);
      }
      return false;
    }
    if (!applySession(generation, created)) return false;
    setRuntimeSessionId(created.session_id);
    setInitialPrompt(prompt.trim());
    try {
      await refreshSessionList();
    } catch {
      if (requestGeneration.current === generation) setRefreshError(true);
    } finally {
      if (requestGeneration.current === generation) setRestarting(false);
    }
    return requestGeneration.current === generation;
  };
  const handleUnarchive = async (archivedSessionId: string, openSession: boolean): Promise<void> => {
    if (restarting) return;
    const generation = ++requestGeneration.current;
    const previousRuntimeSessionId = runtimeSessionId;
    if (openSession) setRuntimeSessionId(null);
    setRestarting(true);
    setRefreshError(false);
    let restored: ChatboxSession;
    try {
      restored = await unarchiveChatboxSession(archivedSessionId, openSession);
    } catch {
      if (requestGeneration.current === generation) {
        setRuntimeSessionId(previousRuntimeSessionId);
        setRefreshError(true);
        setRestarting(false);
      }
      return;
    }
    if (requestGeneration.current !== generation) return;
    if (openSession && applySession(generation, restored)) setRuntimeSessionId(restored.session_id);
    try {
      await refreshSessionList();
    } catch {
      if (requestGeneration.current === generation) setRefreshError(true);
    } finally {
      if (requestGeneration.current === generation) setRestarting(false);
    }
  };
  const handleDeleteArchived = async (archivedSessionId: string): Promise<void> => {
    if (restarting) return;
    const generation = ++requestGeneration.current;
    setRestarting(true);
    setRefreshError(false);
    try {
      await deleteArchivedChatboxSession(archivedSessionId);
      if (requestGeneration.current !== generation) return;
      await refreshSessionList();
    } catch {
      if (requestGeneration.current === generation) setRefreshError(true);
    } finally {
      if (requestGeneration.current === generation) setRestarting(false);
    }
  };
  return (
    <>
      <ChatboxLauncher onOpen={handleOpen} />
      <ChatboxPanel
        onClose={() => setOpen(false)}
        onArchive={handleArchive}
        onDeleteArchived={handleDeleteArchived}
        onNewConversation={handleNewConversation}
        onRetry={loadSession}
        onSelectSession={handleSelectSession}
        onStartConversation={handleStartConversation}
        onUnarchive={handleUnarchive}
        open={open}
        archivedSessions={archivedSessions}
        initialPrompt={initialPrompt}
        onInitialPromptConsumed={() => setInitialPrompt(null)}
        refreshError={refreshError}
        restarting={restarting}
        runtimeEnabled={runtimeSessionId === sessionId}
        sessionId={sessionId}
        sessions={sessions}
        sessionStatus={sessionStatus}
      />
    </>
  );
}
