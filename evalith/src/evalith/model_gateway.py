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
import urllib.parse
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


def _scrub_known_secret(text: str, secret: str | None) -> str:
    """Remove pattern-shaped and literally configured credentials from text."""
    cleaned = redact_text(text)
    if secret:
        variants = {secret, secret.strip(), urllib.parse.quote(secret, safe="")}
        for variant in variants:
            if variant:
                cleaned = cleaned.replace(variant, "[REDACTED]")
    return cleaned


def _boolean_field(value: dict[str, Any], name: str, *, default: bool = False) -> bool:
    """Accept only JSON booleans.

    A malformed ``"false"`` string must never be coerced into authorization or
    sufficiency; raise so the failure is visible and the gate stays closed.
    """
    if name not in value:
        return default
    actual = value[name]
    if not isinstance(actual, bool):
        raise ModelError(f"模型返回的 {name} 必须是布尔值，收到 {type(actual).__name__}")
    return actual


def _normalise_items(
    key: str, raw: Any, *, require_source: bool = False
) -> list[dict[str, str]]:
    """Validate model-generated array elements before they reach the UI or DB.

    Each item must have a non-empty string ``text``.  Allowed metadata fields
    are strings; ``None`` is dropped.  Anything else is a visible model error,
    not a value the workspace later dereferences.
    """
    if not isinstance(raw, list):
        raise ModelError(f"模型返回的 {key} 不是数组")
    allowed = {"known": "source", "inferred": "basis", "unknowns": "why"}
    metadata = allowed[key]
    normalised: list[dict[str, str]] = []
    for index, item in enumerate(raw):
        if isinstance(item, str):
            text = item.strip()
            if not text:
                raise ModelError(f"模型返回的 {key}[{index}] 缺少 text")
            if require_source:
                raise ModelError(f"模型返回的 {key}[{index}] 缺少来源")
            normalised.append({"text": text})
            continue
        if not isinstance(item, dict):
            raise ModelError(f"模型返回的 {key}[{index}] 不是对象或字符串")
        text = item.get("text")
        if not isinstance(text, str) or not text.strip():
            raise ModelError(f"模型返回的 {key}[{index}] 缺少非空 text")
        entry = {"text": text.strip()}
        value = item.get(metadata)
        if value is not None:
            if not isinstance(value, str):
                raise ModelError(f"模型返回的 {key}[{index}].{metadata} 必须是字符串")
            entry[metadata] = value.strip()
        if require_source and not entry.get("source"):
            raise ModelError(f"模型返回的 {key}[{index}] 缺少非空来源")
        normalised.append(entry)
    return normalised


def _normalise_understanding(value: dict[str, Any], *, model_name: str) -> dict[str, Any]:
    summary = value.get("summary")
    if not isinstance(summary, str) or not summary.strip():
        raise ModelError("模型返回的理解缺少 summary")
    agent_or_flow = value.get("agent_or_flow", "")
    if agent_or_flow is None:
        agent_or_flow = ""
    if not isinstance(agent_or_flow, str):
        raise ModelError("模型返回的 agent_or_flow 必须是字符串")
    sufficient_reason = value.get("sufficient_reason", "")
    if sufficient_reason is None:
        sufficient_reason = ""
    if not isinstance(sufficient_reason, str):
        raise ModelError("模型返回的 sufficient_reason 必须是字符串")
    return {
        "summary": summary.strip(),
        "agent_or_flow": agent_or_flow.strip(),
        "known": _normalise_items(
            "known", value.get("known", []), require_source=True
        ),
        "inferred": _normalise_items("inferred", value.get("inferred", [])),
        "unknowns": _normalise_items("unknowns", value.get("unknowns", [])),
        "sufficient": _boolean_field(value, "sufficient"),
        "sufficient_reason": sufficient_reason.strip(),
        "model": model_name,
    }


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

    def _scrub(self, text: str) -> str:
        return _scrub_known_secret(
            text, self.config.api_key if self.config is not None else None
        )

    def scrub(self, text: str) -> str:
        """Remove pattern-shaped and literally configured credentials."""
        return self._scrub(text)

    def withdraws_continuation(self, text: str) -> bool:
        return any(marker in text for marker in WITHDRAWAL_MARKERS)

    def _scrub_value(self, value: Any) -> Any:
        if isinstance(value, str):
            return self._scrub(value)
        if isinstance(value, list):
            return [self._scrub_value(item) for item in value]
        if isinstance(value, dict):
            return {key: self._scrub_value(item) for key, item in value.items()}
        return value

    def _request_chat(self, messages: list[dict[str, str]]) -> dict[str, Any]:
        assert self.config is not None
        if not self.config.base_url:
            raise ModelError("模型配置缺少服务地址")
        url = self.config.base_url.rstrip("/") + "/chat/completions"
        headers = {"Content-Type": "application/json"}
        if self.config.api_key:
            headers["Authorization"] = f"Bearer {self.config.api_key}"
        # Every model-input route is redacted again here, independent of the
        # caller, so a new caller cannot bypass the credential boundary.
        safe_messages = [
            {"role": item["role"], "content": self._scrub(item["content"])}
            for item in messages
        ]
        body = {
            "model": self.config.model_name,
            "messages": safe_messages,
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
            raise ModelError(f"模型服务请求失败：{self._scrub(str(exc))}") from exc
        if response.status_code >= 400:
            # Scrub the complete body first; truncating first can leave a
            # configured key's prefix in the persisted error.
            detail = self._scrub(response.text)[:300]
            raise ModelError(f"模型服务返回 {response.status_code}：{detail}")
        try:
            payload = response.json()
            content = payload["choices"][0]["message"]["content"]
        except (ValueError, KeyError, IndexError, TypeError) as exc:
            raise ModelError("模型服务响应缺少 choices[0].message.content") from exc
        if not isinstance(content, str):
            raise ModelError("模型返回内容不是文本")
        parsed = _extract_json(content)
        # A successful provider response may echo a bare configured key in
        # summary/reply/structured fields.  Scrub decoded strings recursively
        # before returning them to the service for persistence.
        return self._scrub_value(parsed)

    def analyze(
        self,
        *,
        project_name: str,
        context_text: str,
        sources: list[dict[str, Any]],
        supplemental: list[dict[str, str]],
        current: dict[str, Any] | None = None,
        history: list[dict[str, str]] | None = None,
    ) -> dict[str, Any]:
        if self.config is None:
            raise ModelError("项目尚未配置模型，无法分析")
        if self.config.provider == "stub":
            return _normalise_understanding(
                _stub_understanding(project_name, context_text, sources, current),
                model_name="stub",
            )
        current_payload = (
            json.dumps(current, ensure_ascii=False) if current is not None else "无"
        )
        history_payload = json.dumps((history or [])[-10:], ensure_ascii=False)
        prompt = (
            f"项目名称：{redact_text(project_name)}\n"
            f"资料范围：{len(sources)} 项，内容指纹已随资料给出。\n\n"
            f"当前理解（JSON）：\n{current_payload}\n\n"
            f"最近会话（JSON）：\n{history_payload}\n\n"
            f"{context_text}\n\n"
            "请重新分析项目。必须保留用户此前的纠正和已表达的评测方向；"
            "不要把用户纠正改写成未经验证的推断。"
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
            f"项目名称：{redact_text(project_name)}\n\n当前理解（JSON）：\n"
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
        raw_understanding = value.get("understanding")
        understanding_supplied = isinstance(raw_understanding, dict)
        understanding = (
            _normalise_understanding(raw_understanding, model_name=self.name)
            if understanding_supplied
            else _normalise_understanding(current, model_name=self.name)
        )
        _boolean_field(value, "continue_requested")  # reject malformed fields
        # Explicit user consent is decided by the message, identically for both
        # providers.  The provider's boolean is validated but must not invent
        # consent from a descriptive/correction message.
        continue_requested = _affirmative_continuation(user_message)
        # Preserve a validated model sufficiency judgement during ordinary
        # discussion. Only an explicit retraction/contradiction revokes it;
        # requiring the user to repeat "依据足够" would override the model.
        if understanding["sufficient"] and (
            _negates_sufficiency(user_message)
            or _is_conditional_statement(user_message)
            or (
                "足够" in user_message
                and _is_descriptive_statement(user_message)
            )
        ):
            understanding["sufficient"] = False
            understanding["sufficient_reason"] = (
                "用户明确表示依据仍不足或仅作描述；未知项保留，推进门保持关闭。"
            )
        return {
            "reply": reply.strip(),
            "continue_requested": continue_requested,
            "understanding": understanding,
            "understanding_supplied": understanding_supplied,
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
            return False, f"连接失败：{self._scrub(str(exc))}"
        if response.status_code == 200:
            return True, "连接成功"
        if response.status_code in (401, 403):
            return False, f"认证失败（HTTP {response.status_code}）"
        return False, f"服务返回 HTTP {response.status_code}"


NEGATION_MARKERS = (
    "不要",
    "不想",
    "先不",
    "还不能",
    "不能",
    "尚未",
    "还没",
    "别",
    "暂不",
    "不继续",
    "不开始",
    "不足以",
    "不觉得",
    "没有足够",
    "拒绝",
    "不同意",
    "反对",
    "不答应",
    "不愿意",
    "不可以",
    "不行",
    "不肯",
    "不打算",
    "不准备",
    "无意",
    "不情愿",
    "停止",
    "中止",
    "不许",
    "不准",
    "不应该",
    "不该",
    "不应",
    "不应当",
    "请勿",
    "切勿",
    "禁止",
    "请不",
    "请别",
)


def _has_negation(text: str) -> bool:
    return any(marker in text for marker in NEGATION_MARKERS)


NON_AFFIRMATIVE_MARKERS = (
    "?",
    "？",
    "如何",
    "什么",
    "哪些",
    "为什么",
    "是否",
    "能否",
    "可不可以",
    "会不会",
    "要不要",
    "该不该",
    "能不能",
    "好不好",
    "是否会",
    "是否要",
    "吗",
    "多少",
    "何时",
    "怎么",
    "解释",
    "说明",
    "讨论",
    "继续前",
    "继续之前",
    "如果继续",
    "若要继续",
)


def _is_non_affirmative(text: str) -> bool:
    return any(marker in text for marker in NON_AFFIRMATIVE_MARKERS)


def _first_keyword_outside_quotes(text: str, keyword: str) -> int | None:
    spans: list[tuple[int, int]] = []
    for left, right in (("“", "”"), ("\"", "\""), ("「", "」"), ("『", "』")):
        start = 0
        while True:
            opening = text.find(left, start)
            if opening < 0:
                break
            closing = text.find(right, opening + 1)
            if closing < 0:
                spans.append((opening, len(text)))
                break
            spans.append((opening, closing + 1))
            start = closing + 1
    position = 0
    while True:
        found = text.find(keyword, position)
        if found < 0:
            return None
        if not any(start <= found and found + len(keyword) <= end for start, end in spans):
            return found
        position = found + 1


def _keyword_outside_quotes(text: str, keyword: str) -> bool:
    return _first_keyword_outside_quotes(text, keyword) is not None


CONTINUATION_PHRASES = ("继续", "进入下一步", "开始出题", "开始设计", "进入下一阶段")
REQUEST_PREFIXES = (
    "我",
    "我会",
    "我同意",
    "我确认",
    "请",
    "可以",
    "确认",
    "同意",
    "那就",
    "我们",
    "现在",
    "好的",
    "好",
    "开始",
    "进入",
    "继续",
)
DESCRIPTIVE_MARKERS = (
    "按钮",
    "文案",
    "应为",
    "改为",
    "位于",
    "描述",
    "示例",
    "引用",
    "名称",
    "定义",
    "概念",
    "术语",
    "状态",
    "含义",
    "意思",
    "代表",
    "表示",
    "翻译",
    "英文",
    "中文",
    "转成",
    "复述",
    "改写",
)


CONDITIONAL_MARKERS = (
    "等",
    "才",
    "再",
    "如果",
    "假如",
    "若",
    "待",
    "暂时",
    "到时候",
    "确认后",
    "之前",
    "以后",
    "之后",
    "后继续",
    "之后再",
    "材料齐全",
    "齐全后",
    "完成后",
    "补充后",
    "准备后",
    "就绪后",
)

HESITATION_MARKERS = (
    "考虑",
    "想想",
    "研究",
    "决定",
    "评估",
    "再想想",
    "商量",
    "或许",
    "可能",
    "也许",
    "不确定",
    "尚未决定",
)

WITHDRAWAL_MARKERS = (
    "拒绝继续",
    "不继续",
    "不要继续",
    "不想继续",
    "不打算继续",
    "不准备继续",
    "停止继续",
    "取消继续",
    "撤回继续",
    "请勿继续",
    "切勿继续",
    "不应该继续",
    "不该继续",
    "不应继续",
    "不应当继续",
    "别继续",
)


def _is_conditional_statement(text: str) -> bool:
    return any(marker in text for marker in CONDITIONAL_MARKERS)


def _is_descriptive_statement(text: str) -> bool:
    return text.startswith(("纠正：", "纠正:")) or any(
        marker in text for marker in DESCRIPTIVE_MARKERS
    )


def _affirmative_continuation(text: str) -> bool:
    """Return True only for an explicit, non-descriptive continuation request."""
    stripped = text.strip()
    if not stripped:
        return False
    if _has_negation(stripped) or _is_non_affirmative(stripped):
        return False
    if _is_descriptive_statement(stripped) or _is_conditional_statement(stripped):
        return False
    if any(marker in stripped for marker in HESITATION_MARKERS):
        return False
    for phrase in CONTINUATION_PHRASES:
        index = _first_keyword_outside_quotes(stripped, phrase)
        if index is None:
            continue
        prefix = stripped[:index].strip(" ，,。.！!；;：:")
        suffix = stripped[index + len(phrase) :].strip(" ，,。.！!；;：:")
        if suffix not in ("", "吧", "了", "好"):
            continue
        if not prefix:
            return True
        if prefix in REQUEST_PREFIXES:
            return True
        if prefix.startswith(("请", "可以", "确认", "同意", "那就", "我们", "现在", "好的", "我会", "我同意", "我确认")):
            return True
    return False


def _affirmative_sufficiency(text: str) -> bool:
    stripped = text.strip()
    if not stripped or _has_negation(stripped) or _is_non_affirmative(stripped):
        return False
    if _is_descriptive_statement(stripped) or _is_conditional_statement(stripped):
        return False
    return _keyword_outside_quotes(stripped, "依据足够")


def _negates_sufficiency(text: str) -> bool:
    if any(
        marker in text
        for marker in (
            "还不能说依据足够",
            "依据不足",
            "不足以",
            "不能算足够",
            "不觉得足够",
            "尚未足够",
            "没有足够",
        )
    ):
        return True
    return "足够" in text and _has_negation(text)


def _stub_discuss(current: dict[str, Any], user_message: str) -> dict[str, Any]:
    text = user_message.strip()
    understanding = json.loads(json.dumps(current, ensure_ascii=False))
    continue_requested = _affirmative_continuation(text)
    sufficient = bool(understanding.get("sufficient", False))
    if _affirmative_sufficiency(text):
        sufficient = True
        understanding["sufficient_reason"] = "用户声明依据足够；未知项仍保留，等待后续阶段核对。"
    if _negates_sufficiency(text):
        sufficient = False
        understanding["sufficient_reason"] = (
            "用户明确表示依据仍不足；未知项保留，推进门保持关闭。"
        )
    if text.startswith("纠正：") or text.startswith("纠正:"):
        corrected = text.split("：", 1)[-1].split(":", 1)[-1].strip()
        understanding["summary"] = corrected or understanding.get("summary", "")
        understanding["known"] = list(understanding.get("known") or []) + [
            {"text": f"用户纠正：{corrected}", "source": "会话"}
        ]
        understanding["sufficient_reason"] = (
            "用户提供了纠正，但尚未确认关键未知项；继续保留未知项。"
        )
    # Persist both true and false; a retraction must close an already-open gate.
    understanding["sufficient"] = sufficient
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
        "understanding_supplied": True,
        "direction_update": "",
        "model": "stub",
    }
