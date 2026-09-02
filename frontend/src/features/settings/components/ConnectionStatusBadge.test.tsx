import "@testing-library/jest-dom/vitest";
import { render, screen } from "@testing-library/react";
import { describe, expect, it } from "vitest";

import ConnectionStatusBadge from "./ConnectionStatusBadge";

const healthyResult = {
  status: "healthy" as const,
  latency_ms: 45,
  error: null,
  details: null,
  model_results: null,
};

const unhealthyResult = {
  status: "unhealthy" as const,
  latency_ms: null,
  error: "Connection refused",
  details: null,
  model_results: null,
};

const noHealthUrlResult = {
  status: "unavailable" as const,
  error_code: "PROVIDER_HEALTH_URL_MISSING",
  latency_ms: null,
  error: "No health URL configured",
  details: null,
  model_results: null,
};

const noModelsResult = {
  status: "unavailable" as const,
  error_code: "PROVIDER_MODELS_UNAVAILABLE",
  latency_ms: null,
  error: "No models configured",
  details: null,
  model_results: null,
};

const vlmHealthyResult = {
  status: "healthy" as const,
  latency_ms: 120,
  error: null,
  details: { ok: 2, total: 2 },
  model_results: [
    { model_id: "gpt-4", display_name: "GPT-4", status: "ok" as const, latency_ms: 60, error: null },
    { model_id: "gpt-5", display_name: "GPT-5", status: "ok" as const, latency_ms: 55, error: null },
  ],
};

const vlmMixedResult = {
  status: "unhealthy" as const,
  latency_ms: 100,
  error: null,
  details: { ok: 1, total: 2 },
  model_results: [
    { model_id: "gpt-4", display_name: "GPT-4", status: "ok" as const, latency_ms: 50, error: null },
    { model_id: "gpt-5", display_name: "GPT-5", status: "failed" as const, latency_ms: 30, error: "Connection refused" },
  ],
};

describe("ConnectionStatusBadge", () => {
  it("T-BADGE-01: Healthy (engine_service) — shows green badge with latency", () => {
    render(<ConnectionStatusBadge result={healthyResult} />);

    expect(screen.getByText(/Healthy/)).toBeInTheDocument();
    expect(screen.getByText(/45ms/)).toBeInTheDocument();
  });

  it("T-BADGE-02: Unhealthy (engine_service) — shows red badge", () => {
    render(<ConnectionStatusBadge result={unhealthyResult} />);

    expect(screen.getByText("Unhealthy")).toBeInTheDocument();
  });

  it("T-BADGE-03: No health URL — shows warning badge", () => {
    render(<ConnectionStatusBadge result={noHealthUrlResult} />);

    expect(screen.getByText("No Health URL")).toBeInTheDocument();
  });

  it("T-BADGE-04: No models — shows warning badge", () => {
    render(<ConnectionStatusBadge result={noModelsResult} />);

    expect(screen.getByText("No Models")).toBeInTheDocument();
  });

  it("T-BADGE-05: VLM all healthy — shows summary and per-model badges", () => {
    render(<ConnectionStatusBadge result={vlmHealthyResult} />);

    expect(screen.getByText("2/2 models OK")).toBeInTheDocument();
    expect(screen.getByText(/GPT-4/)).toBeInTheDocument();
    expect(screen.getByText(/GPT-5/)).toBeInTheDocument();
  });

  it("T-BADGE-06: VLM mixed — shows error summary and per-model badges", () => {
    render(<ConnectionStatusBadge result={vlmMixedResult} />);

    expect(screen.getByText("1/2 models OK")).toBeInTheDocument();
    expect(screen.getByText(/GPT-4/)).toBeInTheDocument();
    expect(screen.getByText(/GPT-5/)).toBeInTheDocument();
  });
});
