"""
生成对账教程用的模拟 Excel 数据。
左表：业务台账（收付款明细）
右表：银行流水（招商银行账户）

数据刻意埋入 7 种典型对账差异，供教程逐步演示。
"""
import os
from collections.abc import Sequence

from openpyxl import Workbook
from openpyxl.styles import Alignment, Border, Font, PatternFill, Side
from openpyxl.utils import get_column_letter
from openpyxl.worksheet.worksheet import Worksheet

# 输出到脚本所在目录，便于从任意工作目录调用
_HERE = os.path.dirname(os.path.abspath(__file__))
wb = Workbook()

# ---------- 样式 ----------
HEADER_FONT = Font(name="微软雅黑", bold=True, color="FFFFFF", size=11)
HEADER_FILL = PatternFill("solid", fgColor="305496")
LEFT_FILL = PatternFill("solid", fgColor="DDEBF7")   # 左表 header 浅蓝
RIGHT_FILL = PatternFill("solid", fgColor="E2EFDA")  # 右表 header 浅绿
NOTE_FILL = PatternFill("solid", fgColor="FFF2CC")   # 说明 sheet 浅黄
THIN = Side(style="thin", color="BFBFBF")
BORDER = Border(left=THIN, right=THIN, top=THIN, bottom=THIN)
CENTER = Alignment(horizontal="center", vertical="center")
LEFT_ALIGN = Alignment(horizontal="left", vertical="center", wrap_text=True)


def style_header(ws: Worksheet, row: int, n_cols: int, fill: PatternFill) -> None:
    for c in range(1, n_cols + 1):
        cell = ws.cell(row=row, column=c)
        cell.font = HEADER_FONT
        cell.fill = fill
        cell.alignment = CENTER
        cell.border = BORDER


def style_body(ws: Worksheet, start_row: int, end_row: int, n_cols: int) -> None:
    for r in range(start_row, end_row + 1):
        for c in range(1, n_cols + 1):
            cell = ws.cell(row=r, column=c)
            cell.border = BORDER
            if c <= 2 or c >= 4:
                cell.alignment = CENTER
            # 金额列右对齐
            if ws.cell(row=1, column=c).value and "金额" in str(ws.cell(row=1, column=c).value):
                cell.alignment = Alignment(horizontal="right", vertical="center")
                cell.number_format = '#,##0.00'


def autosize(ws: Worksheet, widths: Sequence[float]) -> None:
    for i, w in enumerate(widths, start=1):
        ws.column_dimensions[get_column_letter(i)].width = w


# ========== Sheet 1: 业务台账（左表）==========
ws1 = wb.active
ws1.title = "业务台账（左表）"

headers1 = ["序号", "记账日期", "交易类型", "对方账户", "摘要", "金额（元）", "记账人", "业务单号"]
ws1.append(headers1)
style_header(ws1, 1, len(headers1), LEFT_FILL)

left_rows = [
    # ① 完全匹配 —— 与银行流水 #B001 对应
    [1, "2026-07-01", "收款", "深圳·星河科技有限公司", "7月 SaaS 订阅费",         5800.00, "王小莉", "AR-2026-0701-01"],
    # ⑦ 日期错位 —— 台账 7/3 记，银行 7/4 才入账（对应 #B003）
    [2, "2026-07-03", "收款", "北京·远方文化传媒",     "内容代运营服务费",        15000.00, "王小莉", "AR-2026-0703-02"],
    # ② 金额不一致 —— 台账 5800，银行实收 5808（手续费差，对应 #B004）
    [3, "2026-07-04", "收款", "上海·云栖商贸",         "商品尾款",                5800.00, "王小莉", "AR-2026-0704-03"],
    # ③ 一对多 —— 台账一笔 12000，银行拆成 8000+4000（对应 #B005、#B006）
    [4, "2026-07-05", "收款", "广州·鸿运物流",         "三季度运输合同款",        12000.00, "王小莉", "AR-2026-0705-04"],
    # ④ 多对一 —— 台账两笔 3500+2500，银行合并一笔 6000（对应 #B008）
    [5, "2026-07-06", "收款", "成都·锦绣文创",         "设计费-第一笔",           3500.00, "王小莉", "AR-2026-0706-05"],
    [6, "2026-07-06", "收款", "成都·锦绣文创",         "设计费-第二笔",           2500.00, "王小莉", "AR-2026-0706-06"],
    # ① 完全匹配 —— 与 #B009 对应
    [7, "2026-07-07", "付款", "杭州·云计算服务",       "7月服务器费用",          -8200.00, "李大伟", "AP-2026-0707-01"],
    # ⑤ 左表多 —— 台账有记录，银行流水里没有（在途 / 未到账）
    [8, "2026-07-08", "收款", "武汉·长江贸易",         "货款-客户自营",          9600.00,  "王小莉", "AR-2026-0708-07"],
    # ① 完全匹配 —— 与 #B011 对应
    [9, "2026-07-09", "付款", "深圳·绿能电力",         "6-7月电费",             -4300.00, "李大伟", "AP-2026-0709-02"],
    # ⑤ 左表多 —— 另一笔未到账
    [10, "2026-07-09", "收款", "南京·金陵书城",        "图书批发款",            7700.00,  "王小莉", "AR-2026-0709-08"],
    # ① 完全匹配 —— 与 #B012 对应
    [11, "2026-07-10", "付款", "上海·前海人力",        "7月工资代发",           -66000.00, "李大伟", "AP-2026-0710-03"],
    # ⑦ + 日期错位 —— 台账 7/10，银行还未入账（左表多，次日才到）
    [12, "2026-07-10", "收款", "深圳·星河科技",        "7月增值服务费",          3200.00, "王小莉", "AR-2026-0710-09"],
]
for row in left_rows:
    ws1.append(row)
style_body(ws1, 2, 1 + len(left_rows), len(headers1))
autosize(ws1, [6, 12, 10, 26, 22, 13, 9, 22])
ws1.freeze_panes = "A2"


# ========== Sheet 2: 银行流水（右表）==========
ws2 = wb.create_sheet("银行流水（右表）")

headers2 = ["序号", "交易日期", "收/付", "对方账户", "摘要", "金额（元）", "银行流水号"]
ws2.append(headers2)
style_header(ws2, 1, len(headers2), RIGHT_FILL)

right_rows = [
    # ① 完全匹配（对应台账 #1）
    [1,  "2026-07-01", "收入", "星河科技有限公司",       "代收-SaaS订阅费",         5800.00,  "B001-20260701-8834"],
    # 噪声：一笔小额收款，不在台账窗口关心的范围（可教学"范围过滤"）
    [2,  "2026-07-02", "收入", "支付宝（中国）网络",     "转账-归集",               500.00,   "B002-20260702-2210"],
    # ⑦ 日期错位（台账 #2 记的是 7/3）
    [3,  "2026-07-04", "收入", "远方文化传媒",           "代收-服务费",            15000.00,  "B003-20260704-9921"],
    # ② 金额不一致（台账 #3 记的是 5800）
    [4,  "2026-07-04", "收入", "云栖商贸",               "代收-商品款",             5808.00,  "B004-20260704-6638"],
    # ③ 一对多（对应台账 #4 的 12000）
    [5,  "2026-07-05", "收入", "鸿运物流",               "代收-合同款-第一期",       8000.00,  "B005-20260705-1102"],
    [6,  "2026-07-05", "收入", "鸿运物流",               "代收-合同款-第二期",       4000.00,  "B006-20260705-1103"],
    # ⑥ 右表多 —— 银行扣的手续费，台账没记
    [7,  "2026-07-06", "支出", "招商银行",               "手续费-跨行转账",          -15.00,  "B007-20260706-5512"],
    # ④ 多对一（对应台账 #5、#6 合计 6000）
    [8,  "2026-07-06", "收入", "锦绣文创",               "代收-设计费",             6000.00,  "B008-20260706-7741"],
    # ① 完全匹配（对应台账 #7）
    [9,  "2026-07-07", "支出", "云计算服务",             "代付-服务器费",          -8200.00,  "B009-20260707-3329"],
    # ⑥ 右表多 —— 银行结息，台账未记
    [10, "2026-07-08", "收入", "招商银行",               "季度结息",                 126.50, "B010-20260708-0091"],
    # ① 完全匹配（对应台账 #9）
    [11, "2026-07-09", "支出", "绿能电力",               "代付-电费",              -4300.00,  "B011-20260709-4478"],
    # ① 完全匹配（对应台账 #11）
    [12, "2026-07-10", "支出", "前海人力",               "代付-工资",             -66000.00,  "B012-20260710-8890"],
    # ⑥ 右表多 —— 客户直接线下转账，台账漏记
    [13, "2026-07-10", "收入", "匿名（待核实）",         "转账-备注咨询费",         4500.00,  "B013-20260710-2231"],
]
for row in right_rows:
    ws2.append(row)
style_body(ws2, 2, 1 + len(right_rows), len(headers2))
autosize(ws2, [6, 12, 8, 26, 24, 13, 24])
ws2.freeze_panes = "A2"


# ========== Sheet 3: 差异说明（教案）==========
ws3 = wb.create_sheet("差异说明（教案）")
ws3.append(["差异类型", "左表（业务台账）情况", "右表（银行流水）情况", "对应行号", "教学要点"])
style_header(ws3, 1, 5, NOTE_FILL)
note_rows = [
    ["① 完全匹配",   "有一笔",            "有一笔，金额/日期一致",     "#1↔B001 / #7↔B009 / #9↔B011 / #11↔B012", "对账的基线：能直接配平，先锚定它们缩小范围"],
    ["② 金额不一致", "5,800.00",          "5,808.00",                 "#3 ↔ B004",                              "差额 8 元——常见于手续费、汇兑损益，需人工判定"],
    ["③ 一对多",     "一笔 12,000.00",    "拆成 8,000 + 4,000 两笔",  "#4 ↔ B005+B006",                         "台账合并记账、银行分次入账：要按合计金额匹配"],
    ["④ 多对一",     "两笔 3,500 + 2,500", "合并一笔 6,000.00",        "#5+#6 ↔ B008",                           "反向拆分：同样按合计金额匹配"],
    ["⑤ 左表多",     "有记录",            "银行流水无对应",            "#8 / #10 / #12",                         "可能是在途资金、记错账号、或次日才到账"],
    ["⑥ 右表多",     "台账无记录",         "银行有流水",               "B007 / B010 / B013",                     "可能是漏记账、银行手续费/利息、或待核实的匿名收入"],
    ["⑦ 日期错位",   "7/3 记账",          "7/4 实际入账",             "#2 ↔ B003",                              "跨日对账要容忍 ±N 天的日期浮动，不能卡死同日"],
]
for note_row in note_rows:
    ws3.append(note_row)

for r in range(2, 2 + len(note_rows)):
    for c in range(1, 6):
        cell = ws3.cell(row=r, column=c)
        cell.border = BORDER
        cell.alignment = LEFT_ALIGN if c in (2, 3, 5) else CENTER
        cell.font = Font(name="微软雅黑", size=10)
autosize(ws3, [14, 26, 28, 34, 46])
ws3.freeze_panes = "A2"

# 在说明 sheet 顶部加一行汇总提示
ws3.insert_rows(1)
ws3.cell(row=1, column=1, value="说明：本工作簿为对账教学模拟数据，左表 12 笔、右表 13 笔，共埋入 7 类典型差异，详见下表。")
ws3.merge_cells(start_row=1, start_column=1, end_row=1, end_column=5)
ws3.cell(row=1, column=1).font = Font(name="微软雅黑", bold=True, size=11, color="C00000")
ws3.cell(row=1, column=1).alignment = LEFT_ALIGN


# 保存
out_path = os.path.join(_HERE, "对账演示数据.xlsx")
wb.save(out_path)
print(f"已生成: {out_path}")
print(f"左表（业务台账）: {len(left_rows)} 行")
print(f"右表（银行流水）: {len(right_rows)} 行")
print(f"差异说明（教案）: {len(note_rows)} 类差异")
