"""version —— 本 Skill 运行期版本号的唯一事实源（scripts/ 侧）。

运行清单（FT-08）必须记录 `skill_version`，它是审计证据的一部分。此前该值以字面量
硬编码在 `reconcile.py` 里，与 `SKILL_META.yaml` 各写一份，改版本时容易只改一处——
运行清单里的版本号一旦与实际发布版本不符，NFR-04/NFR-05 的可审计与可重复就失真了。

现在业务代码只从这里取，且由 `tests/supply_chain/test_version_consistency.py` 守卫本值
与 `SKILL_META.yaml`、`CHANGELOG.md`、`SKILL.md` 完全一致。
版本层级与 bump 时机见 `docs/governance/versioning.md`。

规则版本与契约版本不在此处：它们随运行配置传入（见 `config.py` 的 `rule_version` /
`contract_version`），因为同一份代码可以按不同规则版本运行。
"""
from __future__ import annotations

SKILL_VERSION = "0.3.0"
