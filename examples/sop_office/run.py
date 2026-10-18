"""Create and run office SOPs through the account's real DeepSeek model."""

import argparse
import getpass
import json
import os
import time
import urllib.error
import urllib.request
from pathlib import Path
from urllib.parse import urlencode, urlsplit

from scenarios import SCENARIOS


class Client:
    def __init__(self, base):
        self.base = base.rstrip("/")
        self.token = None

    def call(self, method, path, body=None, retries=5):
        headers = {"Content-Type": "application/json"}
        if self.token:
            headers["Authorization"] = "Bearer " + self.token
        request = urllib.request.Request(
            self.base + path,
            data=json.dumps(body, ensure_ascii=False).encode() if body is not None else None,
            headers=headers,
            method=method,
        )
        try:
            with urllib.request.urlopen(request, timeout=60) as response:
                return json.load(response) if response.status != 204 else None
        except urllib.error.HTTPError as exc:
            raise RuntimeError(f"{method} {path}: HTTP {exc.code}: {exc.read().decode()[:1200]}") from None
        except (urllib.error.URLError, ConnectionError, TimeoutError):
            if method == "GET" and retries:
                time.sleep(2)
                return self.call(method, path, body, retries=retries - 1)
            raise


AUTHOR = """你是轻办公流程的执行者，使用当前配置的真实模型分析实际给定的材料。
优先完成当前节点的任务，而不是执行整条流程。运行输入若提供了新的业务材料，以新的材料为准；否则使用流程描述中的默认素材。
只根据材料陈述事实，推断须标注；缺失的信息写待确认，不伪造责任人、承诺、时间、金额、执行结果或来源。
所有必需材料已在当前会话及 Bound node inputs 中，不需要读取其他文件、访问网络、运行系统命令或调用其他智能体。
分析完成必须调用 SubmitHandover，handover 写简洁中文交接摘要，outputs 严格符合给定 JSON Schema，尤其将节点数据放到 data 对象中。
不需要创建工作区文件，最终文档完整放在 data.report_markdown 字符串中。artifact_paths 使用空数组。
如果当前任务附带上一轮的审核意见，重新核对材料并修正具体问题后提交；不能只口头说已修复。
成功提交后用一句话结束，不要再次提交或调用其他工具。"""

REVIEWER = """你是独立质量审核员，使用真实模型逐项核对本节点的标准和原始材料。
阅读本次 submission 和上游交接，检查事实、计算、完整性、逻辑及承诺边界。只基于实际内容判断，不预设通过或失败。
若只有表述风格、接近目标的字数等非实质差异，给出通过；若有事实错误、计算错误、关键遗漏或违反明确要求，则拒绝并说明原始编号、错误位置、原因和可执行修复建议。
不需要读取文件、访问网络或执行命令。必须调用 SubmitVerdict(passed, message) 记录真实判断；成功后简短结束，不要再次提交。"""


def ensure_agent(client, name, prompt, agents):
    existing = next((a for a in agents if a["data"]["name"] == name), None)
    if existing:
        return existing["id"]
    return client.call("POST", "/agent/", {
        "name": name,
        "system_prompt": prompt,
        "chat_config": {"react_config": {"max_iters": 12, "max_tool_calls_per_reply": 10}},
    })["agent_id"]


def provision(client, credential_id, model):
    agents = client.call("GET", "/agent/")["agents"]
    author = ensure_agent(client, "轻办公执行员 · DeepSeek", AUTHOR, agents)
    reviewer = ensure_agent(client, "轻办公质量审核员 · DeepSeek", REVIEWER, agents)
    existing = client.call("GET", "/sop/")["sops"]
    result = []
    for scenario in SCENARIOS:
        data = {
            "name": scenario["name"],
            "description": scenario["description"] + "\n\n默认任务素材：\n" + scenario["input"],
            "execution_mode": "dag",
            "max_concurrency": 2,
            "workspace_grain": "per_node",
            "steps": [],
            "session_settings": {},
        }
        for node in scenario["nodes"]:
            session_key = scenario["key"] + "-" + node["id"]
            data["session_settings"][session_key] = {
                "chat_model_config": {
                    "type": "deepseek_chat", "credential_id": credential_id,
                    "model": model, "parameters": {"max_tokens": 6000, "thinking_enable": False},
                },
                "permission_mode": "default",
            }
            schema = {
                "type": "object",
                "properties": {
                    "summary": {"type": "string"},
                    "data": {"type": "object", "properties": {k: {"type": v} for k, v in node["fields"].items()}, "required": list(node["fields"])},
                },
                "required": ["summary", "data"],
            }
            step = {
                "id": node["id"], "subject": node["subject"], "description": node["description"],
                "depends_on": node.get("depends_on", []), "input_bindings": node.get("bindings", {}),
                "output_schema": schema,
                "executor": {"agent_id": author, "session_key": session_key},
                "max_attempts": 2, "timeout_seconds": 360, "retry_delay_seconds": 3,
            }
            if node.get("review"):
                review_key = session_key + "-review"
                step["verifier"] = {"type": "agent", "agent": {"agent_id": reviewer, "session_key": review_key}, "criteria": node["review"]}
                data["session_settings"][review_key] = json.loads(json.dumps(data["session_settings"][session_key]))
            data["steps"].append(step)
        record = next((s for s in existing if s["data"]["name"] == scenario["name"]), None)
        if record is None:
            sop_id = client.call("POST", "/sop/", {"data": data})["sop_id"]
        else:
            sop_id = record["id"]
            stored_settings = record["data"]["session_settings"]
            if any(stored_settings.get(key, {}).get(field) != value for key, settings in data["session_settings"].items() for field, value in settings.items()):
                raise RuntimeError("An existing office SOP has different model settings; review it before rerunning: " + sop_id)
        print(json.dumps({"sop": scenario["name"], "id": sop_id, "model": model}, ensure_ascii=False), flush=True)
        result.append((scenario, sop_id))
    return result


def ensure_run(client, scenario, sop_id):
    marker = "[real-office-v1:" + scenario["key"] + "]"
    for run in client.call("GET", "/sop/runs?" + urlencode({"sop_id": sop_id}))["runs"]:
        if marker in json.dumps(run["state"]["inputs"], ensure_ascii=False):
            return run
    return client.call("POST", f"/sop/{sop_id}/runs", {"inputs": [{"name": "user", "role": "user", "content": [{"type": "text", "text": scenario["input"] + "\n" + marker}]}]})


def export_record(root, scenario, run):
    directory = root / run["id"]
    directory.mkdir(parents=True, exist_ok=True)
    (directory / "run.json").write_text(json.dumps(run, ensure_ascii=False, indent=2), encoding="utf-8")
    final = run["state"]["steps"][-1]
    report = final.get("outputs", {}).get("data", {}).get("report_markdown")
    filename = scenario["file"]
    if not report and run["state"]["phase"] == "failed" and final.get("attempts"):
        report = final["attempts"][-1].get("outputs", {}).get("data", {}).get("report_markdown")
        filename = Path(filename).stem + "（审核未通过）.md"
        earlier_export = directory / scenario["file"]
        known_drafts = [a.get("outputs", {}).get("data", {}).get("report_markdown") for a in final["attempts"]]
        if earlier_export.exists() and earlier_export.read_text(encoding="utf-8") in known_drafts:
            earlier_export.unlink()
    if report:
        (directory / filename).write_text(report, encoding="utf-8")
    return {"id": run["id"], "scenario": scenario["name"], "phase": run["state"]["phase"], "document": str(directory / filename) if report else None, "attempts": {s["node_id"]: len(s["attempts"]) for s in run["state"]["steps"]}}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--base-url", default="http://127.0.0.1:8001")
    parser.add_argument("--username", default="test")
    parser.add_argument("--credential-id")
    parser.add_argument("--model", default="deepseek-v4-flash")
    parser.add_argument("--start", action="store_true")
    parser.add_argument("--output-dir", type=Path, default=Path("outputs/sop_office"))
    args = parser.parse_args()
    client = Client(args.base_url)
    password = os.getenv("SOP_OFFICE_PASSWORD") or getpass.getpass("Account password: ")
    login = client.call("POST", "/auth/login", {"username": args.username, "password": password})
    client.token = login["access_token"]
    candidates = [c for c in client.call("GET", "/credential/")["credentials"] if c["data"].get("type") == "deepseek_credential"]
    if args.credential_id:
        candidates = [c for c in candidates if c["id"] == args.credential_id]
    if len(candidates) != 1:
        raise RuntimeError("Choose exactly one real DeepSeek credential with --credential-id")
    credential = candidates[0]
    print(json.dumps({"account": login["user"]["username"], "provider": credential["data"]["type"], "endpoint_host": urlsplit(credential["data"].get("base_url") or "https://api.deepseek.com").hostname, "model": args.model}, ensure_ascii=False), flush=True)
    definitions = provision(client, credential["id"], args.model)
    if not args.start:
        return
    pending = {s["key"]: (s, ensure_run(client, s, sop_id)["id"]) for s, sop_id in definitions}
    previous = {}
    completed = []
    deadline = time.monotonic() + 1800
    while pending and time.monotonic() < deadline:
        for key, (scenario, run_id) in list(pending.items()):
            run = client.call("GET", "/sop/runs/" + run_id)
            state = run["state"]
            signature = [(n["phase"], len(n["attempts"]), n.get("error")) for n in state["steps"]]
            if signature != previous.get(key):
                print(json.dumps({"scenario": key, "run": run_id, "phase": state["phase"], "nodes": [{"id": n["node_id"], "phase": n["phase"], "attempts": len(n["attempts"]), "error": n.get("error")} for n in state["steps"]]}, ensure_ascii=False), flush=True)
                previous[key] = signature
                export_record(args.output_dir, scenario, run)
            if state["phase"] in ("completed", "failed", "cancelled"):
                completed.append(export_record(args.output_dir, scenario, run))
                del pending[key]
        if pending:
            time.sleep(3)
    if pending:
        raise RuntimeError("Still executing; inspect the persisted runs: " + str(pending))
    print(json.dumps({"results": completed}, ensure_ascii=False, indent=2), flush=True)


if __name__ == "__main__":
    main()
