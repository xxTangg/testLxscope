"""reporter —— 生成 7 张中文工作表（技术设计 §7 / 输出契约）。"""
from __future__ import annotations

from typing import Any

from models import ResultItem
from openpyxl import Workbook

_SHEETS = ["对账总览", "待处理事项", "已匹配", "重复与冲突", "数据质量", "审计明细", "运行参数"]
_PENDING_COLS = ["优先级", "问题类型", "业务编号", "左侧金额", "右侧金额", "金额差异",
                 "判断依据", "建议动作", "来源行", "复核状态", "复核人", "复核意见"]


def _rows_for(items: list[ResultItem], sheet: str) -> list[ResultItem]:
    return [i for i in items if i.sheet == sheet]


def write_workbook(
    items: list[ResultItem], summary: dict[str, Any], run_params: dict[str, Any], path: str
) -> None:
    wb = Workbook()
    ws = {
        name: (wb.active if idx == 0 else wb.create_sheet(name))
        for idx, name in enumerate(_SHEETS)
    }
    ws["对账总览"].title = "对账总览"

    # 对账总览 + 隐私运行摘要
    ov = ws["对账总览"]
    ov.append(["对账总览"])
    ov.append(["匹配率", summary["match_rate"]])
    ov.append(["数量勾稽", "通过" if summary["quantity_reconciled"] else "不通过"])
    ov.append(["金额勾稽", "通过" if summary["amount_reconciled"] else "不通过"])
    ov.append(["左金额合计", summary["left_amount_total"]])
    ov.append(["右金额合计", summary["right_amount_total"]])
    for status, cnt in summary["counts"].items():
        ov.append([status, cnt])
    ov.append([])
    ov.append(["隐私运行摘要"])
    ov.append(["运行模式", "本地隔离"])
    ov.append(["原始数据进入模型", "否"])
    ov.append(["网络访问", "已禁用"])
    ov.append(["源文件修改", "否"])

    # 待处理事项
    pend = ws["待处理事项"]
    pend.append(_PENDING_COLS)
    for i in _rows_for(items, "待处理事项"):
        pend.append([i.priority, i.status.value, i.no, _s(i.amount_left), _s(i.amount_right),
                     _s(i.amount_diff), i.basis, i.suggested_action,
                     f"L{i.left_source_row or ''}/R{i.right_source_row or ''}", "待复核", "", ""])

    # 已匹配
    matched = ws["已匹配"]
    matched.append(["业务编号", "左侧金额", "右侧金额", "匹配依据", "来源行"])
    for i in _rows_for(items, "已匹配"):
        matched.append([i.no, _s(i.amount_left), _s(i.amount_right), i.basis,
                        f"L{i.left_source_row}/R{i.right_source_row}"])

    # 重复与冲突
    conf = ws["重复与冲突"]
    conf.append(["业务编号", "状态", "候选清单", "冲突原因"])
    for i in _rows_for(items, "重复与冲突"):
        cand = "; ".join(f"row{c.row_id}:{c.no}" for c in i.candidates)
        conf.append([i.no, i.status.value, cand, i.basis])

    # 数据质量
    dq = ws["数据质量"]
    dq.append(["问题类型", "业务编号", "来源行"])
    for i in _rows_for(items, "数据质量"):
        dq.append([i.status.value, i.no, f"L{i.left_source_row or ''}/R{i.right_source_row or ''}"])

    # 审计明细
    audit = ws["审计明细"]
    audit.append(["状态", "业务编号", "左侧金额", "右侧金额", "金额差异", "命中规则", "来源行"])
    for i in items:
        audit.append([i.status.value, i.no, _s(i.amount_left), _s(i.amount_right),
                      _s(i.amount_diff), i.basis,
                      f"L{i.left_source_row or ''}/R{i.right_source_row or ''}"])

    # 运行参数
    rp = ws["运行参数"]
    rp.append(["参数", "值"])
    for k, v in run_params.items():
        rp.append([k, str(v)])

    wb.save(path)


def _s(v: object) -> str:
    return "" if v is None else str(v)
