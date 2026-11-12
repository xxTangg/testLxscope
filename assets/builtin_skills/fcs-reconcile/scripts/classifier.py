"""classifier —— 将匹配 outcome 富化为中文业务结果项（技术设计 §6）。"""
from __future__ import annotations

from models import PRIORITY, SHEET, MatchOutcome, ResultItem, Status

_ACTION = {
    Status.AUTO_MATCHED: "无需处理",
    Status.SUSPECT: "人工确认容差内差异是否可接受",
    Status.AMOUNT_DIFF: "核对金额差异来源",
    Status.LEFT_ONLY: "核对该笔是否漏记于右表",
    Status.RIGHT_ONLY: "核对该笔是否漏记于左表",
    Status.DUP_NO: "核对重复编号的真实对应关系",
    Status.MULTI_CANDIDATE: "人工从多个候选中选择正确对应",
    Status.DATA_QUALITY: "修正源数据质量问题后重跑",
}


def classify(outcomes: list[MatchOutcome]) -> list[ResultItem]:
    items: list[ResultItem] = []
    for o in outcomes:
        items.append(ResultItem(
            status=o.status,
            priority=PRIORITY[o.status],
            sheet=SHEET[o.status],
            no=(o.left.no if o.left else (o.right.no if o.right else None)),
            amount_left=(o.left.amount if o.left else None),
            amount_right=(o.right.amount if o.right else None),
            amount_diff=o.amount_diff,
            basis=o.rule,
            suggested_action=_ACTION[o.status],
            left_source_row=(o.left.source_row if o.left else None),
            right_source_row=(o.right.source_row if o.right else None),
            candidates=o.candidates,
        ))
    return items
