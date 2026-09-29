import { useId } from "react";
import type { RuntimeConfig } from "../../api/types";
import { SEGMENT_LIMITS, type ProcessingValues, type SegmentField } from "./processing";

const SUBTITLE_SOURCES: Array<{ value: ProcessingValues["subtitleSource"]; label: string }> = [
  { value: "auto", label: "自动（有人工字幕就用，否则识别）" },
  { value: "existing", label: "只用人工字幕" },
  { value: "asr", label: "语音识别" }
];

type Props = {
  value: ProcessingValues;
  onChange: (value: ProcessingValues) => void;
  config: RuntimeConfig;
  issues: string[];
};

export function ProcessingOptions({ value, onChange, config, issues }: Props) {
  const issuesId = useId();
  const update = (patch: Partial<ProcessingValues>) => onChange({ ...value, ...patch });

  return (
    <fieldset className="options">
      <legend>处理参数</legend>
      <label>
        识别后端
        <select
          value={value.asrBackend ?? ""}
          onChange={(event) => update({ asrBackend: event.target.value })}
        >
          {/* 只列出当前服务真实可用的后端 */}
          {config.asrBackends.map((backend) => (
            <option key={backend} value={backend}>
              {backend}
            </option>
          ))}
        </select>
      </label>
      <label>
        字幕来源
        <select
          value={value.subtitleSource}
          onChange={(event) =>
            update({ subtitleSource: event.target.value as ProcessingValues["subtitleSource"] })
          }
        >
          {SUBTITLE_SOURCES.map((item) => (
            <option key={item.value} value={item.value}>
              {item.label}
            </option>
          ))}
        </select>
      </label>
      <label>
        语言
        <input
          value={value.language ?? ""}
          placeholder="留空自动检测"
          onChange={(event) => update({ language: event.target.value.trim() || null })}
        />
      </label>
      <label className="checkbox">
        <input
          type="checkbox"
          checked={value.makeClips}
          onChange={(event) => update({ makeClips: event.target.checked })}
        />
        预先生成全部单句音频
      </label>
      {(Object.keys(SEGMENT_LIMITS) as SegmentField[]).map((field) => {
        const limit = SEGMENT_LIMITS[field];
        const current = value[field];
        const outOfRange = !Number.isFinite(current) || current < limit.min || current > limit.max;
        const unordered =
          (field === "minDuration" || field === "maxDuration") &&
          value.minDuration >= value.maxDuration;
        const invalid = outOfRange || unordered;
        return (
          <label key={field}>
            {limit.label}（秒）
            <input
              type="number"
              inputMode="decimal"
              step={0.05}
              min={limit.min}
              max={limit.max}
              value={Number.isFinite(current) ? current : ""}
              aria-invalid={invalid}
              aria-describedby={invalid ? issuesId : undefined}
              onChange={(event) => update({ [field]: event.target.valueAsNumber })}
            />
          </label>
        );
      })}
      {issues.length > 0 ? (
        <ul id={issuesId} className="issues" role="alert">
          {issues.map((issue) => (
            <li key={issue}>{issue}</li>
          ))}
        </ul>
      ) : null}
    </fieldset>
  );
}
