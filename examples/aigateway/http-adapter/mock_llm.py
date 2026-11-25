"""Deterministic OpenAI-compatible mock used by the ai-gateway demo.

It is intentionally narrow: it recognizes the demo utterances and returns one
tool call or a final answer, so the real Handler still owns session, audit and
confirmation behavior.
"""

import json
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer


def _last_user(messages):
    for message in reversed(messages):
        if message.get("role") == "user":
            return str(message.get("content") or "")
    return ""


def _tool(name, arguments):
    return {
        "role": "assistant",
        "content": "",
        "tool_calls": [{
            "id": "call_1",
            "type": "function",
            "function": {"name": name, "arguments": json.dumps(arguments)},
        }],
    }


def decide(messages):
    tool_results = [str(m.get("content") or "") for m in messages if m.get("role") == "tool"]
    if tool_results:
        result = tool_results[-1]
        if "退款成功" in result or "退回" in result:
            return {"role": "assistant", "content": result}
        if "取消" in result:
            return {"role": "assistant", "content": "已取消，本次没有执行退款。"}
        if "余额" in result or "2000" in result:
            return {"role": "assistant", "content": "当前现金余额 ¥2000.00。"}
        return {"role": "assistant", "content": "已根据工具结果完成处理。"}
    text = _last_user(messages)
    if "然后" in text or "顺便" in text:
        return {"role": "assistant", "content": "请分开说明查询和退款需求，我不能同时处理。"}
    if "租户" in text:
        return {"role": "assistant", "content": "无法操作其他租户。"}
    if "退" in text and "5000" in text:
        return _tool("refund_recharge", {"amount_money": 5000})
    if "退" in text and "100" in text:
        return _tool("refund_recharge", {"amount_money": 100})
    if "退" in text:
        return {"role": "assistant", "content": "请提供退款金额或订单号。"}
    if "充" in text:
        return {"role": "assistant", "content": "请告诉我充值金额。"}
    if "9999" in text or "余额" in text or "多少钱" in text or "账户" in text:
        return _tool("get_balance", {})
    return {"role": "assistant", "content": "请说明你要办理的业务。"}


class Handler(BaseHTTPRequestHandler):
    def do_POST(self):
        length = int(self.headers.get("content-length", "0"))
        body = json.loads(self.rfile.read(length) or b"{}")
        payload = {
            "id": "mock-1",
            "model": "mock",
            "choices": [{"index": 0, "message": decide(body.get("messages") or []), "finish_reason": "stop"}],
            "usage": {"prompt_tokens": 10, "completion_tokens": 5, "total_tokens": 15},
        }
        encoded = json.dumps(payload, ensure_ascii=False).encode()
        self.send_response(200)
        self.send_header("content-type", "application/json")
        self.send_header("content-length", str(len(encoded)))
        self.end_headers()
        self.wfile.write(encoded)

    def log_message(self, *args):
        pass


if __name__ == "__main__":
    ThreadingHTTPServer(("127.0.0.1", 9300), Handler).serve_forever()
