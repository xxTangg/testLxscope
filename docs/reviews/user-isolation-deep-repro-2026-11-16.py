"""Isolated multi-account audit. Never connects to production storage or models.

Run inside the service image with python; browser check uses its bundled Playwright.
Only temporary files, fake accounts, and an InMemoryMessageBus are used.
"""
import asyncio
import importlib.util
import io
import json
import os
import socket
import sys
from pathlib import Path
from tempfile import TemporaryDirectory
from types import SimpleNamespace
from urllib.parse import urlencode

import httpx
import uvicorn
from fastapi import FastAPI, HTTPException
from fastapi.responses import HTMLResponse

from agentscope.app import deps
from agentscope.app._router._workspace import workspace_router, read_workspace_file
from agentscope.app._router._session import session_router
from agentscope.app._router._chat import chat_router
from agentscope.app._router._agent import agent_router
from agentscope.app._router._credential import credential_router
from agentscope.app._router._knowledge_base import knowledge_base_router
from agentscope.app.rag.blob_store import LocalBlobStore
from agentscope.app._service import KnowledgeBaseService
from agentscope.app._service import WorkspaceService, SessionService, ChatService, ResourceAccessService
from agentscope.app._service._session_projection import SessionProjection
from agentscope.app._service._projectors import SubagentHitlProjector
from agentscope.app.access import DenyAllResourceAccessPolicy
from agentscope.app._manager import ChatRunRegistry
from agentscope.app.message_bus import InMemoryMessageBus, MessageBusKeys
from agentscope.app.storage import AgentData, AgentRecord, SessionConfig, SessionRecord, CredentialRecord
from agentscope.app.workspace_manager import LocalWorkspaceManager
from agentscope.permission import PermissionContext, PermissionEngine, PermissionMode, AdditionalWorkingDirectory
from agentscope.state import AgentState

spec = importlib.util.spec_from_file_location("isolation_audit_auth", "/app/examples/agent_service/auth.py")
authmod = importlib.util.module_from_spec(spec)
sys.modules[spec.name] = authmod
spec.loader.exec_module(authmod)


class Accounts:
    def __init__(self):
        self.accounts = {}

    def get_client(self):
        return self

    async def hget(self, key, username):
        record = self.accounts.get(username)
        return record.model_dump_json() if record else None


class Storage:
    def __init__(self):
        self.sessions, self.agents, self.messages = {}, {}, {}
        self.credentials = {}
        self.document = None

    async def get_session(self, user_id, agent_id, session_id):
        return self.sessions.get((user_id, agent_id, session_id))

    async def get_agent(self, user_id, agent_id):
        return self.agents.get((user_id, agent_id))

    async def list_agents(self, user_id):
        return [r for (owner, _), r in self.agents.items() if owner == user_id]

    async def delete_session(self, user_id, agent_id, session_id):
        return self.sessions.pop((user_id, agent_id, session_id), None) is not None

    async def upsert_message(self, user_id, session_id, message):
        self.messages.setdefault((user_id, session_id), []).append(message)

    async def list_messages(self, user_id, session_id, **kwargs):
        return self.messages.get((user_id, session_id), []), False

    async def get_team(self, user_id, team_id):
        return None

    async def get_credential(self, user_id, credential_id):
        return self.credentials.get((user_id, credential_id))

    async def list_credentials(self, user_id):
        return [r for (owner, _), r in self.credentials.items() if owner == user_id]

    async def get_knowledge_base(self, user_id, knowledge_base_id):
        if (user_id, knowledge_base_id) == ("audit-b", "kb-b"):
            return SimpleNamespace(user_id="audit-b", id="kb-b")
        return None

    async def get_knowledge_document(self, user_id, knowledge_base_id, document_id):
        if (user_id, knowledge_base_id, document_id) == ("audit-b", "kb-b", "doc-b"):
            return self.document
        return None


class Bus(InMemoryMessageBus):
    def __init__(self):
        super().__init__()
        self.broadcasts = []

    async def publish(self, channel, payload):
        self.broadcasts.append((channel, payload))
        return await super().publish(channel, payload)


async def main():
    results = []

    def record(case, **values):
        result = {"case": case, **values}
        results.append(result)
        print(json.dumps(result, ensure_ascii=False), flush=True)

    storage, accounts, bus = Storage(), Accounts(), Bus()
    auth = authmod.JWTAuthService(accounts, "audit-temporary-secret-000000000000000000000", 60)
    headers = {}
    for owner in ("audit-a", "audit-b"):
        account = authmod._Account(id=owner, username=owner, is_admin=False, enabled=True, salt="unused", password_digest="unused")
        accounts.accounts[owner] = account
        headers[owner] = {"Authorization": "Bearer " + auth._login_response(account).access_token}
    with TemporaryDirectory(prefix="account-audit-") as tmp:
        manager = LocalWorkspaceManager(str(Path(tmp, "workspaces")))
        access = ResourceAccessService(storage, DenyAllResourceAccessPolicy())
        workspaces = {}
        for owner, agent, sid in (("audit-a", "agent-a", "session-a"), ("audit-b", "agent-b", "session-b")):
            ws = await manager.get_workspace(owner, agent, sid)
            workspaces[owner] = ws
            storage.agents[owner, agent] = AgentRecord(user_id=owner, id=agent, data=AgentData(id=agent, name=agent))
            storage.credentials[owner, "credential-"+owner] = CredentialRecord(id="credential-"+owner,user_id=owner,data={"type":"openai_credential","name":owner,"api_key":"SYNTHETIC_"+owner})
            storage.sessions[owner, agent, sid] = SessionRecord(id=sid, user_id=owner, agent_id=agent, config=SessionConfig(workspace_id=ws.workspace_id))
            Path(ws.workdir, "private.txt").write_text("SYNTHETIC_" + owner)
        wa, wb = workspaces["audit-a"], workspaces["audit-b"]
        service = WorkspaceService(storage, manager, "audit-download-secret")
        sessions = SessionService(storage, bus)
        chat = ChatService(storage, manager, None, None, bus, access)
        registry = ChatRunRegistry()
        blobs = LocalBlobStore(Path(tmp, "blobs"))
        blob_uri = await blobs.write_stream("kb-b/doc-b", io.BytesIO(b"SYNTHETIC_B_DOCUMENT"))
        storage.document = SimpleNamespace(data=SimpleNamespace(blob_uri=blob_uri,filename="private.txt",content_type="text/plain"))
        kb = KnowledgeBaseService(storage,None,blobs,bus,access)
        app = FastAPI()
        app.state.download_secret = "audit-download-secret"
        for router in (workspace_router, session_router, chat_router, agent_router, credential_router, knowledge_base_router, auth.router):
            app.include_router(router)
        app.dependency_overrides[deps.get_current_user_id] = auth.get_current_user_id
        for dep, value in ((deps.get_knowledge_base_service,kb), (deps.get_storage, storage), (deps.get_workspace_manager, manager), (deps.get_workspace_service, service), (deps.get_session_service, sessions), (deps.get_chat_service, chat), (deps.get_message_bus, bus), (deps.get_resource_access_service, access), (deps.get_chat_run_registry, registry)):
            def bound(value):
                return lambda: value
            app.dependency_overrides[dep] = bound(value)

        @app.get("/audit-seed", response_class=HTMLResponse)
        async def seed():
            return "<html><body>isolated test</body></html>"

        @app.get("/audit-internal/models")
        async def internal():
            return {"data":[{"id":"SYNTHETIC_INTERNAL_ONLY"}]}

        async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://audit") as client:
            ha, hb = headers["audit-a"], headers["audit-b"]
            a = {"agent_id": "agent-a", "session_id": "session-a"}
            b = {"agent_id": "agent-b", "session_id": "session-b"}
            for name, method, path, params, body, auth_headers, expected in (
                ("no_identity_directory", "GET", "/workspace/directories", a, None, {}, 401),
                ("spoofed_user_header", "GET", "/workspace/directories", b, None, {"X-User-ID":"audit-b"}, 401),
                ("owner_directory", "GET", "/workspace/directories", b, None, hb, 200),
                ("cross_user_directory", "GET", "/workspace/directories", b, None, ha, 404),
                ("cross_user_messages", "GET", "/sessions/session-b/messages", {"agent_id":"agent-b"}, None, ha, 404),
                ("cross_user_status", "GET", "/sessions/session-b/status", {"agent_id":"agent-b"}, None, ha, 404),
                ("cross_user_sse", "GET", "/sessions/session-b/stream", {"agent_id":"agent-b"}, None, ha, 404),
                ("cross_user_config", "PATCH", "/sessions/session-b", {"agent_id":"agent-b"}, {"name":"tampered"}, ha, 404),
                ("cross_user_agent_edit", "PATCH", "/agent/agent-b", {}, {"name":"tampered"}, ha, 404),
                ("parent_escape", "GET", "/workspace/directories", {**a,"path":"~/.."}, None, ha, 403),
                ("absolute_other_user_path", "POST", "/workspace/files/download-token", {**a,"path":str(Path(wb.workdir,"private.txt"))}, None, ha, 403),
                ("legacy_binding_request", "POST", "/sessions/", {}, {"agent_id":"agent-a","workspace_id":wb.workspace_id}, ha, 422),
                ("legacy_download_header", "GET", "/workspace/files", {**b,"path":"private.txt"}, None, {"X-User-ID":"audit-b"}, 422),
                ("regular_user_admin_api", "GET", "/admin/users", {}, None, ha, 403),
            ):
                response = await client.request(method,path,params=params,json=body,headers=auth_headers)
                record("control_"+name,status=response.status_code,expected=expected,passed=response.status_code==expected)
            r = await client.get("/agent/", headers=ha)
            record("control_agent_list",status=r.status_code,passed={v["id"] for v in r.json()["agents"]}=={"agent-a"})


            r = await client.get("/credential/",headers=ha)
            record("control_credentials_list",status=r.status_code,passed="SYNTHETIC_audit-b" not in r.text and "credential-audit-a" in r.text)
            for name,method,path,body,expected in (
                ("credential_edit","PATCH","/credential/credential-audit-b",{"data":{"type":"openai_credential","name":"edited","api_key":"fake"}},404),
                ("credential_delete","DELETE","/credential/credential-audit-b",None,404),
                ("kb_document_token","POST","/knowledge_bases/kb-b/documents/doc-b/download_token",None,404),
                ("kb_chunks","GET","/knowledge_bases/kb-b/documents/doc-b/chunks",None,404),
                ("kb_search","POST","/knowledge_bases/kb-b/search",{"query":"audit"},404),
            ):
                response=await client.request(method,path,json=body,headers=ha)
                record("control_cross_user_"+name,status=response.status_code,passed=response.status_code==expected)
            r=await client.post("/knowledge_bases/kb-b/documents/doc-b/download_token",headers=hb)
            token_b=r.json()["token"]
            r=await client.get("/knowledge_bases/kb-b/documents/doc-b",params={"token":token_b})
            record("control_owner_kb_download",status=r.status_code,passed=r.content==b"SYNTHETIC_B_DOCUMENT")
            r=await client.get("/knowledge_bases/kb-b/documents/doc-b",headers={"X-User-ID":"audit-b"})
            record("control_kb_header_spoof",status=r.status_code,passed=r.status_code==422)
            accounts.accounts["audit-b"].enabled=False
            r=await client.get("/auth/me",headers=hb)
            record("control_disabled_account_token",status=r.status_code,passed=r.status_code==401)
            accounts.accounts["audit-b"].enabled=True
            original_version=accounts.accounts["audit-b"].session_version
            accounts.accounts["audit-b"].session_version="revoked"
            r=await client.get("/auth/me",headers=hb)
            record("control_revoked_account_token",status=r.status_code,passed=r.status_code==401)
            accounts.accounts["audit-b"].session_version=original_version

            # No model is invoked: foreign ownership fails during assembly.
            before = len(await bus.log_read(MessageBusKeys.session_events("session-b")))
            r = await client.post("/chat/",headers=ha,json={**b,"input":None})
            for _ in range(100):
                if len(await bus.log_read(MessageBusKeys.session_events("session-b")))>before:
                    break
                await asyncio.sleep(.01)
            events = await bus.log_read(MessageBusKeys.session_events("session-b"))
            record("F_chat_foreign_session_event_write",http_status=r.status_code,victim_events_added=len(events)-before,victim_persistent_messages=len(storage.messages.get(("audit-b","session-b"),[])),attacker_namespace_messages=len(storage.messages.get(("audit-a","session-b"),[])))

            # A read-only denial still has cancellation and deletion effects.
            await bus.log_append(MessageBusKeys.session_events("session-b"),{"audit":"victim-event"})
            pending={"worker_session_id":"worker-b","worker_agent_id":"worker-agent-b","reply_id":"reply-b"}
            projection=SessionProjection(bus)
            await projection.upsert("session-b",SubagentHitlProjector.KIND,"worker-b:reply-b",pending)
            r=await client.post("/chat/",headers=ha,json={**b,"input":{"type":"USER_CONFIRM_RESULT","reply_id":"reply-b","confirm_results":[]}})
            queued=await bus.queue_drain(MessageBusKeys.wakeup_queue(),max_count=100)
            record("F_foreign_confirmation_routing",http_status=r.status_code,returned_worker_session=r.json().get("session_id"),queued_triggers=len(queued))
            r=await client.delete("/sessions/session-b",params={"agent_id":"agent-b"},headers=ha)
            record("F_foreign_delete_side_effects",http_status=r.status_code,victim_record_survived=("audit-b","agent-b","session-b") in storage.sessions,victim_events_remaining=len(await bus.log_read(MessageBusKeys.session_events("session-b"))),victim_projections_remaining=len(await projection.list("session-b",SubagentHitlProjector.KIND)),victim_cancel_sent=any(ch==MessageBusKeys.session_cancel_channel() and pay.get("session_id")=="session-b" for ch,pay in bus.broadcasts))

            # Use the real builtin Read and permission engine with A's state.
            read=next(t for t in await wa.list_tools() if t.name=="Read")
            state=AgentState()
            permission=PermissionEngine(PermissionContext(mode=PermissionMode.ACCEPT_EDITS,working_directories={wa.workdir:AdditionalWorkingDirectory(path=wa.workdir,source="session")}))
            decision=await permission.check_permission(read,{"file_path":str(Path(wb.workdir,"private.txt"))})
            chunk=await read(file_path=str(Path(wb.workdir,"private.txt")),_agent_state=state)
            record("F_builtin_read_other_user",permission=str(decision.behavior),read_synthetic_b_marker="SYNTHETIC_audit-b" in json.dumps(chunk.model_dump(mode="json")))
            os.environ["AUDIT_SYNTHETIC_ENV"]="FAKE_SERVICE_SECRET"
            execution=await wa.get_backend().exec_shell([sys.executable,"-c","import os;print(os.getenv('AUDIT_SYNTHETIC_ENV'))"],cwd=wa.workdir)
            record("F_tool_inherits_service_environment",synthetic_environment_inherited=b"FAKE_SERVICE_SECRET" in execution.stdout)
            del os.environ["AUDIT_SYNTHETIC_ENV"]

            # Deferred file opening permits parent-directory replacement.
            folder=Path(wa.workdir,"switchable");folder.mkdir()
            (folder/"private.txt").write_text("SAFE_A_FILE")
            path="switchable/private.txt"
            token,_=service.sign_download_token("audit-a","agent-a","session-a",path)
            response=await read_workspace_file(agent_id="agent-a",session_id="session-a",path=path,download=False,token=token,workspace_service=service)
            folder.rename(folder.with_name("original"))
            folder.symlink_to(wb.workdir,target_is_directory=True)
            payload=b"".join([part async for part in response.body_iterator])
            record("F_file_open_race",read_synthetic_b_marker=b"SYNTHETIC_audit-b" in payload)

            # Realpath cannot recognize a hard link to another owner's inode.
            os.link(Path(wb.workdir,"private.txt"),Path(wa.workdir,"linked.txt"))
            signed=await client.post("/workspace/files/download-token",params={**a,"path":"linked.txt"},headers=ha)
            linked=await client.get("/workspace/files",params={**a,"path":"linked.txt","token":signed.json()["token"]})
            record("F_hardlink_file_alias",read_synthetic_b_marker=linked.content==b"SYNTHETIC_audit-b")

            # Same-origin HTML capability can read the viewing browser's token.
            html_payload=b"<html><body><script>document.body.textContent=localStorage.getItem('agentscope_access_token')</script></body></html>"
            skill_payload=b"---\nname: audit-html\ndescription: harmless isolated audit\n---\nAudit"
            manifest={"entries":[{"path":"audit-html/SKILL.md","size":len(skill_payload)},{"path":"audit-html/audit.html","size":len(html_payload)}]}
            upload=await client.post("/workspace/skill/upload",params=a,headers=ha,data={"manifest":json.dumps(manifest)},files=[("files",("SKILL.md",skill_payload)),("files",("audit.html",html_payload))])
            record("F_html_upload_without_model_or_shell",status=upload.status_code)
            html_path="skills/agent-a/audit-html/audit.html"
            r=await client.post("/workspace/files/download-token",params={**a,"path":html_path},headers=ha)
            params={**a,"path":html_path,"token":r.json()["token"]}
            r=await client.get("/workspace/files",params=params)
            record("F_html_response_headers",status=r.status_code,content_type=r.headers.get("content-type"),content_disposition=r.headers.get("content-disposition"),csp=r.headers.get("content-security-policy"))

            sock=socket.socket();sock.bind(("127.0.0.1",0));port=sock.getsockname()[1]
            server=uvicorn.Server(uvicorn.Config(app,log_level="critical",lifespan="off"))
            task=asyncio.create_task(server.serve(sockets=[sock]))
            try:
                for _ in range(100):
                    if server.started:break
                    await asyncio.sleep(.02)
                node_script="""const {chromium}=require('/usr/local/lib/node_modules/@playwright/mcp/node_modules/playwright');(async()=>{const b=await chromium.launch({headless:true,executablePath:process.argv[3],args:['--no-sandbox']});try{const page=await b.newPage();await page.goto(process.argv[1]+'/audit-seed');await page.evaluate(()=>localStorage.setItem('agentscope_access_token','SYNTHETIC_B_BROWSER_TOKEN'));await page.goto(process.argv[2]);console.log(JSON.stringify({browser_script_read_fake_victim_token:(await page.locator('body').innerText())==='SYNTHETIC_B_BROWSER_TOKEN'}));}finally{await b.close()}})().catch(e=>{console.error(e);process.exit(1)})"""
                base=f"http://127.0.0.1:{port}"
                probe=await client.post("/credential/newapi/models",headers=ha,json={"base_url":base+"/audit-internal","api_key":"synthetic"})
                record("R_gateway_internal_http_access",status=probe.status_code,synthetic_internal_response_returned="SYNTHETIC_INTERNAL_ONLY" in probe.text)
                proc=await asyncio.create_subprocess_exec("node","-e",node_script,base,base+"/workspace/files?"+urlencode(params),str(next(Path("/ms-playwright").glob("*/chrome-linux*/chrome"))),stdout=asyncio.subprocess.PIPE,stderr=asyncio.subprocess.PIPE)
                out,err=await asyncio.wait_for(proc.communicate(),40)
                if proc.returncode: raise RuntimeError(err.decode())
                record("F_same_origin_file_xss",**json.loads(out.decode()))
            finally:
                server.should_exit=True
                await task
                sock.close()
        await manager.close_all()
        await bus.aclose()
    assert all(r.get("passed",True) for r in results if r["case"].startswith("control_")),"An ownership control failed"
    print(json.dumps({"total_cases":len(results),"storage":"synthetic in-memory only","models_called":False}),flush=True)

asyncio.run(main())
