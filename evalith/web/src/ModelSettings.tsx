import { useState } from "react";
import {
  Dialog,
  DialogTitle,
  DialogContent,
  DialogActions,
  Button,
  Tooltip,
} from "@mui/material";
import AddRounded from "@mui/icons-material/AddRounded";
import SmartToyOutlined from "@mui/icons-material/SmartToyOutlined";
import { FormDrawer, PageHeader } from "./ui";
import { api } from "./api";
import type { ModelConfig } from "./types";

export function ModelSettings({
  models,
  onRefresh,
  onBack,
  onError,
  onNotice,
}: {
  models: ModelConfig[];
  onRefresh: () => Promise<void>;
  onBack: () => void;
  onError: (message: string) => void;
  onNotice: (message: string) => void;
}) {
  const [deleting, setDeleting] = useState(false);
  const [deleteError, setDeleteError] = useState<string | null>(null);
  const [adding, setAdding] = useState(false);
  const [deleteTarget, setDeleteTarget] = useState<ModelConfig | null>(null);
  const [name, setName] = useState("");
  const [provider, setProvider] = useState<"stub" | "openai_compatible">(
    "stub",
  );
  const [baseUrl, setBaseUrl] = useState("");
  const [modelName, setModelName] = useState("stub-understanding");
  const [apiKey, setApiKey] = useState("");
  const [busy, setBusy] = useState(false);
  const [testing, setTesting] = useState<string | null>(null);
  const [localError, setLocalError] = useState<string | null>(null);

  const submit = async (event: React.FormEvent) => {
    event.preventDefault();
    setLocalError(null);
    if (!name.trim() || !modelName.trim()) {
      setLocalError("名称与模型名不能为空。");
      return;
    }
    setBusy(true);
    try {
      await api.createModel({
        name: name.trim(),
        provider,
        base_url: provider === "stub" ? null : baseUrl.trim(),
        model_name: modelName.trim(),
        api_key: apiKey,
      });
      setName("");
      setApiKey("");
      await onRefresh();
      onNotice("模型配置已保存。");
      setAdding(false);
    } catch (err) {
      const message = err instanceof Error ? err.message : "保存失败";
      setLocalError(message);
      onError(message);
    } finally {
      setBusy(false);
    }
  };

  const test = async (model: ModelConfig) => {
    setTesting(model.id);
    try {
      const result = await api.testModel(model.id);
      await onRefresh();
      onNotice(result.message);
    } catch (err) {
      onError(err instanceof Error ? err.message : "连接测试失败");
    } finally {
      setTesting(null);
    }
  };

  const remove = async (model: ModelConfig) => {
    if (deleting) return;
    setDeleting(true);
    setDeleteError(null);
    try {
      await api.deleteModel(model.id);
      await onRefresh();
      onNotice("模型配置已删除。");
      setDeleteTarget(null);
    } catch (err) {
      setDeleteError(err instanceof Error ? err.message : "删除失败");
    } finally {
      setDeleting(false);
    }
  };

  return (
    <div className="settings-page page">
      <PageHeader
        title="模型与凭据"
        description="管理项目理解与会话使用的模型。密钥加密保存，默认可使用离线替身验证流程。"
        breadcrumb={
          <button className="link-button" onClick={onBack}>
            返回
          </button>
        }
        actions={
          <Tooltip title="添加模型服务">
            <Button
              variant="contained"
              aria-label="添加模型服务"
              startIcon={<AddRounded />}
              onClick={() => setAdding(true)}
            >
              添加模型
            </Button>
          </Tooltip>
        }
      />
      <div className="settings-layout">
        <section className="config-list">
          <div className="section-heading">
            <h2>已有配置</h2>
            <span>{models.length} 个</span>
          </div>
          {models.length === 0 && (
            <p className="empty-list">
              还没有模型配置。点击右上角的加号添加模型服务。
            </p>
          )}
          {models.map((model) => (
            <article className="config-row" key={model.id}>
              <div className="config-main">
                <div className="model-card-title">
                  <SmartToyOutlined />
                  <h3>{model.name}</h3>
                </div>
                <p className="mono">
                  {model.provider === "stub"
                    ? "确定性替身（不调用真实模型）"
                    : `${model.base_url ?? "未填写地址"} · ${model.model_name}`}
                </p>
                <p className="muted small">
                  {model.has_api_key ? "已保存加密密钥" : "无密钥"}
                  {model.last_test_at
                    ? ` · 最近测试：${model.last_test_ok ? "成功" : "失败"}，${model.last_test_message ?? ""}`
                    : " · 尚未测试"}
                </p>
              </div>
              <div className="config-actions">
                <button
                  className="btn btn-quiet"
                  onClick={() => void test(model)}
                  disabled={testing === model.id}
                >
                  {testing === model.id ? "测试中…" : "测试连接"}
                </button>
                <button
                  className="link-button danger"
                  onClick={() => {
                    setDeleteError(null);
                    setDeleteTarget(model);
                  }}
                >
                  删除
                </button>
              </div>
            </article>
          ))}
        </section>

        {adding && (
          <FormDrawer
            title="添加模型服务"
            onClose={() => setAdding(false)}
            footer={
              <>
                <button
                  className="btn btn-quiet"
                  onClick={() => setAdding(false)}
                >
                  取消
                </button>
                <button
                  className="btn btn-primary"
                  type="submit"
                  form="model-config-form"
                  disabled={busy}
                >
                  {busy ? "保存中…" : "保存配置"}
                </button>
              </>
            }
          >
            <form
              id="model-config-form"
              className="form-sheet compact-sheet"
              onSubmit={submit}
            >
              <label className="field">
                <span>配置名称</span>
                <input
                  value={name}
                  onChange={(event) => setName(event.target.value)}
                  placeholder="例如：本地确定性替身"
                />
              </label>
              <label className="field">
                <span>提供方</span>
                <select
                  value={provider}
                  onChange={(event) => {
                    const next = event.target.value as
                      | "stub"
                      | "openai_compatible";
                    setProvider(next);
                    setModelName(next === "stub" ? "stub-understanding" : "");
                  }}
                >
                  <option value="stub">确定性替身（离线，不产生费用）</option>
                  <option value="openai_compatible">OpenAI 兼容服务</option>
                </select>
              </label>
              {provider === "openai_compatible" && (
                <>
                  <label className="field">
                    <span>服务地址</span>
                    <input
                      value={baseUrl}
                      onChange={(event) => setBaseUrl(event.target.value)}
                      placeholder="https://api.example.com/v1"
                      className="mono"
                    />
                  </label>
                  <label className="field">
                    <span>模型名</span>
                    <input
                      value={modelName}
                      onChange={(event) => setModelName(event.target.value)}
                      placeholder="model-name"
                      className="mono"
                    />
                  </label>
                  <label className="field">
                    <span>API 密钥（可选）</span>
                    <input
                      type="password"
                      value={apiKey}
                      onChange={(event) => setApiKey(event.target.value)}
                      placeholder="只加密保存，不回传"
                      autoComplete="off"
                    />
                  </label>
                </>
              )}
              {provider === "stub" && (
                <p className="inline-note">
                  替身按固定规则返回理解与讨论内容，用于验证链路和边界，不代表真实模型判断。
                </p>
              )}
              {localError && (
                <p className="form-error" role="alert">
                  {localError}
                </p>
              )}
            </form>
          </FormDrawer>
        )}
      </div>
      <Dialog
        open={Boolean(deleteTarget)}
        onClose={deleting ? undefined : () => setDeleteTarget(null)}
        aria-labelledby="delete-model-title"
      >
        <DialogTitle id="delete-model-title">删除模型配置？</DialogTitle>
        <DialogContent>
          确认删除“{deleteTarget?.name}”？项目会话与已有记录会保留。
          {deleteError && (
            <p role="alert" className="form-error">
              {deleteError}
            </p>
          )}
        </DialogContent>
        <DialogActions>
          <Button disabled={deleting} onClick={() => setDeleteTarget(null)}>
            取消
          </Button>
          <Button
            color="error"
            disabled={deleting}
            onClick={() => deleteTarget && void remove(deleteTarget)}
          >
            确认删除
          </Button>
        </DialogActions>
      </Dialog>
    </div>
  );
}
