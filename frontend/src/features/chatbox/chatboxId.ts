let fallbackSequence = 0;

export function generateChatboxId(prefix: string): string {
  const randomUuid = globalThis.crypto?.randomUUID;
  if (typeof randomUuid === "function") {
    return `${prefix}-${randomUuid.call(globalThis.crypto)}`;
  }

  fallbackSequence += 1;
  const timestamp = Date.now().toString(36);
  const random = Math.random().toString(36).slice(2, 10);
  return `${prefix}-${timestamp}-${fallbackSequence.toString(36)}-${random}`;
}
