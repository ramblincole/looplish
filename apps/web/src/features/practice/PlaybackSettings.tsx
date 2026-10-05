import { Field, ToggleField } from "../../components/Field/Field";
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
import styles from "./PlaybackSettings.module.css";

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

/** 旋钮排：循环、语速、跟读间隔与两个开关；播放时不重渲染（不订阅播放进度）。 */
export function PlaybackSettings() {
  const { state, send } = usePlayer();
  const actions = usePlayerActions();
  const { repeat, rate, gapMode, autoAdvance, alwaysHide } = state;

  return (
    <div className={styles.knobs}>
      <Field label="循环" layout="inline">
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
      </Field>
      <Field label="语速" layout="inline">
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
      </Field>
      <Field label="跟读间隔" layout="inline">
        <select
          value={gapValue(gapMode)}
          onChange={(event) => send({ type: "setGap", value: parseGap(event.target.value) })}
        >
          {FIXED_GAPS.map((seconds) => (
            <option key={seconds} value={String(seconds)}>
              {`${seconds}s`}
            </option>
          ))}
          <option value="sentence">与句子等长</option>
        </select>
      </Field>
      <ToggleField
        label="自动下一句"
        checked={autoAdvance}
        onChange={actions.toggleAutoAdvance}
        aria-keyshortcuts="A"
      />
      <ToggleField
        label="换句自动遮住"
        checked={alwaysHide}
        onChange={() => send({ type: "toggleAlwaysHide" })}
      />
    </div>
  );
}
