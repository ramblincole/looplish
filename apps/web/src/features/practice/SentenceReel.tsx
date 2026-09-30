import { useEffect, useId, useRef, useState } from "react";
import type { JobResult } from "../../api/types";
import { usePlayer } from "./playerContext";

type Sentence = JobResult["sentences"][number];

function formatClock(seconds: number): string {
  const total = Math.max(0, Math.floor(seconds));
  const minutes = Math.floor(total / 60);
  return `${minutes}:${String(total % 60).padStart(2, "0")}`;
}

export function SentenceReel({ sentences }: { sentences: Sentence[] }) {
  const { state, send } = usePlayer();
  const [query, setQuery] = useState("");
  const searchId = useId();
  const currentRef = useRef<HTMLButtonElement | null>(null);
  const needle = query.trim().toLowerCase();
  const matches = needle
    ? sentences.filter((sentence) => sentence.text.toLowerCase().includes(needle))
    : sentences;
  // 盲听模式下列表不预先剧透原文；用户主动搜索时才显示命中句的文本。
  const showText = !state.alwaysHide || needle.length > 0;

  useEffect(() => {
    // 自动前进或快捷键切句后，让当前句保持在列表可见区域内。
    currentRef.current?.scrollIntoView?.({ block: "nearest" });
  }, [state.sentenceIndex]);

  return (
    <nav className="reel" aria-label="句子列表">
      <label htmlFor={searchId}>搜索句子</label>
      <input
        id={searchId}
        type="search"
        value={query}
        onChange={(event) => setQuery(event.target.value)}
        placeholder="输入单词或短语"
      />
      <p className="reel-summary" role="status">
        {needle
          ? `找到 ${matches.length} 句`
          : `共 ${sentences.length} 句，已练 ${state.visitedIndexes.size} 句`}
      </p>
      <ol>
        {matches.map((sentence) => {
          const current = sentence.index === state.sentenceIndex;
          const visited = state.visitedIndexes.has(sentence.index);
          return (
            <li key={sentence.index}>
              <button
                type="button"
                ref={current ? currentRef : undefined}
                className={current ? "reel-item reel-item--current" : "reel-item"}
                aria-current={current ? "true" : undefined}
                onClick={() => send({ type: "select", index: sentence.index })}
              >
                <span className="reel-index">
                  <span className="visually-hidden">第 </span>
                  {sentence.index + 1}
                  <span className="visually-hidden"> 句</span>
                </span>
                <span className="reel-text">
                  {showText ? sentence.text : formatClock(sentence.start)}
                </span>
                {/* 已练状态用文字标出，不只依赖颜色。 */}
                {visited ? <span className="reel-visited">已练</span> : null}
              </button>
            </li>
          );
        })}
      </ol>
    </nav>
  );
}
