import { type FormEvent, useState } from "react";
import { useCreateJob } from "../jobs/useJobs";
import { errorMessage, type ProcessingValues } from "./processing";

const HTTP_URL = /^https?:\/\//i;

type Props = {
  options: ProcessingValues;
  disabled: boolean;
  allowLocalPaths: boolean;
};

export function SourceForm({ options, disabled, allowLocalPaths }: Props) {
  const [source, setSource] = useState("");
  const [hint, setHint] = useState<string | null>(null);
  const create = useCreateJob();

  function submit(event: FormEvent) {
    event.preventDefault();
    const value = source.trim();
    // 服务端未开放本机路径时提前提示；最终仍以服务端校验为准。
    if (!allowLocalPaths && !HTTP_URL.test(value)) {
      setHint("此服务只接受 http(s) 链接；本机文件请用下方的上传。");
      return;
    }
    setHint(null);
    // 提交时读取最新 options，保证 URL 与文件入口使用同一份参数语义。
    create.mutate({ source: value, ...options }, { onSuccess: () => setSource("") });
  }

  return (
    <form onSubmit={submit} aria-label="通过链接创建素材" className="source-form">
      <label>
        {allowLocalPaths ? "视频链接或本机媒体路径" : "视频链接"}
        <input
          value={source}
          onChange={(event) => setSource(event.target.value)}
          placeholder="https://"
          required
        />
      </label>
      <button disabled={disabled || create.isPending}>
        {create.isPending ? "提交中…" : "开始处理"}
      </button>
      {hint ? <p role="alert">{hint}</p> : null}
      {create.isError ? <p role="alert">{errorMessage(create.error)}</p> : null}
      {create.isSuccess ? <p role="status">已加入处理队列。</p> : null}
    </form>
  );
}
