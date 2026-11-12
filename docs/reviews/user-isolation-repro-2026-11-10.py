import asyncio
import importlib.util
import json
import io
import os
import sys
from pathlib import Path
from tempfile import TemporaryDirectory
from types import SimpleNamespace

import httpx
from fastapi import FastAPI, HTTPException
from agentscope.app import deps
from agentscope.app._router._workspace import workspace_router
from agentscope.app._router._session import session_router
from agentscope.app._router._chat import chat_router
from agentscope.app._router._knowledge_base import knowledge_base_router
from agentscope.app.rag.blob_store import LocalBlobStore
from agentscope.app._service import KnowledgeBaseService
from agentscope.tool import LocalBackend
from agentscope.app._manager import ChatRunRegistry
from agentscope.app._service import WorkspaceService, SessionService, ChatService
from agentscope.app.message_bus import InMemoryMessageBus, MessageBusKeys
from agentscope.app.workspace_manager import LocalWorkspaceManager, IsolationPolicy
from agentscope.app.storage import SessionConfig, SessionRecord

spec = importlib.util.spec_from_file_location("audit_auth", "/app/examples/agent_service/auth.py")
authmod = importlib.util.module_from_spec(spec)
sys.modules[spec.name] = authmod
spec.loader.exec_module(authmod)

class Storage:
    def __init__(self):
        self.sessions = {}
        self.messages = {}
    async def get_session(self, user_id, agent_id, session_id):
        return self.sessions.get((user_id, agent_id, session_id))
    async def upsert_session(self, user_id, agent_id, config, **kwargs):
        record = SessionRecord(user_id=user_id, agent_id=agent_id, config=config)
        self.sessions[(user_id, agent_id, record.id)] = record
        return record
    async def get_knowledge_document(self, user_id, knowledge_base_id, document_id):
        if (user_id, knowledge_base_id, document_id) == ("audit-b", "kb-b", "doc-b"):
            return self.document_b
        return None
    async def delete_session(self, user_id, agent_id, session_id):
        return self.sessions.pop((user_id, agent_id, session_id), None) is not None
    async def upsert_message(self, user_id, session_id, message):
        self.messages.setdefault((user_id, session_id), []).append(message)

class Access:
    async def resolve_agent(self, user_id, agent_id):
        if (user_id, agent_id) not in {("audit-a", "agent-a"), ("audit-b", "agent-b")}:
            raise HTTPException(404, "not owned")
        return SimpleNamespace(id=agent_id, user_id=user_id, data=SimpleNamespace(name=agent_id))

    async def resolve_knowledge_base(self, user_id, knowledge_base_id):
        if (user_id, knowledge_base_id) != ("audit-b", "kb-b"):
            raise HTTPException(404, "not owned")
        return SimpleNamespace(user_id="audit-b")

class Bus(InMemoryMessageBus):
    def __init__(self):
        super().__init__()
        self.published = []
    async def publish(self, channel, payload):
        self.published.append((channel, payload))
        return await super().publish(channel, payload)

async def main():
    results = []
    def record(name, **details):
        result = {"case": name, **details}
        results.append(result)
        print(json.dumps(result), flush=True)
    storage, access, bus = Storage(), Access(), Bus()
    auth = authmod.JWTAuthService(
        {"alice": ("audit-a", "audit-password-a"), "bob": ("audit-b", "audit-password-b")},
        "temporary-audit-secret-00000000000000000000",
    )
    ta, _ = auth.issue_access_token(authmod.AuthUser(id="audit-a", username="alice"))
    tb, _ = auth.issue_access_token(authmod.AuthUser(id="audit-b", username="bob"))
    ha, hb = {"Authorization": "Bearer " + ta}, {"Authorization": "Bearer " + tb}
    with TemporaryDirectory(prefix="agentscope-isolation-audit-") as tmp:
        manager = LocalWorkspaceManager(tmp)
        wa = await manager.get_workspace("audit-a", "agent-a", "session-a", "workspace-a")
        wb = await manager.get_workspace("audit-b", "agent-b", "session-b", "workspace-b")
        Path(wb.workdir, "private.txt").write_text("AUDIT_B_PRIVATE_MARKER", encoding="utf-8")
        sa = SessionRecord(id="session-a", user_id="audit-a", agent_id="agent-a", config=SessionConfig(workspace_id="workspace-a"))
        sb = SessionRecord(id="session-b", user_id="audit-b", agent_id="agent-b", config=SessionConfig(workspace_id="workspace-b"))
        storage.sessions[("audit-a", "agent-a", sa.id)] = sa
        storage.sessions[("audit-b", "agent-b", sb.id)] = sb
        workspace_service = WorkspaceService(storage, manager, "temporary-download-secret")
        session_service = SessionService(storage, bus, manager)
        chat_service = ChatService(storage, manager, None, None, bus, access)
        registry = ChatRunRegistry()
        blob_store = LocalBlobStore(Path(tmp, "blobs"))
        uri = await blob_store.write_stream("kb-b/doc-b", io.BytesIO(b"AUDIT_B_DOCUMENT_MARKER"))
        storage.document_b = SimpleNamespace(data=SimpleNamespace(blob_uri=uri, filename="private.txt", content_type="text/plain"))
        kb_service = KnowledgeBaseService(storage, None, blob_store, bus, access)
        app = FastAPI()
        for router in (workspace_router, session_router, chat_router, knowledge_base_router, auth.router):
            app.include_router(router)
        app.dependency_overrides[deps.get_current_user_id] = auth.get_current_user_id
        for dep, obj in (
            (deps.get_storage, storage), (deps.get_workspace_manager, manager),
            (deps.get_workspace_service, workspace_service),
            (deps.get_session_service, session_service),
            (deps.get_chat_service, chat_service),
            (deps.get_message_bus, bus), (deps.get_resource_access_service, access),
            (deps.get_chat_run_registry, registry),
            (deps.get_knowledge_base_service, kb_service),
            (deps.get_download_secret, "temporary-download-secret"),
        ):
            def bound(value):
                async def get_value():
                    return value
                return get_value
            app.dependency_overrides[dep] = bound(obj)

        async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://audit") as c:
            params_b = {"agent_id": "agent-b", "session_id": "session-b", "path": "private.txt"}
            r = await c.get("/sessions/session-b/messages", params={"agent_id": "agent-b"}, headers=ha)
            record("control_cross_user_message_read", status=r.status_code, blocked=r.status_code == 404)
            r = await c.get("/workspace/directories", params={"agent_id": "agent-a", "session_id": "session-a"})
            record("control_directory_without_jwt", status=r.status_code, blocked=r.status_code == 401)

            r = await c.get("/workspace/files", params=params_b, headers={"X-User-ID": "audit-b"})
            record("F1_file_download_identity_spoof", status=r.status_code, no_jwt=True, read_b_marker=r.text == "AUDIT_B_PRIVATE_MARKER")
            r = await c.get("/workspace/files", params=params_b, headers=hb)
            record("F1_valid_bearer_without_download_token", status=r.status_code, rejected=r.status_code == 401)

            r = await c.get("/knowledge_bases/kb-b/documents/doc-b", headers={"X-User-ID": "audit-b"})
            record("F1_document_download_identity_spoof", status=r.status_code, no_jwt=True, read_b_marker=r.text == "AUDIT_B_DOCUMENT_MARKER")

            traversal = {"agent_id": "agent-a", "session_id": "session-a", "path": "../agent-b/private.txt"}
            r = await c.post("/workspace/files/download-token", params=traversal, headers=ha)
            assert r.status_code == 200, r.text
            r = await c.get("/workspace/files", params={**traversal, "token": r.json()["token"]})
            record("F2_jwt_a_path_escape", status=r.status_code, read_b_marker=r.text == "AUDIT_B_PRIVATE_MARKER")
            r = await c.get("/workspace/directories", params={"agent_id": "agent-a", "session_id": "session-a", "path": ".."}, headers=ha)
            record("F2_parent_directory_listing", status=r.status_code, sees_b_directory=any(e["name"] == "agent-b" for e in r.json()["entries"]))

            r = await c.post("/sessions/", json={"agent_id": "agent-a", "workspace_id": "workspace-b"}, headers=ha)
            assert r.status_code == 201, r.text
            injected_sid = r.json()["session_id"]
            injected = await workspace_service.resolve("audit-a", "agent-a", injected_sid)
            record("F3_cross_user_workspace_binding", status=r.status_code, bound_to_b_workspace=injected is wb)

            r = await c.post("/chat/", json={"agent_id": "agent-b", "session_id": "session-b", "input": None}, headers=ha)
            task = registry.get("session-b")
            if task is not None:
                await task
            events = await bus.log_read(MessageBusKeys.session_events("session-b"))
            record("F5_unauthorized_chat_event_pollution", status=r.status_code, victim_stream_event_count=len(events),
                   types=[e.get("type") for _, e in events], victim_db_unchanged=("audit-b", "session-b") not in storage.messages)

            bus.published.clear()
            r = await c.delete("/sessions/session-b", params={"agent_id": "agent-b"}, headers=ha)
            remaining = await bus.log_read(MessageBusKeys.session_events("session-b"))
            cancelled = any(k == MessageBusKeys.session_cancel_channel() and p.get("session_id") == "session-b" for k, p in bus.published)
            record("F4_cross_user_delete_side_effect", status=r.status_code, victim_record_retained=("audit-b", "agent-b", "session-b") in storage.sessions,
                   victim_cancel_sent=cancelled, victim_events_purged=bool(events) and not remaining)

            r = await c.post("/auth/logout", headers=ha)
            r2 = await c.get("/auth/me", headers=ha)
            record("F7_logout_token_still_valid", logout_status=r.status_code, reused_token_status=r2.status_code)
        await manager.close_all()

    with TemporaryDirectory(prefix="agentscope-per-session-audit-") as tmp:
        manager = LocalWorkspaceManager(tmp, isolation=IsolationPolicy.PER_SESSION)
        one = await manager.get_workspace("audit-a", "agent-a", "session-1", "wid-1")
        two = await manager.get_workspace("audit-a", "agent-a", "session-2", "wid-2")
        record("F6_local_per_session_directory_reused", separate_workspace_ids=one.workspace_id != two.workspace_id, same_workdir=one.workdir == two.workdir)
        await manager.close_all()

    os.environ["AUDIT_INHERITED_MARKER"] = "AUDIT_PROCESS_ENV_MARKER"
    child = await LocalBackend().exec_shell([sys.executable, "-c", "import os; print(os.getenv('AUDIT_INHERITED_MARKER', 'missing'))"])
    record("F6_tool_process_inherits_service_environment", inherited_marker=child.stdout.decode().strip() == "AUDIT_PROCESS_ENV_MARKER")

asyncio.run(main())
