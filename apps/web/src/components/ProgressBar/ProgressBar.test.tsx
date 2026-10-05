import { render, screen } from "@testing-library/react";
import { describe, expect, it } from "vitest";
import { ProgressBar } from "./ProgressBar";

describe("ProgressBar", () => {
  it.each([
    [0.4, "40"],
    [1.5, "100"],
    [-1, "0"],
    [Number.NaN, "0"]
  ])("reports %s as %s percent", (value, percent) => {
    render(<ProgressBar value={value} label="处理进度" />);
    const bar = screen.getByRole("progressbar", { name: "处理进度" });
    expect(bar).toHaveAttribute("aria-valuenow", percent);
    expect(bar).toHaveAttribute("aria-valuetext", `${percent}%`);
  });
});
