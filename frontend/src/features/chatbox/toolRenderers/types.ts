import type { ToolExecution } from "@/features/chatbox/piEventAssembler";
import { isSafeImageMimeType } from "@/features/chatbox/safeImage";

export type ToolStatus = "pending" | "success" | "error";

export interface ToolResultContentBlock {
  readonly type: string;
  readonly text?: unknown;
  readonly data?: unknown;
  readonly mimeType?: unknown;
}

export interface ToolResultPayload {
  readonly content: readonly ToolResultContentBlock[];
  readonly details?: unknown;
}

export interface ToolExecutionView {
  readonly toolCallId: string;
  readonly toolName: string;
  readonly args: Record<string, unknown> | null;
  readonly partial: ToolResultPayload | null;
  readonly result: ToolResultPayload | null;
  readonly status: ToolStatus;
}

export interface ToolRendererProps {
  readonly exec: ToolExecutionView;
  readonly forceExpand: boolean;
}

const MAX_TOOL_PREVIEW_CHARACTERS = 16_000;
const MAX_TOOL_IMAGE_BASE64_CHARACTERS = 10_000_000;

export interface ToolTextPreview {
  readonly text: string;
  readonly omittedCharacters: number;
}

function isRecord(value: unknown): value is Record<string, unknown> {
  return typeof value === "object" && value !== null && !Array.isArray(value);
}

function toPayload(value: unknown): ToolResultPayload | null {
  if (!isRecord(value) || !Array.isArray(value.content)) return null;
  if (!value.content.every((block) => isRecord(block) && typeof block.type === "string")) {
    return null;
  }
  return { content: value.content as readonly ToolResultContentBlock[], details: value.details };
}

function deriveToolStatus(hasResult: boolean, isError: boolean): ToolStatus {
  if (isError) return "error";
  if (!hasResult) return "pending";
  return "success";
}

export function toToolExecutionView(exec: ToolExecution): ToolExecutionView {
  const isError = exec.isError === true;
  const result = exec.result === undefined ? null : toPayload(exec.result);
  return {
    toolCallId: exec.toolCallId,
    toolName: exec.toolName,
    args: isRecord(exec.args) ? exec.args : null,
    partial: exec.partialResult === undefined ? null : toPayload(exec.partialResult),
    result,
    status: deriveToolStatus(result !== null, isError)
  };
}

export function payloadText(payload: ToolResultPayload | null): string {
  if (payload === null) return "";
  return payload.content
    .filter(isTextContentBlock)
    .map((block) => block.text)
    .join("\n");
}

export function payloadImage(payload: ToolResultPayload | null): { data: string; mimeType: string } | null {
  const block = payload?.content.find(isSafeImageContentBlock);
  return block ? { data: block.data, mimeType: block.mimeType } : null;
}

function isTextContentBlock(
  block: ToolResultContentBlock,
): block is ToolResultContentBlock & { readonly text: string } {
  return block.type === "text" && typeof block.text === "string";
}

function isSafeImageContentBlock(
  block: ToolResultContentBlock,
): block is ToolResultContentBlock & { readonly data: string; readonly mimeType: string } {
  return block.type === "image"
    && typeof block.data === "string"
    && block.data.length <= MAX_TOOL_IMAGE_BASE64_CHARACTERS
    && typeof block.mimeType === "string"
    && isSafeImageMimeType(block.mimeType);
}

export function truncateToolPreview(text: string): ToolTextPreview {
  if (text.length <= MAX_TOOL_PREVIEW_CHARACTERS) {
    return { text, omittedCharacters: 0 };
  }
  let end = MAX_TOOL_PREVIEW_CHARACTERS;
  const lastCodeUnit = text.charCodeAt(end - 1);
  if (lastCodeUnit >= 0xD800 && lastCodeUnit <= 0xDBFF) end -= 1;
  return {
    text: text.slice(0, end),
    omittedCharacters: text.length - end,
  };
}

export interface TruncationInfo {
  readonly truncated: boolean;
  readonly truncatedBy?: string;
  readonly totalLines?: number;
  readonly outputLines?: number;
  readonly totalBytes?: number;
  readonly outputBytes?: number;
  readonly lastLinePartial?: boolean;
  readonly firstLineExceedsLimit?: boolean;
  readonly maxLines?: number;
  readonly maxBytes?: number;
  readonly fullOutputPath?: string;
}

export function payloadTruncation(payload: ToolResultPayload | null): TruncationInfo | null {
  const details = payload?.details;
  if (!isRecord(details) || !isRecord(details.truncation)) return null;
  const truncation = details.truncation;
  if (truncation.truncated !== true) return null;
  return {
    truncated: true,
    ...(typeof truncation.truncatedBy === "string" ? { truncatedBy: truncation.truncatedBy } : {}),
    ...(typeof truncation.totalLines === "number" ? { totalLines: truncation.totalLines } : {}),
    ...(typeof truncation.outputLines === "number" ? { outputLines: truncation.outputLines } : {}),
    ...(typeof truncation.totalBytes === "number" ? { totalBytes: truncation.totalBytes } : {}),
    ...(typeof truncation.outputBytes === "number" ? { outputBytes: truncation.outputBytes } : {}),
    ...(typeof truncation.lastLinePartial === "boolean" ? { lastLinePartial: truncation.lastLinePartial } : {}),
    ...(typeof truncation.firstLineExceedsLimit === "boolean" ? { firstLineExceedsLimit: truncation.firstLineExceedsLimit } : {}),
    ...(typeof truncation.maxLines === "number" ? { maxLines: truncation.maxLines } : {}),
    ...(typeof truncation.maxBytes === "number" ? { maxBytes: truncation.maxBytes } : {}),
    ...(typeof details.fullOutputPath === "string" ? { fullOutputPath: details.fullOutputPath } : {}),
  };
}

export function payloadDiff(payload: ToolResultPayload | null): string {
  const details = payload?.details;
  return isRecord(details) && typeof details.diff === "string" ? details.diff : "";
}

export function payloadResultLimitReached(payload: ToolResultPayload | null): boolean {
  const details = payload?.details;
  if (!isRecord(details)) return false;
  const value = details.resultLimitReached;
  return value === true || (typeof value === "number" && value > 0);
}

export function payloadFullOutputPath(payload: ToolResultPayload | null): string | null {
  const details = payload?.details;
  return isRecord(details) && typeof details.fullOutputPath === "string"
    ? details.fullOutputPath
    : null;
}

export function argString(args: Record<string, unknown> | null, key: string): string {
  const value = args?.[key];
  return typeof value === "string" ? value : "";
}

export function argNumber(args: Record<string, unknown> | null, key: string): number | null {
  const value = args?.[key];
  return typeof value === "number" && Number.isFinite(value) ? value : null;
}
