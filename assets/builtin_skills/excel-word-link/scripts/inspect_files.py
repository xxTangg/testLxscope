"""
探查脚本：把 Word 和 Excel 的结构 dump 出来，供 Claude "看见"两边内容、做自动识别。

这是「Excel↔Word 联动」工作流的第一步：
  ① 探查（本脚本）→ ② 自动识别对应关系 → ③ 人工检查 → ④ 人工修改 → ⑤ 填充(apply_mapping.py)

输出里每个 Word 位置都带**稳定定位 ID**，后续 apply_mapping.py 用同样的 ID 精确替换：
  P{n}            第 n 个段落（全局序号，从 0 起）
  T{t}R{r}C{c}    第 t 个表格、第 r 行、第 c 列的单元格

用法：
  python inspect_files.py <word.docx> <excel.xlsx>          # 人类/Claude 可读
  python inspect_files.py <word.docx> <excel.xlsx> --json   # 机器可读（生成映射时用）
"""
import argparse
import json
import sys
from pathlib import Path

try:
    import openpyxl
    from docx import Document
    from docx.table import Table
    from docx.text.paragraph import Paragraph
    from docx.oxml.table import CT_Tbl
    from docx.oxml.text.paragraph import CT_P
except ImportError as e:
    miss = 'openpyxl' if 'openpyxl' in str(e) else 'python-docx'
    print(f'❌ 缺少依赖：{miss}，请先安装：pip install openpyxl python-docx')
    sys.exit(1)


def iter_block_items(doc):
    """按文档流顺序产出段落和表格（保留二者的先后关系，便于理解上下文）。"""
    body = doc.element.body
    for child in body.iterchildren():
        if isinstance(child, CT_P):
            yield 'p', Paragraph(child, doc)
        elif isinstance(child, CT_Tbl):
            yield 't', Table(child, doc)


def inspect_word(path: Path) -> dict:
    """读 Word，返回结构化内容：文档流顺序的段落与表格，段落带 P{n}、单元格带 T{t}R{r}C{c}。"""
    doc = Document(str(path))
    flow = []          # 文档流顺序，元素含定位 ID 和文本
    para_idx = 0
    table_idx = 0
    for kind, block in iter_block_items(doc):
        if kind == 'p':
            text = block.text.strip()
            flow.append({'kind': 'para', 'id': f'P{para_idx}', 'text': text})
            para_idx += 1
        else:
            rows = []
            for r, row in enumerate(block.rows):
                cells = []
                for c, cell in enumerate(row.cells):
                    cells.append({'id': f'T{table_idx}R{r}C{c}', 'text': cell.text.strip()})
                rows.append(cells)
            flow.append({'kind': 'table', 'index': table_idx,
                         'shape': [len(block.rows), len(block.columns)], 'rows': rows})
            table_idx += 1
    return {'file': path.name, 'para_count': para_idx, 'table_count': table_idx, 'flow': flow}


def inspect_excel(path: Path) -> dict:
    """读 Excel，返回每个 sheet 的单元格内容（只读已用区域，data_only 取计算结果）。"""
    wb = openpyxl.load_workbook(str(path), data_only=True)
    sheets = []
    for ws in wb.worksheets:
        rows = []
        for r, row in enumerate(ws.iter_rows(values_only=True), start=1):
            # 去掉整行全空的尾部噪声
            if all(v is None for v in row):
                continue
            cells = ['' if v is None else v for v in row]
            rows.append({'row': r, 'cells': cells})
        sheets.append({'name': ws.title, 'shape': [ws.max_row, ws.max_column], 'rows': rows})
    return {'file': path.name, 'sheet_count': len(sheets), 'sheets': sheets}


def print_human(word: dict, excel: dict) -> None:
    """打印人类/Claude 可读的探查结果。"""
    print('=' * 70)
    print(f'WORD：{word["file"]}　段落 {word["para_count"]} 个，表格 {word["table_count"]} 个')
    print('=' * 70)
    for item in word['flow']:
        if item['kind'] == 'para':
            if item['text']:                       # 空段落不打印，省噪声
                print(f'  {item["id"]}: {item["text"]}')
        else:
            rr, cc = item['shape']
            print(f'  ┌─ 表格{item["index"]}　{rr}行 x {cc}列')
            for row in item['rows']:
                for cell in row:
                    val = cell['text'] if cell['text'] else '·空·'
                    print(f'  │  {cell["id"]}: {val}')
            print('  └─')
    print()
    print('=' * 70)
    print(f'EXCEL：{excel["file"]}　{excel["sheet_count"]} 个 sheet')
    print('=' * 70)
    for sh in excel['sheets']:
        rr, cc = sh['shape']
        print(f'  【{sh["name"]}】 {rr}行 x {cc}列')
        for row in sh['rows']:
            cells = ' | '.join(str(c) for c in row['cells'])
            print(f'    R{row["row"]}: {cells}')
        print()


def main() -> None:
    parser = argparse.ArgumentParser(description='探查 Word + Excel 结构，供自动识别')
    parser.add_argument('word', help='Word 文件 (.docx)')
    parser.add_argument('excel', help='Excel 文件 (.xlsx)')
    parser.add_argument('--json', action='store_true', help='输出 JSON（机器可读）')
    args = parser.parse_args()

    word_path = Path(args.word)
    excel_path = Path(args.excel)
    if not word_path.exists():
        print(f'❌ 找不到 Word：{word_path}')
        sys.exit(1)
    if not excel_path.exists():
        print(f'❌ 找不到 Excel：{excel_path}')
        sys.exit(1)

    word = inspect_word(word_path)
    excel = inspect_excel(excel_path)

    if args.json:
        print(json.dumps({'word': word, 'excel': excel}, ensure_ascii=False, indent=2))
    else:
        print_human(word, excel)


if __name__ == '__main__':
    main()
