import type { JobResult } from "../../api/types";
import { usePlayhead } from "./playerContext";

type Sentence = JobResult["sentences"][number];

type Token = { lead: string; core: string; start: number; end: number; timed: boolean };

function tokenize(sentence: Sentence): Token[] {
  if (sentence.words.length > 0) {
    // 词文本沿用识别结果的前导空格（句子文本即各词直接拼接），拆出前导空白，只高亮词本身。
    return sentence.words.map((word) => {
      const core = word.text.trimStart();
      return {
        lead: word.text.slice(0, word.text.length - core.length),
        core,
        start: word.start,
        end: word.end,
        timed: true
      };
    });
  }
  // 缺少词级时间时按空白切分文本作为显示降级，不伪造任何高亮时间。
  return sentence.text
    .split(/\s+/)
    .filter(Boolean)
    .map((core, index) => ({ lead: index > 0 ? " " : "", core, start: 0, end: 0, timed: false }));
}

export function VeiledTranscript({
  sentence,
  revealed
}: {
  sentence: Sentence;
  revealed: boolean;
}) {
  // 只有这里订阅播放时间：词高亮每帧更新，不牵动练习台的其他部分。
  const currentTime = usePlayhead();
  const tokens = tokenize(sentence);
  return (
    <div className="transcript" aria-live="polite">
      {revealed ? null : (
        <span className="visually-hidden">文本已隐藏，共 {tokens.length} 个词。</span>
      )}
      <p className={revealed ? "transcript-text" : "transcript-text transcript-text--veiled"}>
        {tokens.map((token, index) => {
          // 高亮严格使用每个词自己的时间；句子的 start/end 只决定播放范围。
          const active = token.timed && token.start <= currentTime && currentTime < token.end;
          if (!revealed) {
            // 遮罩块宽度与词长相关，保留句子节奏，但不向读屏软件暴露任何字母。
            return (
              <span
                key={index}
                className="word word--veiled"
                style={{ inlineSize: `${Math.max(1, token.core.length)}ch` }}
                aria-hidden="true"
              />
            );
          }
          return (
            <span key={index}>
              {token.lead}
              <span
                className={active ? "word word--active" : "word"}
                aria-current={active ? "true" : undefined}
              >
                {token.core}
              </span>
            </span>
          );
        })}
      </p>
    </div>
  );
}
