"""Local deterministic Chat Completions endpoint, exclusively for DAG demos.

Only returns SubmitHandover/SubmitVerdict calls. It never writes application
storage, invokes a real model, accesses files, or executes business actions.
"""
import json
import time
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from uuid import uuid4

from scenarios import SCENARIOS, calculate, find_node, model_id


def message_text(message):
    content = message.get("content") or ""
    if isinstance(content, str):
        return content
    return "\n".join(p.get("text", "") for p in content if isinstance(p, dict))


def bound_inputs(messages):
    for message in reversed(messages):
        text = message_text(message)
        if "Bound node inputs:" in text:
            tail = text.split("Bound node inputs:", 1)[1]
            return json.JSONDecoder().raw_decode(tail[tail.index("{"):])[0]
    return {}


class Handler(BaseHTTPRequestHandler):
    def log_message(self, *_args):
        pass

    def json_response(self, status, payload):
        body = json.dumps(payload, ensure_ascii=False).encode()
        self.send_response(status)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def do_GET(self):
        if self.path == "/health":
            return self.json_response(200, {"status": "ok", "mode": "local-simulation"})
        if self.path == "/v1/models":
            ids = [model_id(s["key"], n["id"]) for s in SCENARIOS for n in s["nodes"]]
            ids.append("dag-demo-daily-quality-review")
            return self.json_response(200, {"object": "list", "data": [{"id": i, "object": "model", "owned_by": "local-demo"} for i in ids]})
        self.json_response(404, {"error": {"message": "Unknown demo endpoint"}})

    def do_POST(self):
        if self.path != "/v1/chat/completions":
            return self.json_response(404, {"error": {"message": "Unknown demo endpoint"}})
        if self.headers.get("Authorization") != "Bearer local-sop-demo-only":
            return self.json_response(401, {"error": {"message": "Local demo credential required"}})
        try:
            size = int(self.headers.get("Content-Length", "0"))
            if not 0 < size <= 4 * 1024 * 1024:
                return self.json_response(413, {"error": {"message": "Invalid demo request size"}})
            body = json.loads(self.rfile.read(size))
            model = body.get("model", "")
            reviewing = model == "dag-demo-daily-quality-review"
            scenario, node = find_node(model)
            if not reviewing and node is None:
                return self.json_response(400, {"error": {"message": "Choose a dag-demo model for this local simulator"}})
            messages = body.get("messages", [])
            texts = "\n".join(message_text(m) for m in messages)
            tool_name = "SubmitVerdict" if reviewing else "SubmitHandover"
            submitted = any(t.get("function", {}).get("name") == tool_name for m in messages if m.get("role") == "assistant" for t in m.get("tool_calls", []) or [])
            available = {t.get("function", {}).get("name") for t in body.get("tools", [])}
            call = None
            delay = 0
            if not submitted and tool_name in available:
                if reviewing:
                    passed = '"validation_status": "recovered"' in texts
                    args = {"passed": passed, "message": "修复后的虚拟金额完整，质量校验通过。" if passed else "演示故障：南城店 paid_amount 缺失。请点击此节点的“只重试此节点”；成功的准备和指标分支将保留。"}
                    delay = 1
                else:
                    inputs = bound_inputs(messages)
                    data = calculate(scenario, node["id"], inputs, retry="Your last attempt was not accepted:" in texts)
                    outputs = {"summary": node["subject"] + "：本地模拟执行完成", "data_source": "虚构业务数据 / 本地确定性模拟模型", "data": data, "received_inputs": inputs}
                    args = {"handover": "【本地模拟演示，非真实业务结论】\n" + node["subject"] + "\n" + json.dumps(data, ensure_ascii=False, indent=2), "outputs": outputs, "artifact_paths": []}
                    delay = node["delay"]
                call = {"id": "call_" + uuid4().hex, "type": "function", "function": {"name": tool_name, "arguments": json.dumps(args, ensure_ascii=False)}}
            content = "【本地模拟模型】已提交此节点结果，可在 SOP 运行详情查看输出、依赖关系与尝试历史。" if submitted else "【本地模拟模型】正在处理虚构业务数据。"
            self.respond(body, model, content, call, delay)
            print(json.dumps({"model": model, "action": tool_name if call else "finish"}), flush=True)
        except (KeyError, ValueError, TypeError) as exc:
            self.json_response(400, {"error": {"message": "Demo input mismatch: " + str(exc)}})
        except (BrokenPipeError, ConnectionResetError):
            pass

    def respond(self, body, model, content, call, delay):
        completion_id = "chatcmpl-demo-" + uuid4().hex
        created = int(time.time())
        if not body.get("stream"):
            time.sleep(delay)
            message = {"role": "assistant", "content": content}
            if call:
                message["tool_calls"] = [call]
            return self.json_response(200, {"id": completion_id, "object": "chat.completion", "created": created, "model": model, "choices": [{"index": 0, "message": message, "finish_reason": "tool_calls" if call else "stop"}], "usage": {"prompt_tokens": 0, "completion_tokens": 0, "total_tokens": 0}})
        self.send_response(200)
        self.send_header("Content-Type", "text/event-stream")
        self.send_header("Cache-Control", "no-cache")
        self.send_header("Connection", "close")
        self.end_headers()

        def emit(delta, finish=None):
            chunk = {"id": completion_id, "object": "chat.completion.chunk", "created": created, "model": model, "choices": [{"index": 0, "delta": delta, "finish_reason": finish}]}
            self.wfile.write(("data: " + json.dumps(chunk, ensure_ascii=False) + "\n\n").encode())
            self.wfile.flush()

        emit({"role": "assistant", "content": content})
        time.sleep(delay)
        if call:
            emit({"tool_calls": [{"index": 0, **call}]})
        emit({}, "tool_calls" if call else "stop")
        self.wfile.write(b"data: [DONE]\n\n")
        self.wfile.flush()
        self.close_connection = True


if __name__ == "__main__":
    print("Local SOP demo simulator listening on :8080 (no real model calls)", flush=True)
    ThreadingHTTPServer(("0.0.0.0", 8080), Handler).serve_forever()
