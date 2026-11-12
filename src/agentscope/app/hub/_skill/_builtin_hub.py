# -*- coding: utf-8 -*-
"""An offline catalog backed by reviewed skill directories in the image."""

import hashlib
import io
import json
from pathlib import Path
import zipfile
from uuid import NAMESPACE_URL, uuid5

import frontmatter

from ._base import SkillArchive, SkillHubBase
from ._card import SkillCard, SkillHubPage
from ...storage import SkillRecord

BUILTIN_MARKER = ".agentscope-builtin.json"


class BuiltinSkillHub(SkillHubBase):
    """Serve a pinned, local catalog without contacting a registry.

    ``manifest.json`` lists the reviewed directories and their display fields.
    Archives record that a skill was explicitly added to a workspace, so
    they can be distinguished from legacy copies installed automatically.
    """

    def __init__(self, directory: str | Path, hub_id: str = "builtin") -> None:
        super().__init__(
            hub_id,
            "系统内置",
            "默认提供给所有用户的内网办公技能；卸载仅影响当前账号，可随时重新安装。",
        )
        self._root = Path(directory).resolve()
        manifest = json.loads(
            (self._root / "manifest.json").read_text("utf-8")
        )
        self.cards: dict[str, SkillCard] = {}
        self._archives: dict[str, bytes] = {}
        for item in manifest["skills"]:
            name = item["name"]
            directory_path = (self._root / name).resolve()
            if (
                directory_path.parent != self._root
                or not directory_path.is_dir()
            ):
                raise ValueError(f"Invalid built-in skill directory: {name!r}")
            parsed = frontmatter.loads(
                (directory_path / "SKILL.md").read_text("utf-8-sig"),
            )
            if parsed.get("name") != name or not parsed.get("description"):
                raise ValueError(f"Invalid built-in skill metadata: {name!r}")
            files = sorted(
                p
                for p in directory_path.rglob("*")
                if p.is_file()
                and "__pycache__" not in p.parts
                and p.suffix not in {".pyc", ".pyo"}
                and p.name != BUILTIN_MARKER
            )
            digest = hashlib.sha256()
            for path in files:
                if path.is_symlink() or not path.resolve().is_relative_to(
                    directory_path
                ):
                    raise ValueError(f"Unsafe built-in skill file: {path}")
                digest.update(
                    path.relative_to(directory_path).as_posix().encode()
                )
                digest.update(b"\0")
                digest.update(path.read_bytes())
            version = digest.hexdigest()[:16]
            self.cards[name] = SkillCard(
                hub_id=self.hub_id,
                id=name,
                name=name,
                display_name=item["display_name"],
                description=str(parsed["description"]),
                markdown=parsed.content,
                tags=["系统内置", *item.get("tags", [])],
                author=item.get("author"),
                url=item.get("url"),
                version=version,
                metadata={"builtin": True, "license": item["license"]},
            )
            buffer = io.BytesIO()
            with zipfile.ZipFile(buffer, "w", zipfile.ZIP_DEFLATED) as archive:
                for path in files:
                    archive.write(
                        path, path.relative_to(directory_path).as_posix()
                    )
                archive.writestr(
                    BUILTIN_MARKER,
                    json.dumps(
                        {
                            "hub_id": self.hub_id,
                            "card_id": name,
                            "version": version,
                            "added_to_workspace": True,
                        }
                    ),
                )
            self._archives[name] = buffer.getvalue()

    def record(self, user_id: str, card_id: str) -> SkillRecord:
        """Return a stable per-user default without writing to storage."""
        card = self.cards[card_id]
        return SkillRecord(
            id=uuid5(
                NAMESPACE_URL,
                f"agentscope:builtin:{self.hub_id}:{user_id}:{card_id}",
            ).hex,
            user_id=user_id,
            name=card.name,
            display_name=card.display_name,
            description=card.description,
            markdown=card.markdown or "",
            tags=card.tags,
            author=card.author,
            url=card.url,
            hub_id=self.hub_id,
            card_id=card.id,
            version=card.version,
        )

    async def list_skills(self, user_id, q=None, cursor=None, limit=20):
        needle = (q or "").strip().casefold()
        cards = [
            card
            for card in self.cards.values()
            if not needle
            or needle
            in " ".join(
                [
                    card.name,
                    card.display_name or "",
                    card.description,
                    *card.tags,
                ],
            ).casefold()
        ]
        offset = int(cursor or 0)
        if offset < 0 or limit < 1:
            raise ValueError("Invalid catalog pagination")
        end = offset + limit
        return SkillHubPage(
            cards=[
                card.model_copy(update={"markdown": None})
                for card in cards[offset:end]
            ],
            next_cursor=str(end) if end < len(cards) else None,
        )

    async def get_skill(self, user_id, card_id):
        return self.cards[card_id].model_copy(deep=True)

    async def download(self, user_id, card_id, version=None):
        card = self.cards[card_id]
        if version is not None and version != card.version:
            raise ValueError(
                "This built-in skill version is no longer bundled"
            )

        async def stream():
            payload = self._archives[card_id]
            for offset in range(0, len(payload), 65536):
                yield payload[offset : offset + 65536]

        return SkillArchive("zip", stream())
