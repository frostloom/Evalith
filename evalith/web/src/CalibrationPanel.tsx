import { useCallback, useEffect, useState } from "react";
import { Alert, Button, MenuItem, TextField } from "@mui/material";
import { Plus, ShieldCheck } from "lucide-react";
import { evaluationApi as api } from "./evaluationApi";
import type { CalibrationJob, CalibrationReport, Grader } from "./evaluationTypes";
import type { ModelConfig } from "./types";

const failure = (e: unknown) => (e instanceof Error ? e.message : "操作失败");

export const calibrationLabels: Record<string, string> = {
  unverified: "未校准",
  calibrated: "已校准",
  disagreement: "校准不一致",
};
const verdictLabels: Record<string, string> = {
  pass: "通过",
  fail: "失败",
  missing_evidence: "缺证据",
};

type CalibrationDraft = { name: string; document: string; expected: string };

export function CalibrationPanel({
  projectId,
  grader,
  models,
  onSaved,
}: {
  projectId: string;
  grader: Grader;
  models: ModelConfig[];
  onSaved: () => Promise<void>;
}) {
  const [samples, setSamples] = useState<CalibrationDraft[]>([
    { name: "", document: "", expected: "pass" },
  ]);
  const [modelId, setModelId] = useState(grader.model_config_id ?? "");
  const [jobId, setJobId] = useState<string | null>(null);
  const [reports, setReports] = useState<CalibrationReport[]>([]);
  const [selected, setSelected] = useState<string | null>(null);
  const [error, setError] = useState("");
  const [busy, setBusy] = useState(false);

  const reload = useCallback(async () => {
    const result = await api.calibrations(projectId, grader.id);
    setReports(result.items);
    setSelected((current) => current ?? result.items[0]?.id ?? null);
  }, [projectId, grader.id]);
  useEffect(() => {
    void reload().catch(() => {});
  }, [reload]);

  useEffect(() => {
    if (!jobId) return;
    const timer = window.setInterval(() => {
      void api
        .jobs(projectId)
        .then(({ items }) => {
          const job = items.find((item) => item.id === jobId);
          if (!job) {
            window.clearInterval(timer);
            setJobId(null);
            setError("校准任务记录不存在或已丢失");
            return;
          }
          if (job.status === "pending" || job.status === "running") return;
          window.clearInterval(timer);
          setJobId(null);
          if (job.status === "failed") setError(job.error ?? "校准任务失败");
          return Promise.all([reload(), onSaved()]);
        })
        .catch(() => {});
    }, 1200);
    return () => window.clearInterval(timer);
  }, [jobId, projectId, reload, onSaved]);

  const valid =
    !!samples.length &&
    samples.every(
      (sample) => !!sample.name.trim() && !!sample.document.trim(),
    ) &&
    new Set(samples.map((sample) => sample.name.trim().toLowerCase())).size ===
      samples.length;
  const start = async () => {
    setBusy(true);
    setError("");
    try {
      const job: CalibrationJob = await api.startCalibration(
        projectId,
        grader.id,
        samples.map((sample) => ({
          name: sample.name.trim(),
          document: sample.document.trim(),
          expected: sample.expected,
        })),
        modelId || null,
      );
      setJobId(job.id);
    } catch (e) {
      setError(failure(e));
    } finally {
      setBusy(false);
    }
  };
  const patch = (index: number, change: Partial<CalibrationDraft>) =>
    setSamples(
      samples.map((item, at) => (at === index ? { ...item, ...change } : item)),
    );
  const report = reports.find((item) => item.id === selected) ?? reports[0];
  return (
    <section className="calibration-panel" aria-label="评分标准校准">
      <div className="review-banner">
        <ShieldCheck />
        <div>
          <h3>
            校准 · {calibrationLabels[grader.calibration_state] ?? "未校准"}
          </h3>
          <p>
            用已知结果的样本核对当前版本的评分行为；校准一致不等于业务真值。
          </p>
        </div>
      </div>
      {samples.map((sample, index) => (
        <div className="calibration-sample" key={index}>
          <TextField
            label={`样本 ${index + 1} 名称`}
            value={sample.name}
            onChange={(e) => patch(index, { name: e.target.value })}
          />
          <TextField
            select
            label="预期结果"
            value={sample.expected}
            onChange={(e) => patch(index, { expected: e.target.value })}
          >
            <MenuItem value="pass">应通过</MenuItem>
            <MenuItem value="fail">应失败</MenuItem>
            <MenuItem value="missing_evidence">应缺证据</MenuItem>
          </TextField>
          <TextField
            label="观察文档（评分模型可见的全部证据）"
            multiline
            minRows={2}
            value={sample.document}
            onChange={(e) => patch(index, { document: e.target.value })}
          />
          {samples.length > 1 && (
            <Button
              size="small"
              onClick={() =>
                setSamples(samples.filter((_, at) => at !== index))
              }
            >
              移除样本
            </Button>
          )}
        </div>
      ))}
      <div className="calibration-actions">
        <Button
          size="small"
          startIcon={<Plus />}
          disabled={samples.length >= 20}
          onClick={() =>
            setSamples([
              ...samples,
              { name: "", document: "", expected: "pass" },
            ])
          }
        >
          添加样本
        </Button>
        <TextField
          select
          label="评分模型"
          value={modelId}
          onChange={(e) => setModelId(e.target.value)}
          className="calibration-model"
        >
          <MenuItem value="">跟随标准绑定模型</MenuItem>
          {models
            .filter((m) => m.provider === "openai_compatible")
            .map((m) => (
              <MenuItem key={m.id} value={m.id}>
                {m.name} · {m.model_name}
              </MenuItem>
            ))}
        </TextField>
        <Button
          variant="contained"
          disabled={!valid || busy || !!jobId}
          onClick={() => void start()}
        >
          {jobId
            ? "校准进行中…"
            : `开始校准（${samples.length} 个样本，每样本一次模型调用）`}
        </Button>
      </div>
      {error && <Alert severity="error">{error}</Alert>}
      {report && (
        <div className="calibration-report">
          <h4>
            校准报告 v{report.grader_version} ·{" "}
            {report.stale
              ? "已过期（标准在校准期间被修改）"
              : report.state === "calibrated"
                ? "全部样本一致"
                : `${report.summary.matched}/${report.summary.total} 一致`}
            {reports.length > 1 && (
              <select
                value={report.id}
                aria-label="选择校准报告"
                onChange={(e) => setSelected(e.target.value)}
              >
                {reports.map((item) => (
                  <option key={item.id} value={item.id}>
                    {new Date(item.created_at).toLocaleString()}
                  </option>
                ))}
              </select>
            )}
          </h4>
          <dl>
            <dt>模型</dt>
            <dd>{report.model}</dd>
            <dt>用量</dt>
            <dd>
              {report.usage?.input_tokens ?? "未知"} 输入 /{" "}
              {report.usage?.output_tokens ?? "未知"} 输出 tokens，费用未知
            </dd>
          </dl>
          {report.samples.map((sample) => (
            <div className="review-step" key={sample.name}>
              <span>{sample.matched ? "✓" : "✗"}</span>
              <div>
                <strong>{sample.name}</strong>：预期{" "}
                {verdictLabels[sample.expected] ?? sample.expected} · 实际{" "}
                {verdictLabels[sample.actual] ?? sample.actual}
                {sample.score !== null && ` · 分数 ${sample.score}`}
                {sample.reason && ` · ${sample.reason}`}
              </div>
            </div>
          ))}
        </div>
      )}
    </section>
  );
}
