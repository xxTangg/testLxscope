"""integrity —— 文件完整性校验（FT-06）。"""
from __future__ import annotations

import hashlib
import os


def sha256_of(path: str) -> str:
    """计算文件的 SHA-256 十六进制摘要（分块读取，适配大文件）。"""
    h = hashlib.sha256()
    with open(path, "rb") as f:
        for chunk in iter(lambda: f.read(65536), b""):
            h.update(chunk)
    return h.hexdigest()


def assert_output_not_overwrites_input(output_path: str, input_paths: list[str]) -> None:
    """校验输出路径不等于任一输入（realpath 归一后比较），相等则抛 ValueError。"""
    out = os.path.realpath(output_path)
    for p in input_paths:
        if os.path.realpath(p) == out:
            raise ValueError(f"输出路径不得覆盖输入文件：{output_path}")


def verify_unchanged(before: dict[str, str], after: dict[str, str]) -> None:
    """比对运行前后输入哈希，任一缺失或不一致则抛 ValueError。"""
    for path, h in before.items():
        if after.get(path) != h:
            raise ValueError(f"源文件运行前后哈希不一致（疑似被修改）：{path}")
