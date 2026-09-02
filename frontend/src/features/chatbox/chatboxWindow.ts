export interface ChatboxWindowSize {
  readonly width: number;
  readonly height: number;
}

export interface PointerPosition {
  readonly x: number;
  readonly y: number;
}

export const CHATBOX_MIN_WIDTH = 360;
export const CHATBOX_MAX_WIDTH = 760;
export const CHATBOX_MIN_HEIGHT = 420;
export const CHATBOX_MAX_HEIGHT = 900;
export const CHATBOX_VIEWPORT_MARGIN = 48;

export function resizeChatboxWindow(
  startSize: ChatboxWindowSize,
  startPointer: PointerPosition,
  pointer: PointerPosition,
  viewport: ChatboxWindowSize,
): ChatboxWindowSize {
  const maxWidth = Math.max(
    CHATBOX_MIN_WIDTH,
    Math.min(CHATBOX_MAX_WIDTH, viewport.width - CHATBOX_VIEWPORT_MARGIN),
  );
  const maxHeight = Math.max(
    CHATBOX_MIN_HEIGHT,
    Math.min(CHATBOX_MAX_HEIGHT, viewport.height - CHATBOX_VIEWPORT_MARGIN),
  );
  return {
    width: Math.max(
      CHATBOX_MIN_WIDTH,
      Math.min(maxWidth, startSize.width + startPointer.x - pointer.x),
    ),
    height: Math.max(
      CHATBOX_MIN_HEIGHT,
      Math.min(maxHeight, startSize.height + startPointer.y - pointer.y),
    ),
  };
}
