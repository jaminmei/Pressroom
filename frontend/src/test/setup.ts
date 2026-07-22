import "@testing-library/jest-dom/vitest";
import "@/i18n";
import { vi } from "vitest";

class ResizeObserverMock {
  observe() {
    return undefined;
  }

  unobserve() {
    return undefined;
  }

  disconnect() {
    return undefined;
  }
}

Object.defineProperty(window, "ResizeObserver", {
  writable: true,
  value: window.ResizeObserver ?? ResizeObserverMock
});

Object.defineProperty(window, "matchMedia", {
  writable: true,
  value:
    window.matchMedia ??
    vi.fn().mockImplementation((query: string) => ({
      matches: false,
      media: query,
      onchange: null,
      addListener: vi.fn(),
      removeListener: vi.fn(),
      addEventListener: vi.fn(),
      removeEventListener: vi.fn(),
      dispatchEvent: vi.fn()
    }))
});

const nativeGetComputedStyle = window.getComputedStyle;
window.getComputedStyle = ((element: Element, pseudoElt?: string) =>
  nativeGetComputedStyle(element, pseudoElt ? undefined : pseudoElt)) as typeof window.getComputedStyle;
