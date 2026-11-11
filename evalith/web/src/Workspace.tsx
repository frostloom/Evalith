import { useEffect, useMemo, useRef, useState } from "react";
import { Button, Tab, Tabs } from "@mui/material";
import RefreshRounded from "@mui/icons-material/RefreshRounded";
import TuneOutlined from "@mui/icons-material/TuneOutlined";
import FolderOutlined from "@mui/icons-material/FolderOutlined";
import ArrowUpwardRounded from "@mui/icons-material/ArrowUpwardRounded";
import { FormDrawer, PageHeader } from "./ui";
import { api, ApiError } from "./api";
import type {
  Message,
  ModelConfig,
  ProjectDetail,
  SentScope,
  Understanding,
  UnderstandingItem,
  WorkspaceTab,
} from "./types";

function shortHash(value?: string | null) {
  return value ? value.slice(0, 12) : "—";
}

function bytes(value?: number) {
  if (!value) return "0 B";
  if (value < 1024) return `${value} B`;
  if (value < 1024 * 1024) return `${(value / 1024).toFixed(1)} KB`;
  return `${(value / (1024 * 1024)).toFixed(1)} MB`;
}

function itemText(item: UnderstandingItem | string | null | undefined): string {
  if (typeof item === "string") return item;
  if (item && typeof item === "object" && typeof item.text === "string") {
    return item.text;
  }
  return "";
}

function itemHint(
  item: UnderstandingItem | string | null | undefined,
): string | null {
  if (!item || typeof item !== "object") return null;
  return item.source ?? item.basis ?? item.why ?? null;
}

export function Workspace({
  detail,
  models,
  busy,
  onDetail,
  onHome,
  onError,
  onNotice,
  tab,
  onTabChange,
}: {
  detail: ProjectDetail;
  tab?: WorkspaceTab;
  onTabChange?: (tab: WorkspaceTab) => void;
  models: ModelConfig[];
  busy: boolean;
  onDetail: (detail: ProjectDetail) => void;
  onHome: () => void;
  onError: (message: string) => void;
  onNotice: (message: string) => void;
}) {
  const mountedRef = useRef(true);
  useEffect(() => {
    mountedRef.current = true;
    return () => {
      mountedRef.current = false;
    };
  }, []);
  const applyDetail = (next: ProjectDetail) => {
    if (mountedRef.current) onDetail(next);
  };
  const reportError = (message: string) => {
    if (mountedRef.current) onError(message);
  };
  const reportNotice = (message: string) => {
    if (mountedRef.current) onNotice(message);
  };
  const { project, understanding, readiness, snapshot, messages } = detail;
  const [message, setMessage] = useState("");
  const [composing, setComposing] = useState(false);
  const [working, setWorking] = useState(false);
  const [editingSources, setEditingSources] = useState(false);
  const [editingModel, setEditingModel] = useState(false);
  const composerRef = useRef<HTMLTextAreaElement | null>(null);
  const projectIdRef = useRef(project.id);
  useEffect(() => {
    projectIdRef.current = project.id;
  }, [project.id]);

  const lastScope: SentScope | null = useMemo(() => {
    for (let index = messages.length - 1; index >= 0; index -= 1) {
      if (messages[index].sent_scope) return messages[index].sent_scope;
    }
    return null;
  }, [messages]);

  const run = async (
    action: () => Promise<ProjectDetail>,
    success?: string,
  ) => {
    const origin = project.id;
    setWorking(true);
    try {
      const next = await action();
      if (
        !mountedRef.current ||
        projectIdRef.current !== origin ||
        next.project.id !== origin
      ) {
        return;
      }
      applyDetail(next);
      if (success) reportNotice(success);
    } catch (err) {
      if (mountedRef.current && projectIdRef.current === origin) {
        reportError(err instanceof Error ? err.message : "操作失败");
        if (err instanceof ApiError && err.code === "understanding_stale") {
          try {
            const latest = await api.getProject(origin);
            if (
              mountedRef.current &&
              projectIdRef.current === origin &&
              latest.project.id === origin
            ) {
              applyDetail(latest);
            }
          } catch {
            // Keep the source-change error visible if refreshing also fails.
          }
        }
      }
    } finally {
      if (mountedRef.current && projectIdRef.current === origin) {
        setWorking(false);
      }
    }
  };

  const send = async (text: string) => {
    const content = text.trim();
    if (!content) return;
    const origin = project.id;
    setWorking(true);
    try {
      const next = await api.sendMessage(project.id, content);
      if (
        !mountedRef.current ||
        projectIdRef.current !== origin ||
        next.project.id !== origin
      ) {
        return;
      }
      applyDetail(next);
      setMessage("");
    } catch (err) {
      if (mountedRef.current && projectIdRef.current === origin) {
        reportError(err instanceof Error ? err.message : "发送失败");
        // The server persists an explicit withdrawal before a failing model
        // call. Re-read detail so readiness and the conversation reflect it.
        try {
          const latest = await api.getProject(origin);
          if (
            mountedRef.current &&
            projectIdRef.current === origin &&
            latest.project.id === origin
          ) {
            applyDetail(latest);
          }
        } catch {
          // Keep the original request error; the next open will refresh.
        }
      }
    } finally {
      if (mountedRef.current && projectIdRef.current === origin) {
        setWorking(false);
      }
    }
  };

  const disabled = working || busy;
  const [localTab, setLocalTab] = useState<WorkspaceTab>("overview");
  const activeTab = tab ?? localTab;
  const changeTab = (next: WorkspaceTab) => {
    setLocalTab(next);
    onTabChange?.(next);
  };
  const messagesEnd = useRef<HTMLDivElement | null>(null);
  useEffect(() => {
    if (activeTab === "conversation")
      messagesEnd.current?.scrollIntoView?.({ block: "end" });
  }, [activeTab, messages.length]);

  return (
    <div className="workspace">
      <PageHeader
        title={project.name}
        breadcrumb={
          <>
            <button className="link-button" onClick={onHome}>
              项目
            </button>
          </>
        }
        actions={
          <>
            <Button
              variant="text"
              startIcon={<TuneOutlined />}
              onClick={() => setEditingModel(true)}
            >
              模型
            </Button>
            <Button
              variant="text"
              startIcon={<RefreshRounded />}
              onClick={() =>
                void run(() => api.rescan(project.id), "资料范围已重新扫描。")
              }
              disabled={disabled}
            >
              重新扫描
            </Button>
            <Button
              variant="text"
              startIcon={<FolderOutlined />}
              onClick={() => setEditingSources(true)}
            >
              资料与范围
            </Button>
          </>
        }
      />
      <Tabs
        selectionFollowsFocus
        value={activeTab}
        onChange={(_, value: WorkspaceTab) => changeTab(value)}
        aria-label="项目工作区章节"
        className="detail-tabs"
        variant="scrollable"
        scrollButtons="auto"
      >
        <Tab
          value="conversation"
          label="主会话"
          id="tab-conversation"
          aria-controls="panel-conversation"
        />
        <Tab
          value="overview"
          label="项目理解"
          id="tab-overview"
          aria-controls="panel-overview"
        />
        <Tab
          value="sources"
          label="资料来源"
          id="tab-sources"
          aria-controls="panel-sources"
        />
      </Tabs>
      <div className="workspace-panels">
        <div
          hidden={activeTab !== "overview"}
          role="tabpanel"
          id="panel-overview"
          aria-labelledby="tab-overview"
          className="overview-panel"
        >
          <div className="section-toolbar">
            <h2>项目理解</h2>
            <Button
              startIcon={<RefreshRounded />}
              onClick={() =>
                void run(
                  () => api.reanalyse(project.id),
                  "已重新生成初步理解。",
                )
              }
              disabled={disabled}
            >
              重新分析
            </Button>
          </div>
          {understanding ? (
            <UnderstandingPanel understanding={understanding} />
          ) : (
            <section className="understanding empty" id="project-understanding">
              <p>还没有项目理解。检查模型配置后点击“重新分析”。</p>
            </section>
          )}

          <section
            className={`readiness ${readiness.generation_allowed ? "is-open" : ""}`}
          >
            <div className="readiness-state">
              <span className="status-dot" aria-hidden="true" />
              <div>
                <h2>
                  {readiness.generation_allowed
                    ? "已满足进入后续阶段的条件"
                    : "尚未满足继续条件"}
                </h2>
                <p>{readiness.reason}</p>
              </div>
            </div>
            <div className="readiness-actions">
              {!readiness.generation_allowed &&
                !understanding?.error &&
                !understanding?.stale && (
                  <button
                    className="btn btn-primary"
                    onClick={() =>
                      void run(
                        () => api.continueProject(project.id),
                        "已记录继续意愿；未知项仍未确认。",
                      )
                    }
                    disabled={disabled}
                  >
                    表示可以继续
                  </button>
                )}
              <button
                className="btn btn-quiet"
                onClick={() => {
                  changeTab("conversation");
                  window.requestAnimationFrame(() =>
                    composerRef.current?.focus(),
                  );
                }}
              >
                补充或纠正
              </button>
              <span className="stage-tag">题目生成 · 阶段 2</span>
            </div>
          </section>
        </div>
        <section
          hidden={activeTab !== "conversation"}
          role="tabpanel"
          id="panel-conversation"
          aria-labelledby="tab-conversation"
          className="conversation"
          aria-label="项目主会话"
        >
          <div className="conversation-main">
            <div className="conversation-heading">
              <span>项目主会话</span>
              <span>自动保存</span>
            </div>
            <div className="messages">
              {messages.length === 0 && (
                <div className="chat-empty">
                  <h3>先一起了解这个项目</h3>
                  <p>补充业务背景、纠正理解，或说明你希望重点评测的方向。</p>
                </div>
              )}
              {messages.map((item) => (
                <MessageRow
                  key={item.id}
                  message={item}
                  onInspect={() => changeTab("overview")}
                />
              ))}
              <div ref={messagesEnd} />
            </div>
            <div className="composer">
              <label className="sr-only" htmlFor="composer-input">
                给主会话发送消息
              </label>
              <textarea
                id="composer-input"
                ref={composerRef}
                value={message}
                onChange={(event) => setMessage(event.target.value)}
                onCompositionStart={() => setComposing(true)}
                onCompositionEnd={() => setComposing(false)}
                onKeyDown={(event) => {
                  if (
                    event.key === "Enter" &&
                    !event.shiftKey &&
                    !composing &&
                    !event.nativeEvent.isComposing
                  ) {
                    event.preventDefault();
                    void send(message);
                  }
                }}
                rows={2}
                placeholder="补充资料、纠正理解，或说明希望评测的方向。Enter 发送，Shift+Enter 换行。"
                disabled={disabled}
              />
              <div className="composer-foot">
                <span>
                  <button
                    className="composer-model"
                    onClick={() => setEditingModel(true)}
                    disabled={disabled}
                  >
                    <TuneOutlined />
                    {models.find((item) => item.id === project.model_config_id)
                      ?.name ?? "选择模型"}
                  </button>
                </span>
                <button
                  className="send-button"
                  aria-label={working ? "处理中…" : "发送"}
                  onClick={() => void send(message)}
                  disabled={disabled || !message.trim()}
                >
                  <ArrowUpwardRounded fontSize="small" />
                </button>
              </div>
            </div>
          </div>
          <aside className="conversation-context" aria-label="当前项目上下文">
            <div className="context-section">
              <div className="context-label">
                {understanding?.stale ? "历史理解" : "当前理解"}
                <button
                  className="quiet-link"
                  onClick={() => changeTab("overview")}
                >
                  查看详情
                </button>
              </div>
              {understanding?.stale && (
                <p className="context-warning" role="status">
                  资料已变化，需重新核对。
                </p>
              )}
              <p className="context-summary">
                {understanding?.error
                  ? "分析失败，请检查模型或资料后重试。"
                  : understanding?.summary ||
                    "还没有形成项目理解，可先配置模型或补充资料。"}
              </p>
              {understanding?.error && (
                <p className="context-warning">{understanding.error}</p>
              )}
            </div>
            <div className="context-section">
              <div className="context-label">
                待确认<span>{understanding?.unknowns.length ?? 0}</span>
              </div>
              <ul className="context-unknowns">
                {understanding?.unknowns.slice(0, 2).map((item, index) => (
                  <li key={index}>{itemText(item)}</li>
                ))}
              </ul>
              {!understanding?.unknowns.length && (
                <p className="context-muted">暂无待确认项</p>
              )}
            </div>
            <div className="context-section">
              <div className="context-label">
                {understanding?.stale ? "原分析来源" : "参考资料"}
                <button
                  className="quiet-link"
                  onClick={() => changeTab("sources")}
                >
                  {snapshot?.file_count ?? 0} 份
                </button>
              </div>
              <ul className="context-files">
                {(understanding?.sources ?? []).slice(0, 3).map((source) => (
                  <li key={source.path}>
                    <FolderOutlined />
                    <span title={source.path}>{source.path}</span>
                  </li>
                ))}
              </ul>
              <button
                className="context-add"
                onClick={() => setEditingSources(true)}
              >
                <span>＋</span>补充项目资料
              </button>
            </div>
            <div className="context-section context-next">
              <div className="context-label">下一步</div>
              <p className="context-muted">
                {understanding?.stale
                  ? "先重新分析最新资料，再确认评测方向。"
                  : readiness.generation_allowed
                    ? "已确认继续意愿。题目设计将在后续阶段开放。"
                    : "讨论并确认理解，再进入题目设计。"}
              </p>
              <button
                className="quiet-link"
                onClick={() => changeTab("overview")}
              >
                {understanding?.stale ? "重新核对理解" : "查看准备状态"}
              </button>
            </div>
          </aside>
        </section>

        <aside
          hidden={activeTab !== "sources"}
          role="tabpanel"
          id="panel-sources"
          aria-labelledby="tab-sources"
          className="evidence"
          aria-label="资料来源与发送范围"
        >
          <section>
            <div className="section-heading small">
              <h2>资料范围</h2>
              <span>{snapshot?.file_count ?? 0} 个文件</span>
            </div>
            <p className="evidence-meta">
              快照 <span className="mono">{shortHash(snapshot?.digest)}</span>
              <br />
              {snapshot?.created_at &&
                new Date(snapshot.created_at).toLocaleString("zh-CN", {
                  hour12: false,
                })}
            </p>
            <ul className="file-list">
              {snapshot?.files.map((file) => (
                <li key={file.path} title={file.reason ?? undefined}>
                  <span className="file-path">{file.path}</span>
                  <span className="file-meta mono">
                    {bytes(file.size)} · {shortHash(file.sha256)}
                    {file.binary ? " · 二进制，仅指纹" : ""}
                    {file.redactions > 0 ? ` · 脱敏 ${file.redactions}` : ""}
                  </span>
                </li>
              ))}
              {!snapshot?.files.length && (
                <li className="file-empty">选定范围内没有可读文本文件。</li>
              )}
            </ul>
          </section>

          <section>
            <div className="section-heading small">
              <h2>已排除</h2>
              <span>{snapshot?.excluded_count ?? 0} 项</span>
            </div>
            <details className="excluded-details">
              <summary>查看排除原因</summary>
              <ul className="file-list muted-list">
                {snapshot?.excluded.map((item) => (
                  <li key={item.path}>
                    <span className="file-path">{item.path}</span>
                    <span className="file-meta">{item.reason}</span>
                  </li>
                ))}
              </ul>
            </details>
            {(snapshot?.read_error_count ?? 0) > 0 && (
              <div className="read-errors">
                <h3>读取失败 {snapshot?.read_error_count} 项</h3>
                <ul>
                  {snapshot?.read_errors.map((item) => (
                    <li key={item.path}>
                      <span className="mono">{item.path}</span>：{item.error}
                    </li>
                  ))}
                </ul>
              </div>
            )}
          </section>

          <section>
            <div className="section-heading small">
              <h2>本次发送</h2>
            </div>
            {lastScope ? (
              <dl className="scope-stats">
                <div>
                  <dt>来源</dt>
                  <dd>
                    {lastScope.files_sent} / {lastScope.files_listed}
                  </dd>
                </div>
                <div>
                  <dt>内容</dt>
                  <dd>{bytes(lastScope.bytes_sent)}</dd>
                </div>
                <div>
                  <dt>脱敏</dt>
                  <dd>{lastScope.redactions} 处</dd>
                </div>
              </dl>
            ) : (
              <p className="aside-note">尚未向模型发送资料。</p>
            )}
            <p className="aside-note">
              发送范围与快照指纹一同记录在会话中；密钥不会进入模型上下文。
            </p>
          </section>

          <section className="later-links">
            <div>
              <span>题集</span>
              <em>阶段 2</em>
            </div>
            <div>
              <span>运行结果</span>
              <em>阶段 3</em>
            </div>
          </section>
        </aside>
      </div>

      {editingModel && (
        <ModelPicker
          project={project}
          models={models}
          onClose={() => setEditingModel(false)}
          onSaved={(next) => {
            if (!mountedRef.current) return;
            applyDetail(next);
            setEditingModel(false);
            reportNotice("模型配置已保存，项目主会话保持不变。");
          }}
          onError={reportError}
        />
      )}

      {editingSources && (
        <SourceEditor
          detail={detail}
          onClose={() => setEditingSources(false)}
          onSaved={(next) => {
            if (!mountedRef.current) return;
            applyDetail(next);
            setEditingSources(false);
            reportNotice("资料范围已保存并重新分析。");
          }}
          onError={reportError}
        />
      )}
    </div>
  );
}

function UnderstandingPanel({
  understanding,
}: {
  understanding: Understanding;
}) {
  const stale = understanding.stale;
  const bands = [
    {
      key: "known",
      title: stale ? "历史依据" : "已知",
      hint: stale ? "来自旧快照，需重新核对" : "有资料或用户输入依据",
      items: understanding.known,
    },
    {
      key: "inferred",
      title: stale ? "历史推断" : "推断",
      hint: "不是事实",
      items: understanding.inferred,
    },
    {
      key: "unknowns",
      title: stale ? "待重新核对" : "未知",
      hint: "影响评测方向",
      items: understanding.unknowns,
    },
  ] as const;

  return (
    <section
      className={`understanding ${stale ? "is-stale" : ""}`}
      id="project-understanding"
    >
      {stale && (
        <div className="stale-notice" role="alert">
          <strong>资料已变化 · 理解待更新</strong>
          <p>
            以下结论来自历史快照，不能作为当前依据。点击“重新分析”核对最新资料；历史会话保留。
          </p>
        </div>
      )}
      <div className="understanding-head">
        <div>
          <p className="kicker">{stale ? "历史理解" : "初步理解"}</p>
          <p className="understanding-summary">{understanding.summary}</p>
          {understanding.agent_or_flow && (
            <p className="understanding-flow">
              <span>识别到的 Agent / 流程</span>
              {understanding.agent_or_flow}
            </p>
          )}
        </div>
        <div className="understanding-stamp">
          <span className="mono">{understanding.model ?? "unknown"}</span>
          <span>快照 {shortHash(understanding.snapshot_id)}</span>
        </div>
      </div>

      {understanding.error && (
        <p className="form-error" role="alert">
          分析失败：{understanding.error}
        </p>
      )}

      <div className="bands">
        {bands.map((band) => (
          <div className={`band band-${band.key}`} key={band.key}>
            <div className="band-head">
              <h2>{band.title}</h2>
              <span>{band.items.length} 项</span>
            </div>
            <p className="band-hint">{band.hint}</p>
            <ul>
              {band.items.map((item, index) => {
                const hint = itemHint(item);
                return (
                  <li key={`${band.key}-${index}`}>
                    <p>{itemText(item)}</p>
                    {hint && <span className="item-hint mono">{hint}</span>}
                  </li>
                );
              })}
              {band.items.length === 0 && <li className="band-empty">暂无</li>}
            </ul>
          </div>
        ))}
      </div>

      {understanding.sufficient_reason && (
        <p className="sufficiency-note">{understanding.sufficient_reason}</p>
      )}
    </section>
  );
}

function MessageRow({
  message,
  onInspect,
}: {
  message: Message;
  onInspect: () => void;
}) {
  const kind = message.payload?.kind;
  if (kind === "understanding") {
    const initial = message.payload?.understanding;
    return (
      <div className="message message-assistant message-understanding">
        <span className="message-role">E</span>
        <div className="message-content">
          <span className="message-caption">项目理解已更新</span>
          <p>{initial?.summary || "已根据选定资料更新项目理解。"}</p>
          <button className="message-inspect" onClick={onInspect}>
            查看理解与来源 <span>↗</span>
          </button>
        </div>
      </div>
    );
  }
  if (message.role === "system") {
    const isError = kind === "error";
    return (
      <div className={`message message-system ${isError ? "is-error" : ""}`}>
        <span className="message-role">{isError ? "错误" : "记录"}</span>
        <p>{message.content}</p>
      </div>
    );
  }
  return (
    <div className={`message message-${message.role}`}>
      <span className="message-role">
        {message.role === "user" ? "你" : "E"}
      </span>
      <p>{message.content}</p>
    </div>
  );
}

function ModelPicker({
  project,
  models,
  onClose,
  onSaved,
  onError,
}: {
  project: ProjectDetail["project"];
  models: ModelConfig[];
  onClose: () => void;
  onSaved: (detail: ProjectDetail) => void;
  onError: (message: string) => void;
}) {
  const [modelId, setModelId] = useState(project.model_config_id ?? "");
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);

  const save = async () => {
    setBusy(true);
    setError(null);
    try {
      const next = await api.updateProjectModel(project.id, modelId || null);
      onSaved(next);
    } catch (err) {
      const message = err instanceof Error ? err.message : "保存失败";
      setError(message);
      onError(message);
    } finally {
      setBusy(false);
    }
  };

  return (
    <FormDrawer
      title="模型配置"
      onClose={onClose}
      footer={
        <>
          <button
            className="btn btn-primary"
            onClick={() => void save()}
            disabled={busy || models.length === 0}
          >
            {busy ? "保存并分析中…" : "保存模型"}
          </button>
          <button className="btn btn-quiet" onClick={onClose}>
            取消
          </button>
        </>
      }
    >
      <div className="modal-body">
        {models.length === 0 ? (
          <p className="inline-note">
            还没有模型配置。请先在“模型与凭据”中添加；保存项目模型不会创建新的主会话。
          </p>
        ) : (
          <label className="field">
            <span>模型服务</span>
            <select
              value={modelId}
              onChange={(event) => setModelId(event.target.value)}
            >
              <option value="">未配置（保留当前会话，暂停分析）</option>
              {models.map((model) => (
                <option key={model.id} value={model.id}>
                  {model.name} ·{" "}
                  {model.provider === "stub" ? "确定性替身" : model.model_name}
                </option>
              ))}
            </select>
            <small>
              保存后如项目此前因缺少模型而分析失败，会自动重新分析；主会话与已有纠正保留。
            </small>
          </label>
        )}
        {error && (
          <p className="form-error" role="alert">
            {error}
          </p>
        )}
      </div>
    </FormDrawer>
  );
}

export function SourceEditor({
  detail,
  onClose,
  onSaved,
  onError,
}: {
  detail: ProjectDetail;
  onClose: () => void;
  onSaved: (detail: ProjectDetail) => void;
  onError: (message: string) => void;
}) {
  const [includePaths, setIncludePaths] = useState(
    detail.project.include_paths.join("\n"),
  );
  const [excludePatterns, setExcludePatterns] = useState(
    detail.project.exclude_patterns.join("\n"),
  );
  const [supplemental, setSupplemental] = useState<
    Array<{ title: string; content: string }>
  >(
    detail.project.supplemental.map((item) => ({
      title: item.title,
      content: item.content,
    })),
  );
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);

  const save = async () => {
    setBusy(true);
    setError(null);
    try {
      const docs = supplemental
        .filter((item) => item.title.trim() || item.content.trim())
        .map((item, index) => ({
          title: item.title.trim() || `补充资料 ${index + 1}`,
          content: item.content,
        }));
      const next = await api.updateSources(detail.project.id, {
        include_paths: includePaths
          .split("\n")
          .map((item) => item.trim())
          .filter(Boolean),
        exclude_patterns: excludePatterns
          .split("\n")
          .map((item) => item.trim())
          .filter(Boolean),
        supplemental: docs,
      });
      if (next.project.id !== detail.project.id) return;
      onSaved(next);
    } catch (err) {
      const message = err instanceof Error ? err.message : "保存失败";
      setError(message);
      onError(message);
    } finally {
      setBusy(false);
    }
  };

  return (
    <FormDrawer
      title="资料与分析范围"
      onClose={onClose}
      footer={
        <>
          <button
            className="btn btn-primary"
            onClick={() => void save()}
            disabled={busy}
          >
            {busy ? "扫描并分析中…" : "保存并重新分析"}
          </button>
          <button className="btn btn-quiet" onClick={onClose}>
            取消
          </button>
        </>
      }
    >
      <div className="modal-body">
        <label className="field">
          <span>只分析这些路径</span>
          <textarea
            value={includePaths}
            onChange={(event) => setIncludePaths(event.target.value)}
            rows={4}
            className="mono"
            placeholder="留空表示整个目录"
          />
          <small>相对项目根目录。保存后会重新扫描并重新分析。</small>
        </label>
        <label className="field">
          <span>额外排除</span>
          <textarea
            value={excludePatterns}
            onChange={(event) => setExcludePatterns(event.target.value)}
            rows={3}
            className="mono"
          />
          <small>敏感凭据规则始终生效，不能被这里的排除或选择覆盖。</small>
        </label>
        <fieldset className="supplement-field">
          <legend>补充资料</legend>
          {supplemental.length === 0 && (
            <p className="inline-note">
              还没有补充资料。补充文档会作为独立来源参与分析。
            </p>
          )}
          {supplemental.map((doc, index) => (
            <div className="supplement-editor" key={index}>
              <label className="field">
                <span>标题</span>
                <input
                  value={doc.title}
                  onChange={(event) =>
                    setSupplemental((current) =>
                      current.map((item, itemIndex) =>
                        itemIndex === index
                          ? { ...item, title: event.target.value }
                          : item,
                      ),
                    )
                  }
                  placeholder={`补充资料 ${index + 1}`}
                />
              </label>
              <label className="field">
                <span>内容</span>
                <textarea
                  value={doc.content}
                  onChange={(event) =>
                    setSupplemental((current) =>
                      current.map((item, itemIndex) =>
                        itemIndex === index
                          ? { ...item, content: event.target.value }
                          : item,
                      ),
                    )
                  }
                  rows={4}
                  placeholder="保留段落与空行；每个文档单独保存。"
                />
              </label>
              <button
                type="button"
                className="link-button danger supplement-remove"
                onClick={() =>
                  setSupplemental((current) =>
                    current.filter((_, itemIndex) => itemIndex !== index),
                  )
                }
              >
                移除
              </button>
            </div>
          ))}
          <button
            type="button"
            className="btn btn-quiet"
            onClick={() =>
              setSupplemental((current) => [
                ...current,
                { title: `补充资料 ${current.length + 1}`, content: "" },
              ])
            }
          >
            添加补充资料
          </button>
        </fieldset>
        {error && (
          <p className="form-error" role="alert">
            {error}
          </p>
        )}
      </div>
    </FormDrawer>
  );
}
