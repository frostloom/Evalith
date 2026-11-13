import { useCallback, useEffect, useRef, useState } from "react";
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
  TestSet,
} from "./evaluationTypes";
import type { ModelConfig, ProjectDetail, WorkspaceTab } from "./types";
import { PageHeader } from "./ui";
import {
  AnalysisDialog,
  GenerationDialog,
  RunDialog,
  TaskDialog,
} from "./EvaluationDialogs";

import { active, StateBadge, UsageLine } from "./evaluationUi";
import { EvaluationRunView } from "./EvaluationRunView";
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
  models = [],
  collection = null,
}: {
  detail: ProjectDetail;
  section: WorkspaceTab;
  models?: ModelConfig[];
  collection?: TestSet | null;
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
  const scopedTasks = collection
    ? tasks.filter((t) => collection.task_ids.includes(t.id))
    : tasks;
  const shown = scopedTasks.filter(
    (t) =>
      (category === "all" || t.definition.category === category) &&
      `${t.definition.title} ${t.definition.objective}`
        .toLowerCase()
        .includes(query.toLowerCase()),
  );
  const run = runs.find((r) => r.id === runId) ?? runs[0];
  const generation = jobs.find((j) => active(j.status));
  const selectedTasks = tasks.filter((t) => selected.includes(t.id));
  const selectedResult =
    (result && run?.results.find((r) => r.id === result.id)) || null;
  const reports = analyses.filter((a) => a.run_id === run?.id);
  return (
    <div
      className="evaluation-workspace"
      role="tabpanel"
      id={`panel-${section}`}
      aria-labelledby={`tab-${section}`}
    >
      <div className="eval-breadcrumb">
        <span>{detail.project.name}</span>
        {collection && section === "tasks" && (
          <button className="link-button" onClick={() => onSection("sets")}>
            测试集 /
          </button>
        )}
        <ChevronRight size={13} />
        <strong>
          {section === "tasks"
            ? (collection?.name ?? "测试题目")
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
              ? (collection?.name ?? "测试题目")
              : section === "runs"
                ? "评测运行"
                : "结果分析"
          }
          description={
            section === "tasks"
              ? (collection?.description ??
                "把项目资料变成可追溯的评测，再用证据检查实际表现。")
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
                  variant={collection ? "outlined" : "contained"}
                  startIcon={collection ? undefined : <Plus />}
                  disabled={
                    !collection &&
                    (!detail.readiness.generation_allowed ||
                      Boolean(generation))
                  }
                  onClick={() =>
                    collection ? onSection("sets") : setDialog("generation")
                  }
                >
                  {collection ? "管理测试集" : "生成题目"}
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
              <p>模型正在生成题目、Rubric 与 Grader，完成后自动组成测试集。</p>
              <LinearProgress />
            </div>
          </div>
        )}
        {section === "tasks" && !generation && jobs[0]?.status === "failed" && (
          <Alert severity="error">题目生成失败：{jobs[0].error}</Alert>
        )}
        {section === "tasks" &&
          !generation &&
          jobs[0]?.status === "completed" &&
          jobs[0].operation === "preparation" && (
            <Alert severity="success">
              已准备 {jobs[0].result?.task_ids.length ?? 0} 道题目、
              {jobs[0].result?.grader_ids.length ?? 0} 项 Grader
              和测试集。评分标准未校准，执行环境仍需确认。
              <Button size="small" onClick={() => onSection("sets")}>
                查看测试集
              </Button>
              <Button size="small" onClick={() => onSection("graders")}>
                查看 Grader
              </Button>
            </Alert>
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
                  new Set(scopedTasks.map((t) => t.definition.category)),
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
          <EvaluationRunView
            runs={runs}
            run={run}
            section={section}
            selectedRunId={runId}
            busy={busy}
            selectedResultIds={resultIds}
            onSelect={(id) => {
              setRunId(id);
              setResult(null);
              setResultIds([]);
            }}
            onResult={setResult}
            onSelection={setResultIds}
            onAnalyze={() => setDialog("analysis")}
            onCancel={() => void act(() => ev.cancel(pid, run!.id))}
          >
            <AnalysisReports
              reports={reports}
              onResult={(id) => {
                const value = run?.results.find((r) => r.id === id);
                if (value) setResult(value);
              }}
              onAnalyze={() => setDialog("analysis")}
              disabled={run ? active(run.status) : true}
            />
          </EvaluationRunView>
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
          models={models}
          defaultModel={detail.project.model_config_id}
          defaultGraderIds={collection?.grader_ids ?? []}
          testSet={collection}
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
    <FormDrawer title="测试结果" width={1050} onClose={onClose}>
      <div className="evidence-heading">
        <StateBadge status={r.status} />
        <span>v{r.task.version}</span>
        <h3>{r.task.definition.title}</h3>
        <p>{r.task.definition.objective}</p>
      </div>
      {r.error && <Alert severity="warning">{r.error}</Alert>}
      <div className="evidence-tabs">
        {[
          ["response", "对话"],
          ["checks", "评估"],
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
              <h4>{c.grader_name || c.description || c.type}</h4>
              {c.threshold !== undefined && (
                <p>
                  标准 v{c.grader_version} · 通过阈值 ≥ {c.threshold} ·{" "}
                  {c.judge_model ?? "确定性检查"}
                </p>
              )}
              <p>{c.reason}</p>
              {!!c.uncertainties?.length && (
                <Alert severity="warning">{c.uncertainties.join("；")}</Alert>
              )}
              <dl>
                <dt>期望</dt>
                <dd>
                  <pre>
                    {typeof c.expected === "string"
                      ? c.expected
                      : JSON.stringify(c.expected, null, 2)}
                  </pre>
                </dd>
                <dt>{c.type === "judge" ? "模型评分" : "实际"}</dt>
                <dd>
                  <pre>
                    {c.type === "judge"
                      ? c.score == null
                        ? "尚未评分"
                        : `${c.score} / 1`
                      : c.actual === undefined
                        ? "未返回实际值"
                        : JSON.stringify(c.actual, null, 2)}
                  </pre>
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
