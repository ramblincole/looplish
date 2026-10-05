import { useEffect, useId, useRef } from "react";
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
  const { reset: resetUpload } = upload;
  // 上传是异步的：成功回调里要读到「此刻」的文件，而不是提交时闭包里的旧值。
  const currentFile = useRef(file);
  useEffect(() => {
    currentFile.current = file;
  }, [file]);

  // 文件由父组件持有（拖放落在整张卡片上），所以不能只在选择按钮的 onChange 里复位：
  // 任何来源换了文件，上一次的上传错误与原生输入框的残留选择都要一起丢掉。
  useEffect(() => {
    resetUpload();
    const native = input.current;
    // 原生输入框仍持有旧文件时必须清空，否则再次选择同一个文件不会触发 change。
    if (native && (file === null || native.files?.[0] !== file)) native.value = "";
  }, [file, resetUpload]);

  function submit() {
    if (file === null) return;
    const submitted = file;
    // 用 mutateAsync 而不是 mutate 的回调：拖入新文件会 reset 这次变更，
    // 此后 mutate 的回调不再触发，但素材已经创建，必须通知父组件。
    upload.mutateAsync(toUploadForm(submitted, options)).then(
      (job) => {
        // 上传期间用户可能已换了文件，只清掉刚上传的那个，别误删新选的文件。
        if (currentFile.current === submitted) onFileChange(null);
        onCreated(job);
      },
      () => {
        // 失败信息由 upload.error 展示，这里只避免未处理的 Promise 拒绝。
      }
    );
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
        onChange={(event) => onFileChange(event.target.files?.[0] ?? null)}
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
          <Button variant="ghost" onClick={() => onFileChange(null)} disabled={upload.isPending}>
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
