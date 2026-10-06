import { type ClipboardEvent, type FormEvent, useId, useState } from "react";
import type { Job } from "../../api/types";
import { Button } from "../../components/Button/Button";
import { useCreateJob } from "../jobs/useJobs";
import styles from "./IntakeCard.module.css";
import { errorMessage, type ProcessingValues } from "./processing";
import { extractSourceUrl, normalizeSource } from "./sourceLink";

const HTTP_URL = /^https?:\/\//i;

type Props = {
  options: ProcessingValues;
  disabled: boolean;
  allowLocalPaths: boolean;
  onCreated: (job: Job) => void;
};

export function SourceForm({ options, disabled, allowLocalPaths, onCreated }: Props) {
  const inputId = useId();
  const [source, setSource] = useState("");
  const [hint, setHint] = useState<string | null>(null);
  const create = useCreateJob();

  // 粘贴整段分享文案时只插入其中的链接，让用户提交前就能看到实际要下载的地址；
  // 和普通粘贴一样只替换选中的文字，输入框里其余内容保留。
  function paste(event: ClipboardEvent<HTMLInputElement>) {
    const text = event.clipboardData.getData("text");
    const url = extractSourceUrl(text);
    if (!url || url === text.trim()) return;
    event.preventDefault();
    const input = event.currentTarget;
    const start = input.selectionStart ?? input.value.length;
    const end = input.selectionEnd ?? start;
    setSource(input.value.slice(0, start) + url + input.value.slice(end));
    setHint(null);
  }

  function submit(event: FormEvent) {
    event.preventDefault();
    // 手动输入或拖入的文案同样只提交其中的链接。
    const value = normalizeSource(source);
    // 服务端未开放本机路径时提前提示；最终仍以服务端校验为准。
    if (!allowLocalPaths && !HTTP_URL.test(value)) {
      setHint("此服务只接受 http(s) 链接；本机文件请用下方的「选择本地文件」。");
      return;
    }
    setHint(null);
    // 提交时读取最新 options，保证 URL 与文件入口使用同一份参数语义。
    create.mutate(
      { source: value, ...options },
      {
        onSuccess: (job) => {
          setSource("");
          onCreated(job);
        }
      }
    );
  }

  return (
    <form onSubmit={submit} aria-label="通过链接创建素材" className={styles.form}>
      {/* 视觉上只留输入框与占位提示，读屏仍能读到完整标签。 */}
      <label htmlFor={inputId} className="visuallyHidden">
        {allowLocalPaths ? "视频链接或本机媒体路径" : "视频链接"}
      </label>
      <input
        id={inputId}
        className={styles.sourceInput}
        value={source}
        onChange={(event) => setSource(event.target.value)}
        onPaste={paste}
        placeholder={
          allowLocalPaths
            ? "https://www.bilibili.com/video/…  或本机文件路径"
            : "https://www.bilibili.com/video/…"
        }
        autoComplete="off"
        spellCheck={false}
        required
      />
      <Button type="submit" variant="primary" disabled={disabled || create.isPending}>
        {create.isPending ? "提交中…" : "开始切分"}
      </Button>
      {hint ? (
        <p role="alert" className={styles.error}>
          {hint}
        </p>
      ) : null}
      {create.isError ? (
        <p role="alert" className={styles.error}>
          {errorMessage(create.error)}
        </p>
      ) : null}
    </form>
  );
}
