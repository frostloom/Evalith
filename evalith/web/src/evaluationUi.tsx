import type { EvalRun } from "./evaluationTypes";
export const statusNames: Record<string, string> = {
  passed: "通过",
  failed: "失败",
  completed: "已完成",
  running: "运行中",
  pending: "等待中",
  validating: "验证中",
  review_required: "待复核",
  validation_error: "证据缺失",
  execution_error: "执行错误",
  budget_stopped: "预算停止",
  cancelled: "已取消",
  cancelling: "正在停止",
  skipped: "已跳过",
  interrupted: "已中断",
  planned: "待确认",
  preparing: "准备中",
  ready: "已就绪",
  missing_evidence: "缺少证据",
  needs_judge: "待模型判断",
};
export const active = (status: string) =>
  ["running", "pending", "validating", "preparing", "cancelling"].includes(
    status,
  );
export function StateBadge({ status }: { status: string }) {
  return (
    <span className={`eval-state state-${status}`}>
      <span />
      {statusNames[status] ?? status}
    </span>
  );
}
export function UsageLine({ value }: { value: EvalRun["usage"] }) {
  return (
    <span className="usage-line">
      {value.model_calls ?? "—"} 次调用{" "}
      <span>
        输入 {value.input_tokens?.toLocaleString() ?? "未知"} / 输出{" "}
        {value.output_tokens?.toLocaleString() ?? "未知"} tokens
      </span>
      <span>费用未知</span>
    </span>
  );
}
