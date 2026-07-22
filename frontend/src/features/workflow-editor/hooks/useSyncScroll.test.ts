import { act, renderHook } from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";
import type { MockInstance } from "vitest";

import { getScrollRatio, getScrollTopByRatio, useSyncScroll } from "@/features/workflow-editor/hooks/useSyncScroll";

interface ScrollElementOptions {
  clientHeight: number;
  scrollHeight: number;
  scrollTop?: number;
  onScrollTopSet?: () => void;
}

interface ScrollElementController {
  element: HTMLElement;
  getScrollTop: () => number;
  setScrollTop: (value: number) => void;
}

interface RafController {
  requestSpy: MockInstance<(callback: FrameRequestCallback) => number>;
  flushAllFrames: () => void;
  flushNextFrame: () => void;
}

function createScrollElement({
  clientHeight,
  scrollHeight,
  scrollTop = 0,
  onScrollTopSet
}: ScrollElementOptions): ScrollElementController {
  const element = document.createElement("div");
  let currentTop = scrollTop;

  Object.defineProperty(element, "clientHeight", {
    configurable: true,
    get: () => clientHeight
  });

  Object.defineProperty(element, "scrollHeight", {
    configurable: true,
    get: () => scrollHeight
  });

  Object.defineProperty(element, "scrollTop", {
    configurable: true,
    get: () => currentTop,
    set: (value: number) => {
      currentTop = value;
      onScrollTopSet?.();
    }
  });

  return {
    element,
    getScrollTop: () => currentTop,
    setScrollTop: (value) => {
      currentTop = value;
    }
  };
}

function mockRequestAnimationFrame(): RafController {
  const frameQueue: Array<{ id: number; callback: FrameRequestCallback }> = [];
  let nextFrameId = 1;

  const requestSpy = vi.spyOn(window, "requestAnimationFrame").mockImplementation((callback: FrameRequestCallback) => {
    const frameId = nextFrameId;
    nextFrameId += 1;
    frameQueue.push({ id: frameId, callback });
    return frameId;
  });

  vi.spyOn(window, "cancelAnimationFrame").mockImplementation((frameId: number) => {
    const targetIndex = frameQueue.findIndex((entry) => entry.id === frameId);
    if (targetIndex >= 0) {
      frameQueue.splice(targetIndex, 1);
    }
  });

  const flushNextFrame = () => {
    const frame = frameQueue.shift();
    if (!frame) {
      return;
    }

    frame.callback(performance.now());
  };

  const flushAllFrames = () => {
    while (frameQueue.length > 0) {
      flushNextFrame();
    }
  };

  return {
    requestSpy,
    flushAllFrames,
    flushNextFrame
  };
}

describe("useSyncScroll", () => {
  afterEach(() => {
    vi.restoreAllMocks();
  });

  it("computes scroll ratio and target scrollTop using proportional mapping", () => {
    const left = createScrollElement({ scrollHeight: 300, clientHeight: 100, scrollTop: 80 });
    const right = createScrollElement({ scrollHeight: 500, clientHeight: 100 });

    expect(getScrollRatio(left.element)).toBeCloseTo(0.4, 4);
    expect(getScrollTopByRatio(right.element, 0.4)).toBeCloseTo(160, 4);
  });

  it("syncs right container when left container scrolls", () => {
    const raf = mockRequestAnimationFrame();
    const left = createScrollElement({ scrollHeight: 300, clientHeight: 100, scrollTop: 100 });
    const right = createScrollElement({ scrollHeight: 500, clientHeight: 100, scrollTop: 0 });

    const leftRef = { current: left.element };
    const rightRef = { current: right.element };

    const { result } = renderHook(() => useSyncScroll({ leftRef, rightRef, enabled: true }));

    act(() => {
      result.current.handleLeftScroll();
    });

    act(() => {
      raf.flushAllFrames();
    });

    expect(right.getScrollTop()).toBeCloseTo(200, 4);
  });

  it("throttles burst scroll events to a single animation frame", () => {
    const raf = mockRequestAnimationFrame();
    const left = createScrollElement({ scrollHeight: 300, clientHeight: 100, scrollTop: 0 });
    const right = createScrollElement({ scrollHeight: 500, clientHeight: 100, scrollTop: 0 });

    const leftRef = { current: left.element };
    const rightRef = { current: right.element };

    const { result } = renderHook(() => useSyncScroll({ leftRef, rightRef, enabled: true }));

    act(() => {
      left.setScrollTop(40);
      result.current.handleLeftScroll();
      left.setScrollTop(100);
      result.current.handleLeftScroll();
      left.setScrollTop(150);
      result.current.handleLeftScroll();
    });

    expect(raf.requestSpy).toHaveBeenCalledTimes(1);

    act(() => {
      raf.flushAllFrames();
    });

    expect(right.getScrollTop()).toBeCloseTo(300, 4);
  });

  it("prevents recursive A→B→A syncing with lock flag", () => {
    const raf = mockRequestAnimationFrame();
    let handleRightScroll: (() => void) | null = null;

    const left = createScrollElement({ scrollHeight: 300, clientHeight: 100, scrollTop: 100 });
    const right = createScrollElement({
      scrollHeight: 500,
      clientHeight: 100,
      scrollTop: 0,
      onScrollTopSet: () => {
        handleRightScroll?.();
      }
    });

    const leftRef = { current: left.element };
    const rightRef = { current: right.element };

    const { result } = renderHook(() => {
      const sync = useSyncScroll({ leftRef, rightRef, enabled: true });
      handleRightScroll = sync.handleRightScroll;
      return sync;
    });

    act(() => {
      result.current.handleLeftScroll();
    });

    expect(raf.requestSpy).toHaveBeenCalledTimes(1);

    act(() => {
      raf.flushNextFrame();
    });

    expect(right.getScrollTop()).toBeCloseTo(200, 4);
    expect(raf.requestSpy).toHaveBeenCalledTimes(2);

    act(() => {
      raf.flushNextFrame();
    });

    expect(raf.requestSpy).toHaveBeenCalledTimes(2);
  });

  it("does not sync scroll positions when synchronization is disabled", () => {
    const raf = mockRequestAnimationFrame();
    const left = createScrollElement({ scrollHeight: 300, clientHeight: 100, scrollTop: 100 });
    const right = createScrollElement({ scrollHeight: 500, clientHeight: 100, scrollTop: 0 });

    const leftRef = { current: left.element };
    const rightRef = { current: right.element };

    const { result, rerender } = renderHook(
      ({ enabled }) => useSyncScroll({ leftRef, rightRef, enabled }),
      {
        initialProps: { enabled: true }
      }
    );

    act(() => {
      result.current.handleLeftScroll();
      raf.flushAllFrames();
    });

    expect(right.getScrollTop()).toBeCloseTo(200, 4);

    right.setScrollTop(0);

    rerender({ enabled: false });
    left.setScrollTop(50);

    act(() => {
      result.current.handleLeftScroll();
      raf.flushAllFrames();
    });

    expect(right.getScrollTop()).toBe(0);
  });
});
