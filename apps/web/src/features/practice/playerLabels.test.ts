import { describe, expect, it } from "vitest";
import { formatClock, formatDuration, formatLoop, formatStart } from "./playerLabels";

describe("playerLabels", () => {
  it.each([
    [0, "00:00.0"],
    [1.23, "00:01.2"],
    [59.96, "00:59.9"],
    [61.05, "01:01.0"],
    [-0.4, "00:00.0"]
  ])("formatClock(%s) = %s", (seconds, expected) => {
    expect(formatClock(seconds)).toBe(expected);
  });

  it("formats sentence durations", () => {
    expect(formatDuration(2.94)).toBe("2.9s");
  });

  it.each([
    [3.2, "00:03"],
    [63.9, "01:04"],
    [3599.6, "1:00:00"],
    [3725, "1:02:05"],
    [-1, "00:00"]
  ])("formatStart(%s) = %s", (seconds, expected) => {
    expect(formatStart(seconds)).toBe(expected);
  });

  it("caps the loop round at the repeat count and marks infinite loops", () => {
    expect(formatLoop(0, 1)).toBe("循环 1/1");
    expect(formatLoop(1, 3)).toBe("循环 2/3");
    expect(formatLoop(5, 3)).toBe("循环 3/3");
    expect(formatLoop(3, "infinite")).toBe("循环 4/∞");
  });
});
