import { useCallback, useEffect, useRef } from "react";
import type { RefObject } from "react";

type ScrollSide = "left" | "right";

interface ScrollContainer {
  scrollTop: number;
  scrollHeight: number;
  clientHeight: number;
}

interface UseSyncScrollParams {
  leftRef: RefObject<HTMLElement | null>;
  rightRef: RefObject<HTMLElement | null>;
  enabled: boolean;
}

interface UseSyncScrollResult {
  handleLeftScroll: () => void;
  handleRightScroll: () => void;
}

type FrameHandle = number | ReturnType<typeof globalThis.setTimeout>;

function requestFrame(callback: FrameRequestCallback): FrameHandle {
  if (typeof window !== "undefined" && typeof window.requestAnimationFrame === "function") {
    return window.requestAnimationFrame(callback);
  }

  return globalThis.setTimeout(() => callback(Date.now()), 16);
}

function cancelFrame(handle: FrameHandle): void {
  if (typeof window !== "undefined" && typeof window.cancelAnimationFrame === "function") {
    window.cancelAnimationFrame(handle as number);
    return;
  }

  globalThis.clearTimeout(handle);
}

const getScrollableHeight = (element: ScrollContainer): number => {
  return Math.max(element.scrollHeight - element.clientHeight, 0);
};

export const getScrollRatio = (element: ScrollContainer): number => {
  const scrollableHeight = getScrollableHeight(element);
  if (scrollableHeight === 0) {
    return 0;
  }

  return Math.min(Math.max(element.scrollTop / scrollableHeight, 0), 1);
};

export const getScrollTopByRatio = (element: ScrollContainer, ratio: number): number => {
  const scrollableHeight = getScrollableHeight(element);
  const boundedRatio = Math.min(Math.max(ratio, 0), 1);
  return boundedRatio * scrollableHeight;
};

export const useSyncScroll = ({ leftRef, rightRef, enabled }: UseSyncScrollParams): UseSyncScrollResult => {
  const syncingRef = useRef(false);
  const pendingSourceRef = useRef<ScrollSide | null>(null);
  const syncRafRef = useRef<FrameHandle | null>(null);
  const unlockRafRef = useRef<FrameHandle | null>(null);

  const clearSyncFrame = useCallback(() => {
    if (syncRafRef.current !== null) {
      cancelFrame(syncRafRef.current);
      syncRafRef.current = null;
    }
  }, []);

  const clearUnlockFrame = useCallback(() => {
    if (unlockRafRef.current !== null) {
      cancelFrame(unlockRafRef.current);
      unlockRafRef.current = null;
    }
  }, []);

  const unlockOnNextFrame = useCallback(() => {
    clearUnlockFrame();
    unlockRafRef.current = requestFrame(() => {
      unlockRafRef.current = null;
      syncingRef.current = false;
    });
  }, [clearUnlockFrame]);

  const scheduleSync = useCallback(
    (source: ScrollSide) => {
      if (!enabled || syncingRef.current) {
        return;
      }

      pendingSourceRef.current = source;
      if (syncRafRef.current !== null) {
        return;
      }

      syncRafRef.current = requestFrame(() => {
        syncRafRef.current = null;

        const activeSource = pendingSourceRef.current;
        pendingSourceRef.current = null;

        if (!enabled || syncingRef.current || activeSource === null) {
          return;
        }

        const sourceElement = activeSource === "left" ? leftRef.current : rightRef.current;
        const targetElement = activeSource === "left" ? rightRef.current : leftRef.current;

        if (!sourceElement || !targetElement) {
          return;
        }

        const sourceRatio = getScrollRatio(sourceElement);
        const targetScrollTop = getScrollTopByRatio(targetElement, sourceRatio);

        if (Math.abs(targetElement.scrollTop - targetScrollTop) < 0.5) {
          return;
        }

        syncingRef.current = true;
        targetElement.scrollTop = targetScrollTop;
        unlockOnNextFrame();
      });
    },
    [enabled, leftRef, rightRef, unlockOnNextFrame]
  );

  const handleLeftScroll = useCallback(() => {
    scheduleSync("left");
  }, [scheduleSync]);

  const handleRightScroll = useCallback(() => {
    scheduleSync("right");
  }, [scheduleSync]);

  useEffect(() => {
    if (!enabled) {
      pendingSourceRef.current = null;
      syncingRef.current = false;
      clearSyncFrame();
      clearUnlockFrame();
    }
  }, [clearSyncFrame, clearUnlockFrame, enabled]);

  useEffect(() => {
    return () => {
      clearSyncFrame();
      clearUnlockFrame();
      pendingSourceRef.current = null;
      syncingRef.current = false;
    };
  }, [clearSyncFrame, clearUnlockFrame]);

  return {
    handleLeftScroll,
    handleRightScroll
  };
};
