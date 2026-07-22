import type { TaskInputFileIdentity } from "@/types/task";

export function inputFileFingerprint(files: TaskInputFileIdentity[] | undefined | null): string {
  if (!files || files.length === 0) return "";
  return files
    .slice()
    .sort((a, b) => a.name.localeCompare(b.name) || a.size - b.size)
    .map((f) => `${f.name}:${f.size}`)
    .join("|");
}

export function inputFilesMatch(
  a: TaskInputFileIdentity[] | undefined | null,
  b: TaskInputFileIdentity[] | undefined | null
): boolean {
  return inputFileFingerprint(a) === inputFileFingerprint(b);
}
