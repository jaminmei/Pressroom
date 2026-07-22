import { act, renderHook } from "@testing-library/react";
import { MemoryRouter } from "react-router-dom";
import { beforeEach, describe, expect, it, vi } from "vitest";

import { useDomainShortcuts } from "@/features/projects/hooks/useDomainShortcuts";
import { initialUIState, useUIStore } from "@/stores/uiStore";

const navigate = vi.fn();
let pathname = "/studio";

vi.mock("react-router-dom", async (importOriginal) => {
  const actual = await importOriginal<typeof import("react-router-dom")>();
  return {
    ...actual,
    useLocation: () => ({ pathname, search: "", hash: "", state: null, key: "test" }),
    useNavigate: () => navigate,
  };
});

describe("useDomainShortcuts", () => {
  beforeEach(() => {
    navigate.mockReset();
    pathname = "/studio";
    useUIStore.setState(initialUIState);
  });

  it("recognizes the projects alias and saves its canonical database route", () => {
    pathname = "/projects/db_1";

    renderHook(() => useDomainShortcuts(), { wrapper: MemoryRouter });

    expect(useUIStore.getState().lastDatabaseRoute).toBe("/database/db_1");
  });

  it("returns to the canonical database route from either database alias", () => {
    pathname = "/database/db_2";
    renderHook(() => useDomainShortcuts(), { wrapper: MemoryRouter });

    act(() => {
      window.dispatchEvent(new KeyboardEvent("keydown", { ctrlKey: true, key: "2" }));
    });

    expect(navigate).toHaveBeenCalledWith("/database/db_2");
  });
});
