import { api } from "../../api/client";
import { ButtonLink } from "../../components/Button/Button";
import styles from "./PracticeActions.module.css";
import { ResegmentDialog } from "./ResegmentDialog";

type Props = {
  jobId: string;
  resegmentOpen: boolean;
  onResegmentOpenChange: (open: boolean) => void;
};

export function PracticeActions({ jobId, resegmentOpen, onResegmentOpenChange }: Props) {
  // 下载地址只来自 api.urls，组件不拼接 API 路径；文件名由服务端按清理后的标题给出。
  return (
    <div className={styles.actions}>
      <nav aria-label="导出" className={styles.exports}>
        <ButtonLink href={api.urls.subtitle(jobId, "srt")} download>
          下载 SRT
        </ButtonLink>
        <ButtonLink href={api.urls.subtitle(jobId, "vtt")} download>
          下载 VTT
        </ButtonLink>
        <ButtonLink href={api.urls.subtitle(jobId, "txt")} download>
          下载文本
        </ButtonLink>
        {/* 服务端会按需生成缺失的单句音频，句子多时首次下载需要稍等。 */}
        <ButtonLink href={api.urls.bundle(jobId)} download>
          学习包 ZIP
        </ButtonLink>
      </nav>
      <ResegmentDialog jobId={jobId} open={resegmentOpen} onOpenChange={onResegmentOpenChange} />
    </div>
  );
}
