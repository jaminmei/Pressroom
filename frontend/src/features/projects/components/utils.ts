import type { FieldDiff } from "@/features/projects/types";
import type { DiffField } from "@/types/project";

export function diffToFieldDiff(diff: DiffField[]): FieldDiff[] {
  return diff.map((f) => ({
    fieldName: f.fieldName,
    expected: f.expected,
    actual: f.actual,
    status: f.match ? "match" : "mismatch",
  }));
}