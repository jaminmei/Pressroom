import { render, screen } from "@testing-library/react";
import { describe, expect, it } from "vitest";

import { DOC_CONV_ICON_PATHS, createDocConvIcon } from "./index";

describe("DocConvIcon", () => {
  it("renders project-authored path data through the public icon exports", () => {
    const TestIcon = createDocConvIcon("TestIcon", DOC_CONV_ICON_PATHS.input);

    render(<TestIcon aria-label="Input" color="#123456" size={32} />);

    const icon = screen.getByRole("img", { name: "Input" });
    expect(icon).toHaveAttribute("viewBox", "0 0 2560 2560");
    expect(icon).toHaveAttribute("width", "32");
    expect(icon).toHaveAttribute("fill", "#123456");
    expect(icon.querySelectorAll("path")).toHaveLength(DOC_CONV_ICON_PATHS.input.length);
  });
});
