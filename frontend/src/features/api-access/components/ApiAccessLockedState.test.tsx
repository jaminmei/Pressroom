import "@testing-library/jest-dom/vitest";
import { fireEvent, render, screen } from "@testing-library/react";
import { MemoryRouter, Route, Routes } from "react-router-dom";
import { describe, expect, it, vi } from "vitest";

import ApiAccessLockedState from "@/features/api-access/components/ApiAccessLockedState";

const navigateMock = vi.fn();
vi.mock("react-router-dom", async () => {
  const actual = await vi.importActual<typeof import("react-router-dom")>("react-router-dom");
  return { ...actual, useNavigate: () => navigateMock };
});

function renderLocked(workflowId: string) {
  return render(
    <MemoryRouter>
      <Routes>
        <Route element={<ApiAccessLockedState workflowId={workflowId} />} path="/" />
      </Routes>
    </MemoryRouter>
  );
}

describe("ApiAccessLockedState", () => {
  it("renders a lock message explaining publish is required", () => {
    renderLocked("wf_x");

    expect(screen.getByText(/requires a published workflow/i)).toBeInTheDocument();
    expect(screen.queryByRole("button", { name: /generate/i })).not.toBeInTheDocument();
  });

  it("navigates to the editor when the primary action is clicked", () => {
    renderLocked("wf_x");

    fireEvent.click(screen.getByRole("button", { name: /open in editor|back to editor|publish/i }));

    expect(navigateMock).toHaveBeenCalledWith("/workflows/wf_x");
  });
});
