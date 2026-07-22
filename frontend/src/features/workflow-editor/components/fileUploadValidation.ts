function matchesAcceptedType(fileType: string, acceptedType: string): boolean {
  if (acceptedType.endsWith("/*")) {
    const [prefix] = acceptedType.split("/");
    return fileType.startsWith(`${prefix}/`);
  }

  return fileType === acceptedType;
}

export function validateUploadFile(file: File, accept: string[] = [], maxSizeMb = 50, t?: TFunction): string | null {
  if (accept.length > 0 && !accept.some((acceptedType) => matchesAcceptedType(file.type, acceptedType))) {
    return t?.("workflows:editorText.unsupportedFileType", { types: accept.join(", ") }) ?? `檔案類型不支援，允許類型：${accept.join(", ")}`;
  }

  const maxBytes = maxSizeMb * 1024 * 1024;
  if (file.size > maxBytes) {
    return t?.("workflows:editorText.fileTooLarge", { maxSizeMb }) ?? `檔案大小超過限制（${maxSizeMb} MB）`;
  }

  return null;
}
import type { TFunction } from "i18next";
