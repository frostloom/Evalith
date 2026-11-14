import {
  Plus as AddRounded,
  TerminalSquare as TerminalRounded,
  Globe2 as LanguageRounded,
} from "lucide-react";
import { useEffect, useState } from "react";
import {
  Alert,
  Button,
  Dialog,
  DialogActions,
  DialogContent,
  DialogTitle,
} from "@mui/material";
import { api } from "./api";
import { FormDrawer, PageHeader } from "./ui";
import type { ExecutorConfig, ExecutorDefinition } from "./types";

const backendNames = {
  local_command: "本地命令",
  http_api: "HTTP API",
  harbor: "Harbor",
};

export function ExecutorSettings() {
  const [items, setItems] = useState<ExecutorConfig[]>([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [notice, setNotice] = useState<string | null>(null);
  const [editing, setEditing] = useState<ExecutorConfig | "new" | null>(null);
  const [deleting, setDeleting] = useState<ExecutorConfig | null>(null);
  const [deleteError, setDeleteError] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);
  const [reload, setReload] = useState(0);
  useEffect(() => {
    let active = true;
    setLoading(true);
    setError(null);
    api
      .listExecutorConfigs()
      .then((result) => {
        if (active) setItems(result.items);
      })
      .catch((err) => {
        if (active)
          setError(err instanceof Error ? err.message : "无法加载执行器配置。");
      })
      .finally(() => {
        if (active) setLoading(false);
      });
    return () => {
      active = false;
    };
  }, [reload]);
  const remove = async () => {
    if (!deleting || busy) return;
    setBusy(true);
    setDeleteError(null);
    try {
      await api.deleteExecutorConfig(deleting.id);
      setItems((current) => current.filter((item) => item.id !== deleting.id));
      setDeleting(null);
      setNotice("执行器配置已删除。");
    } catch (err) {
      setDeleteError(err instanceof Error ? err.message : "删除失败。");
    } finally {
      setBusy(false);
    }
  };
  return (
    <div className="page settings-page">
      <PageHeader
        title="执行器配置"
        description="定义评测如何运行，与项目资料、模型服务分别管理。"
        actions={
          <Button
            variant="contained"
            startIcon={<AddRounded />}
            onClick={() => setEditing("new")}
          >
            添加执行器
          </Button>
        }
      />
      {notice && (
        <Alert
          severity="success"
          onClose={() => setNotice(null)}
          className="settings-feedback"
        >
          {notice}
        </Alert>
      )}
      <div className="settings-info">
        <TerminalRounded />
        <div>
          <strong>先配置执行后端</strong>
          <p>
            保存定义后，在项目中查看并确认独立运行环境，再启动评测。Harbor
            后端在容器内执行命令题目，评分与证据判定仍在 Evalith 侧进行。
          </p>
        </div>
      </div>
      {error && (
        <Alert
          severity="error"
          action={
            <Button onClick={() => setReload((value) => value + 1)}>
              重试
            </Button>
          }
        >
          {error}
        </Alert>
      )}
      {loading ? (
        <p role="status" className="settings-loading">
          正在加载执行器…
        </p>
      ) : (
        !error && (
          <div className="service-list" role="region" aria-label="执行器列表">
            <div className="service-list-header">
              <span>执行器</span>
              <span>类型</span>
              <span>状态</span>
              <span />
            </div>
            {items.map((item) => (
              <article className="service-row" key={item.id}>
                <div className="service-main">
                  <span className="service-icon">
                    {item.backend === "http_api" ? (
                      <LanguageRounded />
                    ) : (
                      <TerminalRounded />
                    )}
                  </span>
                  <div>
                    <h2>{item.name}</h2>
                    <p title={item.base_url || item.command.join(" ")}>
                      {item.base_url || item.command.join(" ")}
                    </p>
                  </div>
                </div>
                <span className="service-provider">
                  {backendNames[item.backend]}
                </span>
                <span className="service-status">
                  <i />
                  未验证
                </span>
                <div className="service-actions">
                  <button onClick={() => setEditing(item)}>编辑</button>
                  <button
                    className="danger-action"
                    onClick={() => {
                      setDeleting(item);
                      setDeleteError(null);
                    }}
                  >
                    删除
                  </button>
                </div>
              </article>
            ))}
            {!items.length && (
              <div className="service-empty">
                <TerminalRounded />
                <h2>添加第一个执行器</h2>
                <p>
                  选择本地命令、HTTP API 或 Harbor，为后续评测准备运行方式。
                </p>
                <button onClick={() => setEditing("new")}>添加执行器</button>
              </div>
            )}
          </div>
        )
      )}
      {editing && (
        <ExecutorEditor
          key={editing === "new" ? "new" : editing.id}
          initial={editing === "new" ? undefined : editing}
          onClose={() => setEditing(null)}
          onSaved={(saved) => {
            setItems((current) => [
              ...current.filter((item) => item.id !== saved.id),
              saved,
            ]);
            setEditing(null);
            setNotice("执行器配置已保存，尚未执行验证。");
          }}
        />
      )}
      <Dialog
        open={Boolean(deleting)}
        onClose={busy ? undefined : () => setDeleting(null)}
        aria-labelledby="delete-executor-title"
      >
        <DialogTitle id="delete-executor-title">删除执行器配置？</DialogTitle>
        <DialogContent>
          确认删除“{deleting?.name}”？
          {deleteError && (
            <p className="form-error" role="alert">
              {deleteError}
            </p>
          )}
        </DialogContent>
        <DialogActions>
          <Button onClick={() => setDeleting(null)} disabled={busy}>
            取消
          </Button>
          <Button color="error" onClick={() => void remove()} disabled={busy}>
            确认删除
          </Button>
        </DialogActions>
      </Dialog>
    </div>
  );
}

function ExecutorEditor({
  initial,
  onClose,
  onSaved,
}: {
  initial?: ExecutorConfig;
  onClose: () => void;
  onSaved: (saved: ExecutorConfig) => void;
}) {
  const [name, setName] = useState(initial?.name ?? "");
  const [backend, setBackend] = useState<ExecutorDefinition["backend"]>(
    initial?.backend ?? "local_command",
  );
  const [program, setProgram] = useState(initial?.command[0] ?? "");
  const [args, setArgs] = useState(initial?.command.slice(1).join("\n") ?? "");
  const [directory, setDirectory] = useState(initial?.working_directory ?? "");
  const [url, setUrl] = useState(initial?.base_url ?? "");
  const [timeout, setTimeoutSeconds] = useState(initial?.timeout_seconds ?? 60);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const submit = async (event: React.FormEvent) => {
    event.preventDefault();
    setError(null);
    if (!name.trim() || (backend !== "http_api" && !program.trim())) {
      setError("请填写名称和执行程序。");
      return;
    }
    const definition: ExecutorDefinition = {
      name: name.trim(),
      backend,
      command:
        backend === "http_api"
          ? []
          : [
              program.trim(),
              ...args
                .split("\n")
                .map((value) => value.trim())
                .filter(Boolean),
            ],
      working_directory:
        backend === "http_api" ? null : directory.trim() || null,
      base_url: backend === "http_api" ? url.trim() : null,
      timeout_seconds: timeout,
    };
    setBusy(true);
    try {
      onSaved(
        initial
          ? await api.updateExecutorConfig(initial.id, definition)
          : await api.createExecutorConfig(definition),
      );
    } catch (err) {
      setError(err instanceof Error ? err.message : "保存失败。");
    } finally {
      setBusy(false);
    }
  };
  return (
    <FormDrawer
      presentation="dialog"
      title={initial ? "编辑执行器" : "添加执行器"}
      onClose={onClose}
      busy={busy}
      footer={
        <>
          <Button onClick={onClose} disabled={busy}>
            取消
          </Button>
          <Button
            type="submit"
            form="executor-form"
            variant="contained"
            disabled={busy}
          >
            {busy ? "正在保存…" : "保存配置"}
          </Button>
        </>
      }
    >
      <p className="drawer-intro">
        执行器负责评测运行。模型服务与项目资料在各自页面管理。
      </p>
      <form id="executor-form" className="form-sheet" onSubmit={submit}>
        <label className="field">
          <span>配置名称</span>
          <input
            autoFocus
            value={name}
            onChange={(event) => setName(event.target.value)}
            placeholder="例如：本地审批测试"
            maxLength={80}
          />
        </label>
        <label className="field">
          <span>执行后端</span>
          <select
            value={backend}
            onChange={(event) => {
              const value = event.target.value as ExecutorDefinition["backend"];
              setBackend(value);
              if (value === "harbor" && !program) setProgram("harbor");
            }}
          >
            <option value="local_command">本地命令</option>
            <option value="http_api">HTTP API</option>
            <option value="harbor">Harbor</option>
          </select>
        </label>
        {backend === "http_api" ? (
          <label className="field">
            <span>API 地址</span>
            <input
              type="url"
              value={url}
              onChange={(event) => setUrl(event.target.value)}
              placeholder="http://127.0.0.1:8800/evaluate"
              required
            />
          </label>
        ) : (
          <>
            <label className="field">
              <span>执行程序</span>
              <input
                value={program}
                onChange={(event) => setProgram(event.target.value)}
                placeholder={backend === "harbor" ? "harbor" : "python"}
              />
              <small>仅保存定义，不运行程序。</small>
            </label>
            <label className="field">
              <span>命令参数（可选）</span>
              <textarea
                rows={3}
                value={args}
                onChange={(event) => setArgs(event.target.value)}
                placeholder={"agent.py\n--mode\ntest"}
              />
              <small>每行一个参数；不要填写 Shell 组合命令或密钥。</small>
            </label>
            <label className="field">
              <span>工作目录（可选）</span>
              <input
                value={directory}
                onChange={(event) => setDirectory(event.target.value)}
                placeholder="/Users/you/projects/agent"
              />
            </label>
          </>
        )}
        <label className="field">
          <span>超时（秒）</span>
          <input
            type="number"
            min={1}
            max={3600}
            value={timeout}
            onChange={(event) => setTimeoutSeconds(Number(event.target.value))}
          />
        </label>
        {error && (
          <p className="form-error" role="alert">
            {error}
          </p>
        )}
      </form>
    </FormDrawer>
  );
}
