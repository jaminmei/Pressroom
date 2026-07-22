export type {
  DiffField,
  DocumentGroundTruth,
  GroundTruthVersionSummary,
  GTVersion,
  Project,
  ProjectDocument,
  ProjectRun,
  RunResult,
} from "@/types/project";

export interface FieldDiff {
  fieldName: string;
  expected: string;
  actual: string;
  status: "match" | "mismatch";
}
