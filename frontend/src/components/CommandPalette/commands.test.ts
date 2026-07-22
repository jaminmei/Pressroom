import { describe, expect, it, vi } from "vitest";

import { buildDefaultCommands } from "@/components/CommandPalette/commands";
import i18n from "@/i18n";

describe("buildDefaultCommands", () => {
  function buildOptions() {
    return {
      t: i18n.t.bind(i18n),
      executeWorkflow: vi.fn(),
      saveDraft: vi.fn(),
      publishWorkflow: vi.fn(),
      togglePalette: vi.fn(),
      navigateToEditor: vi.fn(),
      navigateToTemplateCenter: vi.fn(),
      openRecentRuns: vi.fn(),
      clearCanvas: vi.fn(),
      templates: [
        {
          id: "tpl-ocr-basic",
          name: "PDF → OCR → Markdown",
          description: "OCR template",
          tags: ["ocr", "pdf", "markdown"]
        }
      ],
      applyTemplate: vi.fn(),
      openHistory: vi.fn(),
      navigateToProjects: vi.fn(),
      createProject: vi.fn()
    };
  }

  it("returns required command set", () => {
    const commands = buildDefaultCommands(buildOptions());

    expect(commands.map((command) => command.label)).toEqual([
      "Go to Editor",
      "Go to Template Center",
      "Toggle Command Palette",
      "Execute Workflow",
      "Save Draft",
      "Publish",
      "Clear Canvas",
      "Apply: PDF → OCR → MD",
      "Open Recent Runs",
      "Open History",
      "Go to Databases",
      "Create Database"
    ]);
  });

  it("wires command action callbacks", () => {
    const applyTemplate = vi.fn();
    const commands = buildDefaultCommands({
      ...buildOptions(),
      applyTemplate
    });

    const target = commands.find((command) => command.id === "template-apply-tpl-ocr-basic");
    target?.action();

    expect(applyTemplate).toHaveBeenCalledWith("tpl-ocr-basic");
  });

  it("assigns capabilities to mutating commands", () => {
    const commands = buildDefaultCommands(buildOptions());
    expect(commands.find(c => c.id === "action-execute-workflow")?.capability).toBe("workflow.run");
    expect(commands.find(c => c.id === "action-publish-workflow")?.capability).toBe("workflow.publish");
    expect(commands.find(c => c.id === "action-clear-canvas")?.capability).toBe("workflow.edit_draft");
    expect(commands.find(c => c.id === "action-save-draft")?.capability).toBe("workflow.edit_draft");
    expect(commands.find(c => c.id === "project-create-project")?.capability).toBe("database.create");
  });

  it("assigns workflow.edit_draft to template-apply commands", () => {
    const commands = buildDefaultCommands(buildOptions());
    const templateCmds = commands.filter(c => c.id.startsWith("template-apply-"));
    templateCmds.forEach(c => expect(c.capability).toBe("workflow.edit_draft"));
  });
});
