"""Provision three DAG examples via normal, owner-scoped application APIs."""
import argparse
import getpass
import json
import os
import time
import urllib.error
import urllib.request

from scenarios import DEMO_PREFIX, SCENARIOS, model_id


class Client:
    def __init__(self, base_url):
        self.base_url = base_url.rstrip("/")
        self.token = None

    def call(self, method, path, body=None):
        headers = {"Content-Type": "application/json"}
        if self.token:
            headers["Authorization"] = "Bearer " + self.token
        data = json.dumps(body, ensure_ascii=False).encode() if body is not None else None
        request = urllib.request.Request(self.base_url + path, data=data, headers=headers, method=method)
        try:
            with urllib.request.urlopen(request, timeout=60) as response:
                return json.load(response) if response.status != 204 else None
        except urllib.error.HTTPError as exc:
            detail = exc.read().decode()[:1000]
            raise RuntimeError(f"{method} {path}: HTTP {exc.code}: {detail}") from None

    def wait(self, run_id, phases, timeout=240):
        deadline = time.monotonic() + timeout
        previous = None
        while time.monotonic() < deadline:
            run = self.call("GET", "/sop/runs/" + run_id)
            states = tuple(n["phase"] for n in run["state"]["steps"])
            if states != previous:
                print(json.dumps({"run": run_id, "phase": run["state"]["phase"], "nodes": dict(zip((n["id"] for n in run["definition"]["steps"]), states))}, ensure_ascii=False), flush=True)
                previous = states
            if run["state"]["phase"] in phases:
                return run
            if run["state"]["phase"] in ("failed", "cancelled"):
                raise RuntimeError("Unexpected demo failure: " + json.dumps(run["state"], ensure_ascii=False)[:3000])
            time.sleep(1)
        raise RuntimeError("Timed out waiting for demo run " + run_id)


def provision(client):
    credentials = client.call("GET", "/credential/")["credentials"]
    credential_name = "DAG 本地模拟模型（虚拟数据，无需 API Key）"
    credential_id = next((r["id"] for r in credentials if r["data"].get("name") == credential_name), None)
    if not credential_id:
        models = [model_id(s["key"], n["id"]) for s in SCENARIOS for n in s["nodes"]]
        models.append("dag-demo-daily-quality-review")
        credential_id = client.call("POST", "/credential/", {"data": {"type": "newapi_credential", "name": credential_name, "api_key": "local-sop-demo-only", "base_url": "http://sop-demo-model:8080/v1", "models": "\n".join(models)}})["credential_id"]
    agents = client.call("GET", "/agent/")["agents"]
    agent_ids = []
    for name in ("DAG 演示执行员（本地模拟）", "DAG 演示质量审核员（本地模拟）"):
        agent_id = next((r["id"] for r in agents if r["data"].get("name") == name), None)
        if not agent_id:
            agent_id = client.call("POST", "/agent/", {"name": name, "system_prompt": "你是本地 DAG 演示专用智能体，业务数据全部虚构。遵循当前节点要求，通过 SubmitHandover 或 SubmitVerdict 提交结果。不得联网、发送消息、采购或修改外部业务系统。", "chat_config": {"react_config": {"max_iters": 4, "max_tool_calls_per_reply": 2}}})["agent_id"]
        agent_ids.append(agent_id)
    sops = client.call("GET", "/sop/")["sops"]
    result = {}
    schema = {"type": "object", "properties": {"summary": {"type": "string"}, "data": {"type": "object"}, "data_source": {"type": "string"}, "received_inputs": {"type": "object"}}, "required": ["summary", "data", "data_source"]}
    for scenario in SCENARIOS:
        sop_id = next((r["id"] for r in sops if r["data"].get("name") == scenario["name"]), None)
        if not sop_id:
            steps = []
            settings = {}
            for node in scenario["nodes"]:
                key = scenario["key"] + "-" + node["id"]
                step = {"id": node["id"], "subject": node["subject"], "description": node["description"], "depends_on": node["depends_on"], "input_bindings": node.get("bindings", {}), "output_schema": schema, "executor": {"agent_id": agent_ids[0], "session_key": key}, "max_attempts": node.get("max_attempts", 2), "timeout_seconds": 120, "retry_delay_seconds": 2}
                settings[key] = {"chat_model_config": {"type": "openai_chat", "credential_id": credential_id, "model": model_id(scenario["key"], node["id"]), "parameters": {"max_tokens": 2048}}, "permission_mode": "default"}
                if node.get("human"):
                    step["verifier"] = {"type": "human", "question": node["human"]}
                elif node.get("agent_review"):
                    review_key = key + "-review"
                    step["verifier"] = {"type": "agent", "agent": {"agent_id": agent_ids[1], "session_key": review_key}, "criteria": "拒绝缺失 paid_amount 的数据；修复后 validation_status 为 recovered 时通过。此拒绝用于演示真实的节点失败与局部重试。"}
                    settings[review_key] = {"chat_model_config": {"type": "openai_chat", "credential_id": credential_id, "model": "dag-demo-daily-quality-review", "parameters": {"max_tokens": 1024}}, "permission_mode": "default"}
                steps.append(step)
            sop_id = client.call("POST", "/sop/", {"data": {"name": scenario["name"], "description": scenario["description"], "execution_mode": "dag", "max_concurrency": 3, "workspace_grain": "per_node", "steps": steps, "session_settings": settings}})["sop_id"]
        result[scenario["key"]] = sop_id
        print(json.dumps({"sop": scenario["name"], "id": sop_id}, ensure_ascii=False), flush=True)
    return result


def ensure_run(client, sop_id, scenario, label):
    marker = f"[sop-demo:{scenario['key']}:{label}]"
    runs = client.call("GET", "/sop/runs?sop_id=" + sop_id)["runs"]
    for run in runs:
        if any(marker in json.dumps(m, ensure_ascii=False) for m in run["state"]["inputs"]):
            return run
    return client.call("POST", "/sop/" + sop_id + "/runs", {"inputs": [{"name": "user", "role": "user", "content": [{"type": "text", "text": scenario["input"] + "\n" + marker}]}]})


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--base-url", default="http://127.0.0.1:8001")
    parser.add_argument("--username", default="test")
    parser.add_argument("--start", action="store_true", help="Create four execution examples, including a preserved failed run")
    args = parser.parse_args()
    password = os.getenv("SOP_DEMO_PASSWORD") or getpass.getpass("Account password: ")
    client = Client(args.base_url)
    login = client.call("POST", "/auth/login", {"username": args.username, "password": password})
    client.token = login["access_token"]
    ids = provision(client)
    if not args.start:
        return
    launch, commerce, daily = SCENARIOS
    complete = ensure_run(client, ids["launch"], launch, "completed")
    review = ensure_run(client, ids["commerce"], commerce, "human-review")
    failed = ensure_run(client, ids["daily"], daily, "failed-for-manual-retry")
    recovered = ensure_run(client, ids["daily"], daily, "recovered-example")
    client.wait(complete["id"], {"completed"})
    client.wait(review["id"], {"awaiting", "completed"})
    client.wait(failed["id"], {"failed", "completed"})
    recovered = client.wait(recovered["id"], {"failed", "completed"})
    if recovered["state"]["phase"] == "failed":
        node = recovered["state"]["steps"][1]
        client.call("POST", f"/sop/runs/{recovered['id']}/nodes/quality/retry", {"expected_generation": node["generation"], "include_descendants": False})
        recovered = client.wait(recovered["id"], {"completed"})
    counts = {n["node_id"]: len(n["attempts"]) for n in recovered["state"]["steps"]}
    if counts != {"source": 1, "quality": 2, "metrics": 1, "report": 1}:
        raise RuntimeError("Unexpected attempt counts: " + str(counts))
    summary = {"username": args.username, "sops": ids, "runs": {"parallel_completed": complete["id"], "awaiting_human_review": review["id"], "failed_for_manual_retry": failed["id"], "recovered_in_same_run": recovered["id"]}, "recovered_attempt_counts": counts}
    print(json.dumps(summary, ensure_ascii=False, indent=2), flush=True)


if __name__ == "__main__":
    main()
