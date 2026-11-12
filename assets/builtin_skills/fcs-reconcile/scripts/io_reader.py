"""io_reader —— 读取 xlsx/csv，金额列以字符串载入，计算源文件哈希（技术设计 §4.1）。"""
from __future__ import annotations

import os

import integrity
import pandas as pd
from config import TableSpec


def read_table(spec: TableSpec) -> tuple[pd.DataFrame, str]:
    sha = integrity.sha256_of(spec.file)
    # 金额列强制 str，隔离 float64 精度风险。
    str_cols = {c: str for c in [spec.fields.no, spec.fields.amount] if c}
    ext = os.path.splitext(spec.file)[1].lower()
    if ext in (".xlsx", ".xls"):
        df = pd.read_excel(spec.file, sheet_name=spec.sheet or 0,
                           header=spec.header_row, dtype=str_cols)
    else:
        df = pd.read_csv(spec.file, header=spec.header_row, dtype=str_cols)
    # 若配置的列名与表头不一致，pandas 会静默忽略 dtype 并以 float 载入金额，
    # 绕过"金额永不入 float"。这里显式校验必需列存在，不一致则明确报错。
    missing = {spec.fields.no, spec.fields.amount} - set(df.columns)
    if missing:
        raise ValueError(f"表中缺少配置的列：{sorted(missing)}（表头与字段映射不一致）")
    return df, sha
