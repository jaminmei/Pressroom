import {
  CloseOutlined,
  DeleteOutlined,
  FolderOpenOutlined,
  InboxOutlined,
  PlusOutlined,
  RollbackOutlined,
  StopOutlined,
} from "@ant-design/icons";
import { Button, Drawer, Empty, Input, List, Popconfirm, Result, Select, Spin, Tabs, Tag, Typography } from "antd";
import {
  useEffect,
  useRef,
  useState,
  type CSSProperties,
  type PointerEvent as ReactPointerEvent,
} from "react";
import ReactMarkdown from "react-markdown";
import rehypeSanitize from "rehype-sanitize";
import remarkGfm from "remark-gfm";
import { useTranslation } from "react-i18next";

import { resizeChatboxWindow } from "@/features/chatbox/chatboxWindow";
import { isSafeImageMimeType } from "@/features/chatbox/safeImage";
import { getToolRenderer } from "@/features/chatbox/toolRenderers/registry";
import { toToolExecutionView } from "@/features/chatbox/toolRenderers/types";
import { useChatboxSession } from "@/features/chatbox/useChatboxSession";
import type { CompactionNote, PiContentBlock, PiMessage, ToolExecution } from "@/features/chatbox/piEventAssembler";
import {
  decideToolApproval,
  listToolApprovals,
  type ChatboxSession,
  type ToolApproval,
} from "@/services/chatboxApi";

interface ChatboxPanelProps {
  readonly sessionId: string | null;
  readonly sessionStatus: "loading" | "ready" | "unconfigured" | "unavailable";
  readonly open: boolean;
  readonly onClose: () => void;
  readonly onArchive: () => void;
  readonly onDeleteArchived?: (sessionId: string) => Promise<void>;
  readonly onInitialPromptConsumed?: () => void;
  readonly onNewConversation?: () => void;
  readonly onRefresh?: () => void;
  readonly onRetry: () => void;
  readonly onSelectSession: (sessionId: string) => void;
  readonly onStartConversation?: (prompt: string) => Promise<boolean>;
  readonly onUnarchive?: (sessionId: string, open: boolean) => Promise<void>;
  readonly refreshError: boolean;
  readonly restarting: boolean;
  readonly runtimeEnabled: boolean;
  readonly sessions: readonly ChatboxSession[];
  readonly archivedSessions?: readonly ChatboxSession[];
  readonly initialPrompt?: string | null;
}
const SETTINGS_AGENT_LLM_URL = "/settings#agent-llm-settings";
const SCROLL_FOLLOW_THRESHOLD = 48;

function ThinkingBlock({ text, redacted }: { readonly text: string; readonly redacted: boolean }) {
  const { t } = useTranslation("chatbox");
  const [visible, setVisible] = useState(false);
  if (redacted) {
    return <div className="chatbox-thinking chatbox-thinking-redacted" data-testid="chatbox-thinking">{t("thinkingRedacted")}</div>;
  }
  return (
    <div className="chatbox-thinking" data-testid="chatbox-thinking">
      <button className="chatbox-thinking-toggle" onClick={() => setVisible((value) => !value)} type="button">
        {visible ? t("thinkingHide") : t("thinkingShow")}
      </button>
      {visible ? <div className="chatbox-thinking-body">{text}</div> : null}
    </div>
  );
}

function ImageBlock({ data, mimeType }: { readonly data: string; readonly mimeType: string }) {
  if (!isSafeImageMimeType(mimeType)) return null;
  return <img alt="" className="chatbox-message-image" src={`data:${mimeType};base64,${data}`} />;
}

const ADMISSION_REASON_KEYS = new Set([
  "empty_message",
  "invalid_message",
  "message_too_large",
  "turn_rate_exceeded",
  "needs_clarification",
  "not_pressroom_scope",
  "capability_not_registered",
  "admission_context_invalid",
  "admission_classifier_unavailable",
]);

function AdmissionBlock({ reasonCode }: { readonly reasonCode: string }) {
  const { t } = useTranslation("chatbox");
  const key = ADMISSION_REASON_KEYS.has(reasonCode) ? reasonCode : "admission_classifier_unavailable";
  return (
    <Typography.Text className="chatbox-admission-message" data-testid="chatbox-admission-message" type="warning">
      {t(`admission.${key}`)}
    </Typography.Text>
  );
}

function contentBlockKey(messageId: string, block: PiContentBlock, contentIndex: number): string {
  if (block.type === "toolCall" && typeof block.toolCallId === "string") {
    return `${messageId}-tool-${contentIndex}-${block.toolCallId}`;
  }
  // Pi contentIndex is positional and append-only for the lifetime of a message.
  return `${messageId}-block-${contentIndex}-${block.type}`;
}

function renderableToolCallIds(
  messages: readonly PiMessage[],
  toolExecutions: Readonly<Record<string, ToolExecution>>,
): ReadonlySet<string> {
  const ids = new Set<string>();
  for (const message of messages) {
    for (const block of message.content) {
      if (
        block.type === "toolCall"
        && typeof block.toolCallId === "string"
        && toolExecutions[block.toolCallId] !== undefined
      ) {
        ids.add(block.toolCallId);
      }
    }
  }
  return ids;
}

function isRedundantToolResult(message: PiMessage, toolCardCallIds: ReadonlySet<string>): boolean {
  return message.role === "toolResult"
    && typeof message.toolCallId === "string"
    && toolCardCallIds.has(message.toolCallId);
}

function isRecord(value: unknown): value is Record<string, unknown> {
  return typeof value === "object" && value !== null;
}

function usageText(message: PiMessage): string | null {
  const usage = isRecord(message.usage) ? message.usage : null;
  const model = isRecord(message.model) ? message.model : null;
  if (usage === null && model === null) return null;
  const input = typeof usage?.input === "number" ? usage.input : null;
  const output = typeof usage?.output === "number" ? usage.output : null;
  const cacheRead = typeof usage?.cacheRead === "number" ? usage.cacheRead : null;
  const cacheWrite = typeof usage?.cacheWrite === "number" ? usage.cacheWrite : null;
  const cost = isRecord(usage?.cost) && typeof usage.cost.total === "number" ? usage.cost.total : null;
  const modelId = typeof model?.id === "string" ? model.id : null;
  const parts = [
    modelId,
    input !== null || output !== null ? `↑${input ?? 0} ↓${output ?? 0}` : null,
    cacheRead !== null ? `R${cacheRead}` : null,
    cacheWrite !== null ? `W${cacheWrite}` : null,
    cost !== null && cost > 0 ? `$${cost.toFixed(4)}` : null
  ].filter((part): part is string => part !== null);
  return parts.length > 0 ? parts.join(" · ") : null;
}

function messageStatusKey(message: PiMessage): "aborted" | "error" | null {
  if (message.status === "aborted" || message.stopReason === "aborted") return "aborted";
  if (message.status === "error" || message.stopReason === "error") return "error";
  return null;
}

function DefaultMessageRenderer({
  msg,
  toolExecutions,
  forceExpand
}: {
  readonly msg: PiMessage;
  readonly toolExecutions: Readonly<Record<string, ToolExecution>>;
  readonly forceExpand: boolean;
}) {
  const { t } = useTranslation("chatbox");
  const usage = usageText(msg);
  const statusKey = messageStatusKey(msg);
  return (
    <div className="chatbox-message-blocks">
      {msg.content.map((block: PiContentBlock, index) => {
        const key = contentBlockKey(msg.id, block, index);
        if (block.type === "text" && typeof block.text === "string") {
          return (
            <ReactMarkdown key={key} rehypePlugins={[rehypeSanitize]} remarkPlugins={[remarkGfm]}>
              {block.text}
            </ReactMarkdown>
          );
        }
        if (block.type === "thinking" && typeof block.thinking === "string") {
          return <ThinkingBlock key={key} redacted={block.redacted === true} text={block.thinking} />;
        }
        if (block.type === "toolCall" && typeof block.toolCallId === "string") {
          const execution = toolExecutions[block.toolCallId];
          if (execution === undefined) {
            return <div className="chatbox-tool-pending" key={key}>{t("toolPending")}</div>;
          }
          const Renderer = getToolRenderer(execution.toolName);
          return <Renderer exec={toToolExecutionView(execution)} forceExpand={forceExpand} key={key} />;
        }
        if (block.type === "image" && typeof block.data === "string" && typeof block.mimeType === "string") {
          return <ImageBlock data={block.data} key={key} mimeType={block.mimeType} />;
        }
        if (block.type === "admission" && typeof block.reasonCode === "string") {
          return <AdmissionBlock key={key} reasonCode={block.reasonCode} />;
        }
        return null;
      })}
      {usage !== null ? <div className="chatbox-usage-line">{usage}</div> : null}
      {statusKey !== null ? <Tag className={`chatbox-status-${statusKey}`}>{t(`messageStatus.${statusKey}`)}</Tag> : null}
    </div>
  );
}

function CompactionNoteRow({ note }: { readonly note: CompactionNote }) {
  const { t } = useTranslation("chatbox");
  return (
    <div className="chatbox-compaction-note" data-testid="chatbox-compaction-note">
      {note.aborted ? t("compactionAborted") : t("compactionNote")}
    </div>
  );
}

function ChatboxContent({
  sessionId,
  enabled,
  initialPrompt,
  onClose,
  onArchive,
  onInitialPromptConsumed,
  onManage,
  onNewConversation,
  onSelectSession,
  refreshError,
  restarting,
  sessions,
}: {
  readonly sessionId: string;
  readonly enabled: boolean;
  readonly initialPrompt: string | null;
  readonly onClose: () => void;
  readonly onArchive: () => void;
  readonly onInitialPromptConsumed: () => void;
  readonly onManage: () => void;
  readonly onNewConversation: () => void;
  readonly onSelectSession: (sessionId: string) => void;
  readonly refreshError: boolean;
  readonly restarting: boolean;
  readonly sessions: readonly ChatboxSession[];
}) {
  const { t } = useTranslation("chatbox");
  const [prompt, setPrompt] = useState("");
  const [expandTools, setExpandTools] = useState(false);
  const [approvals, setApprovals] = useState<readonly ToolApproval[]>([]);
  const [approvalError, setApprovalError] = useState(false);
  const [decidingApprovalId, setDecidingApprovalId] = useState<string | null>(null);
  const messageListRef = useRef<HTMLDivElement>(null);
  const followLatestRef = useRef(true);
  const scrollFrameRef = useRef<number | null>(null);
  const {
    messages,
    runningState,
    toolExecutions,
    compactionNotes,
    connected,
    runtimeStatus,
    requiresRefresh,
    accessUnavailable,
    send,
    abort,
  } = useChatboxSession({
    sessionId,
    enabled,
    initialSession: sessions.find((session) => session.session_id === sessionId),
  });
  const toolCardCallIds = renderableToolCallIds(messages, toolExecutions);
  const visibleMessages = messages.filter(
    (message) => !isRedundantToolResult(message, toolCardCallIds),
  );

  useEffect(() => {
    if (initialPrompt === null || !connected) return;
    if (send(initialPrompt)) onInitialPromptConsumed();
  }, [connected, initialPrompt, onInitialPromptConsumed, send]);

  useEffect(() => {
    if (!enabled) return;
    let cancelled = false;
    const refreshApprovals = async () => {
      try {
        const next = await listToolApprovals(sessionId);
        if (!cancelled) setApprovals(next);
      } catch {
        if (!cancelled) setApprovals([]);
      }
    };
    void refreshApprovals();
    const timer = window.setInterval(() => void refreshApprovals(), 1_000);
    return () => {
      cancelled = true;
      window.clearInterval(timer);
    };
  }, [enabled, sessionId]);

  const decide = async (approval: ToolApproval, approved: boolean) => {
    setApprovalError(false);
    setDecidingApprovalId(approval.id);
    try {
      await decideToolApproval(sessionId, approval.id, approved);
      setApprovals((current) => current.filter((item) => item.id !== approval.id));
    } catch {
      setApprovalError(true);
      try {
        setApprovals(await listToolApprovals(sessionId));
      } catch {
        setApprovals([]);
      }
    } finally {
      setDecidingApprovalId(null);
    }
  };

  useEffect(() => {
    if (!followLatestRef.current || scrollFrameRef.current !== null) return;
    scrollFrameRef.current = window.requestAnimationFrame(() => {
      scrollFrameRef.current = null;
      const messageList = messageListRef.current;
      if (messageList !== null && followLatestRef.current) {
        messageList.scrollTop = messageList.scrollHeight;
      }
    });
  }, [compactionNotes, messages, runningState, toolExecutions]);

  useEffect(() => () => {
    if (scrollFrameRef.current !== null) {
      window.cancelAnimationFrame(scrollFrameRef.current);
      scrollFrameRef.current = null;
    }
  }, []);

  const submit = () => {
    if (send(prompt)) setPrompt("");
  };
  return (
    <div className="chatbox-panel-content">
      <div className="chatbox-panel-header">
        <div className="chatbox-panel-heading">
          <Typography.Text className="chatbox-panel-title" strong>{t("title")}</Typography.Text>
          <Tag data-testid="chatbox-running-state">{t(`states.${runningState}`)}</Tag>
          {runtimeStatus !== "ready" ? (
            <Tag data-testid="chatbox-runtime-state">{t(`runtimeStates.${runtimeStatus}`)}</Tag>
          ) : null}
        </div>
        <div className="chatbox-panel-header-actions">
          <Select
            aria-label={t("selectSession")}
            disabled={runningState !== "idle" || restarting}
            onChange={onSelectSession}
            options={sessions.map((session) => ({
              label: session.title ?? t("newConversation"),
              value: session.session_id,
              title: session.preview ?? undefined,
            }))}
            popupMatchSelectWidth={280}
            className="chatbox-session-select"
            size="small"
            value={sessionId}
          />
          {accessUnavailable ? null : (
            <Button
              aria-label={t("newConversation")}
              disabled={runningState !== "idle"}
              icon={<PlusOutlined />}
              loading={restarting}
              onClick={onNewConversation}
              size="small"
              title={t("newConversation")}
              type="text"
            />
          )}
          <Button
            aria-label={t("manageConversations")}
            icon={<FolderOpenOutlined />}
            onClick={onManage}
            size="small"
            title={t("manageConversations")}
            type="text"
          />
          <Button
            aria-label={t("archiveSession")}
            disabled={runningState !== "idle" || restarting}
            icon={<InboxOutlined />}
            onClick={onArchive}
            size="small"
            title={t("archiveSession")}
            type="text"
          />
          {toolCardCallIds.size > 0 ? (
            <Button
              aria-label={t(expandTools ? "collapseAll" : "expandAll")}
              className="chatbox-expand-toggle"
              data-testid="chatbox-expand-toggle"
              onClick={() => setExpandTools((value) => !value)}
              size="small"
              type="text"
            >
              {t(expandTools ? "collapseAll" : "expandAll")}
            </Button>
          ) : null}
          <Button aria-label={t("close")} icon={<CloseOutlined />} onClick={onClose} type="text" />
        </div>
      </div>
      <div
        className="chatbox-message-list"
        data-testid="chatbox-message-list"
        onScroll={(event) => {
          const messageList = event.currentTarget;
          const distanceFromBottom =
            messageList.scrollHeight - messageList.scrollTop - messageList.clientHeight;
          followLatestRef.current = distanceFromBottom <= SCROLL_FOLLOW_THRESHOLD;
        }}
        ref={messageListRef}
      >
        {refreshError ? (
          <Typography.Text className="chatbox-refresh-error" type="danger">
            {t("refreshFailed")}
          </Typography.Text>
        ) : null}
        {accessUnavailable ? (
          <Typography.Text className="chatbox-access-unavailable" type="danger">
            {t("accessUnavailable")}
          </Typography.Text>
        ) : requiresRefresh ? (
          <Typography.Text className="chatbox-session-ended" type="warning">
            {t(messages.length > 0 ? "sessionRestoreFailed" : "sessionEnded")}
          </Typography.Text>
        ) : visibleMessages.length === 0 && compactionNotes.length === 0 ? (
          <Typography.Text type="secondary">{t("empty")}</Typography.Text>
        ) : null}
        {visibleMessages.map((message) => (
          <div className={`chatbox-message chatbox-message-${message.role}`} key={message.id}>
            <DefaultMessageRenderer
              forceExpand={expandTools}
              msg={message}
              toolExecutions={toolExecutions}
            />
          </div>
        ))}
        {compactionNotes.map((note) => <CompactionNoteRow key={note.id} note={note} />)}
      </div>
      <div className="chatbox-composer">
        {approvals.length > 0 || approvalError ? (
          <div className="chatbox-approval-tray" data-testid="chatbox-approval-tray">
            {approvalError ? (
              <Typography.Text className="chatbox-approval-error" type="danger">
                {t("approvalFailed")}
              </Typography.Text>
            ) : null}
            {approvals.map((approval) => {
              const secondsRemaining = Math.max(
                0,
                Math.ceil((Date.parse(approval.expires_at) - Date.now()) / 1_000),
              );
              const deciding = decidingApprovalId === approval.id;
              return (
                <div
                  className="chatbox-tool-approval"
                  data-testid="chatbox-tool-approval"
                  key={approval.id}
                >
                  <div className="chatbox-tool-approval-heading">
                    <Typography.Text strong>
                      {t("approvalTitle", { operation: approval.operation })}
                    </Typography.Text>
                    <Typography.Text type="secondary">
                      {t("approvalExpiresIn", { seconds: secondsRemaining })}
                    </Typography.Text>
                  </div>
                  <Typography.Paragraph code ellipsis={{ rows: 3, expandable: true }}>
                    {approval.argument_summary}
                  </Typography.Paragraph>
                  <div className="chatbox-tool-approval-actions">
                    <Button
                      danger
                      disabled={decidingApprovalId !== null}
                      onClick={() => void decide(approval, false)}
                      size="small"
                    >
                      {t("reject")}
                    </Button>
                    <Button
                      disabled={decidingApprovalId !== null}
                      loading={deciding}
                      onClick={() => void decide(approval, true)}
                      size="small"
                      type="primary"
                    >
                      {t("approve")}
                    </Button>
                  </div>
                </div>
              );
            })}
          </div>
        ) : null}
        <Input.TextArea
          aria-label={t("prompt")}
          autoSize={{ minRows: 2, maxRows: 4 }}
          onChange={(event) => setPrompt(event.target.value)}
          onPressEnter={(event) => {
            if (!event.shiftKey && !event.nativeEvent.isComposing) {
              event.preventDefault();
              submit();
            }
          }}
          placeholder={t("prompt")}
          value={prompt}
        />
        <div className="chatbox-composer-actions">
          <Button disabled={!prompt.trim() || !connected} onClick={submit} type="primary">{t("send")}</Button>
          <Button disabled={runningState === "idle" || !connected} icon={<StopOutlined />} onClick={abort}>{t("abort")}</Button>
        </div>
      </div>
    </div>
  );
}

function ChatboxUnavailableContent({
  sessionStatus,
  onClose,
  onRetry,
}: Pick<ChatboxPanelProps, "sessionStatus" | "onClose" | "onRetry">) {
  const { t } = useTranslation("chatbox");
  const isUnconfigured = sessionStatus === "unconfigured";
  const resultActions = [<Button key="retry" onClick={onRetry}>{t("retry")}</Button>];
  if (isUnconfigured) {
    resultActions.unshift(
      <Button href={SETTINGS_AGENT_LLM_URL} key="configure" type="primary">{t("configure")}</Button>,
    );
  }
  return (
    <div className="chatbox-panel-content">
      <div className="chatbox-panel-header">
        <Typography.Text strong>{t("title")}</Typography.Text>
        <Button aria-label={t("close")} icon={<CloseOutlined />} onClick={onClose} type="text" />
      </div>
      <div className="chatbox-panel-state">
        {sessionStatus === "loading" ? (
          <Spin tip={t("preparing")} />
        ) : (
          <Result
            status={isUnconfigured ? "info" : "warning"}
            title={t(isUnconfigured ? "setupTitle" : "unavailableTitle")}
            subTitle={t(isUnconfigured ? "setupDescription" : "unavailableDescription")}
            extra={resultActions}
          />
        )}
      </div>
    </div>
  );
}

function BlankChatboxContent({
  onClose,
  onManage,
  onSelectSession,
  onStartConversation,
  refreshError,
  restarting,
  sessions,
}: {
  readonly onClose: () => void;
  readonly onManage: () => void;
  readonly onSelectSession: (sessionId: string) => void;
  readonly onStartConversation: (prompt: string) => Promise<boolean>;
  readonly refreshError: boolean;
  readonly restarting: boolean;
  readonly sessions: readonly ChatboxSession[];
}) {
  const { t } = useTranslation("chatbox");
  const [prompt, setPrompt] = useState("");
  const submit = async () => {
    if (await onStartConversation(prompt)) setPrompt("");
  };
  return (
    <div className="chatbox-panel-content">
      <div className="chatbox-panel-header">
        <div className="chatbox-panel-heading">
          <Typography.Text className="chatbox-panel-title" strong>{t("title")}</Typography.Text>
          <Tag>{t("states.idle")}</Tag>
        </div>
        <div className="chatbox-panel-header-actions">
          <Select
            aria-label={t("selectSession")}
            className="chatbox-session-select"
            onChange={onSelectSession}
            options={sessions.map((session) => ({
              label: session.title ?? t("newConversation"),
              value: session.session_id,
              title: session.preview ?? undefined,
            }))}
            placeholder={t("newConversation")}
            popupMatchSelectWidth={280}
            size="small"
            value={undefined}
          />
          <Button aria-label={t("newConversation")} disabled icon={<PlusOutlined />} size="small" title={t("newConversation")} type="text" />
          <Button aria-label={t("manageConversations")} icon={<FolderOpenOutlined />} onClick={onManage} size="small" title={t("manageConversations")} type="text" />
          <Button aria-label={t("close")} icon={<CloseOutlined />} onClick={onClose} type="text" />
        </div>
      </div>
      <div className="chatbox-message-list chatbox-empty-conversation">
        {refreshError ? <Typography.Text type="danger">{t("refreshFailed")}</Typography.Text> : null}
        <Typography.Text type="secondary">{t("empty")}</Typography.Text>
      </div>
      <div className="chatbox-composer">
        <Input.TextArea
          aria-label={t("prompt")}
          autoSize={{ minRows: 2, maxRows: 4 }}
          onChange={(event) => setPrompt(event.target.value)}
          onPressEnter={(event) => {
            if (!event.shiftKey && !event.nativeEvent.isComposing) {
              event.preventDefault();
              void submit();
            }
          }}
          placeholder={t("prompt")}
          value={prompt}
        />
        <div className="chatbox-composer-actions">
          <Button disabled={!prompt.trim()} loading={restarting} onClick={() => void submit()} type="primary">{t("send")}</Button>
        </div>
      </div>
    </div>
  );
}

function ConversationManager({
  archivedSessions,
  onBack,
  onDeleteArchived,
  onSelectSession,
  onUnarchive,
  restarting,
  sessions,
}: {
  readonly archivedSessions: readonly ChatboxSession[];
  readonly onBack: () => void;
  readonly onDeleteArchived: (sessionId: string) => Promise<void>;
  readonly onSelectSession: (sessionId: string) => void;
  readonly onUnarchive: (sessionId: string, open: boolean) => Promise<void>;
  readonly restarting: boolean;
  readonly sessions: readonly ChatboxSession[];
}) {
  const { t } = useTranslation("chatbox");
  const renderList = (items: readonly ChatboxSession[], archived: boolean) => (
    <List
      className="chatbox-conversation-list"
      dataSource={[...items]}
      locale={{ emptyText: <Empty description={t(archived ? "noArchivedConversations" : "noConversations")} image={Empty.PRESENTED_IMAGE_SIMPLE} /> }}
      renderItem={(session) => (
        <List.Item
          actions={archived ? [
            <Button disabled={restarting} key="unarchive" onClick={() => void onUnarchive(session.session_id, false)} size="small" type="link">{t("unarchive")}</Button>,
            <Button disabled={restarting} key="open" onClick={() => void onUnarchive(session.session_id, true)} size="small" type="link">{t("unarchiveAndOpen")}</Button>,
            <Popconfirm
              description={t("deleteConversationDescription")}
              key="delete"
              okButtonProps={{ danger: true }}
              okText={t("deletePermanently")}
              onConfirm={() => onDeleteArchived(session.session_id)}
              title={t("deleteConversationTitle")}
            >
              <Button danger disabled={restarting} icon={<DeleteOutlined />} size="small" type="text" />
            </Popconfirm>,
          ] : [
            <Button disabled={restarting} key="open" onClick={() => onSelectSession(session.session_id)} size="small" type="link">{t("openConversation")}</Button>,
          ]}
        >
          <List.Item.Meta
            description={<Typography.Text ellipsis type="secondary">{session.preview ?? t("noPreview")}</Typography.Text>}
            title={<Typography.Text ellipsis>{session.title ?? t("newConversation")}</Typography.Text>}
          />
        </List.Item>
      )}
    />
  );
  return (
    <div className="chatbox-panel-content chatbox-conversation-manager">
      <div className="chatbox-panel-header">
        <div className="chatbox-panel-heading">
          <Button aria-label={t("backToConversation")} icon={<RollbackOutlined />} onClick={onBack} type="text" />
          <Typography.Text className="chatbox-panel-title" strong>{t("manageConversations")}</Typography.Text>
        </div>
      </div>
      <Tabs
        className="chatbox-conversation-tabs"
        items={[
          { key: "conversations", label: t("conversations"), children: renderList(sessions, false) },
          { key: "archived", label: t("archivedConversations"), children: renderList(archivedSessions, true) },
        ]}
      />
    </div>
  );
}

export function ChatboxPanel({ archivedSessions = [], initialPrompt = null, sessionId, sessionStatus, open, onClose, onArchive, onDeleteArchived = async () => undefined, onInitialPromptConsumed = () => undefined, onNewConversation, onRefresh, onRetry, onSelectSession, onStartConversation = async () => false, onUnarchive = async () => undefined, refreshError, restarting, runtimeEnabled, sessions }: ChatboxPanelProps) {
  const { t } = useTranslation("chatbox");
  const [windowSize, setWindowSize] = useState({ width: 420, height: 560 });
  const [managingConversations, setManagingConversations] = useState(false);
  const resizeCleanup = useRef<(() => void) | null>(null);

  useEffect(() => () => resizeCleanup.current?.(), []);

  const beginResize = (event: ReactPointerEvent<HTMLButtonElement>) => {
    event.preventDefault();
    const startX = event.clientX;
    const startY = event.clientY;
    const startSize = windowSize;
    const previousCursor = document.body.style.cursor;
    const previousUserSelect = document.body.style.userSelect;
    let resizeFrame: number | null = null;
    let pendingPointer: { readonly x: number; readonly y: number } | null = null;
    const cleanup = () => {
      window.removeEventListener("pointermove", move);
      window.removeEventListener("pointerup", cleanup);
      window.removeEventListener("pointercancel", cleanup);
      if (resizeFrame !== null) window.cancelAnimationFrame(resizeFrame);
      resizeFrame = null;
      pendingPointer = null;
      document.body.style.cursor = previousCursor;
      document.body.style.userSelect = previousUserSelect;
      resizeCleanup.current = null;
    };
    const move = (pointer: PointerEvent) => {
      pendingPointer = { x: pointer.clientX, y: pointer.clientY };
      if (resizeFrame !== null) return;
      resizeFrame = window.requestAnimationFrame(() => {
        resizeFrame = null;
        const nextPointer = pendingPointer;
        pendingPointer = null;
        if (nextPointer === null) return;
        setWindowSize(resizeChatboxWindow(
          startSize,
          { x: startX, y: startY },
          nextPointer,
          { width: window.innerWidth, height: window.innerHeight },
        ));
      });
    };
    resizeCleanup.current?.();
    resizeCleanup.current = cleanup;
    document.body.style.cursor = "nwse-resize";
    document.body.style.userSelect = "none";
    window.addEventListener("pointermove", move);
    window.addEventListener("pointerup", cleanup);
    window.addEventListener("pointercancel", cleanup);
  };
  const rootStyle = {
    "--chatbox-window-height": `${windowSize.height}px`,
  } as CSSProperties;

  return (
    <Drawer className="chatbox-window" closable={false} mask={false} onClose={onClose} open={open} placement="right" rootClassName="chatbox-window-root" rootStyle={rootStyle} title={null} width={windowSize.width}>
      <button aria-label={t("resize")} className="chatbox-resize-handle" onPointerDown={beginResize} type="button" />
      {managingConversations ? (
        <ConversationManager archivedSessions={archivedSessions} onBack={() => setManagingConversations(false)} onDeleteArchived={onDeleteArchived} onSelectSession={(nextSessionId) => { setManagingConversations(false); onSelectSession(nextSessionId); }} onUnarchive={async (archivedSessionId, activate) => { await onUnarchive(archivedSessionId, activate); if (activate) setManagingConversations(false); }} restarting={restarting} sessions={sessions} />
      ) : sessionId === null && sessionStatus === "ready" ? (
        <BlankChatboxContent onClose={onClose} onManage={() => setManagingConversations(true)} onSelectSession={onSelectSession} onStartConversation={onStartConversation} refreshError={refreshError} restarting={restarting} sessions={sessions} />
      ) : sessionId === null ? (
        <ChatboxUnavailableContent onClose={onClose} onRetry={onRetry} sessionStatus={sessionStatus} />
      ) : (
        <ChatboxContent enabled={open && runtimeEnabled} initialPrompt={initialPrompt} key={sessionId} onArchive={onArchive} onClose={onClose} onInitialPromptConsumed={onInitialPromptConsumed} onManage={() => setManagingConversations(true)} onNewConversation={onNewConversation ?? onRefresh ?? (() => undefined)} onSelectSession={onSelectSession} refreshError={refreshError} restarting={restarting} sessionId={sessionId} sessions={sessions} />
      )}
    </Drawer>
  );
}
