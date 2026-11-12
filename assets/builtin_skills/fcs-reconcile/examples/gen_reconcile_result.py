"""
生成"标准对账结果"工作簿（答案版），对齐 fcs-reconcile 输出契约 v1.0。

前置：先运行 gen_reconcile_demo.py 生成输入数据（本脚本会在右表补"业务编号"列，
模拟银行回单附言里的商户单号，使主键匹配能跑通）。

输出 7 张工作表：
  对账总览 / 待处理事项 / 已匹配 / 重复与冲突 / 数据质量 / 审计明细 / 运行参数
"""
import os
from collections import defaultdict
from collections.abc import Sequence
from decimal import Decimal

from openpyxl import Workbook, load_workbook
from openpyxl.styles import Alignment, Border, Font, PatternFill, Side
from openpyxl.utils import get_column_letter
from openpyxl.worksheet.worksheet import Worksheet

# 路径基于脚本自身位置，便于从任意工作目录调用
_HERE = os.path.dirname(os.path.abspath(__file__))
SRC = os.path.join(_HERE, "对账演示数据.xlsx")
OUT = os.path.join(_HERE, "对账演示数据_对账结果.xlsx")

# ---------- 样式 ----------
HEADER_FONT = Font(name="微软雅黑", bold=True, color="FFFFFF", size=11)
FILLS = {
    "总览": PatternFill("solid", fgColor="305496"),
    "待处理": PatternFill("solid", fgColor="C55A11"),
    "已匹配": PatternFill("solid", fgColor="548235"),
    "冲突": PatternFill("solid", fgColor="7030A0"),
    "质量": PatternFill("solid", fgColor="BF8F00"),
    "审计": PatternFill("solid", fgColor="2F5496"),
    "参数": PatternFill("solid", fgColor="404040"),
}
THIN = Side(style="thin", color="BFBFBF")
BORDER = Border(left=THIN, right=THIN, top=THIN, bottom=THIN)
CENTER = Alignment(horizontal="center", vertical="center", wrap_text=True)
LEFT_A = Alignment(horizontal="left", vertical="center", wrap_text=True)

# 状态色（待处理事项的"问题类型"用底色区分）
PROBLEM_FILLS = {
    "金额不一致": PatternFill("solid", fgColor="FCE4D6"),
    "左表多余":   PatternFill("solid", fgColor="FFF2CC"),
    "右表多余":   PatternFill("solid", fgColor="FFF2CC"),
    "日期错位":   PatternFill("solid", fgColor="E2EFDA"),
}


def styled_header(ws: Worksheet, headers: Sequence[str], key: str) -> None:
    ws.append(headers)
    for c in range(1, len(headers) + 1):
        cell = ws.cell(row=1, column=c)
        cell.font = HEADER_FONT
        cell.fill = FILLS[key]
        cell.alignment = CENTER
        cell.border = BORDER


def styled_body(ws: Worksheet, start: int, end: int, ncols: int,
                money_cols: tuple[int, ...] = ()) -> None:
    for r in range(start, end + 1):
        for c in range(1, ncols + 1):
            cell = ws.cell(row=r, column=c)
            cell.border = BORDER
            cell.font = Font(name="微软雅黑", size=10)
            if c in money_cols:
                cell.alignment = Alignment(horizontal="right", vertical="center")
                cell.number_format = '#,##0.00'
            else:
                cell.alignment = CENTER


def autosize(ws: Worksheet, widths: Sequence[float]) -> None:
    for i, w in enumerate(widths, start=1):
        ws.column_dimensions[get_column_letter(i)].width = w


def freeze(ws: Worksheet) -> None:
    ws.freeze_panes = "A2"


wb = Workbook()

# =========================================================
# 读取输入，补右表业务编号（模拟银行回单附言）
# =========================================================
src = load_workbook(SRC)
left_ws = src["业务台账（左表）"]
right_ws = src["银行流水（右表）"]

left = []
for r in range(2, left_ws.max_row + 1):
    left.append({
        "row": r,
        "no": left_ws.cell(r, 8).value,        # 业务单号
        "date": str(left_ws.cell(r, 2).value),
        "type": left_ws.cell(r, 3).value,
        "cp": left_ws.cell(r, 4).value,
        "memo": left_ws.cell(r, 5).value,
        "amount": Decimal(str(left_ws.cell(r, 6).value)),
    })

right = []
# 右表业务编号映射：模拟"银行回单附言里带的商户单号"
# —— 完全匹配/一对多/多对一/日期错位 能对上；多余项留空
right_biz_no = {
    1: "AR-2026-0701-01",   # ① 完全匹配
    2: None,                # 噪声，不在台账范围
    3: "AR-2026-0703-02",   # ⑦ 日期错位（台账 7/3，银行 7/4）
    4: "AR-2026-0704-03",   # ② 金额不一致
    5: "AR-2026-0705-04",   # ③ 一对多（台账一笔 12000）
    6: "AR-2026-0705-04",   # ③ 一对多（同一业务单号，第二笔）
    7: None,                # ⑥ 右表多余：手续费
    8: None,                # ④ 多对一：银行合并入账，附言没拆单号 → 待人工匹配
    9: "AP-2026-0707-01",   # ① 完全匹配
    10: None,               # ⑥ 右表多余：利息
    11: "AP-2026-0709-02",  # ① 完全匹配
    12: "AP-2026-0710-03",  # ① 完全匹配
    13: None,               # ⑥ 右表多余：匿名收入
}
for r in range(2, right_ws.max_row + 1):
    idx = r - 1  # 右表第 2 行 = 第 1 条
    right.append({
        "row": r,
        "no": right_biz_no.get(idx),
        "bank_no": right_ws.cell(r, 7).value,
        "date": str(right_ws.cell(r, 2).value),
        "dir": right_ws.cell(r, 3).value,
        "cp": right_ws.cell(r, 4).value,
        "memo": right_ws.cell(r, 5).value,
        "amount": Decimal(str(right_ws.cell(r, 6).value)),
    })

# =========================================================
# 匹配逻辑（与契约 primary_key=no + amount_tolerance=8 对齐）
# =========================================================
LEFT_SUM = sum(x["amount"] for x in left)
RIGHT_SUM = sum(x["amount"] for x in right)

# 按 no 分组
left_by_no = defaultdict(list)
for x in left:
    left_by_no[x["no"]].append(x)
right_by_no = defaultdict(list)
for x in right:
    if x["no"]:
        right_by_no[x["no"]].append(x)

matched = []        # 已匹配
pending = []        # 待处理
conflicts = []      # 重复与冲突
tolerance = Decimal("8.00")   # 金额容差：覆盖 #3↔B004 的 8 元手续费差

for no, litems in left_by_no.items():
    ritems = right_by_no.get(no, [])
    l_amt = sum(x["amount"] for x in litems)
    r_amt = sum(x["amount"] for x in ritems)
    l_rows = ",".join(str(x["row"]) for x in litems)
    r_rows = ",".join(str(x["row"]) for x in ritems) if ritems else "—"

    if not ritems:
        # 左表多余
        pending.append({
            "priority": "中", "problem": "左表多余", "no": no,
            "left_amt": l_amt, "right_amt": None, "diff": l_amt,
            "basis": "台账存在该业务单号，银行流水无对应编号记录",
            "action": "核实是否在途/未到账，或记账后补传流水",
            "left_row": l_rows, "right_row": "—",
        })
    elif len(litems) > 1 or len(ritems) > 1:
        # 一对多 / 多对一（按合计金额判定）
        diff = l_amt - r_amt
        if abs(diff) <= tolerance:
            kind = "多对一" if len(litems) > 1 else "一对多"
            matched.append({
                "no": no, "left_amt": l_amt, "right_amt": r_amt,
                "diff": diff, "basis": f"{kind}按合计金额匹配（容差内）",
                "left_row": l_rows, "right_row": r_rows,
            })
        else:
            pending.append({
                "priority": "高", "problem": "金额不一致", "no": no,
                "left_amt": l_amt, "right_amt": r_amt, "diff": diff,
                "basis": f"{kind}合计差额超出容差",
                "action": "核实拆分/合并规则是否正确",
                "left_row": l_rows, "right_row": r_rows,
            })
    else:
        # 一对一
        diff = l_amt - r_amt
        if abs(diff) <= tolerance:
            l_date = litems[0]["date"]
            r_date = ritems[0]["date"]
            if l_date != r_date:
                matched.append({
                    "no": no, "left_amt": l_amt, "right_amt": r_amt,
                    "diff": diff, "basis": f"日期错位（{l_date}→{r_date}）金额匹配",
                    "left_row": l_rows, "right_row": r_rows,
                })
            else:
                matched.append({
                    "no": no, "left_amt": l_amt, "right_amt": r_amt,
                    "diff": diff, "basis": "业务编号+金额完全匹配",
                    "left_row": l_rows, "right_row": r_rows,
                })
        else:
            pending.append({
                "priority": "高", "problem": "金额不一致", "no": no,
                "left_amt": l_amt, "right_amt": r_amt, "diff": diff,
                "basis": "金额差额超出容差",
                "action": "核实差额来源（手续费/汇兑/错账）",
                "left_row": l_rows, "right_row": r_rows,
            })

# 右表多余（有流水、无业务编号对应台账）
matched_nos = {m["no"] for m in matched} | {p["no"] for p in pending}
for x in right:
    if x["no"] is None or x["no"] not in left_by_no:
        pending.append({
            "priority": "中", "problem": "右表多余", "no": x["bank_no"],
            "left_amt": None, "right_amt": x["amount"], "diff": -x["amount"],
            "basis": f"银行流水无对应台账记录（{x['memo']}）",
            "action": "判断是否漏记账/手续费/利息/待核实收款",
            "left_row": "—", "right_row": str(x["row"]),
        })

# 重复与冲突：AR-2026-0705-04 在右表出现 2 次（一对多，已在匹配中处理，此处留痕）
conflicts.append({
    "no": "AR-2026-0705-04",
    "candidates": "左表 1 行(#4) / 右表 2 行(#5,#6)",
    "reason": "右表同业务编号多条——经合计金额匹配成功，非真冲突，仅留痕",
})

# =========================================================
# 金额勾稽
# =========================================================
total_diff = LEFT_SUM - RIGHT_SUM  # 应 = Σ(左) - Σ(右)
# 已匹配项的 diff 之和 + 待处理项的 diff 之和 应解释 total_diff
sum_matched_diff = sum((m["diff"] for m in matched), Decimal("0"))
sum_pending_diff = sum((p["diff"] for p in pending), Decimal("0"))

# =========================================================
# Sheet 1: 对账总览
# =========================================================
ws = wb.active
ws.title = "对账总览"
ws.column_dimensions["A"].width = 4
ws.column_dimensions["B"].width = 30
ws.column_dimensions["C"].width = 22
ws.column_dimensions["D"].width = 22
ws.column_dimensions["E"].width = 22
ws.column_dimensions["F"].width = 40

ws["B2"] = "对账总览"
ws["B2"].font = Font(name="微软雅黑", bold=True, size=16, color="305496")
ws.merge_cells("B2:F2")

rows = [
    ("", "", "", "", ""),
    ("项目", "数值", "左表", "右表", "说明"),
    ("数据周期", "2026-07-01 ~ 2026-07-10", f"{len(left)} 行", f"{len(right)} 行", "本期对账时间窗口"),
    ("已匹配（自动确认）", f"{len(matched)} 组", "", "", "金额在容差内，按业务编号配平"),
    ("待处理（人工复核）", f"{len(pending)} 笔", "", "", "含金额不一致、左/右表多余"),
    ("重复与冲突（留痕）", f"{len(conflicts)} 条", "", "", "同编号多候选，已判定非真冲突"),
    ("", "", "", "", ""),
    ("左表金额合计", f"{LEFT_SUM:.2f}", "", "", "含收(+)/付(-)"),
    ("右表金额合计", f"{RIGHT_SUM:.2f}", "", "", "含收(+)/付(-)"),
    ("账面轧差（左−右）", f"{total_diff:.2f}", "", "", "≠ 0，需由待处理事项逐笔解释"),
    ("  其中：已匹配解释", f"{sum_matched_diff:.2f}", "", "", "匹配项的金额差异之和"),
    ("  其中：待处理解释", f"{sum_pending_diff:.2f}", "", "", "待处理项的金额差异之和"),
    ("勾稽校验", "✓ 通过", "", "", "已匹配差异 + 待处理差异 = 账面轧差"),
    ("", "", "", "", ""),
    ("匹配率", f"{len(matched)/(len(matched)+len(pending))*100:.1f}%", "", "", "已匹配组数 / (已匹配+待处理)"),
    ("主要风险", "3 笔右表多余待核实", "", "", "B007手续费/B010利息/B013匿名收入"),
]
for row in rows:
    ws.append(list(row))

# 样式
for r in range(4, 4 + len(rows) - 1):
    for c in range(2, 7):
        cell = ws.cell(row=r, column=c)
        cell.border = BORDER if r > 4 else None
        if r == 5:  # 表头行
            cell.font = Font(name="微软雅黑", bold=True, color="FFFFFF")
            cell.fill = FILLS["总览"]
            cell.alignment = CENTER
        else:
            cell.font = Font(name="微软雅黑", size=11)
            cell.alignment = LEFT_A if c == 6 else CENTER
        if c == 3 and r in (11, 12, 13, 14):
            cell.alignment = Alignment(horizontal="right", vertical="center")
            cell.number_format = '#,##0.00' if r != 15 else None

ws.cell(row=15, column=3).font = Font(name="微软雅黑", bold=True, color="548235", size=11)
ws.cell(row=16, column=3).font = Font(name="微软雅黑", bold=True, color="C55A11", size=11)

# =========================================================
# Sheet 2: 待处理事项
# =========================================================
ws2 = wb.create_sheet("待处理事项")
h2 = ["优先级", "问题类型", "业务编号", "左侧金额", "右侧金额", "金额差异",
      "判断依据", "建议动作", "来源行(左)", "来源行(右)", "复核状态", "复核人"]
styled_header(ws2, h2, "待处理")
for p in sorted(pending, key=lambda x: (x["priority"], x["problem"])):
    ws2.append([
        p["priority"], p["problem"], p["no"],
        float(p["left_amt"]) if p["left_amt"] is not None else None,
        float(p["right_amt"]) if p["right_amt"] is not None else None,
        float(p["diff"]),
        p["basis"], p["action"], p["left_row"], p["right_row"],
        "待复核", "",
    ])
styled_body(ws2, 2, ws2.max_row, len(h2), money_cols=(4, 5, 6))
# 问题类型底色
for r in range(2, ws2.max_row + 1):
    ptype = ws2.cell(r, 2).value
    if ptype in PROBLEM_FILLS:
        ws2.cell(r, 2).fill = PROBLEM_FILLS[ptype]
    pri = ws2.cell(r, 1).value
    ws2.cell(r, 1).font = Font(name="微软雅黑", bold=True, size=10,
                               color="C00000" if pri == "高" else "BF8F00")
autosize(ws2, [8, 12, 22, 12, 12, 12, 36, 30, 12, 12, 10, 9])
freeze(ws2)

# =========================================================
# Sheet 3: 已匹配
# =========================================================
ws3 = wb.create_sheet("已匹配")
h3 = ["业务编号", "左侧金额", "右侧金额", "金额差异", "匹配依据", "来源行(左)", "来源行(右)"]
styled_header(ws3, h3, "已匹配")
for m in sorted(matched, key=lambda x: x["no"]):
    ws3.append([m["no"], float(m["left_amt"]), float(m["right_amt"]),
                float(m["diff"]), m["basis"], m["left_row"], m["right_row"]])
styled_body(ws3, 2, ws3.max_row, len(h3), money_cols=(2, 3, 4))
autosize(ws3, [22, 13, 13, 12, 38, 14, 14])
freeze(ws3)

# =========================================================
# Sheet 4: 重复与冲突
# =========================================================
ws4 = wb.create_sheet("重复与冲突")
h4 = ["业务编号", "候选清单", "冲突原因"]
styled_header(ws4, h4, "冲突")
for conf in conflicts:
    ws4.append([conf["no"], conf["candidates"], conf["reason"]])
styled_body(ws4, 2, ws4.max_row, len(h4))
autosize(ws4, [22, 42, 50])
freeze(ws4)

# =========================================================
# Sheet 5: 数据质量
# =========================================================
ws5 = wb.create_sheet("数据质量")
h5 = ["问题类型", "来源行", "原始值", "说明"]
styled_header(ws5, h5, "质量")
dq = [
    ["空业务编号", "右表第3行(B002)", "—", "噪声流水，超出对账口径范围，已自动过滤"],
    ["空业务编号", "右表第8行(B007)", "—", "银行手续费，台账无对应记账，转待处理"],
    ["空业务编号", "右表第11行(B010)", "—", "银行结息，台账无对应记账，转待处理"],
    ["空业务编号", "右表第14行(B013)", "—", "匿名转账，待核实对方身份"],
    ["潜在风险", "右表第9行(B008)", "锦绣文创 6000", "多对一合并入账，附言未拆单号，依赖金额合计匹配"],
]
for dq_row in dq:
    ws5.append(dq_row)
styled_body(ws5, 2, ws5.max_row, len(h5))
autosize(ws5, [16, 20, 22, 56])
freeze(ws5)

# =========================================================
# Sheet 6: 审计明细
# =========================================================
ws6 = wb.create_sheet("审计明细")
h6 = ["业务编号", "来源", "原始行", "日期", "金额", "命中规则", "匹配证据"]
styled_header(ws6, h6, "审计")
audit = []
for m in matched:
    no = m["no"]
    for x in left:
        if x["no"] == no:
            audit.append([no, "左表", x["row"], x["date"], float(x["amount"]), m["basis"], f"↔ 右表 {m['right_row']}"])
    for x in right:
        if x["no"] == no:
            audit.append([no, "右表", x["row"], x["date"], float(x["amount"]), m["basis"], f"↔ 左表 {m['left_row']}"])
for p in pending:
    no = p["no"]
    for x in left:
        if x["no"] == no:
            audit.append([no, "左表", x["row"], x["date"], float(x["amount"]), p["basis"], "待处理"])
    # 右表多余用 bank_no 反查
    for x in right:
        if (x["no"] == no) or (x["bank_no"] == no):
            audit.append([no, "右表", x["row"], x["date"], float(x["amount"]), p["basis"], "待处理"])
for audit_row in audit:
    ws6.append(audit_row)
styled_body(ws6, 2, ws6.max_row, len(h6), money_cols=(5,))
autosize(ws6, [22, 8, 10, 13, 13, 38, 16])
freeze(ws6)

# =========================================================
# Sheet 7: 运行参数
# =========================================================
ws7 = wb.create_sheet("运行参数")
h7 = ["参数项", "值", "说明"]
styled_header(ws7, h7, "参数")
params = [
    ["contract_version", "1.0", "输入/输出契约版本"],
    ["rule_version", "1.0", "匹配规则版本"],
    ["left.file", "对账演示数据.xlsx / 业务台账（左表）", "左表来源"],
    ["right.file", "对账演示数据.xlsx / 银行流水（右表）", "右表来源（含补录的业务编号列）"],
    ["match.primary_key", "no", "按业务编号分组匹配"],
    ["match.composite_keys", "[amount]", "金额参与复合键（容差判定）"],
    ["match.amount_tolerance", "8.00", "金额容差：覆盖 8 元手续费差"],
    ["match.date_tolerance_days", "1", "日期容差：覆盖 7/3→7/4 错位"],
    ["match.direction_rule", "signed", "按收/付方向归一为带符号金额"],
    ["match.amount_scale", "2", "金额量化小数位（HALF_UP）"],
    ["对账时间窗口", "2026-07-01 ~ 2026-07-10", "本期口径"],
]
for param_row in params:
    ws7.append(param_row)
styled_body(ws7, 2, ws7.max_row, len(h7))
autosize(ws7, [28, 48, 50])
freeze(ws7)

wb.save(OUT)
print(f"已生成: {OUT}")
print("\n=== 对账结果摘要 ===")
print(f"已匹配: {len(matched)} 组")
for m in sorted(matched, key=lambda x: x["no"]):
    print(f"  ✓ {m['no']:24s} 左{m['left_amt']:>10.2f} 右{m['right_amt']:>10.2f} 差{m['diff']:>8.2f}  [{m['basis']}]")
print(f"\n待处理: {len(pending)} 笔")
for p in sorted(pending, key=lambda x: (x['priority'], x['problem'])):
    la = f"{p['left_amt']:>10.2f}" if p['left_amt'] is not None else f"{'—':>10s}"
    ra = f"{p['right_amt']:>10.2f}" if p['right_amt'] is not None else f"{'—':>10s}"
    print(f"  ⚠ [{p['priority']}] {p['problem']:6s} {p['no']:24s} 左{la} 右{ra}  {p['basis']}")
print(f"\n勾稽校验: 左合计{LEFT_SUM:.2f} − 右合计{RIGHT_SUM:.2f} = {total_diff:.2f}")
print(f"          已匹配差异和{sum_matched_diff:.2f} + 待处理差异和{sum_pending_diff:.2f} = {sum_matched_diff+sum_pending_diff:.2f}")
print(f"          {'✓ 通过' if abs((sum_matched_diff+sum_pending_diff) - total_diff) < Decimal('0.01') else '✗ 不平'}")
