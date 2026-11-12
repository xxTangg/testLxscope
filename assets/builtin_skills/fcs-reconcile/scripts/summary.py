"""summary —— 汇总字典（唯一进 AI 出口）+ 勾稽（技术设计 §7.2）。无交易明细。

只有本模块产出的 summary 可上交上层/AI。原始行、单元格值、DataFrame、标准行
**绝不**序列化进模型上下文（技术设计 §2.1）。

summary 仅含：计数、比率、金额合计、各状态分布、勾稽结论、错误码等汇总量。

勾稽（NFR-01，技术设计 §7.2）：
  数量勾稽：左表行数 = Σ(各状态左侧计数)；右表行数 = Σ(各状态右侧计数)。
  金额勾稽：左金额合计 − 右金额合计 = Σ 金额差异（Decimal）。
"""

from __future__ import annotations

from collections import Counter
from decimal import Decimal

from models import MatchOutcome, Status


def _outcome_diff(o: MatchOutcome) -> Decimal:
    """单个 outcome 的金额差：配对用 matcher 的 amount_diff（真实交叉校验），单边用原始金额差。"""
    if o.amount_diff is not None:
        return o.amount_diff
    left_amt = o.left.amount if o.left and o.left.amount is not None else Decimal(0)
    right_amt = o.right.amount if o.right and o.right.amount is not None else Decimal(0)
    return left_amt - right_amt


def build_summary(
    outcomes: list[MatchOutcome], left_total_rows: int, right_total_rows: int
) -> dict[str, object]:
    """从匹配结果构建汇总字典（不含任何交易明细）。

    Args:
        outcomes: 匹配结果列表（各状态的MatchOutcome）。
        left_total_rows: 左表总行数。
        right_total_rows: 右表总行数。

    Returns:
        包含汇总信息的字典：counts、match_rate、quantity_reconciled、amount_reconciled、
        left_amount_total、right_amount_total、sum_amount_diff（金额均为字符串化Decimal）。
    """
    counts = Counter(o.status.value for o in outcomes)
    left_present = sum(1 for o in outcomes if o.left is not None)
    right_present = sum(1 for o in outcomes if o.right is not None)

    left_total = sum(
        (o.left.amount for o in outcomes if o.left and o.left.amount is not None),
        Decimal(0),
    )
    right_total = sum(
        (o.right.amount for o in outcomes if o.right and o.right.amount is not None),
        Decimal(0),
    )
    sum_diff = sum((_outcome_diff(o) for o in outcomes), Decimal(0))

    total = len(outcomes)
    auto = counts.get(Status.AUTO_MATCHED.value, 0)
    quantity_ok = left_present == left_total_rows and right_present == right_total_rows
    return {
        "counts": {s.value: counts.get(s.value, 0) for s in Status},
        "match_rate": (f"{auto / total:.4f}" if total else "0"),
        "quantity_reconciled": quantity_ok,
        "amount_reconciled": (left_total - right_total) == sum_diff,
        "left_amount_total": str(left_total),
        "right_amount_total": str(right_total),
        "sum_amount_diff": str(sum_diff),
    }
