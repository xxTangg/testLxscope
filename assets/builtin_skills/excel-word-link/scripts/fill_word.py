"""
通用 Excel → Word 联动填充引擎（简单模式）

把 Excel 里的「占位符 → 值」灌进 Word 模板里对应的 {{占位符}}，一键生成新文档。
适用于任何业务：合同、报价单、通知书、报告、证明……只要模板里有 {{占位符}}。

----------------------------------------------------------------------
数据怎么准备（Excel）：
  每个 sheet 三列（表头随意，按列序读取）：
    A列 = 占位符名（不含大括号，例如：客户名称）
    B列 = 值（文本或数字）
    C列 = 格式（可选：money / pct / int / text，留空则自动判断）
  多个 sheet 会全部扫描合并，方便按主题分表。

模板怎么写（Word）：
  在需要联动的位置写 {{占位符名}}，例如：
    甲方：{{客户名称}}    合同金额：{{合同金额}} 元

格式说明：
  money  金额千分位两位小数，负数显示成会计括号 (1,280.00)
  pct    百分比，把 0.2614 显示成 26.14%
  int    整数千分位，1234567 → 1,234,567
  text   原样输出（适合编号、日期、身份证号这类不能当数字算的）
  留空   数字→千分位两位小数；文本→原样
----------------------------------------------------------------------

用法：
  python fill_word.py                               # 用同目录默认文件
  python fill_word.py 数据.xlsx 模板.docx 输出.docx   # 指定文件
  python fill_word.py --data 数据.xlsx --template 模板.docx --output 输出.docx
"""
import argparse
import re
import shutil
import sys
from pathlib import Path

try:
    import openpyxl
    from docx import Document
except ImportError as e:
    miss = 'openpyxl' if 'openpyxl' in str(e) else 'python-docx'
    print(f'❌ 缺少依赖：{miss}')
    print('   请先安装：pip install openpyxl python-docx')
    sys.exit(1)


# ========= 格式化工具 =========
def fmt_money(v):
    """金额：千分位两位小数，负数用会计括号。空值返回 —。"""
    if v is None or v == '':
        return '—'
    try:
        v = float(v)
    except (ValueError, TypeError):
        return str(v)
    return f'({abs(v):,.2f})' if v < 0 else f'{v:,.2f}'


def fmt_pct(v):
    """百分比：把小数（0.2614）显示成 26.14%。"""
    if v is None or v == '':
        return '—'
    try:
        return f'{float(v) * 100:.2f}%'
    except (ValueError, TypeError):
        return str(v)


def fmt_int(v):
    """整数：千分位，无小数。"""
    if v is None or v == '':
        return '—'
    try:
        return f'{int(float(v)):,}'
    except (ValueError, TypeError):
        return str(v)


def fmt_auto(v):
    """自动：数字走千分位两位小数，其余原样。"""
    if v is None:
        return ''
    if isinstance(v, (int, float)):
        return f'{v:,.2f}'
    return str(v)


FORMATTERS = {
    'money': fmt_money,
    'pct': fmt_pct,
    'int': fmt_int,
    'text': lambda v: '' if v is None else str(v),
    '': fmt_auto,
}


# ========= 读 Excel → 占位符字典 =========
def load_placeholders(excel_path):
    """扫描所有 sheet，按「占位符 | 值 | 格式」三列读取，返回 {占位符: 格式化后的字符串}。"""
    wb = openpyxl.load_workbook(excel_path, data_only=True)
    ph = {}
    for ws in wb.worksheets:
        for row in ws.iter_rows(values_only=True):
            if not row or row[0] is None:
                continue
            key = str(row[0]).strip()
            # 跳过明显的表头行（第一列写"占位符/名称/字段/key"等）
            if key in ('占位符', '名称', '字段', 'key', 'Key', '项目') and len(ph) == 0:
                continue
            val = row[1] if len(row) > 1 else None
            fmt = str(row[2]).strip().lower() if len(row) > 2 and row[2] else ''
            formatter = FORMATTERS.get(fmt, fmt_auto)
            ph[key] = formatter(val)
    return ph


# ========= Word 替换 =========
def replace_in_paragraph(paragraph, placeholders):
    """替换一个段落里的所有 {{占位符}}。整段重写到首个 run，避免占位符被拆进多个 run 而漏替换。"""
    full_text = paragraph.text
    if '{{' not in full_text:
        return 0
    new_text = full_text
    n = 0
    for key, val in placeholders.items():
        token = '{{' + key + '}}'
        if token in new_text:
            n += new_text.count(token)
            new_text = new_text.replace(token, val)
    if new_text == full_text:
        return 0
    runs = paragraph.runs
    if not runs:
        return 0
    runs[0].text = new_text
    for r in runs[1:]:
        r.text = ''
    return n


def replace_in_table(table, placeholders):
    """递归替换表格（含嵌套表格）里的占位符。"""
    n = 0
    for row in table.rows:
        for cell in row.cells:
            for p in cell.paragraphs:
                n += replace_in_paragraph(p, placeholders)
            for sub in cell.tables:
                n += replace_in_table(sub, placeholders)
    return n


def find_leftover(doc):
    """找出文档里没被替换的 {{...}}，帮用户发现 Excel 漏填的占位符。"""
    pat = re.compile(r'\{\{[^}]+\}\}')
    leftover = set()
    for p in doc.paragraphs:
        leftover.update(pat.findall(p.text))
    for t in doc.tables:
        for row in t.rows:
            for cell in row.cells:
                for p in cell.paragraphs:
                    leftover.update(pat.findall(p.text))
    return leftover


# ========= 主流程 =========
def fill(excel_path, template_path, output_path):
    """读 Excel → 复制模板 → 替换占位符 → 保存。返回 (替换处数, 残留集合)。"""
    excel_path = Path(excel_path)
    template_path = Path(template_path)
    output_path = Path(output_path)

    if not excel_path.exists():
        print(f'❌ 找不到数据文件：{excel_path}')
        sys.exit(1)
    if not template_path.exists():
        print(f'❌ 找不到模板文件：{template_path}')
        sys.exit(1)

    ph = load_placeholders(excel_path)
    print(f'载入占位符：{len(ph)} 个')

    output_path.parent.mkdir(parents=True, exist_ok=True)
    shutil.copy(template_path, output_path)

    doc = Document(str(output_path))
    n = 0
    for p in doc.paragraphs:
        n += replace_in_paragraph(p, ph)
    for t in doc.tables:
        n += replace_in_table(t, ph)

    leftover = find_leftover(doc)

    try:
        doc.save(str(output_path))
    except PermissionError:
        print(f'❌ 无法保存：{output_path}')
        print('   原因：该文档可能正在 Word 中打开，请关闭后重试。')
        sys.exit(1)

    print(f'替换：{n} 处')
    if leftover:
        print(f'\n⚠️ 模板里有 {len(leftover)} 个占位符在 Excel 里没找到对应值：')
        for t in sorted(leftover):
            print(f'   {t}')
        print('   请检查 Excel 第一列的占位符名是否和模板里的 {{名}} 一致。')
    else:
        print('✅ 所有占位符已替换')
    print(f'\n输出：{output_path}')
    return n, leftover


def main():
    here = Path(__file__).resolve().parent
    parser = argparse.ArgumentParser(description='通用 Excel → Word 联动填充')
    parser.add_argument('data', nargs='?', help='Excel 数据文件（默认：同目录 数据.xlsx）')
    parser.add_argument('template', nargs='?', help='Word 模板文件（默认：同目录 模板.docx）')
    parser.add_argument('output', nargs='?', help='输出文件（默认：同目录 输出.docx）')
    parser.add_argument('--data', dest='data_kw')
    parser.add_argument('--template', dest='template_kw')
    parser.add_argument('--output', dest='output_kw')
    args = parser.parse_args()

    data = args.data_kw or args.data or str(here / '数据.xlsx')
    template = args.template_kw or args.template or str(here / '模板.docx')
    output = args.output_kw or args.output or str(here / '输出.docx')

    fill(data, template, output)


if __name__ == '__main__':
    main()
