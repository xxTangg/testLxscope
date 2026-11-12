"""共享数据类型（平铺模块，不包化）。"""
from __future__ import annotations

from dataclasses import dataclass
from datetime import date
from decimal import Decimal
from enum import StrEnum


class Status(StrEnum):
    AUTO_MATCHED = "已自动匹配"
    SUSPECT = "疑似匹配"
    AMOUNT_DIFF = "金额差异"
    LEFT_ONLY = "左侧单边"
    RIGHT_ONLY = "右侧单边"
    DUP_NO = "重复编号"
    MULTI_CANDIDATE = "多候选冲突"
    DATA_QUALITY = "数据质量问题"


@dataclass(frozen=True)
class StdRow:
    row_id: int                       # 读取顺序稳定分配（同侧唯一）
    source_row: int                   # 源文件行号（审计追溯）
    no: str | None
    amount: Decimal | None            # 方向归一后的带符号金额；None=解析失败
    date: date | None
    counterparty: str | None
    direction_raw: str | None         # 归一前原始方向（审计）
    quality_flags: tuple[str, ...] = ()


@dataclass(frozen=True)
class MatchOutcome:
    status: Status
    left: StdRow | None = None
    right: StdRow | None = None
    amount_diff: Decimal | None = None    # 有配对时 = left.amount - right.amount
    candidates: tuple[StdRow, ...] = ()   # 冲突时的竞争候选（上下文）
    rule: str = ""                        # 命中规则标识（审计）


@dataclass(frozen=True)
class ResultItem:
    status: Status
    priority: str
    sheet: str
    no: str | None
    amount_left: Decimal | None
    amount_right: Decimal | None
    amount_diff: Decimal | None
    basis: str                            # 判断依据
    suggested_action: str                 # 建议动作
    left_source_row: int | None
    right_source_row: int | None
    candidates: tuple[StdRow, ...] = ()


PRIORITY: dict[Status, str] = {
    Status.AUTO_MATCHED: "—",
    Status.SUSPECT: "高",
    Status.AMOUNT_DIFF: "高",
    Status.MULTI_CANDIDATE: "高",
    Status.DATA_QUALITY: "高",
    Status.LEFT_ONLY: "中",
    Status.RIGHT_ONLY: "中",
    Status.DUP_NO: "中",
}

SHEET: dict[Status, str] = {
    Status.AUTO_MATCHED: "已匹配",
    Status.SUSPECT: "待处理事项",
    Status.AMOUNT_DIFF: "待处理事项",
    Status.LEFT_ONLY: "待处理事项",
    Status.RIGHT_ONLY: "待处理事项",
    Status.DUP_NO: "重复与冲突",
    Status.MULTI_CANDIDATE: "重复与冲突",
    Status.DATA_QUALITY: "数据质量",
}
