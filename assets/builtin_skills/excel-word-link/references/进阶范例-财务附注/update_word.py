"""
Excel → Word 联动脚本（复杂版）

读取 Excel 多 sheet → 生成完整占位符字典 → 替换 Word 模板。

用法：python3 update_word.py
"""
import openpyxl
from docx import Document
from pathlib import Path
import shutil
import re

BASE = Path(__file__).resolve().parent
EXCEL = str(BASE / '数据源.xlsx')
TEMPLATE = str(BASE / '附注模板.docx')
OUTPUT = str(BASE / '附注_已填充.docx')


# ========= 格式化工具 =========
def fmt_money(v):
    if v is None or v == '':
        return '—'
    try:
        v = float(v)
    except (ValueError, TypeError):
        return str(v)
    if v < 0:
        return f'({abs(v):,.2f})'
    return f'{v:,.2f}'


def fmt_pct(this_p, last_p):
    try:
        this_p = float(this_p)
        last_p = float(last_p)
    except (ValueError, TypeError):
        return '—'
    if last_p == 0:
        return '—' if this_p == 0 else '+∞'
    pct = (this_p - last_p) / abs(last_p) * 100
    sign = '+' if pct >= 0 else ''
    return f'{sign}{pct:.2f}%'


def fmt_pct_raw(v):
    if v is None or v == '':
        return '—'
    try:
        return f'{float(v) * 100:.2f}%'
    except (ValueError, TypeError):
        return str(v)


def fmt_int(v):
    if v is None:
        return '—'
    try:
        return f'{int(float(v)):,}'
    except (ValueError, TypeError):
        return str(v)


def safe(v):
    return '' if v is None else str(v)


# ========= 各 sheet 读取与映射 =========
def load_excel():
    wb = openpyxl.load_workbook(EXCEL, data_only=True)
    return wb


def load_basic_info(wb):
    """基本信息 sheet → 占位符"""
    ws = wb['基本信息']
    info_map = {
        '公司名称': '公司名',
        '英文名称': '英文名',
        '报告年度': '年度',
        '报告日': '报告日',
        '注册地': '注册地',
        '法定代表人': '法定代表人',
        '注册资本(万元)': '注册资本',
        '员工人数': '员工人数',
        '记账本位币': '本位币',
        '行业类别': '行业类别',
        '成立日': '成立日',
        '统一社会信用代码': '统一社会信用代码',
    }
    ph = {}
    for row in ws.iter_rows(min_row=2, values_only=True):
        k = row[0]
        v = row[1]
        if k in info_map:
            key = info_map[k]
            if key in ('员工人数', '注册资本'):
                ph[key] = fmt_int(v)
            else:
                ph[key] = safe(v)
    return ph


def load_simple(wb):
    """主科目 sheet → {code}_本/上/变"""
    ws = wb['主科目']
    ph = {}
    for row in ws.iter_rows(min_row=2, values_only=True):
        code, name, this_p, last_p = row[:4]
        if not code:
            continue
        ph[f'{code}_本'] = fmt_money(this_p)
        ph[f'{code}_上'] = fmt_money(last_p)
        ph[f'{code}_变'] = fmt_pct(this_p, last_p)
    # 派生：毛利率
    raw = {}
    for row in ws.iter_rows(min_row=2, values_only=True):
        if row[0]:
            raw[row[0]] = (row[2], row[3])
    yysr_t, yysr_l = raw.get('PL_YYSR', (0, 0))
    yycb_t, yycb_l = raw.get('PL_YYCB', (0, 0))
    if yysr_t:
        ml_t = (yysr_t - yycb_t) / yysr_t * 100
        ph['PL_MLL_本'] = f'{ml_t:.2f}%'
    else:
        ml_t = 0
        ph['PL_MLL_本'] = '—'
    if yysr_l:
        ml_l = (yysr_l - yycb_l) / yysr_l * 100
        ph['PL_MLL_上'] = f'{ml_l:.2f}%'
    else:
        ml_l = 0
        ph['PL_MLL_上'] = '—'
    try:
        ph['PL_MLL_变'] = f'{(ml_t - ml_l):+.2f} pct'
    except Exception:
        ph['PL_MLL_变'] = '—'
    return ph


def load_hbzj(wb):
    """货币资金明细：库存现金/银行存款/其他货币资金 → HBZJ_*"""
    ws = wb['货币资金明细']
    rows = list(ws.iter_rows(min_row=2, values_only=True))
    code_map = {'库存现金': 'XJ', '银行存款': 'YH', '其他货币资金': 'QT'}
    ph = {}
    total_this = 0
    total_last = 0
    for r in rows:
        if r[0] == '合计':
            continue
        name, this_p, last_p = r[:3]
        c = code_map.get(name)
        if c:
            ph[f'HBZJ_{c}_本'] = fmt_money(this_p)
            ph[f'HBZJ_{c}_上'] = fmt_money(last_p)
            ph[f'HBZJ_{c}_变'] = fmt_pct(this_p, last_p)
            total_this += this_p or 0
            total_last += last_p or 0
    ph['HBZJ_HJ_本'] = fmt_money(total_this)
    ph['HBZJ_HJ_上'] = fmt_money(total_last)
    ph['HBZJ_HJ_变'] = fmt_pct(total_this, total_last)
    return ph


def load_yszk_zl(wb):
    """应收账款账龄"""
    ws = wb['应收账款账龄']
    code_map = {
        '1年以内': '1NN', '1-2年': '12N', '2-3年': '23N',
        '3-4年': '34N', '4-5年': '45N', '5年以上': '5NS',
    }
    ph = {}
    tot = [0, 0, 0, 0]
    for r in ws.iter_rows(min_row=2, values_only=True):
        if r[0] == '合计':
            continue
        name, yu_m, huai_m, yu_c, huai_c = r[:5]
        c = code_map.get(name)
        if c:
            ph[f'YSZK_ZL_{c}_余末'] = fmt_money(yu_m)
            ph[f'YSZK_ZL_{c}_坏末'] = fmt_money(huai_m)
            ph[f'YSZK_ZL_{c}_余初'] = fmt_money(yu_c)
            ph[f'YSZK_ZL_{c}_坏初'] = fmt_money(huai_c)
            for i, v in enumerate([yu_m, huai_m, yu_c, huai_c]):
                tot[i] += v or 0
    ph['YSZK_ZL_HJ_余末'] = fmt_money(tot[0])
    ph['YSZK_ZL_HJ_坏末'] = fmt_money(tot[1])
    ph['YSZK_ZL_HJ_余初'] = fmt_money(tot[2])
    ph['YSZK_ZL_HJ_坏初'] = fmt_money(tot[3])
    return ph


def load_top5(wb):
    """前五大客户"""
    ws = wb['前五大客户']
    ph = {}
    i = 0
    for r in ws.iter_rows(min_row=2, values_only=True):
        # 跳过合计行
        if r[0] == '—':
            ph['KH_HJ_余'] = fmt_money(r[2])
            ph['KH_HJ_占'] = fmt_pct_raw(r[3])
            ph['KH_HJ_坏'] = fmt_money(r[4])
            continue
        i += 1
        if i > 5:
            break
        seq, name, balance, pct, bad, rel = r[:6]
        ph[f'KH{i}_名'] = safe(name)
        ph[f'KH{i}_余'] = fmt_money(balance)
        ph[f'KH{i}_占'] = fmt_pct_raw(pct)
        ph[f'KH{i}_坏'] = fmt_money(bad)
        ph[f'KH{i}_关'] = safe(rel)
    return ph


def load_ch(wb):
    """存货分类"""
    ws = wb['存货分类']
    code_map = {'原材料': 'YCL', '在产品': 'ZCP', '库存商品': 'KCSP', '周转材料': 'ZZCL'}
    ph = {}
    tot = [0, 0, 0, 0]
    for r in ws.iter_rows(min_row=2, values_only=True):
        if r[0] == '合计':
            continue
        name, yu_m, die_m, yu_c, die_c = r[:5]
        c = code_map.get(name)
        if c:
            ph[f'CH_{c}_余末'] = fmt_money(yu_m)
            ph[f'CH_{c}_跌末'] = fmt_money(die_m)
            ph[f'CH_{c}_余初'] = fmt_money(yu_c)
            ph[f'CH_{c}_跌初'] = fmt_money(die_c)
            for i, v in enumerate([yu_m, die_m, yu_c, die_c]):
                tot[i] += v or 0
    ph['CH_HJ_余末'] = fmt_money(tot[0])
    ph['CH_HJ_跌末'] = fmt_money(tot[1])
    ph['CH_HJ_余初'] = fmt_money(tot[2])
    ph['CH_HJ_跌初'] = fmt_money(tot[3])
    return ph


def load_gdzc(wb):
    """固定资产五栏表"""
    ws = wb['固定资产']
    col_keys = ['FJ', 'JQ', 'YS', 'BG']  # 房屋/机器/运输/办公
    row_keys = {
        '一、原值期初余额':   'YZ_初',
        '    本期增加':       'YZ_增',
        '    本期减少':       'YZ_减',
        '    原值期末余额':   'YZ_末',
        '二、累计折旧期初':   'ZJ_初',
        '    本期计提':       'ZJ_提',
        '    本期减少':       'ZJ_减',  # 注意同名 -- 累计折旧的减少
        '    累计折旧期末':   'ZJ_末',
    }
    ph = {}
    # 记录原值/折旧期初期末用于算账面价值
    val = {}
    seen_jz = False  # 区分原值减少 vs 折旧减少
    for r in ws.iter_rows(min_row=2, values_only=True):
        label = r[0]
        if not label:
            continue
        # 同名处理：第一次见"本期减少" = 原值减少；第二次 = 折旧减少
        if label == '    本期减少':
            key = 'ZJ_减' if seen_jz else 'YZ_减'
            seen_jz = True
        else:
            key = row_keys.get(label)
        if not key:
            continue
        vals = r[1:5]  # 4 列科目
        for ci, ck in enumerate(col_keys):
            ph[f'GDZC_{ck}_{key}'] = fmt_money(vals[ci])
            val[(ck, key)] = vals[ci] or 0
        # 合计列
        ph[f'GDZC_HJ_{key}'] = fmt_money(sum(v or 0 for v in vals))
        val[('HJ', key)] = sum(v or 0 for v in vals)
    # 派生：账面价值 = 原值 - 累计折旧
    for ck in col_keys + ['HJ']:
        zm_c = val.get((ck, 'YZ_初'), 0) - val.get((ck, 'ZJ_初'), 0)
        zm_m = val.get((ck, 'YZ_末'), 0) - val.get((ck, 'ZJ_末'), 0)
        ph[f'GDZC_{ck}_ZM_初'] = fmt_money(zm_c)
        ph[f'GDZC_{ck}_ZM_末'] = fmt_money(zm_m)
    return ph


def load_shui(wb):
    """应交税费"""
    ws = wb['应交税费']
    code_map = {
        '增值税': 'ZZS', '企业所得税': 'SDS', '城市维护建设税': 'CJS',
        '教育费附加': 'JYF', '个人所得税': 'GSF', '印花税': 'YHS',
    }
    ph = {}
    tot = [0, 0]
    for r in ws.iter_rows(min_row=2, values_only=True):
        if r[0] == '合计':
            continue
        name, mo, chu = r[:3]
        c = code_map.get(name)
        if c:
            ph[f'SHUI_{c}_末'] = fmt_money(mo)
            ph[f'SHUI_{c}_初'] = fmt_money(chu)
            tot[0] += mo or 0
            tot[1] += chu or 0
    ph['SHUI_HJ_末'] = fmt_money(tot[0])
    ph['SHUI_HJ_初'] = fmt_money(tot[1])
    return ph


def load_yysr(wb):
    """营收分类"""
    ws = wb['营业收入分类']
    ph = {}
    # 业务类型：第 2-3 行是数据；第 4 行小计
    # 找出"按业务类型"块和"按产品类型"块
    rows = list(ws.iter_rows(values_only=True))
    yw_code_map = {'主营业务收入': 'ZY', '其他业务收入': 'QT'}
    cp_code_map = {'水处理设备销售': 'SB', '工程总承包服务': 'GC', '设备维保售后': 'WB', '技术咨询服务': 'ZX'}

    yw_tot = [0, 0]
    cp_tot = [0, 0]

    for r in rows:
        if not r or r[0] is None:
            continue
        name, this_p, last_p = r[0], r[1], r[2]
        if name in yw_code_map:
            c = yw_code_map[name]
            ph[f'YYSR_YW_{c}_本'] = fmt_money(this_p)
            ph[f'YYSR_YW_{c}_上'] = fmt_money(last_p)
            ph[f'YYSR_YW_{c}_变'] = fmt_pct(this_p, last_p)
            yw_tot[0] += this_p or 0
            yw_tot[1] += last_p or 0
        elif name in cp_code_map:
            c = cp_code_map[name]
            ph[f'YYSR_CP_{c}_本'] = fmt_money(this_p)
            ph[f'YYSR_CP_{c}_上'] = fmt_money(last_p)
            ph[f'YYSR_CP_{c}_变'] = fmt_pct(this_p, last_p)
            cp_tot[0] += this_p or 0
            cp_tot[1] += last_p or 0

    ph['YYSR_YW_HJ_本'] = fmt_money(yw_tot[0])
    ph['YYSR_YW_HJ_上'] = fmt_money(yw_tot[1])
    ph['YYSR_YW_HJ_变'] = fmt_pct(yw_tot[0], yw_tot[1])
    ph['YYSR_CP_HJ_本'] = fmt_money(cp_tot[0])
    ph['YYSR_CP_HJ_上'] = fmt_money(cp_tot[1])
    ph['YYSR_CP_HJ_变'] = fmt_pct(cp_tot[0], cp_tot[1])

    # 产品占比 = 当期 / 主营业务收入小计
    cp_total_this = cp_tot[0] or 0
    for c in ['SB', 'GC', 'WB', 'ZX']:
        # 取回原始本期值
        token = ph.get(f'YYSR_CP_{c}_本', '0').replace(',', '').replace('(', '-').replace(')', '')
        try:
            v = float(token)
            ph[f'YYSR_CP_{c}_占'] = f'{(v / cp_total_this * 100):.2f}%' if cp_total_this else '—'
        except Exception:
            ph[f'YYSR_CP_{c}_占'] = '—'
    return ph


def load_fees_total(simple_data):
    """期间费用合计：销售+管理+研发+财务+税金附加"""
    ph = {}
    keys = ['PL_SJJFJ', 'PL_XSFY', 'PL_GLFY', 'PL_YFFY', 'PL_CWFY']
    total_t = sum(simple_data.get(k, (0, 0))[0] or 0 for k in keys)
    total_l = sum(simple_data.get(k, (0, 0))[1] or 0 for k in keys)
    ph['FEES_HJ_本'] = fmt_money(total_t)
    ph['FEES_HJ_上'] = fmt_money(total_l)
    ph['FEES_HJ_变'] = fmt_pct(total_t, total_l)
    return ph


def load_stock(wb):
    """股本结构"""
    ws = wb['股本结构']
    ph = {}
    i = 0
    for r in ws.iter_rows(min_row=2, values_only=True):
        if r[0] == '合计':
            ph['GD_HJ_末'] = fmt_money(r[1])
            ph['GD_HJ_初'] = fmt_money(r[3])
            continue
        i += 1
        if i > 5:
            break
        name, this_s, pct, last_s, typ = r[:5]
        ph[f'GD{i}_名'] = safe(name)
        ph[f'GD{i}_末'] = fmt_money(this_s)
        ph[f'GD{i}_占'] = fmt_pct_raw(pct)
        ph[f'GD{i}_初'] = fmt_money(last_s)
        ph[f'GD{i}_类'] = safe(typ)
    return ph


def load_glf(wb):
    """关联方交易"""
    ws = wb['关联方交易']
    ph = {}
    i = 0
    for r in ws.iter_rows(min_row=2, values_only=True):
        if r[0] == '合计':
            ph['GLF_HJ_本'] = fmt_money(r[3])
            ph['GLF_HJ_上'] = fmt_money(r[4])
            continue
        i += 1
        if i > 5:
            break
        name, xi, tp, this_p, last_p = r[:5]
        ph[f'GLF{i}_名'] = safe(name)
        ph[f'GLF{i}_系'] = safe(xi)
        ph[f'GLF{i}_型'] = safe(tp)
        ph[f'GLF{i}_本'] = fmt_money(this_p)
        ph[f'GLF{i}_上'] = fmt_money(last_p)
    return ph


def load_all():
    wb = load_excel()
    ph = {}
    ph.update(load_basic_info(wb))
    ph.update(load_simple(wb))
    ph.update(load_hbzj(wb))
    ph.update(load_yszk_zl(wb))
    ph.update(load_top5(wb))
    ph.update(load_ch(wb))
    ph.update(load_gdzc(wb))
    ph.update(load_shui(wb))
    ph.update(load_yysr(wb))
    ph.update(load_stock(wb))
    ph.update(load_glf(wb))

    # 期间费用合计（需要主科目原始数据）
    ws = wb['主科目']
    raw = {}
    for r in ws.iter_rows(min_row=2, values_only=True):
        if r[0]:
            raw[r[0]] = (r[2], r[3])
    ph.update(load_fees_total(raw))
    return ph


# ========= Word 替换 =========
def replace_in_paragraph(paragraph, placeholders):
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
    n = 0
    for row in table.rows:
        for cell in row.cells:
            for p in cell.paragraphs:
                n += replace_in_paragraph(p, placeholders)
            for sub in cell.tables:
                n += replace_in_table(sub, placeholders)
    return n


def main():
    ph = load_all()
    print(f'载入占位符: {len(ph)} 个')

    Path(OUTPUT).parent.mkdir(parents=True, exist_ok=True)
    shutil.copy(TEMPLATE, OUTPUT)

    doc = Document(OUTPUT)
    n_para = 0
    n_table = 0
    for p in doc.paragraphs:
        n_para += replace_in_paragraph(p, ph)
    for t in doc.tables:
        n_table += replace_in_table(t, ph)

    # 残留检查
    pat = re.compile(r'\{\{[^}]+\}\}')
    leftover = set()
    for p in doc.paragraphs:
        for m in pat.findall(p.text):
            leftover.add(m)
    for t in doc.tables:
        for row in t.rows:
            for cell in row.cells:
                for p in cell.paragraphs:
                    for m in pat.findall(p.text):
                        leftover.add(m)

    doc.save(OUTPUT)

    print(f'段落替换: {n_para} 处')
    print(f'表格替换: {n_table} 处')
    if leftover:
        print(f'\n⚠️ 未替换的占位符（{len(leftover)} 个不同的）:')
        for t in sorted(leftover):
            print(f'  {t}')
    else:
        print('✅ 所有占位符已替换')
    print(f'\n输出: {OUTPUT}')


if __name__ == '__main__':
    main()
