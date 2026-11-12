"""config —— 字段映射与规则配置的加载与校验（技术设计 §3）。"""
from __future__ import annotations

from dataclasses import dataclass
from decimal import Decimal, InvalidOperation
from typing import Any

import integrity
import yaml  # PyYAML 随 pandas 生态常见；若未装，Task 0 用 `uv add pyyaml`


class ConfigError(ValueError):
    """配置非法：字段缺失/类型不可解析/输出覆盖输入等。"""


@dataclass(frozen=True)
class FieldMap:
    no: str
    amount: str
    date: str | None
    counterparty: str | None
    direction: str | None


@dataclass(frozen=True)
class TableSpec:
    file: str
    sheet: str | None
    header_row: int
    fields: FieldMap


@dataclass(frozen=True)
class MatchConfig:
    primary_key: str = "no"
    composite_keys: tuple[str, ...] = ()
    amount_tolerance: Decimal = Decimal("0.00")
    date_tolerance_days: int = 0
    direction_rule: str = "signed"
    amount_scale: int = 2


@dataclass(frozen=True)
class ReconcileConfig:
    left: TableSpec
    right: TableSpec
    match: MatchConfig
    output_path: str
    rule_version: str
    contract_version: str


_ALLOWED_MATCH_FIELDS = {"no", "amount", "date", "counterparty"}


def _validate_match(match: MatchConfig, left: FieldMap, right: FieldMap) -> None:
    if match.direction_rule not in {"signed", "none"}:
        raise ConfigError(f"direction_rule 必须为 signed 或 none：{match.direction_rule}")
    if match.direction_rule == "signed" and not (left.direction and right.direction):
        raise ConfigError(
            "direction_rule=signed 时左右表都必须配置 direction 字段"
            "（若金额已带正负号，请改用 direction_rule=none）"
        )
    if match.composite_keys:
        bad = sorted(set(match.composite_keys) - _ALLOWED_MATCH_FIELDS)
        if bad:
            raise ConfigError(
                f"composite_keys 含非法字段 {bad}（允许：{sorted(_ALLOWED_MATCH_FIELDS)}）"
            )
        if "amount" not in match.composite_keys:
            raise ConfigError("composite_keys 必须包含 amount，否则可能自动确认金额不一致的记录")


def _restore_field_keys(fields: dict[str, Any]) -> dict[str, Any]:
    # PyYAML(YAML 1.1) 把未加引号的 no/yes 解析为布尔、null 解析为 None。
    # 字段映射的 `no`（编号）键最易踩坑，这里把被误解析的键还原为字符串，
    # 使契约示例中未加引号的 `fields: {no: ...}` 也能正常工作。
    out: dict[str, Any] = {}
    for k, v in fields.items():
        if isinstance(k, bool):
            out["yes" if k else "no"] = v
        elif k is None:
            out["null"] = v
        else:
            out[k] = v
    return out


def _table(raw: dict[str, Any], side: str) -> TableSpec:
    try:
        f = _restore_field_keys(raw["fields"])
        return TableSpec(
            file=raw["file"],
            sheet=raw.get("sheet"),
            header_row=int(raw.get("header_row", 0)),
            fields=FieldMap(no=f["no"], amount=f["amount"], date=f.get("date"),
                            counterparty=f.get("counterparty"), direction=f.get("direction")),
        )
    except (KeyError, TypeError, ValueError, AttributeError) as e:
        raise ConfigError(f"{side} 表配置非法：{e}") from e


def load_config(path: str) -> ReconcileConfig:
    with open(path, encoding="utf-8") as fh:
        raw = yaml.safe_load(fh)
    if not isinstance(raw, dict):
        raise ConfigError("配置根节点必须为映射")

    left = _table(raw.get("left", {}), "左")
    right = _table(raw.get("right", {}), "右")
    m = raw.get("match") or {}
    if not isinstance(m, dict):
        raise ConfigError("match 配置必须为映射")
    try:
        tol = Decimal(str(m.get("amount_tolerance", "0.00")))
    except InvalidOperation as e:
        raise ConfigError(f"amount_tolerance 非合法 Decimal：{m.get('amount_tolerance')}") from e
    if not tol.is_finite() or tol < 0:
        raise ConfigError(f"amount_tolerance 必须为非负有限小数：{m.get('amount_tolerance')}")

    try:
        match = MatchConfig(
            primary_key=m.get("primary_key", "no"),
            composite_keys=tuple(m.get("composite_keys", []) or ()),
            amount_tolerance=tol,
            date_tolerance_days=int(m.get("date_tolerance_days", 0)),
            direction_rule=m.get("direction_rule", "signed"),
            amount_scale=int(m.get("amount_scale", 2)),
        )
    except (TypeError, ValueError) as e:
        raise ConfigError(f"match 配置非法：{e}") from e
    _validate_match(match, left.fields, right.fields)
    output_path = (raw.get("output") or {}).get("path")
    if not output_path:
        raise ConfigError("缺少 output.path")

    try:
        integrity.assert_output_not_overwrites_input(output_path, [left.file, right.file])
    except ValueError as e:
        raise ConfigError(str(e)) from e

    return ReconcileConfig(left=left, right=right, match=match, output_path=output_path,
                           rule_version=str(raw.get("rule_version", "1.0")),
                           contract_version=str(raw.get("contract_version", "1.0")))
