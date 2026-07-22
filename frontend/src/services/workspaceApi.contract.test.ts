import { describe, expect, it } from "vitest";
import fixture from "@/contracts/workspace-permission-v1.json";
import { ALL_CAPABILITIES } from "@/types/workspace";
import { adaptCapabilities, describeCapabilityDrift } from "./workspaceApi";

const sorted = (capabilities: readonly string[]) => [...capabilities].sort();

describe("workspace capability adapter contract", () => {
  it.each(Object.entries(fixture.derivations))(
    "derives the exact UI capabilities for backend capability %s",
    (backendCapability, expected) => {
      // Given one canonical backend capability
      // When it crosses the API boundary
      const actual = adaptCapabilities([backendCapability]);

      // Then only its approved UI capabilities are granted
      expect(sorted(actual)).toEqual(sorted(expected));
    },
  );

  it.each(fixture.same_name)("passes through approved same-name capability %s", (capability) => {
    // Given an approved same-name capability
    // When it crosses the API boundary
    const actual = adaptCapabilities([capability]);

    // Then the same capability remains granted
    expect(actual).toContain(capability);
  });

  it("covers every backend and UI capability in the shared fixture", () => {
    // Given the language-neutral capability fixture
    const derived = Object.values(fixture.derivations).flat();

    // When its declared capability sets are compared
    // Then every backend capability has a derivation and every UI capability is named
    expect(sorted(Object.keys(fixture.derivations))).toEqual(sorted(fixture.backend_capabilities));
    expect(sorted([...new Set([...derived, ...fixture.authenticated_global])])).toEqual(
      sorted(ALL_CAPABILITIES),
    );
    expect(fixture.authenticated_global).toEqual(["workspace.create"]);
  });

  it("de-duplicates pass-through and derived capabilities", () => {
    // Given duplicate sources and overlapping derivations
    // When capabilities are adapted
    const actual = adaptCapabilities(["workflow.edit_draft", "workflow.edit_draft"]);

    // Then each UI capability appears once
    expect(actual.filter((capability) => capability === "workflow.edit_draft")).toHaveLength(1);
  });

  it("fails closed while reporting unknown backend capability drift", () => {
    // Given an unknown backend capability
    const backendCapabilities = ["future.super_admin"];

    // When it crosses the API boundary
    const actual = adaptCapabilities(backendCapabilities);

    // Then it grants nothing and parity output names the drift
    expect(actual).toEqual([]);
    expect(describeCapabilityDrift(backendCapabilities)).toEqual(["future.super_admin"]);
  });

  it("returns no capabilities for an empty backend capability set", () => {
    // Given no backend capabilities
    // When the set crosses the API boundary
    const actual = adaptCapabilities([]);

    // Then no UI capabilities are granted
    expect(actual).toEqual([]);
  });
});
