---
name: data-cleaning
description: "检查与清洗本地Excel、CSV、TSV或JSONL数据，定位缺失、重复、类型和异常，保留原始文件并输出质量报告、转换记录和前后核对结果。用于台账、名单、销售明细等数据整理。"
license: MIT
compatibility: Works with any Agent Skills client. The bundled profiler requires Python 3.9+ and the standard library; ecosystem tools are optional.
metadata:
  domain: data-quality-and-cleaning
  source: primary-docs-plus-orientation-article
---

## 内网系统适配

本技能使用企业内网模型、用户上传材料与已授权的内部知识库。只读取当前任务资料，不调用公网服务、在线解析或动态安装依赖；缺少本地能力时明确指出缺项。

技能目录使用宿主提供的实际路径（下文以 `$DIR` 表示）；脚本和参考资料按该目录解析，执行脚本使用绝对路径。产物写入当前会话工作区的输出目录，使用绝对路径提供下载；不写入系统共享目录或其他账号的目录。默认用中文交付。

# Data cleaning

Treat cleaning as a controlled transformation of an observed dataset, not cosmetic editing. Preserve raw input, state the target use and grain, make every lossy decision explicit, and prove that the cleaned output satisfies a contract.

When a model proposes data transformations, load [the AI boundary workflow](references/ai-repair-review.md)
and use [the companion record](templates/ai-repair-ledger.csv).

## Route by task

| Need | Read next |
|---|---|
| End-to-end method, scope, and stopping rules | `references/methodology.md` |
| Choose a library or platform | `references/tool-selection.md` |
| Missingness, duplicates, types, ranges, categories, dates, joins | `references/operations.md` |
| Text, identifiers, Unicode, and entity resolution | `references/text-and-entity.md` |
| Schemas, contracts, validation, drift, scale | `references/validation-and-scale.md` |
| CLI, OpenRefine, monitoring, and interactive remediation | `references/cli-and-interactive-tools.md` |
| Source claims and version-sensitive caveats | `references/sources.md` |
| Plan, logs, exceptions, contracts, or reports | `templates/cleaning-plan.md`, `templates/transformation-log.jsonl`, `templates/exception-register.csv`, `templates/schema-contract.yml`, `templates/quality-report.md` |
| Lightweight profile or reconciliation | Run `python3 scripts/profile_dataset.py --help` or `python3 scripts/reconcile_dataset.py --help` |

## Available Scripts

| Script | Purpose | Invocation |
|---|---|---|
| `scripts/profile_dataset.py` | Dependency-free first-pass profiling of a CSV, TSV, or JSONL input without modifying it: missingness, cardinality, type candidates, duplicates, ranges, and value anomalies. Run it at workflow step 3 (Profile before changing) as the evidence-gathering pass before designing any cleaning decision. | `python3 scripts/profile_dataset.py data.csv --output profile.json` |
| `scripts/reconcile_dataset.py` | Reconciliation between a before and after delimited dataset: row counts, key uniqueness/overlap, and per-column sums (`--sum`), keyed by `--key`, writing a machine-readable report. Run it during Validate twice / Review to prove grain preservation and quantify exactly what a transformation changed. | `python3 scripts/reconcile_dataset.py raw.csv cleaned.csv --key id --sum amount --output reconciliation.json` |
| `scripts/test_profile_dataset.py` | Pytest suite covering the profiler's behavior on representative inputs. Run it after modifying the profiler or when auditing its output; CI discovers it automatically. | `python3 -m pytest scripts/test_profile_dataset.py` |
| `scripts/test_reconcile_dataset.py` | Pytest suite covering the reconciler's keying, summing, and reporting behavior. Run it after modifying the reconciler or when auditing its output; CI discovers it automatically. | `python3 -m pytest scripts/test_reconcile_dataset.py` |

## Default workflow

1. **Frame:** identify the decision, owner, source, privacy constraints, unit of observation, keys, expected grain, time window, and acceptance threshold. Do not silently infer a business rule from a suspicious value.
2. **Freeze evidence:** record source path/URI, retrieval time, file size/hash where feasible, encoding, delimiter, schema, row/column counts, and software versions. Keep raw data read-only and write to a new output.
3. **Profile before changing:** inspect missingness, sentinel values, duplicates, cardinality, type candidates, ranges, invalid dates, whitespace/Unicode anomalies, cross-field relationships, and drift. Use the bundled profiler for a dependency-free first pass.
4. **Design decisions:** classify each finding as preserve, standardize, repair, impute, quarantine, reject, or escalate. Record rationale, rule, affected rows, confidence, reversibility, and owner.
5. **Transform in layers:** prefer deterministic named steps: parse → canonicalize → type/coerce → validate → deduplicate → resolve entities → impute/quarantine → reshape. Keep raw, staged, rejected, and final datasets distinct.
6. **Validate twice:** run structural checks before and after transformation. Validate row/grain preservation, key uniqueness, referential integrity, allowed values, units, bounds, null policy, and expected distributions. Tests should identify failing records.
7. **Review and release:** compare before/after metrics, inspect samples of every changed class, obtain domain approval for semantic or lossy changes, publish the report and provenance, and make the run reproducible.

## Non-negotiable controls

- Never overwrite raw data or silently drop rows, columns, categories, outliers, or unmatched entities.
- Separate invalid, missing, not applicable, not collected, and withheld when the domain distinguishes them.
- Parse dates and numbers with an explicit locale, timezone, unit, and error policy. Count parse failures; do not silently turn them into nulls.
- Normalize text conservatively. Retain original and normalized values plus confidence when matching or repairing.
- Fit imputers, encoders, normalization parameters, and deduplication rules only on the permitted training/reference partition. Avoid leakage across time or evaluation boundaries.
- Treat profiling as evidence for investigation, not permission to auto-fix. An anomaly can be a real event.
- Use quarantine for records that cannot be repaired safely. “Clean” means accepted by a stated contract, not “no rows remain.”

## Completion gate

A cleaning task is complete only when the output, transformation/decision log, validation evidence, provenance, and unresolved issues exist; raw data remains intact; acceptance checks pass; and a reviewer can reproduce or audit the result. If semantic ambiguity remains, stop at quarantine or escalation rather than inventing a value.

## When not to use

Do not use this skill for inferential statistics or model selection, which belong to `data-scientist`; for ETL orchestration, storage, or production data-quality operations, route to `data-engineering`; or for operating a named validation or database platform, route to that tool's skill. This skill supplies cleaning judgment and artifacts those workflows consume.

## Prerequisites

- Python 3.9+ with the standard library only for both bundled scripts (per `compatibility`); ecosystem tools (OpenRefine, pandas-backed tooling) are optional accelerators covered in `references/cli-and-interactive-tools.md`.
- A raw input you can keep read-only plus write access to a separate output location — every script reads without modifying its input.
- The templates above when the task warrants formal artifacts: a cleaning plan, transformation log, exception register, schema contract, or quality report.
- `pytest` only when running the bundled test suites.

## Limitations

- The bundled profiler and reconciler are first-pass evidence tools: they surface anomalies and quantify deltas but do not decide preserve/repair/impute/quarantine — those classifications stay with the workflow's decision step.
- Both scripts handle delimited text and JSONL; binary formats, relational databases, and nested document stores need other tooling.
- Profiling output is evidence for investigation, never permission to auto-fix; an anomaly can be a real event.
- A passing reconciliation proves structural preservation on the checked keys and sums only — semantic correctness of values still requires the review and release gate.
