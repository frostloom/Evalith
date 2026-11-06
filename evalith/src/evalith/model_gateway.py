"""Model adapters for project understanding.

Two providers are supported:

* ``stub`` — deterministic, offline, used by tests and by the local demo so a
  verification run never depends on a real model or spends money;
* ``openai_compatible`` — any endpoint exposing ``POST /chat/completions``.

The gateway never logs prompts or responses.  Credentials are passed only in
the HTTP ``Authorization`` header and are redacted from error messages.
"""

from __future__ import annotations

import json
import re
from dataclasses import dataclass
from typing import Any

import httpx

from .security import redact_text

UNDERSTANDING_SCHEMA = {
    "summary": "一句话项目理解（简体中文）",
    "agent_or_flow": "识别到的 Agent、服务或业务流程；不确定时说明依据不足",
    "known": [{"text": "有直接资料依据的已知事实", "source": "文件路径或 supplement:标题"}],
    "inferred": [{"text": "推断（不是事实）", "basis": "推断依据"}],
    "unknowns": [{"text": "影响评测方向但资料中缺失的信息", "why": "为什么重要"}],
    "sufficient": False,
    "sufficient_reason": "为什么当前依据足够或不足",
}

SYSTEM_PROMPT = """你是 Evalith 的项目理解助手。你只根据用户提供的项目资料摘录和补充资料工作。
要求：
1. 区分“已知”“推断”“未知”。已知必须有文件路径或补充资料标题作为来源；推断必须说明依据，不能伪装成事实。
2. 不要编造资料中不存在的业务规则、接口、命令或验收标准。缺少信息时写入 unknowns。
3. 你只做理解和讨论，不生成题目、评分规则或测试数据；用户表示继续也不等于未知业务规则已经确认。
4. 输出严格 JSON，结构如下：
{schema}
5. 只有当资料足以支撑评测方向且关键未知项已不影响理解时，sufficient 才为 true；否则为 false。
""".format(schema=json.dumps(UNDERSTANDING_SCHEMA, ensure_ascii=False, indent=2))

CHAT_SYSTEM_PROMPT = """你是 Evalith 的项目理解助手，正在与用户讨论一个本地项目。
你可以被用户纠正、补充资料或调整评测方向。只根据给定资料和当前理解回答。
输出严格 JSON：
{{
  "reply": "对用户的简短回复（简体中文）",
  "continue_requested": true/false,
  "understanding": {{与当前理解同结构，可更新 summary/known/inferred/unknowns/sufficient}},
  "direction_update": "如果用户调整了评测方向，记录一句话；否则为空字符串"
}}
用户说“继续”只记录继续意愿，不得把未知项标记为已确认。不要生成题目。
""".format()


class ModelError(RuntimeError):
    """The configured model could not produce a usable response."""


@dataclass
class ModelConfig:
    id: str
    name: str
    provider: str
    base_url: str | None
    model_name: str
    api_key: str | None


def _extract_json(text: str) -> dict[str, Any]:
    cleaned = text.strip()
    if cleaned.startswith("```"):
        cleaned = re.sub(r"^```[a-zA-Z]*\s*", "", cleaned)
        cleaned = re.sub(r"\s*```$", "", cleaned)
    try:
        value = json.loads(cleaned)
    except json.JSONDecodeError:
        start = cleaned.find("{")
        end = cleaned.rfind("}")
        if start < 0 or end <= start:
            raise ModelError("模型返回的内容不是可解析的 JSON") from None
        try:
            value = json.loads(cleaned[start : end + 1])
        except json.JSONDecodeError as exc:
            raise ModelError("模型返回的内容不是可解析的 JSON") from exc
    if not isinstance(value, dict):
        raise ModelError("模型返回的 JSON 不是对象")
    return value


def _normalise_understanding(value: dict[str, Any], *, model_name: str) -> dict[str, Any]:
    def as_list(key: str) -> list[Any]:
        raw = value.get(key, [])
        if not isinstance(raw, list):
            raise ModelError(f"模型返回的 {key} 不是数组")
        return raw

    summary = value.get("summary")
    if not isinstance(summary, str) or not summary.strip():
        raise ModelError("模型返回的理解缺少 summary")
    result = {
        "summary": summary.strip(),
        "agent_or_flow": str(value.get("agent_or_flow", "") or "").strip(),
        "known": as_list("known"),
        "inferred": as_list("inferred"),
        "unknowns": as_list("unknowns"),
        "sufficient": bool(value.get("sufficient", False)),
        "sufficient_reason": str(value.get("sufficient_reason", "") or "").strip(),
        "model": model_name,
    }
    return result


def _stub_understanding(
    project_name: str,
    context_text: str,
    sources: list[dict[str, Any]],
    current: dict[str, Any] | None,
) -> dict[str, Any]:
    files: list[str] = []
    supplements: list[str] = []
    for line in context_text.splitlines():
        if line.startswith("### FILE "):
            rest = line[len("### FILE ") :]
            files.append(rest.split(" (sha256", 1)[0])
        elif line.startswith("### SUPPLEMENT "):
            supplements.append(line[len("### SUPPLEMENT ") :])
    known = []
    for path in files[:5]:
        known.append(
            {
                "text": f"项目范围包含 {path}；已记录内容指纹，可回溯到具体快照。",
                "source": path,
            }
        )
    for title in supplements[:3]:
        known.append(
            {
                "text": f"补充资料「{title}」已纳入本次分析；内容指纹已记录。",
                "source": f"supplement:{title}",
            }
        )
    if not known:
        known.append(
            {
                "text": "当前选择范围内没有可读取的文本资料。",
                "source": "snapshot",
            }
        )
    inferred = [
        {
            "text": "从文件命名推测项目包含代码与说明文档，但尚未验证实际启动方式。",
            "basis": "所选路径的扩展名与目录结构",
        }
    ]
    if any(path.endswith((".md", ".txt", ".rst")) for path in files):
        inferred.append(
            {
                "text": "资料中可能包含业务规则或验收说明，仍需逐条对照代码确认。",
                "basis": "存在说明性文档",
            }
        )
    unknowns = [
        {
            "text": "被测 Agent 的交互类型（对话、文件、API、事件或异步流程）尚未确认。",
            "why": "决定后续任务输入和证据形式。",
        },
        {
            "text": "业务验收标准与不可接受结果尚未在资料中明确。",
            "why": "决定题目和评分规则的判定口径。",
        },
    ]
    result = {
        "summary": f"这是本地项目「{project_name}」的初步理解：当前只基于用户选定的 {len(files)} 份资料，未验证运行方式。",
        "agent_or_flow": "资料显示为软件项目；Agent 或业务流程的入口仍需用户确认或进一步阅读代码。",
        "known": known,
        "inferred": inferred,
        "unknowns": unknowns,
        "sufficient": False,
        "sufficient_reason": "关键业务规则和交互方式仍在未知项中；需要用户补充资料或明确继续。",
        "model": "stub",
    }
    if current:
        # Preserve facts the user has already corrected in this session.
        for key in ("known", "unknowns"):
            previous = current.get(key) or []
            if isinstance(previous, list):
                for item in previous:
                    if item not in result[key]:
                        result[key].append(item)
        result["summary"] = current.get("summary") or result["summary"]
        result["sufficient"] = bool(current.get("sufficient", False))
        result["sufficient_reason"] = current.get("sufficient_reason") or result["sufficient_reason"]
    return result


class ModelGateway:
    def __init__(self, config: ModelConfig | None, *, timeout: float = 60.0) -> None:
        self.config = config
        self.timeout = timeout

    @property
    def name(self) -> str:
        if not self.config:
            return "unconfigured"
        if self.config.provider == "stub":
            return "stub"
        return f"{self.config.provider}:{self.config.model_name}"

    def _request_chat(self, messages: list[dict[str, str]]) -> dict[str, Any]:
        assert self.config is not None
        if not self.config.base_url:
            raise ModelError("模型配置缺少服务地址")
        url = self.config.base_url.rstrip("/") + "/chat/completions"
        headers = {"Content-Type": "application/json"}
        if self.config.api_key:
            headers["Authorization"] = f"Bearer {self.config.api_key}"
        body = {
            "model": self.config.model_name,
            "messages": messages,
            "temperature": 0.1,
        }
        try:
            response = httpx.post(
                url,
                json=body,
                headers=headers,
                timeout=self.timeout,
                trust_env=False,
            )
        except httpx.HTTPError as exc:
            raise ModelError(
                f"模型服务请求失败：{redact_text(str(exc))}"
            ) from exc
        if response.status_code >= 400:
            detail = redact_text(response.text[:300])
            raise ModelError(f"模型服务返回 {response.status_code}：{detail}")
        try:
            payload = response.json()
            content = payload["choices"][0]["message"]["content"]
        except (ValueError, KeyError, IndexError, TypeError) as exc:
            raise ModelError("模型服务响应缺少 choices[0].message.content") from exc
        if not isinstance(content, str):
            raise ModelError("模型返回内容不是文本")
        return _extract_json(content)

    def analyze(
        self,
        *,
        project_name: str,
        context_text: str,
        sources: list[dict[str, Any]],
        supplemental: list[dict[str, str]],
        current: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        if self.config is None:
            raise ModelError("项目尚未配置模型，无法分析")
        if self.config.provider == "stub":
            return _normalise_understanding(
                _stub_understanding(project_name, context_text, sources, current),
                model_name="stub",
            )
        prompt = (
            f"项目名称：{project_name}\n"
            f"资料范围：{len(sources)} 项，内容指纹已随资料给出。\n\n"
            f"{context_text}\n\n"
            "请给出初步理解。"
        )
        value = self._request_chat(
            [
                {"role": "system", "content": SYSTEM_PROMPT},
                {"role": "user", "content": prompt},
            ]
        )
        return _normalise_understanding(value, model_name=self.name)

    def discuss(
        self,
        *,
        project_name: str,
        context_text: str,
        current: dict[str, Any],
        history: list[dict[str, str]],
        user_message: str,
    ) -> dict[str, Any]:
        if self.config is None:
            raise ModelError("项目尚未配置模型，无法继续会话")
        if self.config.provider == "stub":
            return _stub_discuss(current, user_message)
        prompt = (
            f"项目名称：{project_name}\n\n当前理解（JSON）：\n"
            f"{json.dumps(current, ensure_ascii=False)}\n\n"
            f"资料摘要：\n{context_text}\n\n"
            f"最近对话：\n{json.dumps(history[-6:], ensure_ascii=False)}\n\n"
            f"用户最新消息：{user_message}\n\n请输出 JSON。"
        )
        value = self._request_chat(
            [
                {"role": "system", "content": CHAT_SYSTEM_PROMPT},
                {"role": "user", "content": prompt},
            ]
        )
        reply = value.get("reply")
        if not isinstance(reply, str) or not reply.strip():
            raise ModelError("模型回复缺少 reply")
        understanding = value.get("understanding")
        if not isinstance(understanding, dict):
            understanding = current
        understanding = _normalise_understanding(understanding, model_name=self.name)
        return {
            "reply": reply.strip(),
            "continue_requested": bool(value.get("continue_requested", False)),
            "understanding": understanding,
            "direction_update": str(value.get("direction_update", "") or "").strip(),
            "model": self.name,
        }

    def test_connection(self) -> tuple[bool, str]:
        if self.config is None:
            return False, "未配置模型"
        if self.config.provider == "stub":
            return True, "确定性替身可用（不调用真实模型，不代表模型质量）"
        if not self.config.base_url:
            return False, "缺少服务地址"
        try:
            response = httpx.get(
                self.config.base_url.rstrip("/") + "/models",
                headers=(
                    {"Authorization": f"Bearer {self.config.api_key}"}
                    if self.config.api_key
                    else {}
                ),
                timeout=min(self.timeout, 20),
                trust_env=False,
            )
        except httpx.HTTPError as exc:
            return False, f"连接失败：{redact_text(str(exc))}"
        if response.status_code == 200:
            return True, "连接成功"
        if response.status_code in (401, 403):
            return False, f"认证失败（HTTP {response.status_code}）"
        return False, f"服务返回 HTTP {response.status_code}"


def _stub_discuss(current: dict[str, Any], user_message: str) -> dict[str, Any]:
    text = user_message.strip()
    understanding = json.loads(json.dumps(current, ensure_ascii=False))
    continue_requested = any(
        keyword in text for keyword in ("继续", "开始出题", "进入下一步", "可以设计")
    )
    sufficient = bool(understanding.get("sufficient", False))
    if "依据足够" in text:
        sufficient = True
        understanding["sufficient_reason"] = "用户声明依据足够；未知项仍保留，等待后续阶段核对。"
    if text.startswith("纠正：") or text.startswith("纠正:"):
        corrected = text.split("：", 1)[-1].split(":", 1)[-1].strip()
        understanding["summary"] = corrected or understanding.get("summary", "")
        understanding["known"] = list(understanding.get("known") or []) + [
            {"text": f"用户纠正：{corrected}", "source": "会话"}
        ]
        understanding["sufficient_reason"] = (
            "用户提供了纠正，但尚未确认关键未知项；继续保留未知项。"
        )
    if sufficient:
        understanding["sufficient"] = True
    reply = (
        "已记录。这不会把未知业务规则自动标记为已确认。"
        if continue_requested
        else "已收到。你可以补充资料、纠正理解，或说明希望评测的方向。"
    )
    if text.startswith("纠正：") or text.startswith("纠正:"):
        reply = "已按你的纠正更新理解；原推断仍保留为推断，未知项没有自动关闭。"
    return {
        "reply": reply,
        "continue_requested": continue_requested,
        "understanding": understanding,
        "direction_update": "",
        "model": "stub",
    }
