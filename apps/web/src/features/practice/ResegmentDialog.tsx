import { useEffect, useId, useRef, useState, type FormEvent, type KeyboardEvent } from "react";
import type { ResegmentRequest } from "../../api/types";
import { errorMessage, SEGMENT_LIMITS, type SegmentField } from "../intake/processing";
import { useResegment } from "../jobs/useJobs";
import { usePlayer } from "./playerContext";

const FIELDS = Object.keys(SEGMENT_LIMITS) as SegmentField[];
type Draft = Record<SegmentField, string>;
const EMPTY: Draft = { minDuration: "", maxDuration: "", hardPause: "", leadPad: "", tailPad: "" };

/** 只把填写了的字段放进请求；返回校验问题与请求体，二者互斥使用。 */
function toOverrides(draft: Draft): { issues: string[]; body: ResegmentRequest } {
  const issues: string[] = [];
  const body: ResegmentRequest = {};
  for (const field of FIELDS) {
    const raw = draft[field].trim();
    if (raw === "") continue;
    const value = Number(raw);
    const limit = SEGMENT_LIMITS[field];
    if (!Number.isFinite(value)) {
      issues.push(`${limit.label}需要填写数字。`);
    } else if (value < limit.min || value > limit.max) {
      issues.push(`${limit.label}需在 ${limit.min} 到 ${limit.max} 秒之间。`);
    } else {
      body[field] = value;
    }
  }
  // 只填一端时无法在客户端比较，交由服务端与已保存的旧参数合并后校验。
  if (
    body.minDuration != null &&
    body.maxDuration != null &&
    body.minDuration >= body.maxDuration
  ) {
    issues.push("最短句长必须小于最长句长。");
  }
  return { issues, body };
}

export function ResegmentDialog({
  jobId,
  open,
  onOpenChange
}: {
  jobId: string;
  open: boolean;
  onOpenChange: (open: boolean) => void;
}) {
  const { send } = usePlayer();
  const resegment = useResegment(jobId);
  const [draft, setDraft] = useState<Draft>(EMPTY);
  const triggerRef = useRef<HTMLButtonElement | null>(null);
  const dialogRef = useRef<HTMLDivElement | null>(null);
  const wasOpen = useRef(open);
  const titleId = useId();
  const { issues, body } = toOverrides(draft);
  const filled = Object.keys(body).length > 0;
  const { reset } = resegment;

  useEffect(() => {
    if (open) {
      // 打开时把焦点移入对话框，并清掉上一次提交留下的错误。
      reset();
      dialogRef.current?.querySelector<HTMLElement>("input")?.focus();
    } else if (wasOpen.current) {
      // 关闭（Escape、取消或提交成功）后焦点回到触发按钮，键盘用户不会迷失位置。
      triggerRef.current?.focus();
    }
    wasOpen.current = open;
  }, [open, reset]);

  function submit(event: FormEvent) {
    event.preventDefault();
    if (!filled || issues.length > 0) return;
    resegment.mutate(body, {
      onSuccess: () => {
        // 新结果的句子索引与旧结果无关，播放器回到第 0 句重新开始。
        send({ type: "reset" });
        setDraft(EMPTY);
        onOpenChange(false);
      }
    });
  }

  function trapFocus(event: KeyboardEvent<HTMLDivElement>) {
    if (event.key !== "Tab" || !dialogRef.current) return;
    const focusable = Array.from(
      dialogRef.current.querySelectorAll<HTMLElement>("input, button:not(:disabled)")
    );
    if (focusable.length === 0) return;
    const first = focusable[0];
    const last = focusable[focusable.length - 1];
    // 模态对话框内循环 Tab 焦点，避免键盘焦点落到被遮住的页面上。
    if (event.shiftKey && document.activeElement === first) {
      event.preventDefault();
      last.focus();
    } else if (!event.shiftKey && document.activeElement === last) {
      event.preventDefault();
      first.focus();
    }
  }

  return (
    <>
      <button
        type="button"
        ref={triggerRef}
        className="secondary"
        onClick={() => onOpenChange(true)}
        aria-haspopup="dialog"
      >
        重新切句
      </button>
      {open ? (
        <div className="dialog-backdrop">
          <div
            ref={dialogRef}
            className="dialog"
            role="dialog"
            aria-modal="true"
            aria-labelledby={titleId}
            onKeyDown={trapFocus}
          >
            <h2 id={titleId}>重新切句</h2>
            <p className="dialog-hint">
              只填写需要调整的参数，留空的沿用该素材上次的设置。重新切句只使用已有的词级时间，不会重新识别。
            </p>
            <form onSubmit={submit} noValidate>
              <div className="dialog-fields">
                {FIELDS.map((field) => {
                  const limit = SEGMENT_LIMITS[field];
                  return (
                    <label key={field}>
                      {limit.label}（秒）
                      <input
                        type="number"
                        inputMode="decimal"
                        step={0.05}
                        min={limit.min}
                        max={limit.max}
                        placeholder={`${limit.min}–${limit.max}`}
                        value={draft[field]}
                        onChange={(event) =>
                          setDraft((current) => ({ ...current, [field]: event.target.value }))
                        }
                      />
                    </label>
                  );
                })}
              </div>
              {issues.length > 0 ? (
                <ul className="issues" role="alert">
                  {issues.map((issue) => (
                    <li key={issue}>{issue}</li>
                  ))}
                </ul>
              ) : null}
              {resegment.isError ? <p role="alert">{errorMessage(resegment.error)}</p> : null}
              <div className="dialog-actions">
                <button type="button" className="secondary" onClick={() => onOpenChange(false)}>
                  取消
                </button>
                <button
                  type="submit"
                  disabled={!filled || issues.length > 0 || resegment.isPending}
                >
                  {resegment.isPending ? "正在切句…" : "应用"}
                </button>
              </div>
            </form>
          </div>
        </div>
      ) : null}
    </>
  );
}
