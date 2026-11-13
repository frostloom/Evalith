import { useCallback, useEffect, useState } from "react";
import {
  Alert,
  Button,
  Checkbox,
  InputAdornment,
  MenuItem,
  Stepper,
  Step,
  StepLabel,
  TextField,
} from "@mui/material";
import {
  ArrowLeft,
  ArrowUpRight,
  Check,
  FolderClosed,
  Layers3,
  Plus,
  Search,
  ShieldCheck,
} from "lucide-react";
import { evaluationApi as api } from "./evaluationApi";
import type {
  Grader,
  GraderDefinition,
  EvalTask,
  TestSet,
} from "./evaluationTypes";
import type { ModelConfig, ProjectDetail } from "./types";
import { FormDrawer, PageHeader } from "./ui";
const failure = (e: unknown) => (e instanceof Error ? e.message : "操作失败");
export const checkLabels: Record<string, string> = {
  judge: "模型判分",
  contains: "文本包含",
  not_contains: "文本不包含",
  json_equals: "JSON 值校验",
  status_code: "HTTP 状态",
  exit_code: "退出码",
  file_exists: "文件存在",
  file_contains: "文件内容",
};
export function EvaluationLibraryPage({
  detail,
  section,
  models,
  onOpenSet,
}: {
  detail: ProjectDetail;
  section: "graders" | "sets";
  models: ModelConfig[];
  onOpenSet: (set: TestSet) => void;
}) {
  const pid = detail.project.id;
  const [graders, setGraders] = useState<Grader[]>([]),
    [sets, setSets] = useState<TestSet[]>([]),
    [tasks, setTasks] = useState<EvalTask[]>([]),
    [error, setError] = useState(""),
    [loaded, setLoaded] = useState(false),
    [query, setQuery] = useState("");
  const [edit, setEdit] = useState<Grader | null | undefined>(undefined),
    [editSet, setEditSet] = useState<TestSet | null | undefined>(undefined);
  const load = useCallback(async () => {
    const [g, s, t] = await Promise.all([
      api.graders(pid),
      api.sets(pid),
      api.tasks(pid),
    ]);
    return { g: g.items, s: s.items, t: t.items };
  }, [pid]);
  useEffect(() => {
    let live = true;
    void load()
      .then((r) => {
        if (live) {
          setGraders(r.g);
          setSets(r.s);
          setTasks(r.t);
          setLoaded(true);
        }
      })
      .catch((e) => {
        if (live) setError(failure(e));
      });
    return () => {
      live = false;
    };
  }, [load]);
  const refresh = async () => {
    const r = await load();
    setGraders(r.g);
    setSets(r.s);
    setTasks(r.t);
  };
  const shown = graders.filter((g) =>
    `${g.name} ${g.description}`.toLowerCase().includes(query.toLowerCase()),
  );
  return (
    <div
      className="asset-workspace"
      role="tabpanel"
      id={`panel-${section}`}
      aria-labelledby={`tab-${section}`}
    >
      <div className="product-breadcrumb">
        <span>{detail.project.name}</span>
        <span>/</span>
        <strong>{section === "graders" ? "评价标准" : "测试集"}</strong>
      </div>
      <div className="asset-page">
        <PageHeader
          title={section === "graders" ? "评价标准" : "测试集"}
          description={
            section === "graders"
              ? "定义怎样才算做好。评分模型、Rubric 和通过阈值在这里统一管理。"
              : "将测试题目组织成可重复运行的集合，为每组测试选择评价标准。"
          }
          actions={
            <Button
              variant="contained"
              startIcon={<Plus />}
              onClick={() =>
                section === "graders" ? setEdit(null) : setEditSet(null)
              }
            >
              {section === "graders" ? "新建评价标准" : "新建测试集"}
            </Button>
          }
        />
        {error && (
          <Alert severity="error" onClose={() => setError("")}>
            {error}
          </Alert>
        )}
        <div className="asset-toolbar">
          <TextField
            value={query}
            onChange={(e) => setQuery(e.target.value)}
            placeholder={
              section === "graders" ? "搜索评价标准…" : "搜索测试集…"
            }
            slotProps={{
              htmlInput: { "aria-label": "搜索评测资产" },
              input: {
                startAdornment: (
                  <InputAdornment position="start">
                    <Search size={17} />
                  </InputAdornment>
                ),
              },
            }}
          />
          <span>{section === "graders" ? graders.length : sets.length} 项</span>
        </div>
        {!loaded ? (
          <p className="library-empty">正在加载…</p>
        ) : section === "graders" ? (
          shown.length ? (
            <div className="standard-grid">
              {shown.map((g) => (
                <button
                  className="standard-card"
                  key={g.id}
                  onClick={() => setEdit(g)}
                >
                  <div className="standard-card-title">
                    <span
                      className={`standard-icon ${g.check.type === "judge" ? "is-judge" : ""}`}
                    >
                      <ShieldCheck size={19} />
                    </span>
                    <span className="standard-version">v{g.version}</span>
                    <ArrowUpRight size={15} />
                  </div>
                  <h2>{g.name}</h2>
                  <p>{g.description || g.rubric}</p>
                  <div className="standard-card-info">
                    <span>{checkLabels[g.check.type] ?? g.check.type}</span>
                    {g.check.type === "judge" && (
                      <span>≥ {Math.round(g.threshold * 100)}%</span>
                    )}
                    <span>
                      {g.check.type === "judge"
                        ? (models.find((m) => m.id === g.model_config_id)
                            ?.name ?? "跟随运行评分模型")
                        : "确定性检查"}
                    </span>
                  </div>
                  <footer>
                    <span>未校准</span>
                    <span>查看与编辑</span>
                  </footer>
                </button>
              ))}
            </div>
          ) : (
            <div className="library-empty">
              <ShieldCheck />
              <h2>建立可复用的评价标准</h2>
              <p>从现有题目的 Rubric 开始，或定义新的检查方式。</p>
              <Button variant="outlined" onClick={() => setEdit(null)}>
                创建第一项标准
              </Button>
            </div>
          )
        ) : sets.length ? (
          <div className="collection-table">
            <div className="collection-row collection-heading">
              <span>测试集名称</span>
              <span>题目</span>
              <span>评价标准</span>
              <span>更新</span>
              <span />
            </div>
            {sets
              .filter((s) => s.name.toLowerCase().includes(query.toLowerCase()))
              .map((s) => (
                <div className="collection-row" key={s.id}>
                  <button onClick={() => onOpenSet(s)}>
                    <span className="collection-icon">
                      <Layers3 size={18} />
                    </span>
                    <div>
                      <strong>{s.name}</strong>
                      <small>{s.description}</small>
                    </div>
                  </button>
                  <span>{s.task_ids.length} 道</span>
                  <span>
                    {s.grader_ids.length
                      ? `${s.grader_ids.length} 项标准`
                      : "继承题目规则"}
                  </span>
                  <span>
                    {new Date(s.created_at).toLocaleDateString("zh-CN", {
                      month: "numeric",
                      day: "numeric",
                    })}
                  </span>
                  <Button size="small" onClick={() => setEditSet(s)}>
                    配置
                  </Button>
                </div>
              ))}
          </div>
        ) : (
          <div className="library-empty">
            <FolderClosed />
            <h2>把题目组织成测试集</h2>
            <p>测试集可关联评价标准，运行时固定本次选用的版本。</p>
          </div>
        )}
      </div>
      {edit !== undefined && (
        <StandardForm
          projectId={pid}
          value={edit}
          models={models}
          tasks={tasks}
          defaultModel={detail.project.model_config_id}
          onClose={() => setEdit(undefined)}
          onSaved={async () => {
            setEdit(undefined);
            await refresh();
          }}
        />
      )}
      {editSet !== undefined && (
        <SetForm
          projectId={pid}
          value={editSet}
          tasks={tasks}
          graders={graders}
          onClose={() => setEditSet(undefined)}
          onSaved={async () => {
            setEditSet(undefined);
            await refresh();
          }}
        />
      )}
    </div>
  );
}
function StandardForm({
  projectId,
  value,
  models,
  tasks,
  defaultModel,
  onClose,
  onSaved,
}: {
  projectId: string;
  value: Grader | null;
  models: ModelConfig[];
  tasks: EvalTask[];
  defaultModel: string | null;
  onClose: () => void;
  onSaved: () => Promise<void>;
}) {
  const [draft, setDraft] = useState<GraderDefinition>(
    value
      ? {
          name: value.name,
          description: value.description,
          rubric: value.rubric,
          steps: value.steps,
          check: value.check,
          model_config_id: value.model_config_id,
          threshold: value.threshold,
          task_kinds: value.task_kinds,
          source_refs: value.source_refs,
          uncertainties: value.uncertainties,
        }
      : {
          name: "",
          description: "",
          rubric: "",
          steps: [],
          check: { type: "judge", expected: "按照 Rubric 判断" },
          model_config_id: defaultModel,
          threshold: 0.8,
        },
  );
  const [step, setStep] = useState(0),
    [error, setError] = useState(""),
    [busy, setBusy] = useState(false),
    [source, setSource] = useState("");
  const [requirement, setRequirement] = useState("");
  const synthesize = async () => {
    setBusy(true);
    setError("");
    try {
      const result = await api.synthesizeGrader(projectId, requirement);
      setDraft(result.draft);
    } catch (e) {
      setError(failure(e));
    } finally {
      setBusy(false);
    }
  };
  const change = (patch: Partial<GraderDefinition>) =>
    setDraft({ ...draft, ...patch });
  const valid =
    !!draft.name.trim() &&
    !!draft.rubric.trim() &&
    Number.isFinite(draft.threshold) &&
    draft.threshold >= 0 &&
    draft.threshold <= 1;
  const save = async () => {
    if (!valid) {
      setError("填写名称、Rubric 和 0–1 的阈值。");
      return;
    }
    setBusy(true);
    setError("");
    try {
      await api.saveGrader(
        projectId,
        { ...draft, steps: draft.steps.filter((s) => s.trim()) },
        value?.id,
      );
      await onSaved();
    } catch (e) {
      setError(failure(e));
      setBusy(false);
    }
  };
  const importRubric = (id: string) => {
    setSource(id);
    const t = tasks.find((t) => t.id === id);
    if (t)
      change({
        name: t.definition.title + " · 评分",
        description: t.definition.objective,
        rubric: t.definition.rubric,
        check: { type: "judge", expected: t.definition.rubric },
        steps: [],
      });
  };
  return (
    <FormDrawer
      title={value ? "编辑评价标准" : "新建评价标准"}
      presentation="dialog"
      onClose={onClose}
      busy={busy}
      footer={
        <>
          <Button
            onClick={step === 1 ? () => setStep(0) : onClose}
            disabled={busy}
            startIcon={step === 1 ? <ArrowLeft /> : undefined}
          >
            {step === 1 ? "返回配置" : "取消"}
          </Button>
          {step === 0 ? (
            <Button
              variant="contained"
              disabled={!valid}
              onClick={() => setStep(1)}
            >
              下一步：确认配置
            </Button>
          ) : (
            <Button
              variant="contained"
              disabled={busy}
              onClick={() => void save()}
            >
              {busy ? "保存中…" : value ? "保存新版本" : "创建评价标准"}
            </Button>
          )}
        </>
      }
    >
      <Stepper activeStep={step} className="standard-stepper">
        <Step>
          <StepLabel>配置标准</StepLabel>
        </Step>
        <Step>
          <StepLabel>确认配置</StepLabel>
        </Step>
      </Stepper>
      {error && <Alert severity="error">{error}</Alert>}
      {step === 0 ? (
        <div className="standard-form">
          <section>
            <h3>让模型编写 Grader</h3>
            <TextField
              label="评分要求"
              multiline
              minRows={2}
              value={requirement}
              onChange={(e) => setRequirement(e.target.value)}
              inputProps={{ maxLength: 4000 }}
              helperText="结合当前项目来源生成 Rubric、检查步骤、适用范围与阈值；生成后可修改并确认保存。"
            />
            <Button
              disabled={busy || !requirement.trim()}
              onClick={() => void synthesize()}
            >
              {busy ? "正在编写…" : "生成 Grader 草稿"}
            </Button>
          </section>
          <section>
            <h3>基本信息</h3>
            {!value && tasks.length > 0 && (
              <TextField
                select
                label="从现有 Rubric 建立（可选）"
                value={source}
                onChange={(e) => importRubric(e.target.value)}
              >
                <MenuItem value="">手动填写</MenuItem>
                {tasks.map((t) => (
                  <MenuItem key={t.id} value={t.id}>
                    {t.definition.title}
                  </MenuItem>
                ))}
              </TextField>
            )}
            <TextField
              label="标准名称"
              value={draft.name}
              onChange={(e) => change({ name: e.target.value })}
              required
            />
            <TextField
              label="用途说明"
              multiline
              minRows={2}
              value={draft.description}
              onChange={(e) => change({ description: e.target.value })}
            />
          </section>
          <section>
            <h3>评估过程</h3>
            <TextField
              select
              label="评分方式"
              value={draft.check.type}
              onChange={(e) =>
                change({ check: { ...draft.check, type: e.target.value } })
              }
            >
              {Object.entries(checkLabels).map(([id, label]) => (
                <MenuItem key={id} value={id}>
                  {label}
                </MenuItem>
              ))}
            </TextField>
            {draft.check.type === "judge" && (
              <TextField
                select
                label="评分模型"
                value={draft.model_config_id ?? ""}
                onChange={(e) =>
                  change({ model_config_id: e.target.value || null })
                }
              >
                <MenuItem value="">跟随本次运行的评分模型</MenuItem>
                {models.map((m) => (
                  <MenuItem key={m.id} value={m.id}>
                    {m.name} · {m.model_name}
                  </MenuItem>
                ))}
              </TextField>
            )}
            <TextField
              label="评分 Rubric"
              multiline
              minRows={5}
              value={draft.rubric}
              onChange={(e) => change({ rubric: e.target.value })}
              helperText="写清通过与失败的条件，以及判断需要的实际证据。"
              required
            />
            {draft.check.type === "judge" ? (
              <>
                <TextField
                  label="检查步骤（每行一步）"
                  multiline
                  minRows={3}
                  value={draft.steps.join("\n")}
                  onChange={(e) =>
                    change({ steps: e.target.value.split("\n") })
                  }
                />
                <TextField
                  label="通过阈值"
                  type="number"
                  inputProps={{ min: 0, max: 1, step: 0.05 }}
                  value={draft.threshold}
                  onChange={(e) =>
                    change({ threshold: Number(e.target.value) })
                  }
                  helperText="评分范围 0–1，达到阈值且判断通过时才通过。"
                />
              </>
            ) : (
              <>
                <TextField
                  label="期望值"
                  value={
                    typeof draft.check.expected === "string"
                      ? draft.check.expected
                      : JSON.stringify(draft.check.expected)
                  }
                  onChange={(e) => {
                    let expected: unknown = e.target.value;
                    if (
                      [
                        "json_equals",
                        "status_code",
                        "exit_code",
                        "file_exists",
                      ].includes(draft.check.type)
                    ) {
                      try {
                        expected = JSON.parse(e.target.value);
                      } catch {
                        /* incomplete input */
                      }
                    }
                    change({ check: { ...draft.check, expected } });
                  }}
                />
                <TextField
                  label="输出 / 文件路径"
                  value={draft.check.path ?? ""}
                  onChange={(e) =>
                    change({ check: { ...draft.check, path: e.target.value } })
                  }
                  helperText="JSON 使用点分路径；文件路径须位于单题目录内。"
                />
              </>
            )}
          </section>
          <TextField
            select
            label="适用任务类型"
            value={draft.task_kinds?.join(",") ?? "conversation,command,http"}
            onChange={(e) => change({ task_kinds: e.target.value.split(",") })}
          >
            <MenuItem value="conversation,command,http">全部类型</MenuItem>
            <MenuItem value="conversation">对话</MenuItem>
            <MenuItem value="command">命令 / 文件</MenuItem>
            <MenuItem value="http">HTTP API</MenuItem>
            {draft.task_kinds &&
              ![
                "conversation,command,http",
                "conversation",
                "command",
                "http",
              ].includes(draft.task_kinds.join(",")) && (
                <MenuItem value={draft.task_kinds.join(",")}>
                  {draft.task_kinds.join(" / ")}
                </MenuItem>
              )}
          </TextField>
          {!!draft.uncertainties?.length && (
            <Alert severity="warning">{draft.uncertainties.join("；")}</Alert>
          )}
        </div>
      ) : (
        <div className="standard-review">
          <div className="review-banner">
            <Check />
            <div>
              <h3>{draft.name}</h3>
              <p>确认后可供测试集和运行复用</p>
            </div>
          </div>
          <dl>
            <dt>评分方式</dt>
            <dd>{checkLabels[draft.check.type]}</dd>
            <dt>评分模型</dt>
            <dd>
              {models.find((m) => m.id === draft.model_config_id)?.name ??
                "跟随本次运行"}
            </dd>
            <dt>通过阈值</dt>
            <dd>
              {draft.check.type === "judge"
                ? `${draft.threshold} / 1`
                : "确定性规则"}
            </dd>
          </dl>
          <h4>评分 Rubric</h4>
          <p>{draft.rubric}</p>
          {draft.steps
            .filter((s) => s.trim())
            .map((s, i) => (
              <div className="review-step" key={i}>
                <span>{i + 1}</span>
                {s}
              </div>
            ))}
          <Alert severity="info">
            标准修改将保存新版本；已完成运行中的标准与结果保持原样。模型判断尚未人工校准。
          </Alert>
        </div>
      )}
    </FormDrawer>
  );
}
function SetForm({
  projectId,
  value,
  tasks,
  graders,
  onClose,
  onSaved,
}: {
  projectId: string;
  value: TestSet | null;
  tasks: EvalTask[];
  graders: Grader[];
  onClose: () => void;
  onSaved: () => Promise<void>;
}) {
  const [name, setName] = useState(value?.name ?? ""),
    [description, setDescription] = useState(value?.description ?? ""),
    [ids, setIds] = useState(value?.task_ids ?? []),
    [gids, setGids] = useState(value?.grader_ids ?? []),
    [busy, setBusy] = useState(false),
    [error, setError] = useState("");
  const save = async () => {
    setBusy(true);
    setError("");
    try {
      await api.saveSet(
        projectId,
        { name, description, task_ids: ids, grader_ids: gids },
        value?.id,
      );
      await onSaved();
    } catch (e) {
      setError(failure(e));
      setBusy(false);
    }
  };
  return (
    <FormDrawer
      title={value ? "配置测试集" : "新建测试集"}
      onClose={onClose}
      busy={busy}
      footer={
        <>
          <Button disabled={busy} onClick={onClose}>
            取消
          </Button>
          <Button
            variant="contained"
            disabled={busy || !name.trim() || !ids.length}
            onClick={() => void save()}
          >
            保存测试集
          </Button>
        </>
      }
    >
      <div className="standard-form">
        {error && <Alert severity="error">{error}</Alert>}
        <TextField
          label="测试集名称"
          value={name}
          onChange={(e) => setName(e.target.value)}
        />
        <TextField
          label="说明"
          multiline
          minRows={2}
          value={description}
          onChange={(e) => setDescription(e.target.value)}
        />
        <section>
          <h3>
            测试题目 <small>{ids.length} 道</small>
          </h3>
          {tasks.map((t) => (
            <label className="asset-selection" key={t.id}>
              <Checkbox
                size="small"
                checked={ids.includes(t.id)}
                onChange={(e) =>
                  setIds(
                    e.target.checked
                      ? [...ids, t.id]
                      : ids.filter((id) => id !== t.id),
                  )
                }
              />
              <span>
                <strong>{t.definition.title}</strong>
                <small>
                  {t.definition.category} · v{t.version}
                </small>
              </span>
            </label>
          ))}
        </section>
        <section>
          <h3>
            评价标准 <small>{gids.length} 项</small>
          </h3>
          <p className="field-note">
            未选择时继承各题目绑定的
            Grader；未绑定时使用内置检查。运行前仍可覆盖。
          </p>
          {graders.map((g) => (
            <label className="asset-selection" key={g.id}>
              <Checkbox
                size="small"
                checked={gids.includes(g.id)}
                onChange={(e) =>
                  setGids(
                    e.target.checked
                      ? [...gids, g.id]
                      : gids.filter((id) => id !== g.id),
                  )
                }
              />
              <span>
                <strong>{g.name}</strong>
                <small>
                  {checkLabels[g.check.type]} · v{g.version}
                </small>
              </span>
            </label>
          ))}
          {gids
            .filter((id) => !graders.some((g) => g.id === id))
            .map((id) => (
              <label className="asset-selection" key={id}>
                <Checkbox
                  size="small"
                  checked
                  onChange={() => setGids(gids.filter((g) => g !== id))}
                />
                <span>
                  <strong>已归档或不可用的标准</strong>
                  <small>取消关联后可保存测试集 · {id}</small>
                </span>
              </label>
            ))}
          {!graders.length && (
            <p className="field-note">先到评价标准建立可复用的 Rubric。</p>
          )}
        </section>
      </div>
    </FormDrawer>
  );
}
