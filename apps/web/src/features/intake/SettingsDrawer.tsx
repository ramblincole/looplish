import { useId, useState } from "react";
import type { RuntimeConfig } from "../../api/types";
import { Field, ToggleField } from "../../components/Field/Field";
import { RangeField } from "../../components/Field/RangeField";
import styles from "./SettingsDrawer.module.css";
import { SEGMENT_LIMITS, type ProcessingValues, type SegmentField } from "./processing";

const SUBTITLE_SOURCES: Array<{ value: ProcessingValues["subtitleSource"]; label: string }> = [
  { value: "auto", label: "优先用自带字幕" },
  { value: "asr", label: "总是重新识别" },
  { value: "existing", label: "只用自带字幕" }
];

const LANGUAGE_SUGGESTIONS = [
  { value: "en", label: "英语" },
  { value: "ja", label: "日语" },
  { value: "zh", label: "中文" },
  { value: "ko", label: "韩语" },
  { value: "fr", label: "法语" },
  { value: "de", label: "德语" },
  { value: "es", label: "西班牙语" }
];

// 步长决定读数的小数位；取值需与服务端默认值对齐（如 hardPause 0.75、leadPad 0.2）。
const SLIDERS: Record<SegmentField, { step: number; digits: number }> = {
  minDuration: { step: 0.1, digits: 1 },
  maxDuration: { step: 0.5, digits: 1 },
  hardPause: { step: 0.05, digits: 2 },
  leadPad: { step: 0.05, digits: 2 },
  tailPad: { step: 0.05, digits: 2 }
};

type Props = {
  value: ProcessingValues;
  onChange: (value: ProcessingValues) => void;
  config: RuntimeConfig;
  issues: string[];
};

export function SettingsDrawer({ value, onChange, config, issues }: Props) {
  const languagesId = useId();
  const [open, setOpen] = useState(false);
  const update = (patch: Partial<ProcessingValues>) => onChange({ ...value, ...patch });
  // 参数冲突时强制展开，用户能直接看到原因；冲突解除后恢复用户自己的展开状态。
  const expanded = open || issues.length > 0;
  const unordered = value.minDuration >= value.maxDuration;

  return (
    <details
      className={styles.drawer}
      open={expanded}
      onToggle={(event) => setOpen(event.currentTarget.open)}
    >
      <summary className={styles.summary}>识别与切分设置</summary>
      <div className={styles.grid}>
        <Field label="识别引擎">
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
        </Field>
        <Field label="字幕来源">
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
        </Field>
        <Field label="语言">
          <input
            value={value.language ?? ""}
            list={languagesId}
            placeholder="留空自动检测"
            onChange={(event) => update({ language: event.target.value.trim() || null })}
          />
        </Field>
        <datalist id={languagesId}>
          {LANGUAGE_SUGGESTIONS.map((item) => (
            <option key={item.value} value={item.value}>
              {item.label}
            </option>
          ))}
        </datalist>
        {(Object.keys(SEGMENT_LIMITS) as SegmentField[]).map((field) => {
          const limit = SEGMENT_LIMITS[field];
          const slider = SLIDERS[field];
          return (
            <RangeField
              key={field}
              label={limit.label}
              value={value[field]}
              min={limit.min}
              max={limit.max}
              step={slider.step}
              unit="s"
              format={(current) => current.toFixed(slider.digits)}
              invalid={(field === "minDuration" || field === "maxDuration") && unordered}
              onChange={(next) => update({ [field]: next })}
            />
          );
        })}
        <div className={styles.toggleRow}>
          <ToggleField
            label="预先生成全部单句音频"
            checked={value.makeClips}
            onChange={(event) => update({ makeClips: event.target.checked })}
          />
        </div>
      </div>
      {issues.length > 0 ? (
        <ul className={styles.issues} role="alert">
          {issues.map((issue) => (
            <li key={issue}>{issue}</li>
          ))}
        </ul>
      ) : null}
    </details>
  );
}
