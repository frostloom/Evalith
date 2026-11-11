import { useEffect, useState } from "react";
import {
  Alert,
  Button,
  LinearProgress,
  MenuItem,
  TextField,
} from "@mui/material";
import { Check, ChevronRight, Play, Plus, Trash2 } from "lucide-react";
import { FormDrawer } from "./ui";
import { api } from "./api";
import { evaluationApi as ev } from "./evaluationApi";
import type {
  Environment,
  EvalRun,
  EvalTask,
  TaskDefinition,
} from "./evaluationTypes";
import type { ExecutorConfig } from "./types";
const errorText = (e: unknown) =>
  e instanceof Error ? e.message : "操作失败，请重试。";
function ErrorNotice({ value }: { value: string }) {
  return value ? <Alert severity="error">{value}</Alert> : null;
}
export function GenerationDialog({
  projectId,
  onClose,
  onCreated,
}: {
  projectId: string;
  onClose: () => void;
  onCreated: () => Promise<void>;
}) {
  const [count, setCount] = useState(3),
    [direction, setDirection] = useState(""),
    [busy, setBusy] = useState(false),
    [error, setError] = useState("");
  const submit = async () => {
    setBusy(true);
    setError("");
    try {
      await ev.generate(projectId, count, direction);
      await onCreated();
    } catch (e) {
      setError(errorText(e));
      setBusy(false);
    }
  };
  return (
    <FormDrawer
      title="生成题目"
      presentation="dialog"
      onClose={onClose}
      busy={busy}
      footer={
        <>
          <Button onClick={onClose} disabled={busy}>
            取消
          </Button>
          <Button
            variant="contained"
            onClick={() => void submit()}
            disabled={
              busy || !Number.isInteger(count) || count < 1 || count > 12
            }
          >
            {busy ? "正在提交…" : "开始生成"}
          </Button>
        </>
      }
    >
      <div className="eval-form">
        <p className="dialog-description">
          根据当前理解和资料设计可编辑的题目。未确认的业务规则会保留为限制。
        </p>
        <ErrorNotice value={error} />
        <TextField
          label="评测方向"
          multiline
          minRows={4}
          placeholder="例如：查询时以工具数据为准，执行写操作前先确认。"
          value={direction}
          onChange={(e) => setDirection(e.target.value)}
          inputProps={{ maxLength: 4000 }}
        />
        <TextField
          label="生成数量"
          type="number"
          value={count}
          onChange={(e) => setCount(Number(e.target.value))}
          inputProps={{ min: 1, max: 12 }}
          helperText="每次 1–12 道，建议先用少量题目验证。"
        />
        <div className="eval-cost-note">
          <strong>本次调用模型 1 次</strong>
          <p>
            使用项目当前模型。账号额度与金额费用未知，失败不会自动更换模型或重试。
          </p>
        </div>
      </div>
    </FormDrawer>
  );
}
export function TaskDialog({
  projectId,
  task,
  onClose,
  onSaved,
}: {
  projectId: string;
  task: EvalTask;
  onClose: () => void;
  onSaved: (task: EvalTask) => Promise<void>;
}) {
  const [editing, setEditing] = useState(false),
    [draft, setDraft] = useState<TaskDefinition>(
      structuredClone(task.definition),
    ),
    [versions, setVersions] = useState<EvalTask[]>([]),
    [version, setVersion] = useState(task.version),
    [busy, setBusy] = useState(false),
    [error, setError] = useState(""),
    [inputText, setInputText] = useState(
      JSON.stringify(task.definition.input, null, 2),
    ),
    [refs, setRefs] = useState(task.definition.source_refs.join("\n"));
  useEffect(() => {
    let cancelled = false;
    void ev
      .versions(projectId, task.task_id || task.id)
      .then((r) => {
        if (!cancelled) setVersions(r.items);
      })
      .catch((e) => {
        if (!cancelled) setError(errorText(e));
      });
    return () => {
      cancelled = true;
    };
  }, [projectId, task]);
  const shown = versions.find((v) => v.version === version) ?? task;
  const change = (patch: Partial<TaskDefinition>) =>
    setDraft({ ...draft, ...patch });
  const save = async () => {
    setError("");
    setBusy(true);
    try {
      const input = JSON.parse(inputText) as Record<string, unknown>;
      const saved = await ev.edit(projectId, task.task_id || task.id, {
        ...draft,
        input,
        source_refs: refs
          .split("\n")
          .map((s) => s.trim())
          .filter(Boolean),
      });
      await onSaved(saved);
      setVersion(saved.version);
      setEditing(false);
    } catch (e) {
      setError(errorText(e));
    } finally {
      setBusy(false);
    }
  };
  return (
    <FormDrawer
      title={editing ? "编辑题目" : "题目详情"}
      onClose={onClose}
      busy={busy}
      footer={
        editing ? (
          <>
            <Button onClick={() => setEditing(false)} disabled={busy}>
              取消编辑
            </Button>
            <Button
              variant="contained"
              onClick={() => void save()}
              disabled={busy}
            >
              {busy ? "保存中…" : "保存新版本"}
            </Button>
          </>
        ) : (
          <>
            <span className="muted">原有运行保留历史版本</span>
            <Button
              variant="outlined"
              onClick={() => {
                setDraft(structuredClone(task.definition));
                setInputText(JSON.stringify(task.definition.input, null, 2));
                setRefs(task.definition.source_refs.join("\n"));
                setEditing(true);
              }}
            >
              编辑题目
            </Button>
          </>
        )
      }
    >
      <div className="eval-form">
        <ErrorNotice value={error} />
        {editing ? (
          <>
            <TextField
              label="题目名称"
              value={draft.title}
              onChange={(e) => change({ title: e.target.value })}
            />
            <TextField
              label="分类"
              value={draft.category}
              onChange={(e) => change({ category: e.target.value })}
            />
            <TextField
              label="评测目标"
              multiline
              minRows={2}
              value={draft.objective}
              onChange={(e) => change({ objective: e.target.value })}
            />
            <TextField
              label="输入数据（JSON）"
              className="json-field"
              multiline
              minRows={5}
              value={inputText}
              onChange={(e) => setInputText(e.target.value)}
              helperText={
                draft.kind === "conversation"
                  ? "turns 为用户消息数组，fixture 为合成数据。"
                  : "输入不得包含执行命令，程序由确认的环境提供。"
              }
            />
            <TextField
              label="评分说明"
              multiline
              minRows={2}
              value={draft.rubric}
              onChange={(e) => change({ rubric: e.target.value })}
            />
            <div className="eval-field-heading">
              <h3>检查规则</h3>
              <Button
                size="small"
                startIcon={<Plus />}
                onClick={() =>
                  change({
                    checks: [
                      ...draft.checks,
                      {
                        type: "contains",
                        expected: "",
                        path: "",
                        description: "",
                      },
                    ],
                  })
                }
              >
                添加规则
              </Button>
            </div>
            {draft.checks.map((check, index) => (
              <div className="check-editor" key={index}>
                <div>
                  <TextField
                    label="检查类型"
                    select
                    value={check.type}
                    onChange={(e) =>
                      change({
                        checks: draft.checks.map((c, i) =>
                          i === index ? { ...c, type: e.target.value } : c,
                        ),
                      })
                    }
                  >
                    {[
                      "contains",
                      "not_contains",
                      "json_equals",
                      "status_code",
                      "exit_code",
                      "file_exists",
                      "file_contains",
                      "judge",
                    ].map((type) => (
                      <MenuItem key={type} value={type}>
                        {type}
                      </MenuItem>
                    ))}
                  </TextField>
                  <Button
                    aria-label={`删除规则 ${index + 1}`}
                    disabled={draft.checks.length === 1}
                    onClick={() =>
                      change({
                        checks: draft.checks.filter((_, i) => i !== index),
                      })
                    }
                  >
                    <Trash2 size={15} />
                  </Button>
                </div>
                <TextField
                  label="期望值"
                  value={
                    typeof check.expected === "string"
                      ? check.expected
                      : JSON.stringify(check.expected)
                  }
                  helperText={
                    check.type === "json_equals"
                      ? "填写 JSON 值，保留数组、数字等类型。"
                      : "文本检查按文字保存；状态码和退出码填写整数。"
                  }
                  onChange={(e) => {
                    let expected: unknown = e.target.value;
                    try {
                      if (
                        [
                          "json_equals",
                          "status_code",
                          "exit_code",
                          "file_exists",
                        ].includes(check.type)
                      )
                        expected = JSON.parse(e.target.value);
                    } catch {
                      /* plain text */
                    }
                    change({
                      checks: draft.checks.map((c, i) =>
                        i === index ? { ...c, expected } : c,
                      ),
                    });
                  }}
                />
                <TextField
                  label="证据路径（可选）"
                  placeholder="例如 writes 或 turns.0.reply"
                  value={check.path ?? ""}
                  onChange={(e) =>
                    change({
                      checks: draft.checks.map((c, i) =>
                        i === index ? { ...c, path: e.target.value } : c,
                      ),
                    })
                  }
                />
              </div>
            ))}
            <TextField
              label="资料来源（每行一项）"
              multiline
              minRows={2}
              value={refs}
              onChange={(e) => setRefs(e.target.value)}
            />
          </>
        ) : (
          <>
            <div className="task-detail-title">
              <span className="eval-category">{shown.definition.category}</span>
              <span className="task-uncalibrated">尚未校准</span>
              <h3>{shown.definition.title}</h3>
              <p>{shown.definition.objective}</p>
            </div>
            <TextField
              label="题目版本"
              select
              value={version}
              onChange={(e) => setVersion(Number(e.target.value))}
            >
              {[task, ...versions.filter((v) => v.version !== task.version)]
                .sort((a, b) => b.version - a.version)
                .map((v) => (
                  <MenuItem key={v.version} value={v.version}>
                    v{v.version}
                    {v.version === task.version ? " · 当前版本" : ""}
                  </MenuItem>
                ))}
            </TextField>
            <section className="task-detail-section">
              <h4>输入</h4>
              {shown.definition.kind === "conversation" ? (
                (shown.definition.input.turns as string[]).map(
                  (turn, index) => (
                    <div className="task-turn" key={index}>
                      <span>用户 {index + 1}</span>
                      <p>{turn}</p>
                    </div>
                  ),
                )
              ) : (
                <pre>{JSON.stringify(shown.definition.input, null, 2)}</pre>
              )}
            </section>
            <section className="task-detail-section">
              <h4>评分规则</h4>
              <p>{shown.definition.rubric}</p>
              {shown.definition.checks.map((check, index) => (
                <div className="task-rule" key={index}>
                  <strong>{check.type}</strong>
                  <p>
                    {typeof check.expected === "string"
                      ? check.expected
                      : JSON.stringify(check.expected)}
                  </p>
                  {check.path && <code>{check.path}</code>}
                </div>
              ))}
            </section>
            <section className="task-detail-section">
              <h4>资料来源</h4>
              {shown.definition.source_refs.map((ref) => (
                <code className="task-source" key={ref}>
                  {ref}
                </code>
              ))}
            </section>
            {shown.definition.uncertainties.length > 0 && (
              <section className="task-detail-section">
                <h4>待确认与限制</h4>
                {shown.definition.uncertainties.map((s, i) => (
                  <p key={i}>{s}</p>
                ))}
              </section>
            )}
          </>
        )}
      </div>
    </FormDrawer>
  );
}
export function RunDialog({
  projectId,
  tasks,
  environments,
  onClose,
  onCreated,
}: {
  projectId: string;
  tasks: EvalTask[];
  environments: Environment[];
  onClose: () => void;
  onCreated: (run: EvalRun) => Promise<void>;
}) {
  const ready = environments.filter((e) => e.status === "ready");
  const [configs, setConfigs] = useState<ExecutorConfig[]>([]),
    [choice, setChoice] = useState(
      ready[0]?.id ??
        (tasks.every((t) => t.definition.kind === "conversation")
          ? "aigateway_go"
          : ""),
    ),
    [limit, setLimit] = useState(
      tasks.every((t) => t.definition.kind === "command") ? 0 : 12,
    ),
    [money, setMoney] = useState(""),
    [env, setEnv] = useState<Environment | null>(ready[0] ?? null),
    [busy, setBusy] = useState(false),
    [error, setError] = useState("");
  useEffect(() => {
    let stopped = false;
    void api
      .listExecutorConfigs()
      .then((r) => {
        if (!stopped) setConfigs(r.items);
      })
      .catch((e) => {
        if (!stopped) setError(errorText(e));
      });
    return () => {
      stopped = true;
    };
  }, []);
  useEffect(() => {
    if (!env || env.status !== "preparing") return;
    let stopped = false;
    const timer = window.setInterval(() => {
      void ev
        .environments(projectId)
        .then((r) => {
          if (!stopped) {
            const value = r.items.find((e) => e.id === env.id);
            if (value) setEnv(value);
          }
        })
        .catch((e) => {
          if (!stopped) setError(errorText(e));
        });
    }, 1600);
    return () => {
      stopped = true;
      window.clearInterval(timer);
    };
  }, [env, projectId]);
  const valid =
    Number.isInteger(limit) &&
    limit >= 0 &&
    limit <= 64 &&
    (money === "" || (Number.isFinite(Number(money)) && Number(money) >= 0));
  const perform = async () => {
    setBusy(true);
    setError("");
    try {
      if (env?.status === "ready") {
        await onCreated(
          await ev.start(projectId, {
            environment_id: env.id,
            version_ids: tasks.map((t) => t.version_id),
            max_model_calls: limit,
            budget_usd: money === "" ? null : Number(money),
          }),
        );
      } else if (env?.status === "planned") {
        setEnv(await ev.confirm(projectId, env));
      } else {
        setEnv(
          await ev.plan(
            projectId,
            choice === "aigateway_go"
              ? { adapter: choice }
              : { executor_config_id: choice, isolated_data_confirmed: true },
          ),
        );
      }
    } catch (e) {
      setError(errorText(e));
    } finally {
      setBusy(false);
    }
  };
  return (
    <FormDrawer
      title="准备评测运行"
      presentation="dialog"
      onClose={onClose}
      busy={busy}
      footer={
        <>
          <Button disabled={busy} onClick={onClose}>
            关闭
          </Button>
          <Button
            variant="contained"
            startIcon={
              env?.status === "ready" ? (
                <Play />
              ) : env?.status === "planned" ? (
                <Check />
              ) : (
                <ChevronRight />
              )
            }
            disabled={
              busy ||
              !valid ||
              !choice ||
              env?.status === "preparing" ||
              !tasks.length
            }
            onClick={() => void perform()}
          >
            {busy
              ? "处理中…"
              : env?.status === "ready"
                ? "启动评测"
                : env?.status === "planned"
                  ? "确认并准备环境"
                  : env?.status === "preparing"
                    ? "正在准备环境"
                    : "查看环境方案"}
          </Button>
        </>
      }
    >
      <div className="eval-form">
        <p className="dialog-description">
          已选 {tasks.length} 道题目。运行将固定当前版本，每题的证据会立即保存。
        </p>
        <ErrorNotice value={error} />
        <TextField
          label="运行环境"
          select
          value={choice}
          disabled={busy || env?.status === "preparing"}
          onChange={(e) => {
            setChoice(e.target.value);
            setEnv(ready.find((env) => env.id === e.target.value) ?? null);
          }}
        >
          <MenuItem value="" disabled>
            选择执行器或已准备环境
          </MenuItem>
          {ready.map((e, i) => (
            <MenuItem key={e.id} value={e.id}>
              已就绪环境 {ready.length - i} · {e.adapter}
            </MenuItem>
          ))}
          {tasks.every((t) => t.definition.kind === "conversation") && (
            <MenuItem value="aigateway_go">AI Gateway · 独立 Go 环境</MenuItem>
          )}
          {configs
            .filter(
              (c) =>
                c.backend !== "harbor" &&
                tasks.every(
                  (t) =>
                    t.definition.kind ===
                    (c.backend === "local_command" ? "command" : "http"),
                ),
            )
            .map((c) => (
              <MenuItem key={c.id} value={c.id}>
                {c.name}
              </MenuItem>
            ))}
        </TextField>
        {configs.some((c) => c.id === choice && c.backend === "http_api") && (
          <Alert severity="warning">
            确认方案表示：目标是专用本机测试服务，使用独立数据；Evalith
            不启动或清理该外部服务。
          </Alert>
        )}
        <div className="eval-budget-fields">
          <TextField
            label="模型调用上限"
            type="number"
            value={limit}
            onChange={(e) => setLimit(Number(e.target.value))}
            inputProps={{ min: 0, max: 64 }}
            helperText="含被测 Agent 的每次请求和评分调用。"
          />
          <TextField
            label="金额上限（可选）"
            type="number"
            value={money}
            onChange={(e) => setMoney(e.target.value)}
            inputProps={{ min: 0 }}
            placeholder="未知"
            helperText="费用未知时，填写金额会阻止模型调用。"
          />
        </div>
        {env && (
          <section className="environment-plan">
            <div className="eval-field-heading">
              <h3>隔离方案</h3>
              <span>
                {env.status === "ready"
                  ? "依赖已就绪"
                  : env.status === "planned"
                    ? "等待确认"
                    : env.status === "preparing"
                      ? "正在准备"
                      : "准备失败"}
              </span>
            </div>
            <dl>
              <dt>源目录 · 只读</dt>
              <dd>{env.plan.source_directory}</dd>
              <dt>产物目录</dt>
              <dd>{env.plan.write_directory}</dd>
              <dt>复制范围</dt>
              <dd>{env.plan.copy_scope}</dd>
              <dt>运行服务</dt>
              <dd>{env.plan.services.join("\n")}</dd>
              <dt>网络访问</dt>
              <dd>{env.plan.network.join("\n")}</dd>
              <dt>凭据来源</dt>
              <dd>
                {env.plan.credential_sources.join("\n") ||
                  "不向执行器传递模型凭据"}
              </dd>
            </dl>
            {env.plan.limitations.map((s, i) => (
              <p className="muted" key={i}>
                {s}
              </p>
            ))}
            {env.events.map((e, i) => (
              <p className="env-event" key={i}>
                <Check size={13} />
                {e.message}
              </p>
            ))}
            {env.status === "preparing" && <LinearProgress />}
            {env.error && <Alert severity="error">{env.error}</Alert>}
          </section>
        )}
        <div className="eval-cost-note">
          <strong>费用未知，调用次数受限</strong>
          <p>
            本地账号额度无法换算成金额。达到次数上限会停止后续模型调用，已经完成的结果会保留。
          </p>
        </div>
      </div>
    </FormDrawer>
  );
}
export function AnalysisDialog({
  projectId,
  run,
  selectedIds,
  onClose,
  onCreated,
}: {
  projectId: string;
  run: EvalRun;
  selectedIds: string[];
  onClose: () => void;
  onCreated: () => Promise<void>;
}) {
  const [selection, setSelection] = useState(
      selectedIds.length ? "selected" : "all",
    ),
    [limit, setLimit] = useState(1),
    [busy, setBusy] = useState(false),
    [error, setError] = useState("");
  const submit = async () => {
    setBusy(true);
    setError("");
    try {
      await ev.analyze(projectId, run.id, {
        selection,
        result_ids: selectedIds,
        max_model_calls: limit,
      });
      await onCreated();
    } catch (e) {
      setError(errorText(e));
      setBusy(false);
    }
  };
  return (
    <FormDrawer
      title="分析运行结果"
      presentation="dialog"
      onClose={onClose}
      busy={busy}
      footer={
        <>
          <Button onClick={onClose} disabled={busy}>
            取消
          </Button>
          <Button
            variant="contained"
            disabled={
              busy || !Number.isInteger(limit) || limit < 0 || limit > 8
            }
            onClick={() => void submit()}
          >
            {busy ? "正在提交…" : "开始分析"}
          </Button>
        </>
      }
    >
      <div className="eval-form">
        <p className="dialog-description">
          使用项目当前模型独立分析已保存的结果，区分事实、可能原因和分析限制。
        </p>
        <ErrorNotice value={error} />
        <TextField
          label="分析范围"
          select
          value={selection}
          onChange={(e) => setSelection(e.target.value)}
        >
          <MenuItem value="all">全部结果</MenuItem>
          <MenuItem value="failed">未通过的结果</MenuItem>
          <MenuItem value="low">低于 80% 的已评分结果</MenuItem>
          <MenuItem value="selected" disabled={!selectedIds.length}>
            已选 {selectedIds.length} 项结果
          </MenuItem>
        </TextField>
        <TextField
          label="独立调用上限"
          type="number"
          value={limit}
          onChange={(e) => setLimit(Number(e.target.value))}
          inputProps={{ min: 0, max: 8 }}
          helperText="当前分析调用 1 次，设为 0 则不会调用模型。"
        />
        <div className="eval-cost-note">
          <strong>分析费用未知</strong>
          <p>
            分析不占用运行预算，也不会修改原始评分。缺失分数、执行错误和跳过项不会自动归入低分。
          </p>
        </div>
      </div>
    </FormDrawer>
  );
}
