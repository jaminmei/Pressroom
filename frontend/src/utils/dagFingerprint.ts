import type { TaskInputFileIdentity } from "@/types/task";
import { inputFileFingerprint } from "./inputFileIdentity";

interface NodeLike {
  id: string;
  type: string;
  config?: Record<string, unknown>;
}

interface EdgeLike {
  source: string;
  target: string;
  sourceHandle?: string | null;
  targetHandle?: string | null;
}

function sortedStringify(value: unknown): string {
  if (value === null || value === undefined) return "null";
  if (typeof value !== "object") return JSON.stringify(value);
  if (Array.isArray(value)) return "[" + value.map(sortedStringify).join(",") + "]";
  const keys = Object.keys(value).sort();
  return "{" + keys.map((k) => JSON.stringify(k) + ":" + sortedStringify((value as Record<string, unknown>)[k])).join(",") + "}";
}

function isExcluded(type: string): boolean {
  return type.startsWith("input/") || type === "end/final";
}

export function computeDagFingerprint(
  nodes: NodeLike[],
  edges: EdgeLike[],
  nodeConfigs: Record<string, Record<string, unknown>>
): string {
  const included = new Map<string, { type: string; configKey: string }>();

  for (const node of nodes) {
    if (isExcluded(node.type)) continue;
    const config = nodeConfigs[node.id] ?? node.config ?? {};
    const configKey = sortedStringify(config);
    included.set(node.id, { type: node.type, configKey });
  }

  const sortedNodes = [...included.entries()]
    .map(([id, { type, configKey }]) => ({ id, type, configKey }))
    .sort((a, b) => {
      const cmp = a.type.localeCompare(b.type);
      return cmp !== 0 ? cmp : a.configKey.localeCompare(b.configKey);
    });

  const edgeEntries = edges
    .filter((e) => included.has(e.source) && included.has(e.target))
    .map((e) => {
      const src = included.get(e.source)!;
      const tgt = included.get(e.target)!;
      return `${src.type}|${src.configKey}->${tgt.type}|${tgt.configKey}|${e.sourceHandle ?? ""}|${e.targetHandle ?? ""}`;
    })
    .sort();

  const canonical = JSON.stringify({
    nodes: sortedNodes.map((n) => `${n.type}:${n.configKey}`),
    edges: edgeEntries,
  });

  return canonical;
}

export function dagFingerprintMatches(
  nodes: NodeLike[],
  edges: EdgeLike[],
  nodeConfigs: Record<string, Record<string, unknown>>,
  storedHash: string | null
): boolean {
  if (!storedHash) return false;
  const current = computeDagFingerprint(nodes, edges, nodeConfigs);
  return current === storedHash;
}

export function workflowUnchangedSinceLastRun(
  nodes: NodeLike[],
  edges: EdgeLike[],
  nodeConfigs: Record<string, Record<string, unknown>>,
  currentFiles: File[] | Record<string, File> | undefined,
  lastRunDagHash: string | null,
  lastRunInputFiles: TaskInputFileIdentity[] | null
): boolean {
  const dagMatch = lastRunDagHash !== null && dagFingerprintMatches(nodes, edges, nodeConfigs, lastRunDagHash);
  if (!dagMatch) return false;

  const fileList: File[] = currentFiles
    ? Array.isArray(currentFiles)
      ? currentFiles
      : Object.values(currentFiles)
    : [];

  if (fileList.length === 0) {
    return lastRunInputFiles === null || lastRunInputFiles.length === 0;
  }

  const currentIdentity: TaskInputFileIdentity[] = fileList
    .map((f) => ({ name: f.name, size: f.size }))
    .sort((a, b) => a.name.localeCompare(b.name) || a.size - b.size);

  return inputFileFingerprint(currentIdentity) === inputFileFingerprint(lastRunInputFiles);
}
