import { describe, expect, it } from "vitest";
import { extractSourceUrl, normalizeSource } from "./sourceLink";

const BILIBILI =
  "https://www.bilibili.com/video/BV1EqVJ6dE6R/?share_source=copy_web&vd_source=f6c20e2fb7bb1ba13441ae3b14ead724";

describe("extractSourceUrl", () => {
  it.each([
    [
      `【【全英vlog】Vlo·07｜跟着油管博主 Sydney Serena 学真实口语 |“朋友都很忙时，如何学会享受独处？”】 ${BILIBILI}`,
      BILIBILI
    ],
    [BILIBILI, BILIBILI],
    ["【标题】https://b23.tv/AbC123，快来看", "https://b23.tv/AbC123"],
    ["看这个：https://youtu.be/dQw4w9WgXcQ?t=42。", "https://youtu.be/dQw4w9WgXcQ?t=42"],
    [
      "(https://www.youtube.com/watch?v=dQw4w9WgXcQ)",
      "https://www.youtube.com/watch?v=dQw4w9WgXcQ"
    ],
    ["https://a.test/1 https://b.test/2", "https://a.test/1"],
    ["HTTP://EXAMPLE.TEST/V", "HTTP://EXAMPLE.TEST/V"]
  ])("extracts the link from %j", (text, expected) => {
    expect(extractSourceUrl(text)).toBe(expected);
  });

  it.each(["", "只有文字没有链接", "/Users/me/talk.mp4", "https://", "ftp://example.test/v"])(
    "returns null for %j",
    (text) => {
      expect(extractSourceUrl(text)).toBeNull();
    }
  );
});

describe("normalizeSource", () => {
  it("keeps non-link input as a trimmed local path", () => {
    expect(normalizeSource("  /Users/me/talk.mp4 ")).toBe("/Users/me/talk.mp4");
  });

  it("drops the share text around a link", () => {
    expect(normalizeSource(`【标题】 ${BILIBILI}  `)).toBe(BILIBILI);
  });
});
