import { describe, expect, it, vi } from "vitest";
import { createPlayhead } from "./playhead";

describe("createPlayhead", () => {
  it("stores the time and notifies subscribers only when it changes", () => {
    const playhead = createPlayhead(0.3);
    const listener = vi.fn();
    const unsubscribe = playhead.subscribe(listener);

    expect(playhead.get()).toBe(0.3);
    playhead.set(0.3);
    expect(listener).not.toHaveBeenCalled();
    playhead.set(0.6);
    expect(playhead.get()).toBe(0.6);
    expect(listener).toHaveBeenCalledTimes(1);

    unsubscribe();
    playhead.set(0.9);
    expect(listener).toHaveBeenCalledTimes(1);
  });
});
