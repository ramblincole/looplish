import { usePlayer, usePlayerActions } from "./playerContext";
import { formatRate, formatRepeat } from "./playerLabels";
import {
  MAX_RATE,
  MIN_RATE,
  RATE_STEP,
  REPEAT_OPTIONS,
  type GapMode,
  type Repeat
} from "./playerReducer";

const RATES = Array.from(
  { length: Math.round((MAX_RATE - MIN_RATE) / RATE_STEP) + 1 },
  (_, index) => Math.round((MIN_RATE + index * RATE_STEP) * 100) / 100
);
const FIXED_GAPS = [0, 1, 2, 3, 5];

function gapValue(gap: GapMode): string {
  return gap.kind === "sentence" ? "sentence" : String(gap.seconds);
}

function parseGap(value: string): GapMode {
  return value === "sentence" ? { kind: "sentence" } : { kind: "fixed", seconds: Number(value) };
}

export function PracticeControls() {
  const { state, sentenceCount, waiting, send } = usePlayer();
  const actions = usePlayerActions();
  const { sentenceIndex, playing, playCount, repeat, rate, gapMode, autoAdvance, alwaysHide } =
    state;
  const round = playCount + 1;

  return (
    <section className="controls" aria-label="播放控制">
      <div className="transport">
        <button
          type="button"
          onClick={actions.previous}
          disabled={sentenceIndex === 0}
          aria-keyshortcuts="ArrowLeft"
        >
          上一句
        </button>
        <button
          type="button"
          className="primary-action"
          onClick={actions.togglePlaying}
          aria-keyshortcuts="Space"
        >
          {playing ? "暂停" : "播放"}
        </button>
        <button type="button" onClick={actions.replay} aria-keyshortcuts="R">
          重听
        </button>
        <button
          type="button"
          onClick={actions.next}
          disabled={sentenceIndex + 1 >= sentenceCount}
          aria-keyshortcuts="ArrowRight"
        >
          下一句
        </button>
      </div>
      {/* 播放进度用文字表达，读屏软件会在循环轮次或留白状态变化时播报。 */}
      <p className="play-status" role="status">
        {repeat === "infinite"
          ? `第 ${round} 遍（无限循环）`
          : `第 ${Math.min(round, repeat)} / ${repeat} 遍`}
        {waiting ? " · 跟读留白中…" : null}
      </p>
      <div className="settings">
        <label>
          循环次数
          <select
            value={String(repeat)}
            onChange={(event) => {
              const value = event.target.value;
              send({
                type: "setRepeat",
                value: value === "infinite" ? "infinite" : (Number(value) as Repeat)
              });
            }}
            aria-keyshortcuts="L"
          >
            {REPEAT_OPTIONS.map((option) => (
              <option key={option} value={String(option)}>
                {formatRepeat(option)}
              </option>
            ))}
          </select>
        </label>
        <label>
          语速
          <select
            value={String(rate)}
            onChange={(event) => send({ type: "setRate", value: Number(event.target.value) })}
            aria-keyshortcuts="[ ]"
          >
            {RATES.map((option) => (
              <option key={option} value={String(option)}>
                {formatRate(option)}
              </option>
            ))}
          </select>
        </label>
        <label>
          跟读留白
          <select
            value={gapValue(gapMode)}
            onChange={(event) => send({ type: "setGap", value: parseGap(event.target.value) })}
          >
            {FIXED_GAPS.map((seconds) => (
              <option key={seconds} value={String(seconds)}>
                {seconds === 0 ? "不留白" : `${seconds} 秒`}
              </option>
            ))}
            <option value="sentence">与句子等长</option>
          </select>
        </label>
        <label className="checkbox">
          <input
            type="checkbox"
            checked={autoAdvance}
            onChange={actions.toggleAutoAdvance}
            aria-keyshortcuts="A"
          />
          自动下一句
        </label>
        <label className="checkbox">
          <input
            type="checkbox"
            checked={alwaysHide}
            onChange={() => send({ type: "toggleAlwaysHide" })}
          />
          切换句子时重新隐藏文本
        </label>
      </div>
    </section>
  );
}
