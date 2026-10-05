import { useId, useRef } from "react";
import type { Job } from "../../api/types";
import { Button } from "../../components/Button/Button";
import { buttonClass } from "../../components/Button/buttonClass";
import { useUploadJob } from "../jobs/useJobs";
import styles from "./IntakeCard.module.css";
import { errorMessage, toUploadForm, type ProcessingValues } from "./processing";

function looksLikeMedia(file: File): boolean {
  // 仅作提示：浏览器给出的类型可能为空或不准，是否能处理由服务端 FFprobe 判定。
  return file.type === "" || file.type.startsWith("audio/") || file.type.startsWith("video/");
}

type Props = {
  file: File | null;
  onFileChange: (file: File | null) => void;
  options: ProcessingValues;
  disabled: boolean;
  onCreated: (job: Job) => void;
};

/** 文件状态由投放卡片持有：拖放区是整张卡片，选择按钮与拖放要落到同一个状态上。 */
export function FilePicker({ file, onFileChange, options, disabled, onCreated }: Props) {
  const inputId = useId();
  const input = useRef<HTMLInputElement>(null);
  const upload = useUploadJob();

  function clear() {
    onFileChange(null);
    upload.reset();
    // 清空原生输入框，否则再次选择同一个文件不会触发 change。
    if (input.current) input.current.value = "";
  }

  function submit() {
    if (file === null) return;
    upload.mutate(toUploadForm(file, options), {
      onSuccess: (job) => {
        clear();
        onCreated(job);
      }
    });
  }

  return (
    <div className={styles.fileRow}>
      {/* 输入框只在视觉上隐藏，仍可用 Tab 聚焦并用键盘打开文件选择。 */}
      <input
        id={inputId}
        ref={input}
        type="file"
        className={`visuallyHidden ${styles.fileInput}`}
        accept="audio/*,video/*"
        onChange={(event) => {
          upload.reset();
          onFileChange(event.target.files?.[0] ?? null);
        }}
      />
      <label htmlFor={inputId} className={buttonClass("ghost")}>
        选择本地文件
      </label>
      {file ? (
        <>
          <span className={styles.selected}>已选择：{file.name}</span>
          <Button variant="primary" onClick={submit} disabled={disabled || upload.isPending}>
            {upload.isPending ? "上传中…" : "上传并处理"}
          </Button>
          <Button variant="ghost" onClick={clear} disabled={upload.isPending}>
            取消
          </Button>
        </>
      ) : (
        <span className={styles.hint}>也可以直接拖放到这个区域</span>
      )}
      {file && !looksLikeMedia(file) ? (
        <p className={styles.note}>这个文件看起来不是音视频，仍可尝试上传，由服务端最终判断。</p>
      ) : null}
      {upload.isError ? (
        <p role="alert" className={styles.error}>
          {errorMessage(upload.error)}
        </p>
      ) : null}
    </div>
  );
}
