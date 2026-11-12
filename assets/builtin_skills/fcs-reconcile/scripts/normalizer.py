"""normalizer —— 金额/日期/编号/方向标准化（技术设计 §4）。金额绝不入 float。"""
from __future__ import annotations

import re
import unicodedata
from datetime import date, datetime
from decimal import ROUND_HALF_UP, Decimal, InvalidOperation

import pandas as pd
from config import FieldMap, MatchConfig
from models import StdRow


def _clean(raw: str | None) -> str | None:
    if raw is None:
        return None
    s = unicodedata.normalize("NFKC", str(raw)).strip()   # 全角→半角
    return s or None


def parse_amount(raw: str | None, scale: int) -> tuple[Decimal | None, str | None]:
    s = _clean(raw)
    if s is None:
        return None, "非法金额"
    s = s.replace(",", "").replace("￥", "").replace("¥", "").replace("$", "")
    try:
        value = Decimal(s).quantize(Decimal(1).scaleb(-scale), rounding=ROUND_HALF_UP)  # 四舍五入
    except (InvalidOperation, ValueError):
        return None, "非法金额"
    if not value.is_finite():   # 拒绝 NaN（Infinity 已在 quantize 抛错被拦）
        return None, "非法金额"
    return value, None


_DATE_FORMATS = ("%Y-%m-%d", "%Y/%m/%d", "%Y.%m.%d", "%Y%m%d")


def parse_date(raw: object) -> tuple[date | None, str | None]:
    if isinstance(raw, datetime):          # pandas Timestamp 亦是 datetime 子类
        return raw.date(), None
    if isinstance(raw, date):              # datetime 已在上一分支处理
        return raw, None
    if raw is None:
        return None, "非法日期"
    s = _clean(str(raw))
    if s is None:
        return None, "非法日期"
    for fmt in _DATE_FORMATS:
        try:
            return datetime.strptime(s, fmt).date(), None
        except ValueError:
            continue
    return None, "非法日期"


_SCI_RE = re.compile(r"^\d+(\.\d+)?[eE][+-]?\d+$")


def normalize_no(raw: str | None) -> tuple[str | None, tuple[str, ...]]:
    s = _clean(raw)
    if s is None:
        return None, ("空编号",)
    flags: tuple[str, ...] = ()
    if _SCI_RE.match(s) or (s.isdigit() and len(s) >= 16):
        flags = ("危险长编号",)   # 曾被 Excel 转科学计数法/丢精度，保留原值不修复
    return s, flags


_POSITIVE = {"收", "借", "收入", "借方"}
_NEGATIVE = {"付", "贷", "支出", "付款", "贷方"}


def normalize_direction(amount: Decimal | None, direction_raw: str | None,
                        rule: str) -> tuple[Decimal | None, str | None]:
    if rule != "signed":
        return amount, None
    d = _clean(direction_raw)
    if d in _POSITIVE:
        return (abs(amount) if amount is not None else None), None
    if d in _NEGATIVE:
        return (-abs(amount) if amount is not None else None), None
    return amount, "方向缺失"


def _raw_cell(r: pd.Series, columns: set[str], col: str | None) -> object:
    """取原始单元格值；缺列或 pandas NA（NaN/NaT/NA）一律视为缺失 → None。"""
    if not col or col not in columns:
        return None
    val = r[col]
    return None if pd.isna(val) else val


def _str_cell(r: pd.Series, columns: set[str], col: str | None) -> str | None:
    """取字符串单元格：缺失 → None；否则去空白，空串归 None。"""
    val = _raw_cell(r, columns, col)
    if val is None:
        return None
    s = str(val).strip()
    return s or None


def normalize(df: pd.DataFrame, fields: FieldMap, match: MatchConfig) -> list[StdRow]:
    """组装 StdRow 列表，聚合各字段质量标记。

    row_id 按行序从 0 开始；source_row = i + 2（表头占第 1 行）。
    空/缺失单元格（含 pandas NaN）视为缺失，交各字段解析器标记质量问题；
    日期传原始值（保留 Timestamp/date），不提前字符串化。
    """
    columns = set(df.columns)
    rows: list[StdRow] = []
    for i, (_, r) in enumerate(df.iterrows()):
        no, no_flags = normalize_no(_str_cell(r, columns, fields.no))
        amount, amt_flag = parse_amount(_str_cell(r, columns, fields.amount), match.amount_scale)
        d: date | None
        date_flag: str | None
        if fields.date:
            d, date_flag = parse_date(_raw_cell(r, columns, fields.date))
        else:
            d, date_flag = None, None
        amount, dir_flag = normalize_direction(
            amount, _str_cell(r, columns, fields.direction), match.direction_rule
        )
        flags: tuple[str, ...] = tuple(
            f for f in (*no_flags, amt_flag, date_flag, dir_flag) if f
        )
        rows.append(
            StdRow(
                row_id=i,
                source_row=i + 2,
                no=no,
                amount=amount,
                date=d,
                counterparty=_str_cell(r, columns, fields.counterparty),
                direction_raw=_str_cell(r, columns, fields.direction),
                quality_flags=flags,
            )
        )
    return rows
