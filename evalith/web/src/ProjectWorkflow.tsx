import { useEffect, useState } from "react";
import {
  ArrowUpRight,
  CheckCircle2,
  FileText,
  Layers3,
  Play,
  ShieldCheck,
} from "lucide-react";
import { evaluationApi as api } from "./evaluationApi";
import type { ProjectDetail, WorkspaceTab } from "./types";
export function ProjectWorkflow({
  detail,
  onSection,
}: {
  detail: ProjectDetail;
  onSection: (tab: WorkspaceTab) => void;
}) {
  const [counts, setCounts] = useState<{
      standards: number;
      sets: number;
      runs: number;
      tests: number;
    } | null>(null),
    [error, setError] = useState("");
  useEffect(() => {
    let live = true;
    void Promise.all([
      api.graders(detail.project.id),
      api.sets(detail.project.id),
      api.runs(detail.project.id),
      api.tasks(detail.project.id),
    ])
      .then(([g, s, r, t]) => {
        if (live)
          setCounts({
            standards: g.items.length,
            sets: s.items.length,
            runs: r.items.length,
            tests: t.items.length,
          });
      })
      .catch(() => {
        if (live) setError("评测资产暂时无法加载");
      });
    return () => {
      live = false;
    };
  }, [detail.project.id]);
  return (
    <aside className="project-workflow" aria-label="项目评测上下文">
      <div className="workflow-heading">
        <h2>项目工作区</h2>
        <span className={detail.readiness.generation_allowed ? "is-ready" : ""}>
          {detail.readiness.generation_allowed ? "可以设计测试" : "待核对理解"}
        </span>
      </div>
      <section>
        <h3>评测依据</h3>
        <button
          className="workflow-source"
          onClick={() => onSection("sources")}
        >
          <FileText />
          <div>
            <strong>{detail.snapshot?.file_count ?? 0} 个资料文件</strong>
            <small>{detail.project.name}</small>
          </div>
          <ArrowUpRight size={14} />
        </button>
        <p>资料中的未知规则会继续保留，生成题目不会自动确认它们。</p>
      </section>
      <section>
        <h3>评测资产</h3>
        {[
          ["graders", "评价标准", ShieldCheck, counts?.standards],
          ["tasks", "测试题目", FileText, counts?.tests],
          ["sets", "测试集", Layers3, counts?.sets],
          ["runs", "评测运行", Play, counts?.runs],
        ].map(([id, label, Icon, count]) => (
          <button
            className="workflow-asset"
            key={String(id)}
            onClick={() => onSection(id as WorkspaceTab)}
          >
            {typeof Icon === "function" || typeof Icon === "object" ? (
              <Icon />
            ) : null}
            <span>{String(label)}</span>
            <strong>{count == null ? "—" : String(count)}</strong>
            <ArrowUpRight size={13} />
          </button>
        ))}
        {error && <p>{error}</p>}
      </section>
      <section className="workflow-next">
        <CheckCircle2 />
        <h3>接下来做什么</h3>
        <p>
          {!counts
            ? "正在读取项目资产。"
            : counts.standards === 0
              ? "把题目的 Rubric 整理为评价标准，指定评分模型和通过阈值。"
              : counts.sets === 0
                ? "将测试题目组成测试集，再关联本次要使用的评价标准。"
                : "选择测试集，确认运行环境和评分标准，再执行一轮评测。"}
        </p>
        <button
          onClick={() => onSection(counts?.standards ? "sets" : "graders")}
        >
          {counts?.standards ? "打开测试集" : "配置评价标准"}
          <ArrowUpRight size={14} />
        </button>
      </section>
    </aside>
  );
}
