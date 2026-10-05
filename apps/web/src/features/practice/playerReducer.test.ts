import { describe, expect, it } from "vitest";
import {
  initialPlayerState,
  nextRepeat,
  playerReducer,
  stepRate,
  type PlayerEvent,
  type PlayerState
} from "./playerReducer";

function run(events: PlayerEvent[], from: Partial<PlayerState> = {}): PlayerState {
  return events.reduce(playerReducer, { ...initialPlayerState, ...from });
}

const completed = (sentenceCount = 3): PlayerEvent => ({ type: "completed", sentenceCount });

describe("defaults", () => {
  it("starts blind, paused, once, 1x, 1s gap, no auto advance", () => {
    expect(initialPlayerState).toMatchObject({
      sentenceIndex: 0,
      playCount: 0,
      revealed: false,
      playing: false,
      rate: 1,
      repeat: 1,
      gapMode: { kind: "fixed", seconds: 1 },
      autoAdvance: false,
      alwaysHide: true
    });
    expect(initialPlayerState.visitedIndexes.size).toBe(0);
  });
});

describe("select and move", () => {
  it("select stops playback, clears the loop count, re-veils and marks visited", () => {
    const state = run([{ type: "select", index: 2 }], {
      playing: true,
      playCount: 1,
      revealed: true
    });
    expect(state).toMatchObject({
      sentenceIndex: 2,
      playCount: 0,
      playing: false,
      revealed: false
    });
    expect([...state.visitedIndexes]).toEqual([2]);
  });

  it("select keeps the text revealed when alwaysHide is off", () => {
    const state = run([{ type: "select", index: 1 }], { revealed: true, alwaysHide: false });
    expect(state.revealed).toBe(true);
  });

  it("move is relative to the latest index, so rapid presses all count", () => {
    const next: PlayerEvent = { type: "move", offset: 1, sentenceCount: 5 };
    expect(run([next, next, next]).sentenceIndex).toBe(3);
  });

  it("move never leaves the sentence range and leaves state untouched at the edges", () => {
    const before = { ...initialPlayerState, playCount: 1 };
    expect(playerReducer(before, { type: "move", offset: -1, sentenceCount: 3 })).toBe(before);
    const last = { ...initialPlayerState, sentenceIndex: 2, playCount: 1 };
    expect(playerReducer(last, { type: "move", offset: 1, sentenceCount: 3 })).toBe(last);
  });
});

describe("playback flags", () => {
  it("togglePlaying and setPlaying", () => {
    expect(run([{ type: "togglePlaying" }]).playing).toBe(true);
    expect(run([{ type: "togglePlaying" }, { type: "togglePlaying" }]).playing).toBe(false);
    expect(run([{ type: "setPlaying", value: true }]).playing).toBe(true);
  });

  it("replay starts playing from a fresh loop and bumps the replay counter", () => {
    const state = run([{ type: "replay" }], { playCount: 2, replayCount: 4 });
    expect(state).toMatchObject({ playing: true, playCount: 0, replayCount: 5 });
  });

  it("toggleReveal, toggleAutoAdvance and toggleAlwaysHide flip their flag", () => {
    const state = run([
      { type: "toggleReveal" },
      { type: "toggleAutoAdvance" },
      { type: "toggleAlwaysHide" }
    ]);
    expect(state).toMatchObject({ revealed: true, autoAdvance: true, alwaysHide: false });
  });
});

describe("rate", () => {
  it.each([
    [0.3, 0.6],
    [0.6, 0.6],
    [0.85, 0.85],
    [1.25, 1.25],
    [2, 1.25]
  ])("clamps %s to %s", (value, expected) => {
    expect(run([{ type: "setRate", value }]).rate).toBe(expected);
  });

  it.each([Number.NaN, Number.POSITIVE_INFINITY])("ignores non-finite %s", (value) => {
    expect(run([{ type: "setRate", value }], { rate: 0.9 }).rate).toBe(0.9);
  });

  it("steps by 0.05 without floating point drift and stops at the bounds", () => {
    const faster: PlayerEvent = { type: "stepRate", direction: 1 };
    const slower: PlayerEvent = { type: "stepRate", direction: -1 };
    expect(run([slower, slower, slower]).rate).toBe(0.85);
    expect(run(Array(10).fill(faster)).rate).toBe(1.25);
    expect(run(Array(20).fill(slower)).rate).toBe(0.6);
    expect(stepRate(0.7, 1)).toBe(0.75);
  });
});

describe("repeat and gap", () => {
  it("setRepeat resets the loop count", () => {
    expect(run([{ type: "setRepeat", value: 3 }], { playCount: 2 })).toMatchObject({
      repeat: 3,
      playCount: 0
    });
  });

  it("cycles 1 → 2 → 3 → 5 → infinite → 1", () => {
    expect([1, 2, 3, 5, "infinite"].map((value) => nextRepeat(value as never))).toEqual([
      2,
      3,
      5,
      "infinite",
      1
    ]);
    expect(run([{ type: "cycleRepeat" }, { type: "cycleRepeat" }]).repeat).toBe(3);
  });

  it("setGap stores fixed and sentence-length gaps", () => {
    expect(run([{ type: "setGap", value: { kind: "sentence" } }]).gapMode).toEqual({
      kind: "sentence"
    });
    expect(run([{ type: "setGap", value: { kind: "fixed", seconds: 3 } }]).gapMode).toEqual({
      kind: "fixed",
      seconds: 3
    });
  });
});

describe("completed", () => {
  it("counts finite loops, then stops on the same sentence", () => {
    const first = run([completed()], { repeat: 3, playing: true });
    expect(first).toMatchObject({ playCount: 1, playing: false, sentenceIndex: 0 });
    const second = playerReducer({ ...first, playing: true }, completed());
    expect(second.playCount).toBe(2);
    const done = playerReducer({ ...second, playing: true }, completed());
    expect(done).toMatchObject({ playCount: 0, playing: false, sentenceIndex: 0 });
  });

  it("keeps looping forever on the current sentence when repeat is infinite", () => {
    const state = run(Array(50).fill(completed()), { repeat: "infinite", autoAdvance: true });
    expect(state).toMatchObject({ sentenceIndex: 0, playCount: 50 });
  });

  it("advances after the last loop when autoAdvance is on, re-veiling the text", () => {
    const state = run([completed()], { autoAdvance: true, revealed: true });
    expect(state).toMatchObject({ sentenceIndex: 1, playCount: 0, revealed: false });
    expect([...state.visitedIndexes]).toEqual([0]);
  });

  it("never advances past the last sentence", () => {
    const state = run([completed(3)], { autoAdvance: true, sentenceIndex: 2 });
    expect(state).toMatchObject({ sentenceIndex: 2, playCount: 0, playing: false });
  });

  it("marks the finished sentence as practiced", () => {
    expect([...run([completed()], { sentenceIndex: 1 }).visitedIndexes]).toEqual([1]);
  });
});

describe("reset", () => {
  it("returns to sentence 0 and forgets practiced marks but keeps preferences", () => {
    const state = run([{ type: "reset" }], {
      sentenceIndex: 4,
      playCount: 1,
      playing: true,
      revealed: true,
      rate: 0.8,
      repeat: 5,
      autoAdvance: true,
      visitedIndexes: new Set([1, 4])
    });
    expect(state).toMatchObject({
      sentenceIndex: 0,
      playCount: 0,
      playing: false,
      revealed: false,
      rate: 0.8,
      repeat: 5,
      autoAdvance: true
    });
    expect(state.visitedIndexes.size).toBe(0);
  });
});

it("never mutates the previous state", () => {
  const before = { ...initialPlayerState, visitedIndexes: new Set([1]) };
  const after = playerReducer(before, { type: "select", index: 2 });
  expect([...before.visitedIndexes]).toEqual([1]);
  expect(after.visitedIndexes).not.toBe(before.visitedIndexes);
});

describe("listenCounts", () => {
  it("starts empty", () => {
    expect(initialPlayerState.listenCounts.size).toBe(0);
  });

  it("counts every completed play per sentence, including loops and auto advance", () => {
    const state = run([completed(), completed(), { type: "select", index: 2 }, completed()], {
      repeat: 3
    });
    expect(state.listenCounts.get(0)).toBe(2);
    expect(state.listenCounts.get(2)).toBe(1);
    expect(state.listenCounts.has(1)).toBe(false);

    const advanced = run([completed()], { autoAdvance: true });
    expect(advanced.listenCounts.get(0)).toBe(1);
    expect(advanced.sentenceIndex).toBe(1);
  });

  it("is cleared by reset because sentence indexes change", () => {
    const state = run([completed(), { type: "reset" }]);
    expect(state.listenCounts.size).toBe(0);
  });
});
