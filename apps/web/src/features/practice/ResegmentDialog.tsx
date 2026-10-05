import { useEffect, useRef, useState, type FormEvent } from "react";
import type { ResegmentRequest } from "../../api/types";
import { Button } from "../../components/Button/Button";
import { Field } from "../../components/Field/Field";
import { Modal } from "../../components/Modal/Modal";
import { errorMessage, SEGMENT_LIMITS, type SegmentField } from "../intake/processing";
import { useResegment } from "../jobs/useJobs";
import { usePlayer } from "./playerContext";
import styles from "./ResegmentDialog.module.css";

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
  const { issues, body } = toOverrides(draft);
  const filled = Object.keys(body).length > 0;
  const { reset } = resegment;

  useEffect(() => {
    // 每次打开都清掉上一次提交留下的错误；焦点移入与返回由 Modal 负责。
    if (open) reset();
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

  return (
    <>
      <Button
        ref={triggerRef}
        variant="ghost"
        onClick={() => onOpenChange(true)}
        aria-haspopup="dialog"
      >
        重新切分
      </Button>
      <Modal
        open={open}
        title="重新切分"
        returnFocusTo={triggerRef}
        onClose={() => onOpenChange(false)}
      >
        <p className={styles.hint}>
          只填写需要调整的参数，留空的沿用该素材上次的设置。重新切分只使用已有的词级时间，不会重新识别。
        </p>
        <form onSubmit={submit} noValidate>
          <div className={styles.fields}>
            {FIELDS.map((field) => {
              const limit = SEGMENT_LIMITS[field];
              return (
                <Field key={field} label={`${limit.label}（秒）`}>
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
                </Field>
              );
            })}
          </div>
          {issues.length > 0 ? (
            <ul className={styles.issues} role="alert">
              {issues.map((issue) => (
                <li key={issue}>{issue}</li>
              ))}
            </ul>
          ) : null}
          {resegment.isError ? (
            <p role="alert" className={styles.error}>
              {errorMessage(resegment.error)}
            </p>
          ) : null}
          <div className={styles.actions}>
            <Button variant="ghost" onClick={() => onOpenChange(false)}>
              取消
            </Button>
            <Button
              type="submit"
              variant="primary"
              disabled={!filled || issues.length > 0 || resegment.isPending}
            >
              {resegment.isPending ? "正在切分…" : "应用"}
            </Button>
          </div>
        </form>
      </Modal>
    </>
  );
}
