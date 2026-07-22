import { diffLines } from "diff";
import { useMemo } from "react";

export type DiffLineType = "same" | "added" | "removed" | "modified";

export interface DiffLine {
  content: string;
  type: DiffLineType;
  isPlaceholder: boolean;
}

export interface DiffHighlightResult {
  leftLines: DiffLine[];
  rightLines: DiffLine[];
  hasDiff: boolean;
}

interface DiffSegment {
  type: "same" | "added" | "removed";
  lines: string[];
}

const splitIntoLines = (value: string): string[] => {
  if (!value) {
    return [];
  }

  const lines = value.split("\n");

  if (lines[lines.length - 1] === "") {
    lines.pop();
  }

  return lines;
};

function normalizeDiffInput(value: string): string {
  if (value.length === 0 || value.endsWith("\n")) {
    return value;
  }

  return `${value}\n`;
}

const buildDiffSegments = (leftText: string, rightText: string): DiffSegment[] => {
  const rawSegments: DiffSegment[] = [];
  const push = (type: DiffSegment["type"], line: string) => {
    const last = rawSegments[rawSegments.length - 1];
    if (last?.type === type) {
      last.lines.push(line);
      return;
    }
    rawSegments.push({ type, lines: [line] });
  };

  const changes = diffLines(normalizeDiffInput(leftText), normalizeDiffInput(rightText));
  for (const change of changes) {
    const lines = splitIntoLines(change.value);
    if (lines.length === 0) {
      continue;
    }

    const type: DiffSegment["type"] = change.added ? "added" : change.removed ? "removed" : "same";
    lines.forEach((line) => push(type, line));
  }

  return rawSegments;
};

export const useDiffHighlight = (leftText: string, rightText: string): DiffHighlightResult => {
  return useMemo(() => {
    const segments = buildDiffSegments(leftText, rightText);
    const leftLines: DiffLine[] = [];
    const rightLines: DiffLine[] = [];
    let hasDiff = false;

    for (let segmentIndex = 0; segmentIndex < segments.length; segmentIndex += 1) {
      const segment = segments[segmentIndex];
      if (segment.type === "same") {
        segment.lines.forEach((line) => {
          leftLines.push({ content: line, type: "same", isPlaceholder: false });
          rightLines.push({ content: line, type: "same", isPlaceholder: false });
        });
        continue;
      }

      hasDiff = true;

      if (segment.type === "removed") {
        const nextSegment = segments[segmentIndex + 1];
        if (nextSegment?.type === "added") {
          const pairCount = Math.max(segment.lines.length, nextSegment.lines.length);
          for (let lineIndex = 0; lineIndex < pairCount; lineIndex += 1) {
            const hasLeft = lineIndex < segment.lines.length;
            const hasRight = lineIndex < nextSegment.lines.length;
            const lineType: DiffLineType =
              hasLeft && hasRight ? "modified" : hasLeft ? "removed" : "added";

            leftLines.push({
              content: hasLeft ? segment.lines[lineIndex] : "",
              type: lineType,
              isPlaceholder: !hasLeft
            });
            rightLines.push({
              content: hasRight ? nextSegment.lines[lineIndex] : "",
              type: lineType,
              isPlaceholder: !hasRight
            });
          }
          segmentIndex += 1;
          continue;
        }

        segment.lines.forEach((line) => {
          leftLines.push({ content: line, type: "removed", isPlaceholder: false });
          rightLines.push({ content: "", type: "removed", isPlaceholder: true });
        });
        continue;
      }

      segment.lines.forEach((line) => {
        leftLines.push({ content: "", type: "added", isPlaceholder: true });
        rightLines.push({ content: line, type: "added", isPlaceholder: false });
      });
    }

    return {
      leftLines,
      rightLines,
      hasDiff
    };
  }, [leftText, rightText]);
};
