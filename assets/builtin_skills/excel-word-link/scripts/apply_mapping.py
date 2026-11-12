"""
填充脚本：按一张「对应关系清单」(mapping.json) 把值精确填进 Word，输出成品。

这是「Excel↔Word 联动」工作流的执行层。mapping.json 是**可复用资产**——
模板不变时，每期只换 Excel 数据、复用同一份 mapping 即可秒出，无需重新识别。

  ① 探查(inspect_files.py) → ② 自动识别 → ③ 人工检查 → ④ Claude 调整 → 存 mapping.json
  之后每期：新 Excel + 已存 mapping.json → 本脚本一键填充

mapping.json 是数组，每条描述「往哪填(locate)、填什么(source 或 value)、怎么格式化(format)」：
  [
    {"locate": {"type": "cell", "table": 0, "row": 1, "col": 1},
     "source": {"sheet": "明细", "key": "货款"}, "format": "money",
     "note": "表0货款 ← Excel 明细.货款"},

    {"locate": {"type": "find", "old": "________", "para": 1},
     "value": "北京华信科技有限公司", "format": "text", "note": "P1 收件方(常量)"}
  ]

取值优先级：有 source 就从 Excel 现取（换数据不用改 mapping）；否则用写死的 value。

locate（往哪填）：
  cell         表格坐标。给 old 替换格内文本，不给则整格填空。坐标用 inspect 的 T{t}R{r}C{c}。
  find         正文查找 old 替换。给 para（P{n} 的 n）限定段落，不给则全文首个。
  placeholder  替换 {{name}}（兼容旧占位符模板）。

source（从 Excel 取值，二选一）：
  {"sheet": "基本信息", "key": "客户名称"}    在该 sheet 第一列找 key，取同行第二列（key-value 表）
  {"sheet": "明细", "row": 2, "col": 3}        直接坐标取值（1 起，和 inspect 的 R 行号一致）

format：money / pct / int / text / 留空自动。

用法：
  python apply_mapping.py <mapping.json> <word.docx> <输出.docx> [--excel <数据.xlsx>]
  python apply_mapping.py <mapping.json> <word.docx> --check [--excel <数据.xlsx>]   # 只检测不写
"""
import argparse
import json
import sys
from pathlib import Path

try:
    import openpyxl
    from docx import Document
except ImportError as e:
    miss = 'openpyxl' if 'openpyxl' in str(e) else 'python-docx'
    print(f'❌ 缺少依赖：{miss}，请先安装：pip install openpyxl python-docx')
    sys.exit(1)

# 复用 fill_word.py 的格式化器，保证两条路径口径一致
sys.path.insert(0, str(Path(__file__).resolve().parent))
from fill_word import FORMATTERS, fmt_auto  # noqa: E402

_MISS = object()   # 标记 Excel 取值没找到，和"值就是 None/空"区分开


def fmt(value, fmt_name: str) -> str:
    """按格式名格式化值；未知格式走自动。"""
    return FORMATTERS.get((fmt_name or '').strip().lower(), fmt_auto)(value)


def get_from_excel(wb, source: dict):
    """按 source 从 Excel 取值。找不到返回 _MISS（便于报告"取值失败"）。"""
    sheet_name = source.get('sheet')
    if sheet_name not in wb.sheetnames:
        return _MISS
    ws = wb[sheet_name]
    if 'key' in source:                              # key-value 表：第一列找 key
        val_col = source.get('col', 2)               # 默认取第二列
        for row in ws.iter_rows(values_only=True):
            if row and row[0] is not None and str(row[0]).strip() == str(source['key']).strip():
                return row[val_col - 1] if len(row) >= val_col else None
        return _MISS
    if 'row' in source and 'col' in source:          # 直接坐标
        return ws.cell(row=source['row'], column=source['col']).value
    return _MISS


def resolve_value(entry: dict, wb):
    """决定一条记录要填的原始值。返回 (值, 取值是否失败说明 或 None)。"""
    if 'source' in entry:
        if wb is None:
            return None, '需要 --excel 才能按 source 取值'
        raw = get_from_excel(wb, entry['source'])
        if raw is _MISS:
            src = entry['source']
            return None, f'Excel 取值失败：{src}'
        return raw, None
    return entry.get('value'), None


def replace_in_paragraph(paragraph, old: str, new: str):
    """段落内把 old 换成 new。优先在单个 run 内替换（保留格式）；跨 run 才合并到首 run。

    返回 (是否命中, 是否发生格式合并)。格式合并会丢段内混合格式，需提示用户。
    """
    for run in paragraph.runs:                       # 单 run 命中：完美保留格式
        if old in run.text:
            run.text = run.text.replace(old, new)
            return True, False
    full = paragraph.text                            # 跨 run：合并到首 run
    if old in full and paragraph.runs:
        paragraph.runs[0].text = full.replace(old, new)
        for r in paragraph.runs[1:]:
            r.text = ''
        return True, True
    return False, False


def set_cell(cell, value: str, old):
    """给表格单元格填值。给 old 则替换格内现有文本；否则整格设为 value（填空场景）。"""
    if old:
        for p in cell.paragraphs:
            hit, loss = replace_in_paragraph(p, old, value)
            if hit:
                return True, loss
        return False, False
    p = cell.paragraphs[0]                            # 填空：写首段首 run，保留格式
    if p.runs:
        p.runs[0].text = value
        for r in p.runs[1:]:
            r.text = ''
    else:
        p.add_run(value)
    for extra in cell.paragraphs[1:]:
        for r in extra.runs:
            r.text = ''
    return True, False


def locate_exists(doc, loc: dict):
    """只检测 locate 是否还能命中（模板变动检测用），不修改文档。返回 (能命中, 说明)。"""
    t = loc['type']
    if t == 'cell':
        try:
            cell = doc.tables[loc['table']].rows[loc['row']].cells[loc['col']]
        except IndexError:
            return False, f'坐标越界 T{loc.get("table")}R{loc.get("row")}C{loc.get("col")}'
        if loc.get('old') and loc['old'] not in cell.text:
            return False, f'格内找不到原文「{loc["old"]}」'
        return True, ''
    if t == 'placeholder':
        return _text_exists(doc, '{{' + loc['name'] + '}}')
    if t == 'find':
        old = loc['old']
        if 'para' in loc:
            try:
                p = doc.paragraphs[loc['para']]
            except IndexError:
                return False, f'段落 P{loc["para"]} 越界'
            return (old in p.text, '' if old in p.text else f'P{loc["para"]} 内找不到「{old}」')
        return _text_exists(doc, old)
    return False, f'未知定位类型：{t}'


def _text_exists(doc, needle: str):
    """全文（正文 + 表格）是否存在 needle。"""
    for p in doc.paragraphs:
        if needle in p.text:
            return True, ''
    for table in doc.tables:
        for row in table.rows:
            for cell in row.cells:
                if needle in cell.text:
                    return True, ''
    return False, f'全文找不到「{needle}」'


def apply_one(doc, loc: dict, value: str):
    """执行一条填充，返回 (是否命中, 是否格式合并)。"""
    t = loc['type']
    if t == 'cell':
        try:
            cell = doc.tables[loc['table']].rows[loc['row']].cells[loc['col']]
        except IndexError:
            return False, False
        return set_cell(cell, value, loc.get('old'))
    if t == 'placeholder':
        return _find_replace_global(doc, '{{' + loc['name'] + '}}', value)
    if t == 'find':
        old = loc['old']
        if 'para' in loc:
            try:
                p = doc.paragraphs[loc['para']]
            except IndexError:
                return False, False
            return replace_in_paragraph(p, old, value)
        return _find_replace_global(doc, old, value)
    return False, False


def _find_replace_global(doc, old: str, new: str):
    """全文查找 old，替换第一个命中处。"""
    for p in doc.paragraphs:
        if old in p.text:
            hit, loss = replace_in_paragraph(p, old, new)
            if hit:
                return True, loss
    for table in doc.tables:
        for row in table.rows:
            for cell in row.cells:
                for p in cell.paragraphs:
                    if old in p.text:
                        hit, loss = replace_in_paragraph(p, old, new)
                        if hit:
                            return True, loss
    return False, False


def load_mapping(mapping_path: Path) -> list:
    """读 mapping.json，校验顶层是数组。"""
    mapping = json.loads(mapping_path.read_text(encoding='utf-8'))
    if not isinstance(mapping, list):
        print('❌ mapping.json 顶层必须是数组 []')
        sys.exit(1)
    return mapping


def check_mapping(mapping: list, doc, wb) -> None:
    """模板变动检测：逐条报告 locate 是否还命中、source 取值是否成功，不修改文档。"""
    ok, broken = [], []
    for i, entry in enumerate(mapping):
        label = entry.get('note') or f'#{i}'
        hit, why = locate_exists(doc, entry['locate'])
        _, src_err = resolve_value(entry, wb)
        if hit and not src_err:
            ok.append(label)
        else:
            reason = why or src_err or '未知'
            broken.append((label, reason))
    print(f'检测：{len(ok)} 条仍命中 / 共 {len(mapping)} 条')
    if broken:
        print(f'\n⚠️ {len(broken)} 条对不上（模板可能被微调，需人工调整这几条）：')
        for label, reason in broken:
            print(f'   ✗ {label} —— {reason}')
    else:
        print('✅ mapping 与当前模板/数据完全吻合，可直接填充')


def fill(mapping: list, doc, wb, output_path: Path) -> dict:
    """逐条填充并保存，返回统计。"""
    hits, misses, warns = [], [], []
    for i, entry in enumerate(mapping):
        label = entry.get('note') or f'#{i}'
        raw, src_err = resolve_value(entry, wb)
        if src_err:
            misses.append(f'{label} —— {src_err}')
            continue
        value = fmt(raw, entry.get('format', ''))
        hit, loss = apply_one(doc, entry['locate'], value)
        if hit:
            hits.append(label)
            if loss:
                warns.append(label)
        else:
            misses.append(f'{label} —— 定位没命中')

    output_path.parent.mkdir(parents=True, exist_ok=True)
    try:
        doc.save(str(output_path))
    except PermissionError:
        print(f'❌ 无法保存 {output_path}：该文档可能正在 Word 中打开，请关闭后重试。')
        sys.exit(1)

    print(f'命中 {len(hits)} 条 / 共 {len(mapping)} 条')
    if misses:
        print(f'\n⚠️ 未命中 {len(misses)} 条：')
        for m in misses:
            print(f'   ✗ {m}')
    if warns:
        print(f'\n⚠️ {len(warns)} 条发生格式合并（段内混合格式可能丢，请目检）：')
        for w in warns:
            print(f'   ! {w}')
    if not misses and not warns:
        print('✅ 全部命中，无格式合并')
    print(f'\n输出：{output_path}')
    return {'hits': len(hits), 'misses': misses, 'warns': warns}


def main() -> None:
    parser = argparse.ArgumentParser(description='按对应关系清单填充 Word（mapping 可复用）')
    parser.add_argument('mapping', help='对应关系清单 mapping.json')
    parser.add_argument('word', help='Word 文件 (.docx)')
    parser.add_argument('output', nargs='?', help='输出文件 (.docx)；--check 模式可省略')
    parser.add_argument('--excel', help='Excel 数据文件（mapping 用 source 取值时必需）')
    parser.add_argument('--check', action='store_true', help='只检测 mapping 是否吻合当前模板/数据，不写文件')
    args = parser.parse_args()

    for label, path in (('mapping', args.mapping), ('Word', args.word)):
        if not Path(path).exists():
            print(f'❌ 找不到 {label}：{path}')
            sys.exit(1)

    mapping = load_mapping(Path(args.mapping))
    doc = Document(args.word)
    wb = None
    if args.excel:
        if not Path(args.excel).exists():
            print(f'❌ 找不到 Excel：{args.excel}')
            sys.exit(1)
        wb = openpyxl.load_workbook(args.excel, data_only=True)

    if args.check:
        check_mapping(mapping, doc, wb)
        return

    if not args.output:
        print('❌ 非检测模式必须给输出文件路径')
        sys.exit(1)
    fill(mapping, doc, wb, Path(args.output))


if __name__ == '__main__':
    main()
