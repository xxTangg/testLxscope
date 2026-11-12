"""fcs-reconcile 入口（薄编排层）。仅 summary 上交上层；明细留本地。

数据平面顶层：解析参数与配置 → 顺序编排各模块 → 写结果与运行清单。
仅把汇总（summary）暴露给上层/AI；原始明细、DataFrame、标准行不越界。

处理管线（见技术设计 §2.1）：
    config → io_reader(+sha256) → normalizer → matcher → classifier
           → 勾稽校验/summary → reporter → integrity(前后哈希) → manifest

本模块与兄弟模块平铺同目录（不包化，见项目结构设计 D4），故直接 `import config` 等。
运行期 sys.path[0] 为 scripts/；测试期由 tests/conftest.py 注入。
"""
from __future__ import annotations

import argparse
import json
import sys
from typing import Any, cast

import classifier
import config as config_mod
import guard
import integrity
import io_reader
import manifest as manifest_mod
import matcher
import normalizer
import reporter
import summary as summary_mod
import version as version_mod


def run(config_obj: config_mod.ReconcileConfig, *, run_id: str, run_at: str) -> dict[str, object]:
    """执行完整对账管线，写工作簿与运行清单，只返回 summary（不含任何明细/DataFrame）。"""
    guard.block_network()

    left_df, left_sha = io_reader.read_table(config_obj.left)
    right_df, right_sha = io_reader.read_table(config_obj.right)
    before = {config_obj.left.file: left_sha, config_obj.right.file: right_sha}

    left_rows = normalizer.normalize(left_df, config_obj.left.fields, config_obj.match)
    right_rows = normalizer.normalize(right_df, config_obj.right.fields, config_obj.match)

    outcomes = matcher.match(left_rows, right_rows, config_obj.match)
    items = classifier.classify(outcomes)
    s = summary_mod.build_summary(outcomes, len(left_rows), len(right_rows))
    errors = 0 if (s["quantity_reconciled"] and s["amount_reconciled"]) else 1

    integrity.assert_output_not_overwrites_input(
        config_obj.output_path, [config_obj.left.file, config_obj.right.file])
    reporter.write_workbook(items, s, {
        "rule_version": config_obj.rule_version,
        "contract_version": config_obj.contract_version,
        "amount_tolerance": str(config_obj.match.amount_tolerance),
        "date_tolerance_days": config_obj.match.date_tolerance_days,
    }, config_obj.output_path)

    after = {config_obj.left.file: integrity.sha256_of(config_obj.left.file),
             config_obj.right.file: integrity.sha256_of(config_obj.right.file)}
    integrity.verify_unchanged(before, after)

    out_sha = integrity.sha256_of(config_obj.output_path)
    m = manifest_mod.build_manifest(
        skill_version=version_mod.SKILL_VERSION, rule_version=config_obj.rule_version,
        contract_version=config_obj.contract_version, run_id=run_id, run_at=run_at,
        inputs=[{"path": config_obj.left.file, "sha256": left_sha},
                {"path": config_obj.right.file, "sha256": right_sha}],
        outputs=[{"path": config_obj.output_path, "sha256": out_sha}],
        field_mapping={"left": vars(config_obj.left.fields),
                       "right": vars(config_obj.right.fields)},
        config_dict={"amount_tolerance": str(config_obj.match.amount_tolerance),
                     "date_tolerance_days": config_obj.match.date_tolerance_days},
        counts=cast(dict[str, Any], s["counts"]), warnings=0, errors=errors)
    manifest_mod.write_manifest(m, config_obj.output_path + ".manifest.json")
    return s


def main(argv: list[str] | None = None) -> int:
    """CLI 入口：`python scripts/reconcile.py --config <config.yaml>`。

    全程走 guard 的网络隔离与日志脱敏；仅打印 summary 的 JSON，不输出任何明细。
    """
    parser = argparse.ArgumentParser(prog="fcs-reconcile")
    parser.add_argument("--config", required=True)
    parser.add_argument("--run-id", default="cli")
    parser.add_argument("--run-at", default="")
    args = parser.parse_args(argv)
    conf = config_mod.load_config(args.config)
    s = run(conf, run_id=args.run_id, run_at=args.run_at)
    print(json.dumps(s, ensure_ascii=False))  # 仅 summary，无明细
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
