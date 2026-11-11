import { useMemo, useState } from "react";
import { FormDrawer } from "./ui";
import { api } from "./api";
import type { ModelConfig, ProjectDetail } from "./types";

export function ImportSheet({
  models,
  token,
  onCancel,
  onCreated,
  onNeedModel,
  onError,
}: {
  models: ModelConfig[];
  token: number;
  onCancel: () => void;
  onCreated: (detail: ProjectDetail, token: number) => void;
  onNeedModel: () => void;
  onError: (message: string) => void;
}) {
  const defaultModel = useMemo(() => {
    return (
      models.find((item) => item.provider === "stub")?.id ?? models[0]?.id ?? ""
    );
  }, [models]);
  const [name, setName] = useState("");
  const [rootPath, setRootPath] = useState("");
  const [modelId, setModelId] = useState(defaultModel);
  const [includePaths, setIncludePaths] = useState("");
  const [excludePatterns, setExcludePatterns] = useState("");
  const [supplementTitle, setSupplementTitle] = useState("");
  const [supplementContent, setSupplementContent] = useState("");
  const [supplemental, setSupplemental] = useState<
    Array<{ title: string; content: string }>
  >([]);
  const [busy, setBusy] = useState(false);
  const [localError, setLocalError] = useState<string | null>(null);

  const addSupplement = () => {
    if (!supplementContent.trim()) return;
    setSupplemental((current) => [
      ...current,
      {
        title: supplementTitle.trim() || `补充资料 ${current.length + 1}`,
        content: supplementContent.trim(),
      },
    ]);
    setSupplementTitle("");
    setSupplementContent("");
  };

  const submit = async (event: React.FormEvent) => {
    event.preventDefault();
    setLocalError(null);
    if (!name.trim()) {
      setLocalError("请填写项目名称。");
      return;
    }
    if (!rootPath.trim()) {
      setLocalError("请填写本地项目目录的绝对路径。");
      return;
    }
    setBusy(true);
    try {
      const detail = await api.createProject({
        name: name.trim(),
        root_path: rootPath.trim(),
        model_config_id: modelId || null,
        include_paths: includePaths
          .split("\n")
          .map((item) => item.trim())
          .filter(Boolean),
        exclude_patterns: excludePatterns
          .split("\n")
          .map((item) => item.trim())
          .filter(Boolean),
        supplemental,
      });
      onCreated(detail, token);
    } catch (err) {
      const message = err instanceof Error ? err.message : "建立项目失败";
      setLocalError(message);
      onError(message);
    } finally {
      setBusy(false);
    }
  };

  return (
    <FormDrawer
      title="建立项目"
      onClose={onCancel}
      footer={
        <>
          <button type="button" className="btn btn-quiet" onClick={onCancel}>
            取消
          </button>
          <button
            type="submit"
            form="import-project-form"
            className="btn btn-primary"
            disabled={busy}
          >
            {busy ? "正在扫描并分析…" : "建立项目"}
          </button>
        </>
      }
    >
      <p className="drawer-intro">
        连接本地目录，为项目准备资料和独立的持续会话。
      </p>
      <form id="import-project-form" className="form-sheet" onSubmit={submit}>
        <div className="field-row">
          <label className="field">
            <span>项目名称</span>
            <input
              value={name}
              onChange={(event) => setName(event.target.value)}
              placeholder="例如：发布审批 Agent"
              autoFocus
            />
          </label>
          <label className="field">
            <span>模型服务</span>
            <select
              value={modelId}
              onChange={(event) => setModelId(event.target.value)}
            >
              <option value="">暂不配置（分析会失败并显示原因）</option>
              {models.map((model) => (
                <option key={model.id} value={model.id}>
                  {model.name} ·{" "}
                  {model.provider === "stub" ? "确定性替身" : model.model_name}
                </option>
              ))}
            </select>
          </label>
        </div>

        <label className="field">
          <span>本地目录（绝对路径）</span>
          <input
            value={rootPath}
            onChange={(event) => setRootPath(event.target.value)}
            placeholder="/Users/you/projects/approval-agent"
            className="mono"
          />
          <small>目录会以只读方式打开；不会创建、修改或删除任何文件。</small>
        </label>

        <details className="advanced-fields">
          <summary>分析范围与补充资料（可选）</summary>
          <div className="field-row">
            <label className="field">
              <span>只分析这些路径（可选）</span>
              <textarea
                value={includePaths}
                onChange={(event) => setIncludePaths(event.target.value)}
                placeholder={"docs\nsrc\nREADME.md"}
                rows={4}
                className="mono"
              />
              <small>
                相对项目目录，一行一个。留空表示整个目录，仍受排除规则限制。
              </small>
            </label>
            <label className="field">
              <span>额外排除（可选）</span>
              <textarea
                value={excludePatterns}
                onChange={(event) => setExcludePatterns(event.target.value)}
                placeholder={"*.snap\nfixtures"}
                rows={4}
                className="mono"
              />
              <small>在默认排除之外追加。敏感凭据规则不能被覆盖。</small>
            </label>
          </div>

          <fieldset className="supplement-field">
            <legend>补充资料</legend>
            <div className="field-row">
              <label className="field">
                <span>标题</span>
                <input
                  value={supplementTitle}
                  onChange={(event) => setSupplementTitle(event.target.value)}
                  placeholder="业务规则补充"
                />
              </label>
              <label className="field grow">
                <span>内容</span>
                <textarea
                  value={supplementContent}
                  onChange={(event) => setSupplementContent(event.target.value)}
                  rows={2}
                  placeholder="不在项目文件中的业务背景、验收标准或已知限制。"
                />
              </label>
            </div>
            <div className="supplement-actions">
              <button
                type="button"
                className="btn btn-quiet"
                onClick={addSupplement}
              >
                添加到本次分析
              </button>
              {supplemental.length > 0 && (
                <span className="muted">{supplemental.length} 条已添加</span>
              )}
            </div>
            {supplemental.length > 0 && (
              <ul className="supplement-list">
                {supplemental.map((item, index) => (
                  <li key={`${item.title}-${index}`}>
                    <span>{item.title}</span>
                    <button
                      type="button"
                      onClick={() =>
                        setSupplemental((current) =>
                          current.filter((_, itemIndex) => itemIndex !== index),
                        )
                      }
                    >
                      移除
                    </button>
                  </li>
                ))}
              </ul>
            )}
          </fieldset>
        </details>
        {models.length === 0 && (
          <p className="inline-note">
            还没有模型配置。可以先用“确定性替身”离线验证流程，不代表真实模型质量。
            <button type="button" className="link-button" onClick={onNeedModel}>
              去添加
            </button>
          </p>
        )}

        {localError && (
          <p className="form-error" role="alert">
            {localError}
          </p>
        )}
      </form>

      <details className="boundary-panel">
        <summary>资料读取规则</summary>
        <ul className="rule-list">
          <li>
            <strong>只读</strong>
            <span>文件以只读方式打开，不会修改项目。</span>
          </li>
          <li>
            <strong>范围受控</strong>
            <span>只读取你选择的路径，越界路径被拒绝。</span>
          </li>
          <li>
            <strong>凭据排除</strong>
            <span>.env、密钥、secrets 等默认排除，显式选择也不能覆盖。</span>
          </li>
          <li>
            <strong>符号链接不跟随</strong>
            <span>指向项目外部的链接会被跳过并记录。</span>
          </li>
          <li>
            <strong>指纹可核对</strong>
            <span>每个文件记录 SHA-256 与大小，理解中的来源可回溯。</span>
          </li>
        </ul>
        <p className="boundary-foot">
          阶段 1 为宿主机本地模式；容器访问尚未实现，配置为非 host 时一律拒绝。
        </p>
      </details>
    </FormDrawer>
  );
}
