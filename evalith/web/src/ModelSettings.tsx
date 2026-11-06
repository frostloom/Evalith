import { useState } from "react";
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
  const [name, setName] = useState("");
  const [provider, setProvider] = useState<"stub" | "openai_compatible">("stub");
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
    try {
      await api.deleteModel(model.id);
      await onRefresh();
      onNotice("模型配置已删除。");
    } catch (err) {
      onError(err instanceof Error ? err.message : "删除失败");
    }
  };

  return (
    <div className="settings-page">
      <header className="page-head compact">
        <p className="kicker">模型与凭据</p>
        <h1>配置会话使用的模型服务。</h1>
        <p className="lede">
          密钥加密保存，接口不会回传明文，模型请求只通过 Authorization 头携带。
          使用“确定性替身”可离线验证流程，但不代表真实模型质量。
        </p>
        <button className="btn btn-quiet" onClick={onBack}>
          返回
        </button>
      </header>

      <div className="settings-layout">
        <section className="config-list">
          <div className="section-heading">
            <h2>已有配置</h2>
            <span>{models.length} 个</span>
          </div>
          {models.length === 0 && (
            <p className="empty-list">还没有模型配置。右侧添加一个确定性替身即可开始。</p>
          )}
          {models.map((model) => (
            <article className="config-row" key={model.id}>
              <div className="config-main">
                <h3>{model.name}</h3>
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
                <button className="link-button danger" onClick={() => void remove(model)}>
                  删除
                </button>
              </div>
            </article>
          ))}
        </section>

        <form className="form-sheet compact-sheet" onSubmit={submit}>
          <h2>添加模型服务</h2>
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
                const next = event.target.value as "stub" | "openai_compatible";
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
          <div className="form-actions">
            <button className="btn btn-primary" type="submit" disabled={busy}>
              {busy ? "保存中…" : "保存配置"}
            </button>
          </div>
        </form>
      </div>
    </div>
  );
}
