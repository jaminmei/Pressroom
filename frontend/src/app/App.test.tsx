import { render, screen } from "@testing-library/react";
import { describe, expect, it, vi } from "vitest";

vi.mock("react-router-dom", () => ({
  RouterProvider: ({ router }: { router: unknown }) => <div data-testid="router-provider">{String(Boolean(router))}</div>
}));

vi.mock("@/app/routes", () => ({
  router: { mocked: true }
}));

import App from "@/app/App";

describe("App", () => {
  it("renders the router provider", () => {
    render(<App />);

    expect(screen.getByTestId("router-provider")).toHaveTextContent("true");
  });
});
