import { useEffect, useId, useRef, useState } from "react";
import type { JobResult } from "../../api/types";
import { usePlayer } from "./playerContext";
import { formatStart } from "./playerLabels";
import styles from "./SentenceReel.module.css";

type Sentence = JobResult["sentences"][number];

export function SentenceReel({ sentences }: { sentences: Sentence[] }) {
  const { state, send } = usePlayer();
  const [query, setQuery] = useState("");
  const titleId = useId();
  const searchId = useId();
  const currentRef = useRef<HTMLButtonElement | null>(null);
  const needle = query.trim().toLowerCase();
  const matches = needle
    ? sentences.filter((sentence) => sentence.text.toLowerCase().includes(needle))
    : sentences;
  // 清单也遵守遮罩：当前句遮着时不能在这里剧透原文；用户主动搜索时命中项照常显示。
  const blurred = !state.revealed && needle.length === 0;

  useEffect(() => {
    // 自动前进或快捷键切句后，让当前句保持在清单可见区域内。
    currentRef.current?.scrollIntoView?.({ block: "nearest" });
  }, [state.sentenceIndex]);

  return (
    <section className={styles.reel} aria-labelledby={titleId}>
      <div className={styles.head}>
        <h2 id={titleId} className={styles.label}>
          全部句子
        </h2>
        <span className={styles.summary} role="status">
          {needle
            ? `找到 ${matches.length} 句`
            : `已练 ${state.visitedIndexes.size} / ${sentences.length}`}
        </span>
        <label htmlFor={searchId} className="visuallyHidden">
          搜索句子
        </label>
        <input
          id={searchId}
          type="search"
          className={styles.search}
          value={query}
          onChange={(event) => setQuery(event.target.value)}
          placeholder="搜索句子…"
          autoComplete="off"
        />
      </div>
      <ol className={styles.list}>
        {matches.map((sentence) => {
          const current = sentence.index === state.sentenceIndex;
          const visited = state.visitedIndexes.has(sentence.index);
          return (
            <li key={sentence.index}>
              <button
                type="button"
                ref={current ? currentRef : undefined}
                className={styles.row}
                data-current={current || undefined}
                data-visited={visited || undefined}
                aria-current={current ? "true" : undefined}
                onClick={() => send({ type: "select", index: sentence.index })}
              >
                <span className={styles.index}>
                  <span className="visuallyHidden">第 </span>
                  {sentence.index + 1}
                  <span className="visuallyHidden"> 句</span>
                </span>
                <span className={styles.time}>{formatStart(sentence.start)}</span>
                <span
                  className={styles.text}
                  data-blurred={blurred || undefined}
                  aria-hidden={blurred ? "true" : undefined}
                >
                  {sentence.text}
                </span>
                {/* 已练状态用文字标出，不只依赖颜色。 */}
                {visited ? <span className={styles.visited}>已练</span> : null}
              </button>
            </li>
          );
        })}
      </ol>
    </section>
  );
}
