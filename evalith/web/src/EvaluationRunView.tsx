import { useState, type ReactNode } from "react";
import {
  Alert,
  Button,
  Checkbox,
  MenuItem,
  Tab,
  Tabs,
  TextField,
  Tooltip,
} from "@mui/material";
import {
  ArrowLeft,
  ArrowUpRight,
  ChevronRight,
  Play,
  Square,
  WandSparkles,
} from "lucide-react";
import type { EvalRun, EvalResult, Check } from "./evaluationTypes";
import type { WorkspaceTab } from "./types";
import { StateBadge, UsageLine, active, statusNames } from "./evaluationUi";
import { checkLabels } from "./EvaluationLibraryPage";
const date = (s: string) =>
  new Date(s).toLocaleString("zh-CN", {
    month: "numeric",
    day: "numeric",
    hour: "2-digit",
    minute: "2-digit",
  });
export function EvaluationRunView({
  runs,
  run,
  section,
  selectedRunId,
  busy,
  selectedResultIds,
  onSelect,
  onResult,
  onSelection,
  onAnalyze,
  onCancel,
  children,
}: {
  runs: EvalRun[];
  run: EvalRun | undefined;
  section: WorkspaceTab;
  selectedRunId: string | null;
  busy: boolean;
  selectedResultIds: string[];
  onSelect: (id: string) => void;
  onResult: (result: EvalResult) => void;
  onSelection: (ids: string[]) => void;
  onAnalyze: () => void;
  onCancel: () => void;
  children: ReactNode;
}) {
  const [opened, setOpened] = useState(Boolean(selectedRunId)),
    [tab, setTab] = useState("summary"),
    [filter, setFilter] = useState("all");
  if (!run) return null;
  const detail = opened || section === "analyses";
  if (!detail)
    return (
      <div className="run-directory">
        <div className="run-table-heading">
          <span>运行批次</span>
          <span>开始时间</span>
          <span>测试题目</span>
          <span>通过率</span>
          <span>状态</span>
          <span />
        </div>
        {runs.map((r, index) => {
          const scored = r.results.filter((v) => v.score !== null);
          const passed = r.results.filter((v) => v.status === "passed");
          return (
            <button
              className="run-directory-row"
              key={r.id}
              onClick={() => {
                onSelect(r.id);
                setOpened(true);
                setTab("summary");
              }}
            >
              <div>
                <span className="run-list-symbol">
                  <Play size={15} />
                </span>
                <span>
                  <strong>
                    {r.name ??
                      `评测运行 ${String(runs.length - index).padStart(2, "0")}`}
                  </strong>
                  <small>{r.models?.target.model ?? "未调用模型"}</small>
                </span>
              </div>
              <span>{date(r.created_at)}</span>
              <span>{r.tasks.length} 道</span>
              <span>
                {scored.length
                  ? `${Math.round((passed.length / scored.length) * 100)}%`
                  : "—"}
              </span>
              <StateBadge status={r.status} />
              <ChevronRight size={15} />
            </button>
          );
        })}
      </div>
    );
  const position = runs.findIndex((r) => r.id === run.id);
  const passed = run.results.filter((r) => r.status === "passed").length;
  const failed = run.results.filter((r) => r.status === "failed").length;
  const scored = run.results.filter((r) => r.score !== null).length;
  const done = run.results.filter((r) => !active(r.status)).length;
  const shown = run.results.filter(
    (r) => filter === "all" || r.status === filter,
  );
  const keys = Array.from(
    new Set(
      run.results.flatMap((r) => r.checks.map((c) => c.grader_id ?? c.type)),
    ),
  );
  const find = (r: EvalResult, key: string) =>
    r.checks.filter((c) => (c.grader_id ?? c.type) === key);
  const label = (key: string) => {
    const c = run.results
      .flatMap((r) => r.checks)
      .find((c) => (c.grader_id ?? c.type) === key);
    return c?.grader_name ?? checkLabels[key] ?? key;
  };
  const cell = (checks: Check[]) =>
    !checks.length
      ? "not_applicable"
      : checks.some((c) => c.status === "failed")
        ? "failed"
        : checks.some((c) => c.status === "missing_evidence")
          ? "validation_error"
          : checks.every((c) => c.status === "passed")
            ? "passed"
            : "review_required";
  return (
    <div className="run-detail-screen">
      <div className="run-detail-heading">
        <div>
          <button
            className="link-button"
            onClick={() => setOpened(false)}
            disabled={section === "analyses"}
          >
            <ArrowLeft size={14} />
            全部运行
          </button>
          <h1>
            {run.name ??
              `评测运行 ${String(runs.length - position).padStart(2, "0")}`}
          </h1>
          <p>
            {date(run.created_at)}
            <span>·</span>
            {run.tasks.length} 道题目 <StateBadge status={run.status} />
          </p>
        </div>
        <div className="run-heading-actions">
          {active(run.status) ? (
            <Button
              variant="outlined"
              startIcon={<Square />}
              disabled={busy || run.status === "cancelling"}
              onClick={onCancel}
            >
              停止运行
            </Button>
          ) : (
            <Button
              variant="contained"
              startIcon={<WandSparkles />}
              onClick={onAnalyze}
            >
              分析结果
            </Button>
          )}
        </div>
      </div>
      {section === "analyses" ? (
        <div className="run-analysis-picker">
          <TextField
            select
            label="选择运行"
            value={run.id}
            onChange={(e) => onSelect(e.target.value)}
          >
            {runs.map((r, i) => (
              <MenuItem key={r.id} value={r.id}>
                评测运行 {runs.length - i} · {date(r.created_at)} ·{" "}
                {statusNames[r.status]}
              </MenuItem>
            ))}
          </TextField>
        </div>
      ) : (
        <Tabs
          value={tab}
          onChange={(_, value: string) => setTab(value)}
          className="run-detail-tabs"
          aria-label="运行详情章节"
        >
          <Tab label="概览" value="summary" />
          <Tab label="测试结果" value="tests" />
          <Tab label="运行配置" value="configuration" />
        </Tabs>
      )}
      {run.error && (
        <Alert severity={run.status === "failed" ? "error" : "warning"}>
          {run.error}
        </Alert>
      )}
      {section === "analyses" ? (
        children
      ) : tab === "summary" ? (
        <>
          <div className="run-stat-grid">
            <section>
              <span>通过率</span>
              <strong>
                {scored ? Math.round((passed / scored) * 100) : "—"}
                <small>{scored ? "%" : ""}</small>
              </strong>
              <div className="result-mini-bars">
                {run.results.map((r) => (
                  <Tooltip
                    key={r.id}
                    title={`${r.task.definition.title} · ${statusNames[r.status]}`}
                  >
                    <button
                      className={"mini-" + r.status}
                      onClick={() => onResult(r)}
                      aria-label={`查看结果 ${r.task.definition.title}`}
                    />
                  </Tooltip>
                ))}
              </div>
              <p>
                {passed} / {scored} 项已评分结果通过
              </p>
            </section>
            <section>
              <span>已执行题目</span>
              <strong>
                {done}
                <small> / {run.tasks.length}</small>
              </strong>
              <div className="stat-progress">
                <span
                  style={{
                    width: `${(100 * done) / Math.max(run.tasks.length, 1)}%`,
                  }}
                />
              </div>
              <p>{active(run.status) ? "正在逐题保存结果" : "执行已经结束"}</p>
            </section>
            <section>
              <span>未通过</span>
              <strong className="eval-bad">{failed}</strong>
              <p>
                {run.results.filter((r) => r.score === null).length}{" "}
                项未评分或未完成
              </p>
            </section>
            <section>
              <span>模型调用</span>
              <strong>
                {run.usage.model_calls ?? "—"}
                <small> 次</small>
              </strong>
              <p>上限 {run.budget.max_model_calls} 次 · 金额费用未知</p>
            </section>
          </div>
          <section className="run-matrix">
            <header>
              <div>
                <h2>评价结果</h2>
                <p>按检查方式查看每道题的实际判断。点击色块查看完整证据。</p>
              </div>
              <Button size="small" onClick={() => setTab("tests")}>
                查看测试结果
                <ArrowUpRight size={14} />
              </Button>
            </header>
            <div className="matrix-row matrix-labels">
              <span>评价标准 / 检查</span>
              <span>通过</span>
              <div>
                {run.results.map((r, i) => (
                  <Tooltip key={r.id} title={r.task.definition.title}>
                    <span>{i + 1}</span>
                  </Tooltip>
                ))}
              </div>
            </div>
            {keys.map((key) => (
              <div className="matrix-row" key={key}>
                <strong>{label(key)}</strong>
                <span>
                  {
                    run.results.filter((r) => cell(find(r, key)) === "passed")
                      .length
                  }
                </span>
                <div>
                  {run.results.map((r) => (
                    <Tooltip
                      key={r.id}
                      title={`${r.task.definition.title} · ${statusNames[cell(find(r, key))] ?? "不适用"}`}
                    >
                      <button
                        className={"matrix-" + cell(find(r, key))}
                        aria-label={`${label(key)}：${r.task.definition.title}`}
                        onClick={() => onResult(r)}
                      />
                    </Tooltip>
                  ))}
                </div>
              </div>
            ))}
            {!keys.length && (
              <p className="field-note">
                尚未产生评分检查，已保存的执行输出可在测试结果中查看。
              </p>
            )}
            <footer>
              {[
                ["passed", "通过"],
                ["failed", "未通过"],
                ["review_required", "待复核"],
                ["not_applicable", "不适用"],
              ].map(([s, name]) => (
                <span key={s}>
                  <i className={"matrix-" + s} />
                  {name}
                </span>
              ))}
            </footer>
          </section>
          <div className="run-token-card">
            <h3>用量与模型</h3>
            <p>
              {run.models.target.model}
              <span>评分模型：{run.models.judge.model}</span>
            </p>
            <UsageLine value={run.usage} />
          </div>
        </>
      ) : tab === "tests" ? (
        <>
          <div className="eval-results-toolbar">
            <div>
              <h2>测试结果</h2>
              <p>{shown.length} 项结果，点击行查看对话和评分。</p>
            </div>
            <TextField
              select
              value={filter}
              onChange={(e) => setFilter(e.target.value)}
              slotProps={{ htmlInput: { "aria-label": "结果筛选" } }}
            >
              <MenuItem value="all">全部状态</MenuItem>
              {Array.from(new Set(run.results.map((r) => r.status))).map(
                (s) => (
                  <MenuItem key={s} value={s}>
                    {statusNames[s]}
                  </MenuItem>
                ),
              )}
            </TextField>
          </div>
          <div className="result-table-header">
            <span>测试目标</span>
            <span>状态</span>
            <span>得分</span>
            <span>耗时</span>
          </div>
          {shown.map((r) => (
            <div className="eval-result-row" key={r.id}>
              <Checkbox
                checked={selectedResultIds.includes(r.id)}
                inputProps={{
                  "aria-label": `选择结果 ${r.task.definition.title}`,
                }}
                onChange={(e) =>
                  onSelection(
                    e.target.checked
                      ? [...selectedResultIds, r.id]
                      : selectedResultIds.filter((id) => id !== r.id),
                  )
                }
              />
              <button onClick={() => onResult(r)}>
                <div>
                  <strong>{r.task.definition.title}</strong>
                  <small>{r.task.definition.objective}</small>
                </div>
                <StateBadge status={r.status} />
                <span>
                  {r.score === null ? "—" : `${Math.round(r.score * 100)}%`}
                </span>
                <span className="result-duration">
                  {r.duration_ms != null
                    ? `${(r.duration_ms / 1000).toFixed(1)}s`
                    : "—"}
                </span>
                <ChevronRight size={14} />
              </button>
            </div>
          ))}
          {selectedResultIds.length > 0 && (
            <Button
              disabled={active(run.status)}
              startIcon={<WandSparkles />}
              onClick={onAnalyze}
            >
              分析选中 {selectedResultIds.length} 项
            </Button>
          )}
        </>
      ) : (
        <div className="run-config-grid">
          <section>
            <h2>模型配置</h2>
            <dl>
              <dt>被测模型</dt>
              <dd>{run.models.target.name}</dd>
              <dt>默认评分模型</dt>
              <dd>{run.models.judge.name}</dd>
              <dt>调用上限</dt>
              <dd>{run.budget.max_model_calls} 次</dd>
              <dt>金额费用</dt>
              <dd>未知</dd>
            </dl>
          </section>
          <section>
            <h2>评价标准</h2>
            {run.graders?.length ? (
              run.graders.map((g) => (
                <article key={g.id}>
                  <h3>
                    {g.name}
                    <small>v{g.version}</small>
                  </h3>
                  <p>{g.rubric}</p>
                  <span>
                    {g.check.type === "judge"
                      ? `通过阈值 ≥ ${g.threshold} · `
                      : ""}
                    {checkLabels[g.check.type]}
                  </span>
                </article>
              ))
            ) : (
              <p>使用题目版本中保存的内置检查与 Rubric。</p>
            )}
          </section>
          <section>
            <h2>运行环境</h2>
            <dl>
              <dt>执行器</dt>
              <dd>{run.environment_snapshot.adapter}</dd>
              <dt>产物目录</dt>
              <dd>
                {run.environment_snapshot.plan?.write_directory ??
                  run.environment_id}
              </dd>
              <dt>清理状态</dt>
              <dd>
                {run.cleanup_status === "completed"
                  ? "子进程已回收，证据保留"
                  : run.cleanup_status}
              </dd>
            </dl>
            {run.environment_snapshot.plan?.limitations?.map((s, i) => (
              <p key={i}>{s}</p>
            ))}
          </section>
        </div>
      )}
    </div>
  );
}
