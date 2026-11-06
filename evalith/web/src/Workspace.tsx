import { useEffect, useMemo, useRef, useState } from "react";
import { api } from "./api";
import type {
  Message,
  ModelConfig,
  ProjectDetail,
  SentScope,
  Understanding,
  UnderstandingItem,
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

function itemHint(item: UnderstandingItem | string | null | undefined): string | null {
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
}: {
  detail: ProjectDetail;
  models: ModelConfig[];
  busy: boolean;
  onDetail: (detail: ProjectDetail) => void;
  onHome: () => void;
  onError: (message: string) => void;
  onNotice: (message: string) => void;
}) {
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

  const run = async (action: () => Promise<ProjectDetail>, success?: string) => {
    const origin = project.id;
    setWorking(true);
    try {
      const next = await action();
      if (projectIdRef.current !== origin || next.project.id !== origin) return;
      onDetail(next);
      if (success) onNotice(success);
    } catch (err) {
      if (projectIdRef.current === origin) {
        onError(err instanceof Error ? err.message : "操作失败");
      }
    } finally {
      if (projectIdRef.current === origin) setWorking(false);
    }
  };

  const send = async (text: string) => {
    const content = text.trim();
    if (!content) return;
    const origin = project.id;
    setWorking(true);
    try {
      const next = await api.sendMessage(project.id, content);
      if (projectIdRef.current !== origin || next.project.id !== origin) return;
      onDetail(next);
      setMessage("");
    } catch (err) {
      if (projectIdRef.current === origin) {
        onError(err instanceof Error ? err.message : "发送失败");
        // The server persists an explicit withdrawal before a failing model
        // call. Re-read detail so readiness and the conversation reflect it.
        try {
          const latest = await api.getProject(origin);
          if (projectIdRef.current === origin && latest.project.id === origin) {
            onDetail(latest);
          }
        } catch {
          // Keep the original request error; the next open will refresh.
        }
      }
    } finally {
      if (projectIdRef.current === origin) setWorking(false);
    }
  };

  const disabled = working || busy;

  return (
    <div className="workspace">
      <header className="workspace-head">
        <div>
          <button className="crumb" onClick={onHome}>
            项目
          </button>
          <span className="crumb-sep">/</span>
          <span className="crumb-current">{project.name}</span>
          <h1>{project.name}</h1>
          <p className="workspace-meta mono" title={project.root_path}>
            {project.root_path} · {snapshot?.file_count ?? 0} 个文件 · 快照{" "}
            {shortHash(snapshot?.digest)}
          </p>
        </div>
        <div className="workspace-actions">
          <button className="btn btn-quiet" onClick={() => setEditingModel(true)}>
            模型
          </button>
          <button
            className="btn btn-quiet"
            onClick={() => void run(() => api.rescan(project.id), "资料范围已重新扫描。")}
            disabled={disabled}
          >
            重新扫描
          </button>
          <button
            className="btn btn-quiet"
            onClick={() => void run(() => api.reanalyse(project.id), "已重新生成初步理解。")}
            disabled={disabled}
          >
            重新分析
          </button>
          <button className="btn btn-primary" onClick={() => setEditingSources(true)}>
            资料与范围
          </button>
        </div>
      </header>

      <div className="workspace-body">
        <div className="document">
          {understanding ? (
            <UnderstandingPanel understanding={understanding} />
          ) : (
            <section className="understanding empty">
              <p>还没有项目理解。检查模型配置后点击“重新分析”。</p>
            </section>
          )}

          <section className={`readiness ${readiness.generation_allowed ? "is-open" : ""}`}>
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
              {!readiness.generation_allowed && !understanding?.error && (
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
                  composerRef.current?.focus();
                  composerRef.current?.scrollIntoView({ behavior: "smooth", block: "center" });
                }}
              >
                补充或纠正
              </button>
              <span className="stage-tag">题目生成 · 阶段 2</span>
            </div>
          </section>

          <section className="conversation" aria-label="项目主会话">
            <div className="section-heading">
              <h2>主会话</h2>
              <span className="mono">每项目一条 · 重开恢复</span>
            </div>
            <div className="messages">
              {messages.map((item) => (
                <MessageRow key={item.id} message={item} />
              ))}
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
                rows={3}
                placeholder="补充资料、纠正理解，或说明希望评测的方向。Enter 发送，Shift+Enter 换行。"
                disabled={disabled}
              />
              <div className="composer-foot">
                <span>
                  模型：
                  {models.find((item) => item.id === project.model_config_id)?.name ??
                    "未配置"}
                  {" · "}阶段 1 不生成题目
                </span>
                <button
                  className="btn btn-primary"
                  onClick={() => void send(message)}
                  disabled={disabled || !message.trim()}
                >
                  {working ? "处理中…" : "发送"}
                </button>
              </div>
            </div>
          </section>
        </div>

        <aside className="evidence" aria-label="资料来源与发送范围">
          <section>
            <div className="section-heading small">
              <h2>资料范围</h2>
              <span>{snapshot?.file_count ?? 0} 个文件</span>
            </div>
            <p className="evidence-meta">
              快照 <span className="mono">{shortHash(snapshot?.digest)}</span>
              <br />
              {snapshot?.created_at?.replace("T", " ").slice(0, 19)}
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
                  <dd>{lastScope.files_sent} / {lastScope.files_listed}</dd>
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
            onDetail(next);
            setEditingModel(false);
            onNotice("模型配置已保存，项目主会话保持不变。");
          }}
          onError={onError}
        />
      )}

      {editingSources && (
        <SourceEditor
          detail={detail}
          onClose={() => setEditingSources(false)}
          onSaved={(next) => {
            onDetail(next);
            setEditingSources(false);
            onNotice("资料范围已保存并重新分析。");
          }}
          onError={onError}
        />
      )}
    </div>
  );
}

function UnderstandingPanel({ understanding }: { understanding: Understanding }) {
  const bands = [
    { key: "known", title: "已知", hint: "有资料或用户输入依据", items: understanding.known },
    { key: "inferred", title: "推断", hint: "不是事实", items: understanding.inferred },
    { key: "unknowns", title: "未知", hint: "影响评测方向", items: understanding.unknowns },
  ] as const;

  return (
    <section className="understanding">
      <div className="understanding-head">
        <div>
          <p className="kicker">初步理解</p>
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

function MessageRow({ message }: { message: Message }) {
  const kind = message.payload?.kind;
  if (kind === "understanding") {
    return (
      <div className="message message-system">
        <span className="message-role">初步理解</span>
        <p>已根据选定资料生成初步理解，见上方三个分区。继续讨论会保留未知项。</p>
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
      <span className="message-role">{message.role === "user" ? "你" : "助手"}</span>
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
    <div className="modal-backdrop" role="dialog" aria-modal="true" aria-label="模型配置">
      <div className="modal">
        <header>
          <div>
            <p className="kicker">模型配置</p>
            <h2>为项目选择模型服务</h2>
          </div>
          <button className="link-button" onClick={onClose}>
            关闭
          </button>
        </header>
        <div className="modal-body">
          {models.length === 0 ? (
            <p className="inline-note">
              还没有模型配置。请先在“模型与凭据”中添加；保存项目模型不会创建新的主会话。
            </p>
          ) : (
            <label className="field">
              <span>模型服务</span>
              <select value={modelId} onChange={(event) => setModelId(event.target.value)}>
                <option value="">未配置（保留当前会话，暂停分析）</option>
                {models.map((model) => (
                  <option key={model.id} value={model.id}>
                    {model.name} · {model.provider === "stub" ? "确定性替身" : model.model_name}
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
        <footer>
          <button className="btn btn-primary" onClick={() => void save()} disabled={busy || models.length === 0}>
            {busy ? "保存并分析中…" : "保存模型"}
          </button>
          <button className="btn btn-quiet" onClick={onClose}>
            取消
          </button>
        </footer>
      </div>
    </div>
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
  const [includePaths, setIncludePaths] = useState(detail.project.include_paths.join("\n"));
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
        include_paths: includePaths.split("\n").map((item) => item.trim()).filter(Boolean),
        exclude_patterns: excludePatterns.split("\n").map((item) => item.trim()).filter(Boolean),
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
    <div className="modal-backdrop" role="dialog" aria-modal="true" aria-label="资料与范围">
      <div className="modal">
        <header>
          <div>
            <p className="kicker">资料与范围</p>
            <h2>调整要分析的内容</h2>
          </div>
          <button className="link-button" onClick={onClose}>
            关闭
          </button>
        </header>
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
              <p className="inline-note">还没有补充资料。补充文档会作为独立来源参与分析。</p>
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
        <footer>
          <button className="btn btn-primary" onClick={() => void save()} disabled={busy}>
            {busy ? "扫描并分析中…" : "保存并重新分析"}
          </button>
          <button className="btn btn-quiet" onClick={onClose}>
            取消
          </button>
        </footer>
      </div>
    </div>
  );
}
