# -*- coding: utf-8 -*-
"""Account storage and JWT authentication for the Web UI."""

from __future__ import annotations

import asyncio
import base64
import hashlib
import hmac
import json
import os
import secrets
from contextlib import asynccontextmanager
from datetime import datetime, timedelta, timezone
from typing import TYPE_CHECKING, Literal
from uuid import NAMESPACE_URL, uuid4, uuid5

import jwt
from fastapi import (
    APIRouter,
    Depends,
    FastAPI,
    Header,
    HTTPException,
    Response,
)
from fastapi import status
from pydantic import BaseModel, Field
from redis.exceptions import WatchError

from agentscope.app.storage import AgentData, AgentRecord

from token_usage import TokenUsage, get_token_usage

if TYPE_CHECKING:
    from agentscope.app.storage import RedisStorage


_ACCOUNTS_KEY = "longxin:auth:accounts"
_ISSUER = "agentscope-web-ui"
_AUDIENCE = "agentscope-api"


class LoginRequest(BaseModel):
    username: str = Field(min_length=1, max_length=64)
    password: str = Field(min_length=1, max_length=1024)


class PasswordRequest(BaseModel):
    password: str = Field(min_length=6, max_length=1024)


class RegisterRequest(PasswordRequest):
    username: str = Field(min_length=1, max_length=64)


class AccountStatusRequest(BaseModel):
    enabled: bool


class AuthUser(BaseModel):
    id: str
    username: str
    is_admin: bool
    enabled: bool


class LoginResponse(BaseModel):
    access_token: str
    user: AuthUser
    show_tour: bool


class _Account(AuthUser):
    salt: str
    password_digest: str
    session_version: str = Field(default_factory=lambda: uuid4().hex)
    # Existing and configured accounts have no pending tour.
    chat_tour_claimed: bool = True

    def public(self) -> AuthUser:
        return AuthUser(
            id=self.id,
            username=self.username,
            is_admin=self.is_admin,
            enabled=self.enabled,
        )


class _ConfiguredAccount(BaseModel):
    user_id: str = Field(pattern=r"^[a-zA-Z0-9_-]+$")
    password: str = Field(min_length=1, max_length=1024)


def _normalize_username(username: str) -> str:
    username = username.strip()
    if not 1 <= len(username) <= 64 or any(c.isspace() for c in username):
        raise ValueError(
            "Username must be 1 to 64 characters without whitespace.",
        )
    return username


def _derive_password(password: str, salt: bytes) -> bytes:
    return hashlib.scrypt(
        password.encode("utf-8"),
        salt=salt,
        n=2**14,
        r=8,
        p=1,
        dklen=32,
    )


async def _password_fields(password: str) -> dict[str, str]:
    salt = secrets.token_bytes(16)
    digest = await asyncio.to_thread(_derive_password, password, salt)
    return {
        "salt": base64.b64encode(salt).decode("ascii"),
        "password_digest": base64.b64encode(digest).decode("ascii"),
    }


def _unauthorized(detail: str) -> HTTPException:
    return HTTPException(401, detail, headers={"WWW-Authenticate": "Bearer"})


class JWTAuthService:
    """Use one Redis account directory for sign-in and administration."""

    def __init__(
        self,
        storage: RedisStorage,
        secret: str,
        token_minutes: int,
    ) -> None:
        if len(secret.encode("utf-8")) < 32:
            raise ValueError("The JWT secret must be at least 32 bytes long.")
        if token_minutes <= 0:
            raise ValueError("JWT token lifetime must be greater than zero.")
        self._storage = storage
        self._secret = secret
        self._token_lifetime = timedelta(minutes=token_minutes)
        self.router = self._build_router()

    async def _initialize(self) -> None:
        """Create configured accounts when the account directory is empty."""
        client = self._storage.get_client()
        if await client.exists(_ACCOUNTS_KEY):
            return

        admin = _normalize_username(os.getenv("AGENTSCOPE_USERNAME", "admin"))
        configured = json.loads(os.getenv("AGENTSCOPE_AUTH_USERS") or "{}")
        if not isinstance(configured, dict):
            raise ValueError("AGENTSCOPE_AUTH_USERS must be a JSON object.")
        seeds = {
            admin: _ConfiguredAccount(
                user_id=os.getenv("AGENTSCOPE_USER_ID", "local-user"),
                password=os.getenv("AGENTSCOPE_PASSWORD", "change-me"),
            ),
        }
        for name, config in configured.items():
            username = _normalize_username(name)
            if username in seeds:
                raise ValueError(
                    f"Duplicate configured username {username!r}."
                )
            seeds[username] = _ConfiguredAccount.model_validate(config)
        if len({seed.user_id for seed in seeds.values()}) != len(seeds):
            raise ValueError(
                "Configured accounts must have distinct user ids."
            )

        records = {}
        for username, seed in seeds.items():
            records[username] = _Account(
                id=seed.user_id,
                username=username,
                is_admin=username == admin,
                enabled=True,
                **await _password_fields(seed.password),
            ).model_dump_json()

        async with client.pipeline() as pipe:
            await pipe.watch(_ACCOUNTS_KEY)
            if await pipe.exists(_ACCOUNTS_KEY):
                return
            pipe.multi()
            pipe.hset(_ACCOUNTS_KEY, mapping=records)
            try:
                await pipe.execute()
            except WatchError:
                # Another process initialized the directory first.
                return

    async def _account(self, username: str) -> _Account | None:
        client = self._storage.get_client()
        raw = await client.hget(_ACCOUNTS_KEY, username)
        return _Account.model_validate_json(raw) if raw is not None else None

    async def _ensure_default_agent(self, user_id: str) -> None:
        """Give an empty account its own general agent, idempotently."""
        if await self._storage.list_agents(user_id):
            return
        agent_id = uuid5(
            NAMESPACE_URL, f"agentscope:account:{user_id}:general-agent"
        ).hex
        await self._storage.upsert_agent(
            user_id,
            AgentRecord(
                id=agent_id,
                user_id=user_id,
                data=AgentData(id=agent_id, name="通用智能体"),
            ),
        )

    async def _authenticate(self, body: LoginRequest) -> _Account:
        account = await self._account(body.username.strip())
        salt = (
            base64.b64decode(account.salt) if account else b"longxin-login--"
        )
        digest = await asyncio.to_thread(_derive_password, body.password, salt)
        if (
            account is None
            or not account.enabled
            or not hmac.compare_digest(
                digest,
                base64.b64decode(account.password_digest),
            )
        ):
            raise _unauthorized("Invalid username or password.")
        await self._ensure_default_agent(account.id)
        return account

    async def _register(self, body: RegisterRequest) -> _Account:
        try:
            username = _normalize_username(body.username)
        except ValueError as exc:
            raise HTTPException(422, str(exc)) from exc
        account = _Account(
            id=f"user-{uuid4().hex}",
            username=username,
            is_admin=False,
            enabled=True,
            chat_tour_claimed=False,
            **await _password_fields(body.password),
        )
        client = self._storage.get_client()
        if not await client.hsetnx(
            _ACCOUNTS_KEY,
            username,
            account.model_dump_json(),
        ):
            raise HTTPException(409, "This username is already registered.")
        await self._ensure_default_agent(account.id)
        return account

    async def _claim_chat_tour(self, account: _Account) -> bool:
        if account.chat_tour_claimed:
            return False

        client = self._storage.get_client()
        while True:
            async with client.pipeline() as pipe:
                try:
                    await pipe.watch(_ACCOUNTS_KEY)
                    raw = await pipe.hget(_ACCOUNTS_KEY, account.username)
                    if raw is None:
                        raise _unauthorized("This login is no longer valid.")
                    current = _Account.model_validate_json(raw)
                    if (
                        not current.enabled
                        or current.session_version != account.session_version
                    ):
                        raise _unauthorized("This login is no longer valid.")
                    if current.chat_tour_claimed:
                        return False

                    current.chat_tour_claimed = True
                    pipe.multi()
                    pipe.hset(
                        _ACCOUNTS_KEY,
                        current.username,
                        current.model_dump_json(),
                    )
                    await pipe.execute()
                    return True
                except WatchError:
                    continue

    async def _login_response(self, account: _Account) -> LoginResponse:
        now = datetime.now(timezone.utc)
        token = jwt.encode(
            {
                "sub": account.id,
                "username": account.username,
                "ver": account.session_version,
                "iss": _ISSUER,
                "aud": _AUDIENCE,
                "iat": now,
                "exp": now + self._token_lifetime,
            },
            self._secret,
            algorithm="HS256",
        )
        return LoginResponse(
            access_token=token,
            user=account.public(),
            show_tour=await self._claim_chat_tour(account),
        )

    async def get_current_user(
        self,
        authorization: str | None = Header(default=None),
    ) -> AuthUser:
        scheme, _, token = (authorization or "").partition(" ")
        if scheme.lower() != "bearer" or not token:
            raise _unauthorized("Bearer access token is required.")
        try:
            claims = jwt.decode(
                token,
                self._secret,
                algorithms=["HS256"],
                issuer=_ISSUER,
                audience=_AUDIENCE,
                options={"require": ["sub", "username", "ver", "iat", "exp"]},
            )
        except jwt.InvalidTokenError as exc:
            raise _unauthorized("Invalid or expired access token.") from exc

        username = claims["username"]
        if not isinstance(username, str):
            raise _unauthorized("Invalid access token identity.")
        account = await self._account(username)
        if (
            account is None
            or not account.enabled
            or account.id != claims["sub"]
            or account.session_version != claims["ver"]
        ):
            raise _unauthorized("This login is no longer valid.")
        return account.public()

    async def get_current_user_id(
        self,
        authorization: str | None = Header(default=None),
    ) -> str:
        return (await self.get_current_user(authorization)).id

    async def _update_account(
        self,
        username: str,
        changes: dict[str, str | bool],
    ) -> AuthUser:
        client = self._storage.get_client()
        while True:
            async with client.pipeline() as pipe:
                try:
                    await pipe.watch(_ACCOUNTS_KEY)
                    raw = await pipe.hget(_ACCOUNTS_KEY, username)
                    if raw is None:
                        raise HTTPException(404, "Account not found.")
                    account = _Account.model_validate_json(raw)
                    if account.is_admin and changes.get("enabled") is False:
                        raise HTTPException(
                            409,
                            "The administrator cannot be disabled.",
                        )
                    if changes == {"enabled": account.enabled}:
                        return account.public()
                    updated = account.model_copy(
                        update={**changes, "session_version": uuid4().hex},
                    )
                    pipe.multi()
                    pipe.hset(
                        _ACCOUNTS_KEY,
                        username,
                        updated.model_dump_json(),
                    )
                    await pipe.execute()
                    return updated.public()
                except WatchError:
                    continue

    def _build_router(self) -> APIRouter:
        @asynccontextmanager
        async def lifespan(_app: FastAPI):
            await self._initialize()
            yield

        router = APIRouter(lifespan=lifespan)

        async def require_admin(
            user: AuthUser = Depends(self.get_current_user),
        ) -> None:
            if not user.is_admin:
                raise HTTPException(403, "Administrator access is required.")

        auth = APIRouter(prefix="/auth", tags=["auth"])

        @auth.get("/health", status_code=status.HTTP_204_NO_CONTENT)
        async def health() -> Response:
            return Response(status_code=status.HTTP_204_NO_CONTENT)

        @auth.post("/login")
        async def login(body: LoginRequest) -> LoginResponse:
            return await self._login_response(await self._authenticate(body))

        @auth.post("/register", status_code=status.HTTP_201_CREATED)
        async def register(body: RegisterRequest) -> LoginResponse:
            return await self._login_response(await self._register(body))

        @auth.get("/me")
        async def me(
            user: AuthUser = Depends(self.get_current_user),
        ) -> AuthUser:
            await self._ensure_default_agent(user.id)
            return user

        @auth.get("/usage")
        async def usage(
            user: AuthUser = Depends(self.get_current_user),
        ) -> TokenUsage:
            return await get_token_usage(self._storage, user.id)

        admin = APIRouter(
            prefix="/admin/users",
            tags=["user management"],
            dependencies=[Depends(require_admin)],
        )

        @admin.get("")
        async def list_users() -> list[AuthUser]:
            records = await self._storage.get_client().hvals(_ACCOUNTS_KEY)
            users = [
                _Account.model_validate_json(raw).public() for raw in records
            ]
            return sorted(
                users,
                key=lambda user: (not user.is_admin, user.username.casefold()),
            )

        @admin.patch("/password")
        async def reset_password(
            username: str, body: PasswordRequest
        ) -> AuthUser:
            return await self._update_account(
                username,
                await _password_fields(body.password),
            )

        @admin.patch("/status")
        async def update_status(
            username: str, body: AccountStatusRequest
        ) -> AuthUser:
            return await self._update_account(
                username,
                {"enabled": body.enabled},
            )

        @admin.get("/usage")
        async def user_usage(
            username: str,
            days: Literal["7", "30"] = "30",
        ) -> TokenUsage:
            account = await self._account(username)
            if account is None:
                raise HTTPException(404, "Account not found.")
            return await get_token_usage(
                self._storage, account.id, days=int(days)
            )

        router.include_router(auth)
        router.include_router(admin)
        return router


def load_auth_from_env(*, storage: RedisStorage) -> JWTAuthService:
    return JWTAuthService(
        storage,
        os.getenv(
            "AGENTSCOPE_JWT_SECRET",
            "change-me-in-production-use-32-bytes",
        ),
        int(os.getenv("AGENTSCOPE_JWT_EXPIRE_MINUTES", "1440")),
    )
