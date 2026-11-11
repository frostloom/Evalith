import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import {
  Alert,
  Button,
  Checkbox,
  IconButton,
  InputAdornment,
  LinearProgress,
  MenuItem,
  TextField,
  Tooltip,
} from "@mui/material";
import {
  ArrowUpRight,
  Clock3,
  FileText,
  FlaskConical,
  Play,
  Plus,
  Search,
  Square,
  ChevronRight,
  WandSparkles,
} from "lucide-react";
import { evaluationApi as ev } from "./evaluationApi";
import type {
  Analysis,
  Environment,
  EvalResult,
  EvalRun,
  EvalTask,
  GenerationJob,
} from "./evaluationTypes";
import type { ProjectDetail, WorkspaceTab } from "./types";
import { PageHeader } from "./ui";
import {
  AnalysisDialog,
  GenerationDialog,
  RunDialog,
  TaskDialog,
} from "./EvaluationDialogs";

export const statusNames: Record<string, string> = {
  passed: "通过",
  failed: "失败",
  completed: "已完成",
  running: "运行中",
  pending: "等待中",
  validating: "验证中",
  review_required: "待复核",
  validation_error: "证据缺失",
  execution_error: "执行错误",
  budget_stopped: "预算停止",
  cancelled: "已取消",
  cancelling: "正在停止",
  skipped: "已跳过",
  interrupted: "已中断",
  planned: "待确认",
  preparing: "准备中",
  ready: "已就绪",
  missing_evidence: "缺少证据",
  needs_judge: "待模型判断",
};
export const active = (status: string) =>
  ["running", "pending", "validating", "preparing", "cancelling"].includes(
    status,
  );
export function StateBadge({ status }: { status: string }) {
  return (
    <span className={`eval-state state-${status}`}>
      <span />
      {statusNames[status] ?? status}
    </span>
  );
}
export function UsageLine({ value }: { value: EvalRun["usage"] }) {
  return (
    <span className="usage-line">
      {value.model_calls ?? "—"} 次调用{" "}
      <span>
        输入 {value.input_tokens?.toLocaleString() ?? "未知"} / 输出{" "}
        {value.output_tokens?.toLocaleString() ?? "未知"} tokens
      </span>
      <span>费用未知</span>
    </span>
  );
}
const date = (value: string) =>
  new Date(value).toLocaleString("zh-CN", {
    month: "numeric",
    day: "numeric",
    hour: "2-digit",
    minute: "2-digit",
  });

export function EvaluationWorkspace({
  detail,
  section,
  onSection,
}: {
  detail: ProjectDetail;
  section: WorkspaceTab;
  onSection: (section: WorkspaceTab) => void;
}) {
  const pid = detail.project.id;
  const [tasks, setTasks] = useState<EvalTask[]>([]),
    [runs, setRuns] = useState<EvalRun[]>([]),
    [analyses, setAnalyses] = useState<Analysis[]>([]),
    [environments, setEnvironments] = useState<Environment[]>([]),
    [jobs, setJobs] = useState<GenerationJob[]>([]);
  const [loaded, setLoaded] = useState(false),
    [error, setError] = useState(""),
    [loadError, setLoadError] = useState(""),
    [busy, setBusy] = useState(false);
  const [query, setQuery] = useState(""),
    [category, setCategory] = useState("all"),
    [selected, setSelected] = useState<string[]>([]),
    [task, setTask] = useState<EvalTask | null>(null),
    [dialog, setDialog] = useState<"generation" | "run" | "analysis" | null>(
      null,
    ),
    [runId, setRunId] = useState<string | null>(null),
    [result, setResult] = useState<EvalResult | null>(null),
    [resultFilter, setResultFilter] = useState("all"),
    [resultIds, setResultIds] = useState<string[]>([]);
  const live = useRef(true);
  useEffect(() => {
    live.current = true;
    return () => {
      live.current = false;
    };
  }, []);
  const refresh = useCallback(async () => {
    const [t, r, a, e, j] = await Promise.all([
      ev.tasks(pid),
      ev.runs(pid),
      ev.analyses(pid),
      ev.environments(pid),
      ev.jobs(pid),
    ]);
    if (!live.current) return;
    setLoadError("");
    setTasks(t.items);
    setRuns(r.items);
    setAnalyses(a.items);
    setEnvironments(e.items);
    setJobs(j.items);
    setLoaded(true);
  }, [pid]);
  useEffect(() => {
    let gone = false;
    const load = () =>
      refresh().catch((e) => {
        if (!gone)
          setLoadError(e instanceof Error ? e.message : "无法加载评测数据");
      });
    void load();
    const timer = window.setInterval(() => void load(), 3000);
    return () => {
      gone = true;
      window.clearInterval(timer);
    };
  }, [refresh]);
  const act = async (action: () => Promise<unknown>) => {
    setBusy(true);
    setError("");
    try {
      await action();
      if (live.current) await refresh();
    } catch (e) {
      if (live.current) setError(e instanceof Error ? e.message : "操作失败");
    } finally {
      if (live.current) setBusy(false);
    }
  };
  const shown = tasks.filter(
    (t) =>
      (category === "all" || t.definition.category === category) &&
      `${t.definition.title} ${t.definition.objective}`
        .toLowerCase()
        .includes(query.toLowerCase()),
  );
  const run = runs.find((r) => r.id === runId) ?? runs[0];
  const currentResults =
    run?.results.filter(
      (r) => resultFilter === "all" || r.status === resultFilter,
    ) ?? [];
  const generation = jobs.find((j) => active(j.status));
  const selectedTasks = tasks.filter((t) => selected.includes(t.id));
  const selectedResult =
    (result && run?.results.find((r) => r.id === result.id)) || null;
  const reports = analyses.filter((a) => a.run_id === run?.id);
  const summary = useMemo(() => {
    const values = run?.results ?? [];
    return {
      passed: values.filter((r) => r.status === "passed").length,
      failed: values.filter((r) => r.status === "failed").length,
      unknown: values.filter((r) => r.score === null && !active(r.status))
        .length,
    };
  }, [run]);
  return (
    <div
      className="evaluation-workspace"
      role="tabpanel"
      id={`panel-${section}`}
      aria-labelledby={`tab-${section}`}
    >
      <div className="eval-breadcrumb">
        <span>{detail.project.name}</span>
        <ChevronRight size={13} />
        <strong>
          {section === "tasks"
            ? "题目集"
            : section === "runs"
              ? "评测运行"
              : "结果分析"}
        </strong>
        <span className="eval-local">本地工作区</span>
      </div>
      <div className="eval-page-body">
        <PageHeader
          title={
            section === "tasks"
              ? "题目集"
              : section === "runs"
                ? "评测运行"
                : "结果分析"
          }
          description={
            section === "tasks"
              ? "把项目资料变成可追溯的评测，再用证据检查实际表现。"
              : section === "runs"
                ? "每次运行固定题目版本，逐题保存输出与检查结果。"
                : "基于已结束的运行生成报告，原始结果独立保留。"
          }
          actions={
            section === "tasks" ? (
              <>
                <Button
                  variant="outlined"
                  startIcon={<Play />}
                  disabled={!selected.length}
                  onClick={() => setDialog("run")}
                >
                  运行选中题目{selected.length ? ` (${selected.length})` : ""}
                </Button>
                <Button
                  variant="contained"
                  startIcon={<Plus />}
                  disabled={
                    !detail.readiness.generation_allowed || Boolean(generation)
                  }
                  onClick={() => setDialog("generation")}
                >
                  生成题目
                </Button>
              </>
            ) : section === "runs" ? (
              <Button
                variant="contained"
                startIcon={<Plus />}
                onClick={() => onSection("tasks")}
              >
                选择题目运行
              </Button>
            ) : run ? (
              <Button
                variant="contained"
                startIcon={<WandSparkles />}
                disabled={active(run.status)}
                onClick={() => setDialog("analysis")}
              >
                分析运行结果
              </Button>
            ) : undefined
          }
        />
        {(error || loadError) && (
          <Alert
            severity="error"
            onClose={() => {
              setError("");
              setLoadError("");
            }}
          >
            {error || loadError}
          </Alert>
        )}
        {section === "tasks" && !detail.readiness.generation_allowed && (
          <Alert
            severity="info"
            action={
              <Button onClick={() => onSection("overview")}>查看理解</Button>
            }
          >
            {detail.readiness.reason}
          </Alert>
        )}
        {section === "tasks" && generation && (
          <div className="eval-progress-note">
            <WandSparkles />
            <div>
              <strong>正在生成 {generation.count} 道题目</strong>
              <p>模型正在核对资料与评分规则，完成后会出现在题目集中。</p>
              <LinearProgress />
            </div>
          </div>
        )}
        {section === "tasks" && !generation && jobs[0]?.status === "failed" && (
          <Alert severity="error">题目生成失败：{jobs[0].error}</Alert>
        )}
        {!loaded ? (
          <div className="eval-empty">
            <Clock3 />
            <h2>正在加载评测工作区</h2>
          </div>
        ) : section === "tasks" ? (
          <>
            <div className="eval-toolbar">
              <TextField
                placeholder="搜索题目…"
                size="small"
                value={query}
                onChange={(e) => setQuery(e.target.value)}
                slotProps={{
                  htmlInput: { "aria-label": "搜索题目" },
                  input: {
                    startAdornment: (
                      <InputAdornment position="start">
                        <Search size={16} />
                      </InputAdornment>
                    ),
                  },
                }}
              />
              <TextField
                select
                size="small"
                value={category}
                onChange={(e) => setCategory(e.target.value)}
                slotProps={{ htmlInput: { "aria-label": "题目分类" } }}
              >
                <MenuItem value="all">全部分类</MenuItem>
                {Array.from(
                  new Set(tasks.map((t) => t.definition.category)),
                ).map((c) => (
                  <MenuItem key={c} value={c}>
                    {c}
                  </MenuItem>
                ))}
              </TextField>
              <span>{shown.length} 道题目</span>
            </div>
            {tasks.length ? (
              <div className="eval-table" role="region" aria-label="项目题目集">
                <div className="eval-task-row eval-table-heading">
                  <Checkbox
                    size="small"
                    checked={
                      shown.length > 0 &&
                      shown.every((t) => selected.includes(t.id))
                    }
                    indeterminate={
                      shown.some((t) => selected.includes(t.id)) &&
                      !shown.every((t) => selected.includes(t.id))
                    }
                    onChange={(e) =>
                      setSelected(
                        e.target.checked
                          ? Array.from(
                              new Set([...selected, ...shown.map((t) => t.id)]),
                            )
                          : selected.filter(
                              (id) => !shown.some((t) => t.id === id),
                            ),
                      )
                    }
                    inputProps={{ "aria-label": "选择全部可见题目" }}
                  />
                  <span>题目</span>
                  <span>分类</span>
                  <span>类型</span>
                  <span>版本</span>
                  <span />
                </div>
                {shown.map((t, index) => (
                  <div
                    key={t.id}
                    className={`eval-task-row ${selected.includes(t.id) ? "is-selected" : ""}`}
                  >
                    <Checkbox
                      size="small"
                      checked={selected.includes(t.id)}
                      inputProps={{
                        "aria-label": `选择题目 ${t.definition.title}`,
                      }}
                      onChange={(e) =>
                        setSelected(
                          e.target.checked
                            ? [...selected, t.id]
                            : selected.filter((id) => id !== t.id),
                        )
                      }
                    />
                    <button
                      className="eval-task-name"
                      onClick={() => setTask(t)}
                      aria-label={`查看题目 ${t.definition.title}`}
                    >
                      <span className="eval-task-code">
                        EV-{String(index + 1).padStart(3, "0")}
                      </span>
                      <div>
                        <strong>{t.definition.title}</strong>
                        <small>{t.definition.objective}</small>
                      </div>
                    </button>
                    <span className="eval-category">
                      {t.definition.category}
                    </span>
                    <span className="eval-kind">
                      {t.definition.kind === "conversation"
                        ? "对话"
                        : t.definition.kind === "http"
                          ? "HTTP"
                          : "命令 / 文件"}
                    </span>
                    <span className="muted">v{t.version}</span>
                    <Tooltip title="查看题目详情">
                      <IconButton
                        size="small"
                        aria-label={`打开 ${t.definition.title}`}
                        onClick={() => setTask(t)}
                      >
                        <ArrowUpRight size={15} />
                      </IconButton>
                    </Tooltip>
                  </div>
                ))}
              </div>
            ) : (
              <Empty
                icon={<FlaskConical />}
                title="从第一组题目开始"
                description="先明确评测方向，模型会从当前项目资料中设计题目和检查规则。"
                action={
                  <Button
                    variant="outlined"
                    disabled={!detail.readiness.generation_allowed}
                    onClick={() => setDialog("generation")}
                  >
                    生成题目
                  </Button>
                }
              />
            )}
            {tasks.length > 0 && (
              <div className="eval-footnote">
                <FileText size={14} />
                <span>
                  题目与资料快照绑定。模型评分尚未校准，修改后将保存为新版本。
                </span>
              </div>
            )}
          </>
        ) : runs.length ? (
          <div className="eval-run-layout">
            <div
              className="eval-run-list"
              role="navigation"
              aria-label="运行批次"
            >
              {runs.map((r, index) => (
                <button
                  key={r.id}
                  className={r.id === run?.id ? "is-active" : ""}
                  onClick={() => {
                    setRunId(r.id);
                    setResult(null);
                    setResultIds([]);
                  }}
                >
                  <div>
                    <strong>
                      运行 {String(runs.length - index).padStart(2, "0")}
                    </strong>
                    <StateBadge status={r.status} />
                  </div>
                  <p>
                    {r.tasks?.length ?? r.results.length} 道题目{" "}
                    <span>{date(r.created_at)}</span>
                  </p>
                </button>
              ))}
            </div>
            {run && (
              <section className="eval-run-detail" aria-label="运行详情">
                <div className="eval-run-title">
                  <div>
                    <h2>
                      {section === "analyses" ? "本次运行分析" : "运行结果"}
                    </h2>
                    <p className="mono">{run.id.slice(-12)}</p>
                  </div>
                  <div>
                    <StateBadge status={run.status} />
                    {active(run.status) ? (
                      <Button
                        color="inherit"
                        size="small"
                        startIcon={<Square />}
                        disabled={busy || run.status === "cancelling"}
                        onClick={() => void act(() => ev.cancel(pid, run.id))}
                      >
                        停止运行
                      </Button>
                    ) : (
                      <Button
                        size="small"
                        startIcon={<WandSparkles />}
                        onClick={() => setDialog("analysis")}
                      >
                        分析结果
                      </Button>
                    )}
                  </div>
                </div>
                {run.error && (
                  <Alert
                    severity={run.status === "failed" ? "error" : "warning"}
                  >
                    {run.error}
                  </Alert>
                )}
                <div className="eval-run-summary">
                  <div>
                    <strong>
                      {run.results.filter((r) => !active(r.status)).length}
                      <small>
                        {" "}
                        / {run.tasks?.length ?? run.results.length}
                      </small>
                    </strong>
                    <span>已处理</span>
                  </div>
                  <div>
                    <strong className="eval-good">{summary.passed}</strong>
                    <span>通过</span>
                  </div>
                  <div>
                    <strong className="eval-bad">{summary.failed}</strong>
                    <span>未通过</span>
                  </div>
                  <div>
                    <strong>{summary.unknown}</strong>
                    <span>未评分</span>
                  </div>
                </div>
                {active(run.status) && (
                  <LinearProgress
                    variant="determinate"
                    value={
                      (100 *
                        run.results.filter((r) => !active(r.status)).length) /
                      Math.max(run.tasks?.length ?? 1, 1)
                    }
                  />
                )}
                <div className="eval-run-meta">
                  <span>{run.models?.target.model ?? "未调用模型"}</span>
                  <span>调用上限 {run.budget?.max_model_calls ?? "—"} 次</span>
                  <UsageLine value={run.usage} />
                </div>
                {section === "runs" ? (
                  <>
                    <div className="eval-results-toolbar">
                      <h3>逐题结果</h3>
                      <TextField
                        select
                        size="small"
                        value={resultFilter}
                        onChange={(e) => setResultFilter(e.target.value)}
                        slotProps={{ htmlInput: { "aria-label": "结果筛选" } }}
                      >
                        <MenuItem value="all">全部结果</MenuItem>
                        {Array.from(
                          new Set(run.results.map((r) => r.status)),
                        ).map((s) => (
                          <MenuItem key={s} value={s}>
                            {statusNames[s] ?? s}
                          </MenuItem>
                        ))}
                      </TextField>
                    </div>
                    <div className="eval-result-list">
                      {currentResults.map((r) => (
                        <div className="eval-result-row" key={r.id}>
                          <Checkbox
                            size="small"
                            checked={resultIds.includes(r.id)}
                            inputProps={{
                              "aria-label": `选择结果 ${r.task.definition.title}`,
                            }}
                            onChange={(e) =>
                              setResultIds(
                                e.target.checked
                                  ? [...resultIds, r.id]
                                  : resultIds.filter((id) => id !== r.id),
                              )
                            }
                          />
                          <button onClick={() => setResult(r)}>
                            <div>
                              <strong>{r.task.definition.title}</strong>
                              <small>
                                v{r.task.version} ·{" "}
                                {r.duration_ms != null
                                  ? `${(r.duration_ms / 1000).toFixed(1)} 秒`
                                  : "等待执行"}
                              </small>
                            </div>
                            <StateBadge status={r.status} />
                            <span className="eval-score">
                              {r.score === null
                                ? "—"
                                : `${Math.round(r.score * 100)}%`}
                            </span>
                            <ChevronRight size={14} />
                          </button>
                        </div>
                      ))}
                      {!run.results.length && (
                        <p className="eval-inline-empty">
                          运行已启动，正在准备第一道题目。
                        </p>
                      )}
                    </div>
                    {resultIds.length > 0 && (
                      <Button
                        startIcon={<WandSparkles />}
                        disabled={active(run.status)}
                        onClick={() => setDialog("analysis")}
                      >
                        分析选中 {resultIds.length} 项结果
                      </Button>
                    )}
                  </>
                ) : (
                  <AnalysisReports
                    reports={reports}
                    onResult={(id) => {
                      const r = run.results.find((r) => r.id === id);
                      if (r) setResult(r);
                    }}
                    onAnalyze={() => setDialog("analysis")}
                    disabled={active(run.status)}
                  />
                )}
                <details className="eval-environment-details">
                  <summary>运行环境与清理状态</summary>
                  <p>
                    {run.environment_snapshot?.plan?.write_directory ??
                      run.environment_id}
                  </p>
                  <p>
                    清理状态：
                    {run.cleanup_status === "completed"
                      ? "本次子进程已回收，证据文件保留"
                      : run.cleanup_status}
                  </p>
                  {run.environment_snapshot?.plan?.limitations?.map((v) => (
                    <p key={v}>{v}</p>
                  ))}
                </details>
              </section>
            )}
          </div>
        ) : (
          <Empty
            icon={<Play />}
            title="还没有评测运行"
            description="到题目集选择要验证的题目，然后准备独立环境并启动运行。"
            action={
              <Button variant="outlined" onClick={() => onSection("tasks")}>
                选择题目
              </Button>
            }
          />
        )}
      </div>
      {task && (
        <TaskDialog
          key={task.id}
          projectId={pid}
          task={task}
          onClose={() => setTask(null)}
          onSaved={async (t) => {
            setTask(t);
            await refresh();
          }}
        />
      )}
      {dialog === "generation" && (
        <GenerationDialog
          projectId={pid}
          onClose={() => setDialog(null)}
          onCreated={async () => {
            setDialog(null);
            await refresh();
          }}
        />
      )}
      {dialog === "run" && (
        <RunDialog
          projectId={pid}
          tasks={selectedTasks}
          environments={environments}
          onClose={() => setDialog(null)}
          onCreated={async (r) => {
            setDialog(null);
            setRunId(r.id);
            await refresh();
            onSection("runs");
          }}
        />
      )}
      {dialog === "analysis" && run && (
        <AnalysisDialog
          projectId={pid}
          run={run}
          selectedIds={resultIds}
          onClose={() => setDialog(null)}
          onCreated={async () => {
            setDialog(null);
            await refresh();
            onSection("analyses");
          }}
        />
      )}
      {selectedResult && (
        <ResultEvidence
          result={selectedResult}
          onClose={() => setResult(null)}
        />
      )}
    </div>
  );
}
function Empty({
  icon,
  title,
  description,
  action,
}: {
  icon: React.ReactNode;
  title: string;
  description: string;
  action?: React.ReactNode;
}) {
  return (
    <div className="eval-empty">
      {icon}
      <h2>{title}</h2>
      <p>{description}</p>
      {action}
    </div>
  );
}
function AnalysisReports({
  reports,
  onResult,
  onAnalyze,
  disabled,
}: {
  reports: Analysis[];
  onResult: (id: string) => void;
  onAnalyze: () => void;
  disabled: boolean;
}) {
  return (
    <div className="eval-reports">
      {reports.length ? (
        reports.map((report) => (
          <article className="eval-report" key={report.id}>
            <header>
              <div>
                <h3>结果分析</h3>
                <p>
                  {date(report.created_at)} · {report.result_ids.length} 项结果
                </p>
              </div>
              <StateBadge status={report.status} />
            </header>
            {report.error && <Alert severity="warning">{report.error}</Alert>}
            {report.report ? (
              <>
                <p className="report-summary">{report.report.summary}</p>
                {(["facts", "hypotheses"] as const).map((key) => (
                  <section key={key}>
                    <h4>{key === "facts" ? "观察事实" : "可能原因"}</h4>
                    {report.report![key].map((item, index) => (
                      <div className="report-fact" key={index}>
                        <p>{item.text}</p>
                        <div>
                          {item.result_ids.map((id, i) => (
                            <button
                              className="link-button"
                              key={id}
                              onClick={() => onResult(id)}
                            >
                              查看证据 {i + 1}
                              <ArrowUpRight size={12} />
                            </button>
                          ))}
                        </div>
                      </div>
                    ))}
                  </section>
                ))}
                <section>
                  <h4>改进建议</h4>
                  <ul>
                    {report.report.recommendations.map((v, i) => (
                      <li key={i}>{v}</li>
                    ))}
                  </ul>
                </section>
                <section className="report-limitations">
                  <h4>分析限制</h4>
                  {report.report.limitations.map((v, i) => (
                    <p key={i}>{v}</p>
                  ))}
                </section>
              </>
            ) : active(report.status) ? (
              <LinearProgress />
            ) : null}
            <UsageLine value={report.usage} />
          </article>
        ))
      ) : (
        <Empty
          icon={<WandSparkles />}
          title="从运行证据中寻找原因"
          description="选择全部、未通过、低分或指定结果。分析使用独立调用预算，保留每项引用。"
          action={
            <Button variant="outlined" disabled={disabled} onClick={onAnalyze}>
              生成结果分析
            </Button>
          }
        />
      )}
    </div>
  );
}
function ResultEvidence({
  result,
  onClose,
}: {
  result: EvalResult;
  onClose: () => void;
}) {
  return <TaskEvidenceDrawer result={result} onClose={onClose} />;
}
import { FormDrawer } from "./ui";
function TaskEvidenceDrawer({
  result: r,
  onClose,
}: {
  result: EvalResult;
  onClose: () => void;
}) {
  const [tab, setTab] = useState("response");
  const document = r.observation?.json as
    | {
        reply?: string;
        turns?: Record<string, unknown>[];
        writes?: unknown[];
        audit?: unknown[];
      }
    | undefined;
  return (
    <FormDrawer title="执行证据" onClose={onClose}>
      <div className="evidence-heading">
        <StateBadge status={r.status} />
        <span>v{r.task.version}</span>
        <h3>{r.task.definition.title}</h3>
        <p>{r.task.definition.objective}</p>
      </div>
      {r.error && <Alert severity="warning">{r.error}</Alert>}
      <div className="evidence-tabs">
        {[
          ["response", "实际输出"],
          ["checks", "评分检查"],
          ["raw", "完整证据"],
        ].map(([id, label]) => (
          <button
            key={id}
            className={tab === id ? "is-active" : ""}
            onClick={() => setTab(id)}
          >
            {label}
          </button>
        ))}
      </div>
      {tab === "checks" ? (
        <div className="evidence-checks">
          {r.checks.map((c, index) => (
            <section key={index}>
              <StateBadge status={c.status ?? "pending"} />
              <h4>{c.description || c.type}</h4>
              <p>{c.reason}</p>
              <dl>
                <dt>期望</dt>
                <dd>
                  <pre>{JSON.stringify(c.expected, null, 2)}</pre>
                </dd>
                <dt>实际</dt>
                <dd>
                  <pre>{JSON.stringify(c.actual ?? null, null, 2)}</pre>
                </dd>
              </dl>
              {c.evidence?.map((quote, i) => (
                <blockquote key={i}>{quote}</blockquote>
              ))}
            </section>
          ))}
        </div>
      ) : tab === "raw" ? (
        <pre className="evidence-json">
          {JSON.stringify(r.observation, null, 2)}
        </pre>
      ) : (
        <div className="evidence-response">
          {document?.turns?.map((turn, i) => (
            <section key={i}>
              <span>第 {i + 1} 轮</span>
              <div className="evidence-user">{String(turn.input ?? "")}</div>
              <div className="evidence-assistant">
                {String(turn.reply ?? turn.error ?? JSON.stringify(turn))}
              </div>
            </section>
          ))}
          {!document?.turns && (
            <pre>
              {String(
                r.observation?.text ??
                  r.observation?.stdout ??
                  "此结果没有可用输出。",
              )}
            </pre>
          )}
          {document?.writes && (
            <div className="evidence-write-count">
              合成后端写操作 <strong>{document.writes.length}</strong>
            </div>
          )}
        </div>
      )}
      <p className="eval-footnote">
        模型判断尚未人工校准；缺失证据保持未评分。
      </p>
    </FormDrawer>
  );
}
