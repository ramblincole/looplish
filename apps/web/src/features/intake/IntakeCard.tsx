import { type DragEvent, useId, useState } from "react";
import type { Job, RuntimeConfig } from "../../api/types";
import { FilePicker } from "./FilePicker";
import styles from "./IntakeCard.module.css";
import type { ProcessingValues } from "./processing";
import { SettingsDrawer } from "./SettingsDrawer";
import { SourceForm } from "./SourceForm";

type Props = {
  config: RuntimeConfig;
  options: ProcessingValues;
  issues: string[];
  onOptionsChange: (value: ProcessingValues) => void;
  onCreated: (job: Job) => void;
};

// 只有携带文件的拖拽才算投放；拖链接或文字到输入框时要保留浏览器原生行为。
function carriesFiles(event: DragEvent<HTMLElement>): boolean {
  return event.dataTransfer.types.includes("Files");
}

export function IntakeCard({ config, options, issues, onOptionsChange, onCreated }: Props) {
  const titleId = useId();
  const [file, setFile] = useState<File | null>(null);
  const [dragging, setDragging] = useState(false);
  const blocked = issues.length > 0;

  function drop(event: DragEvent<HTMLElement>) {
    if (!carriesFiles(event)) return;
    event.preventDefault();
    setDragging(false);
    // 一次只处理一个文件，多选时取第一个；拖入后同样要点「上传并处理」才提交。
    const dropped = event.dataTransfer.files[0];
    if (dropped) setFile(dropped);
  }

  return (
    <section
      className={styles.card}
      aria-labelledby={titleId}
      data-dragging={dragging || undefined}
      onDragOver={(event) => {
        if (!carriesFiles(event)) return;
        event.preventDefault();
        setDragging(true);
      }}
      onDragLeave={(event) => {
        // 拖过卡片内的子元素也会触发 dragleave，只在真正离开卡片时取消高亮。
        if (!event.currentTarget.contains(event.relatedTarget as Node | null)) setDragging(false);
      }}
      onDrop={drop}
    >
      <h1 id={titleId} className={styles.title}>
        把一段视频拆成一句一句来听
      </h1>
      <p className={styles.sub}>
        粘贴 B 站、YouTube 等站点的链接{config.allowLocalPaths ? "或本机媒体路径" : ""}
        ，或把音频 / 视频文件拖进来。
      </p>
      <SourceForm
        options={options}
        disabled={blocked}
        allowLocalPaths={config.allowLocalPaths}
        onCreated={onCreated}
      />
      <FilePicker
        file={file}
        onFileChange={setFile}
        options={options}
        disabled={blocked}
        onCreated={onCreated}
      />
      <SettingsDrawer value={options} onChange={onOptionsChange} config={config} issues={issues} />
    </section>
  );
}
