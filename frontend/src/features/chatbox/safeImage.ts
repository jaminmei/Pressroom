const SAFE_IMAGE_MIME_TYPES = new Set([
  "image/avif",
  "image/bmp",
  "image/gif",
  "image/jpeg",
  "image/png",
  "image/webp",
]);

export function isSafeImageMimeType(value: string): boolean {
  return SAFE_IMAGE_MIME_TYPES.has(value.toLowerCase());
}
