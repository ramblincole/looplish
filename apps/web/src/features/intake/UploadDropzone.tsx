import { type DragEvent, useId, useRef, useState } from "react";
import { useUploadJob } from "../jobs/useJobs";
import { errorMessage, toUploadForm, type ProcessingValues } from "./processing";

function looksLikeMedia(file: File): boolean {
  // 仅作提示：浏览器给出的类型可能为空或不准，是否能处理由服务端 FFprobe 判定。
  return file.type === "" || file.type.startsWith("audio/") || file.type.startsWith("video/");
}

type Props = {
  options: ProcessingValues;
  disabled: boolean;
};

export function UploadDropzone({ options, disabled }: Props) {
  const inputId = useId();
  const input = useRef<HTMLInputElement>(null);
  const [file, setFile] = useState<File | null>(null);
  const [dragging, setDragging] = useState(false);
  const upload = useUploadJob();

  function choose(next: File | undefined) {
    setFile(next ?? null);
    upload.reset();
  }

  function drop(event: DragEvent<HTMLDivElement>) {
    event.preventDefault();
    setDragging(false);
    // 一次只处理一个文件，多选时取第一个。
    choose(event.dataTransfer.files[0]);
  }

  function submit() {
    if (file === null) return;
    upload.mutate(toUploadForm(file, options), {
      onSuccess: () => {
        setFile(null);
        if (input.current) input.current.value = "";
      }
    });
  }

  return (
    <div
      className={dragging ? "dropzone dragging" : "dropzone"}
      onDragOver={(event) => {
        event.preventDefault();
        setDragging(true);
      }}
      onDragLeave={() => setDragging(false)}
      onDrop={drop}
    >
      {/* 输入框只在视觉上隐藏，仍可用 Tab 聚焦并用键盘打开文件选择 */}
      <input
        id={inputId}
        ref={input}
        type="file"
        className="visually-hidden"
        accept="audio/*,video/*"
        onChange={(event) => choose(event.target.files?.[0])}
      />
      <label htmlFor={inputId} className="button-like">
        选择媒体文件
      </label>
      <p>或把文件拖到这里</p>
      {file ? <p>已选择：{file.name}</p> : null}
      {file && !looksLikeMedia(file) ? (
        <p role="status">这个文件看起来不是音视频，仍可尝试上传，由服务端最终判断。</p>
      ) : null}
      <button
        type="button"
        onClick={submit}
        disabled={disabled || file === null || upload.isPending}
      >
        {upload.isPending ? "上传中…" : "上传并处理"}
      </button>
      {upload.isError ? <p role="alert">{errorMessage(upload.error)}</p> : null}
      {upload.isSuccess ? <p role="status">已上传并加入处理队列。</p> : null}
    </div>
  );
}
