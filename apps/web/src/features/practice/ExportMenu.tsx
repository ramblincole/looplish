import { api } from "../../api/client";

const SUBTITLE_FORMATS = [
  { format: "srt", label: "SRT 字幕" },
  { format: "vtt", label: "VTT 字幕" },
  { format: "txt", label: "纯文本" }
] as const;

export function ExportMenu({ jobId }: { jobId: string }) {
  // 下载地址只来自 api.urls，组件不拼接 API 路径；文件名由服务端按清理后的标题给出。
  return (
    <nav className="export" aria-label="导出">
      <span className="export-label">导出</span>
      <ul>
        {SUBTITLE_FORMATS.map(({ format, label }) => (
          <li key={format}>
            <a href={api.urls.subtitle(jobId, format)} download>
              {label}
            </a>
          </li>
        ))}
        <li>
          {/* 服务端会按需生成缺失的单句音频，句子多时首次下载需要稍等。 */}
          <a href={api.urls.bundle(jobId)} download>
            学习包 ZIP（含单句音频）
          </a>
        </li>
      </ul>
    </nav>
  );
}
