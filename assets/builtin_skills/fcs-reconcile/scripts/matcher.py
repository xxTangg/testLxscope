"""matcher —— 分阶段确定性匹配（技术设计 §5）。误判 0：唯一 + 完全满足才自动确认。"""
from __future__ import annotations

from collections import defaultdict
from decimal import Decimal

from config import MatchConfig
from models import MatchOutcome, Status, StdRow


def _by_no(rows: list[StdRow]) -> dict[str, list[StdRow]]:
    groups: dict[str, list[StdRow]] = defaultdict(list)
    for r in rows:
        groups[r.no].append(r)  # type: ignore[index]
    return groups


def match_primary(left: list[StdRow], right: list[StdRow], match: MatchConfig
                  ) -> tuple[list[MatchOutcome], list[StdRow], list[StdRow]]:
    outcomes: list[MatchOutcome] = []
    # 1) 质量分流
    l_ok = [r for r in left if not r.quality_flags]
    r_ok = [r for r in right if not r.quality_flags]
    for r in left:
        if r.quality_flags:
            outcomes.append(MatchOutcome(Status.DATA_QUALITY, left=r, rule="数据质量"))
    for r in right:
        if r.quality_flags:
            outcomes.append(MatchOutcome(Status.DATA_QUALITY, right=r, rule="数据质量"))

    lg, rg = _by_no(l_ok), _by_no(r_ok)
    left_leftover: list[StdRow] = []
    right_leftover: list[StdRow] = []
    tol = match.amount_tolerance

    for no in sorted(set(lg) | set(rg)):
        lc = sorted(lg.get(no, []), key=lambda r: r.row_id)
        rc = sorted(rg.get(no, []), key=lambda r: r.row_id)
        if len(lc) >= 2 or len(rc) >= 2:
            cands = tuple(lc + rc)
            if lc and rc:
                for r in lc:
                    outcomes.append(
                        MatchOutcome(Status.MULTI_CANDIDATE, left=r,
                                     candidates=cands, rule="多候选")
                    )
                for r in rc:
                    outcomes.append(
                        MatchOutcome(Status.MULTI_CANDIDATE, right=r,
                                     candidates=cands, rule="多候选")
                    )
            else:
                for r in lc:
                    outcomes.append(
                        MatchOutcome(Status.DUP_NO, left=r, candidates=cands, rule="重复编号")
                    )
                for r in rc:
                    outcomes.append(
                        MatchOutcome(Status.DUP_NO, right=r, candidates=cands, rule="重复编号")
                    )
            continue
        if len(lc) == 1 and len(rc) == 1:
            left_row, right_row = lc[0], rc[0]
            diff = (left_row.amount or Decimal(0)) - (right_row.amount or Decimal(0))
            if diff == 0:
                outcomes.append(
                    MatchOutcome(Status.AUTO_MATCHED, left=left_row, right=right_row,
                                 amount_diff=diff, rule="主键唯一且金额相等")
                )
            elif tol > 0 and abs(diff) <= tol:
                outcomes.append(
                    MatchOutcome(Status.SUSPECT, left=left_row, right=right_row,
                                 amount_diff=diff, rule="容差内差异")
                )
            else:
                outcomes.append(
                    MatchOutcome(Status.AMOUNT_DIFF, left=left_row, right=right_row,
                                 amount_diff=diff, rule="金额超容差")
                )
        elif lc:
            left_leftover.extend(lc)
        elif rc:
            right_leftover.extend(rc)
    return outcomes, left_leftover, right_leftover


def _composite_equal(a: StdRow, b: StdRow, keys: tuple[str, ...], date_tol: int) -> bool:
    for k in keys:
        va, vb = getattr(a, k), getattr(b, k)
        if va is None or vb is None:      # 任一缺失 → 不视为相等（避免"都缺失"误判为一致）
            return False
        if k == "date":
            if abs((va - vb).days) > date_tol:
                return False
        elif va != vb:
            return False
    return True


def match_composite(left_leftover: list[StdRow], right_leftover: list[StdRow],
                     match: MatchConfig
                    ) -> tuple[list[MatchOutcome], list[StdRow], list[StdRow]]:
    if not match.composite_keys:
        return [], list(left_leftover), list(right_leftover)
    keys, dtol = match.composite_keys, match.date_tolerance_days
    outcomes: list[MatchOutcome] = []
    matched_l: set[int] = set()
    matched_r: set[int] = set()
    for left_row in sorted(left_leftover, key=lambda x: x.row_id):
        rc = [r for r in right_leftover if r.row_id not in matched_r
              and _composite_equal(left_row, r, keys, dtol)]
        if len(rc) != 1:
            continue
        r = rc[0]
        lc = [x for x in left_leftover if x.row_id not in matched_l
              and _composite_equal(x, r, keys, dtol)]
        if len(lc) != 1:
            continue                      # 互唯一才放行
        matched_l.add(left_row.row_id)
        matched_r.add(r.row_id)
        outcomes.append(MatchOutcome(
            Status.AUTO_MATCHED, left=left_row, right=r,
            amount_diff=(left_row.amount or Decimal(0)) - (r.amount or Decimal(0)),
            rule="复合键唯一一致"))
    l_rest = [r for r in left_leftover if r.row_id not in matched_l]
    r_rest = [r for r in right_leftover if r.row_id not in matched_r]
    return outcomes, l_rest, r_rest


def match(left: list[StdRow], right: list[StdRow], match: MatchConfig) -> list[MatchOutcome]:
    outcomes, l_rest, r_rest = match_primary(left, right, match)
    comp, l_rest, r_rest = match_composite(l_rest, r_rest, match)
    outcomes.extend(comp)
    for r in sorted(l_rest, key=lambda x: x.row_id):
        outcomes.append(MatchOutcome(Status.LEFT_ONLY, left=r, rule="仅左侧存在"))
    for r in sorted(r_rest, key=lambda x: x.row_id):
        outcomes.append(MatchOutcome(Status.RIGHT_ONLY, right=r, rule="仅右侧存在"))
    return outcomes
