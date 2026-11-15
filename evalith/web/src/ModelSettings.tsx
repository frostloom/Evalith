import { Plus as AddRounded, Bot as SmartToyOutlined } from "lucide-react";
import { useState } from "react";
import { Button, Modal, Tooltip, App as AntApp } from "antd";
import { FormDrawer, PageHeader, SelectInput, TextInput } from "./ui";
import { api } from "./api";
import type { ModelConfig } from "./types";

export function ModelSettings({
  models,
  onRefresh,
  onBack,
  onError,
}: {
  models: ModelConfig[];
  onRefresh: () => Promise<void>;
  onBack: () => void;
  onError: (message: string) => void;
  onNotice: (message: string) => void;
}) {
  const { message } = AntApp.useApp();
  const [deleting, setDeleting] = useState(false);
  const [deleteError, setDeleteError] = useState<string | null>(null);
  const [adding, setAdding] = useState(false);
  const [deleteTarget, setDeleteTarget] = useState<ModelConfig | null>(null);
  const [name, setName] = useState("");
  const [provider, setProvider] = useState<ModelConfig["provider"]>("stub");
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
        base_url: provider === "openai_compatible" ? baseUrl.trim() : null,
        model_name: modelName.trim(),
        api_key: provider === "openai_compatible" ? apiKey : "",
      });
      setName("");
      setApiKey("");
      await onRefresh();
      message.success("模型配置已保存。");
      setAdding(false);
    } catch (err) {
      const text = err instanceof Error ? err.message : "保存失败";
      setLocalError(text);
      onError(text);
    } finally {
      setBusy(false);
    }
  };

  const test = async (model: ModelConfig) => {
    setTesting(model.id);
    try {
      const result = await api.testModel(model.id);
      await onRefresh();
      if (result.ok) message.success(result.message);
      else message.error(result.message);
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
      message.success("模型配置已删除。");
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
        title="模型配置"
        description="管理项目理解与会话使用的模型。密钥加密保存，可使用离线演示模型体验流程。"
        actions={
          <>
            <button className="link-button" onClick={onBack}>
              返回
            </button>
            <Tooltip title="添加模型服务">
              <Button
                type="primary"
                aria-label="添加模型服务"
                icon={<AddRounded size={16} />}
                onClick={() => setAdding(true)}
              >
                添加模型
              </Button>
            </Tooltip>
          </>
        }
      />
      <div className="settings-layout">
        <section className="service-list" aria-label="模型配置列表">
          <div className="service-list-header">
            <span>模型服务</span>
            <span>提供方</span>
            <span>连接状态</span>
            <span />
          </div>
          {!models.length && (
            <div className="service-empty">
              <SmartToyOutlined />
              <h2>添加第一个模型</h2>
              <p>连接模型服务，在项目会话中复用。</p>
              <button onClick={() => setAdding(true)}>添加模型</button>
            </div>
          )}
          {models.map((model) => (
            <article className="service-row" key={model.id}>
              <div className="service-main">
                <span className="service-icon">
                  <SmartToyOutlined />
                </span>
                <div>
                  <h2>{model.name}</h2>
                  <p>
                    {model.provider === "stub"
                      ? "离线流程验证 · 不调用真实模型"
                      : model.model_name}
                  </p>
                  {model.last_test_at && !model.last_test_ok ? (
                    <div className="service-error-detail">
                      {model.last_test_message}
                    </div>
                  ) : null}
                </div>
              </div>
              <span className="service-provider">
                {model.provider === "stub" ? "离线演示" : model.provider === "codex_local" ? "ChatGPT 账号（已移除）" : "OpenAI 兼容"}
              </span>
              <span
                className={`service-status ${model.last_test_ok ? "is-ok" : model.last_test_at ? "is-error" : ""}`}
              >
                <i />
                {model.last_test_at
                  ? model.last_test_ok
                    ? "已连接"
                    : "连接失败"
                  : "未测试"}
              </span>
              <div className="service-actions">
                <button
                  onClick={() => void test(model)}
                  disabled={testing === model.id}
                >
                  {testing === model.id ? "测试中…" : "测试连接"}
                </button>
                <button
                  className="danger-action"
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
            presentation="dialog"
            busy={busy}
            title="添加模型服务"
            onClose={() => setAdding(false)}
            footer={
              <>
                <Button
                  disabled={busy}
                  onClick={() => setAdding(false)}
                >
                  取消
                </Button>
                <Button
                  type="primary"
                  htmlType="submit"
                  form="model-config-form"
                  loading={busy}
                >
                  保存配置
                </Button>
              </>
            }
          >
            <form
              id="model-config-form"
              className="form-sheet compact-sheet"
              onSubmit={submit}
            >
              <TextInput
                label="配置名称"
                value={name}
                onChange={setName}
                placeholder="例如：本地离线演示"
              />
              <SelectInput
                label="提供方"
                value={provider}
                onChange={(next) => {
                  const value = next as ModelConfig["provider"];
                  setProvider(value);
                  setModelName(
                    value === "stub"
                      ? "stub-understanding"
                      : "",
                  );
                }}
                options={[
                  { value: "stub", label: "离线演示（离线，不产生费用）" },
                  { value: "openai_compatible", label: "OpenAI 兼容服务" },
                ]}
              />
              {provider === "openai_compatible" && (
                <>
                  <TextInput
                    label="服务地址"
                    value={baseUrl}
                    onChange={setBaseUrl}
                    placeholder="https://api.example.com/v1"
                    className="mono"
                  />
                  <TextInput
                    label="模型名"
                    value={modelName}
                    onChange={setModelName}
                    placeholder="model-name"
                    className="mono"
                  />
                  <TextInput
                    label="API 密钥（可选）"
                    value={apiKey}
                    onChange={setApiKey}
                    placeholder="只加密保存，不回传"
                  />
                </>
              )}
              {provider === "stub" && (
                <p className="inline-note">
                  演示模型按固定规则返回理解与讨论内容，用于验证链路和边界，不代表真实模型判断。
                </p>
              )}
              {provider === "openai_compatible" && (
                <p className="inline-note">
                  通过 OpenAI 兼容接口调用真实模型。付费模型需维护者显式开启 EVALITH_ALLOW_PAID_MODELS 后才能保存；密钥加密保存，不回传前端。
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
      <Modal
        open={Boolean(deleteTarget)}
        title="删除模型配置？"
        okText="确认删除"
        okButtonProps={{ danger: true, loading: deleting }}
        cancelText="取消"
        onCancel={deleting ? undefined : () => setDeleteTarget(null)}
        onOk={() => deleteTarget && void remove(deleteTarget)}
      >
        确认删除“{deleteTarget?.name}”？项目会话与已有记录会保留。
        {deleteError && (
          <p role="alert" className="form-error">
            {deleteError}
          </p>
        )}
      </Modal>
    </div>
  );
}
