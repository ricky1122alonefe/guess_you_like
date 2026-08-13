"""Tick 质量校验：供 poll 路径与审计脚本共用，避免 scripts 循环依赖。"""
from __future__ import annotations

import json
from typing import Any

from poll_500 import (
    _is_plausible_ah_water,
    _is_plausible_eu_odds,
    _is_plausible_ou_line,
    _is_plausible_ou_water,
    is_dirty_team_label,
)


def _to_float(v) -> float | None:
    if v is None:
        return None
    try:
        return float(v)
    except (TypeError, ValueError):
        return None


def validate_tick(tick: dict[str, Any], *, fixture_id: str = "") -> dict[str, Any]:
    """校验 tick 字段语义，返回 {ok, errors, warnings}。

    规则：
    - 欧三向要么全合法要么全空；禁止「只有主胜有数」
    - 亚：有 line 则双水必合法
    - 页内 eu_open_* <1.30 疑似串水 → warning，禁止当观测欧初盘
    - jingcai.has_sp=true 则 sp 三向可解析
    - 欧亚全无 → error
    """
    errors: list[str] = []
    warnings: list[str] = []

    eu = [_to_float(tick.get(k)) for k in ("eu_home", "eu_draw", "eu_away")]
    eu_valid = [v is not None and _is_plausible_eu_odds(v) for v in eu]
    if any(eu_valid) and not all(eu_valid):
        errors.append("欧赔三向不完整或含非法值")
    for i, side in enumerate(("主胜", "平局", "客胜")):
        if eu[i] is not None and not _is_plausible_eu_odds(eu[i]):
            if eu[i] is not None and 0.3 <= (eu[i] or 0) <= 1.3:
                warnings.append(f"{side} 欧赔={eu[i]} 疑似亚水串入 eu_*")
            else:
                warnings.append(f"{side} 欧赔={eu[i]} 超出合理区间")

    ah_line = tick.get("ah_line")
    ah_home = _to_float(tick.get("ah_home_water"))
    ah_away = _to_float(tick.get("ah_away_water"))
    if ah_line is not None:
        if ah_home is None or ah_away is None:
            errors.append("亚盘有 line 但缺水位")
        elif not _is_plausible_ah_water(ah_home) or not _is_plausible_ah_water(ah_away):
            errors.append("亚盘水位超出合理区间")

    for k in ("eu_open_home", "eu_open_draw", "eu_open_away"):
        v = _to_float(tick.get(k))
        if v is not None and v < 1.30:
            warnings.append(f"{k}={v} 疑似开盘字段串水，未当观测欧初使用")

    ou_line = _to_float(tick.get("ou_line"))
    if ou_line is not None:
        if not _is_plausible_ou_line(ou_line):
            warnings.append(f"OU 盘口 {ou_line} 不合法")
        for k in ("ou_over", "ou_under"):
            v = _to_float(tick.get(k))
            if v is not None and not _is_plausible_ou_water(v):
                warnings.append(f"{k}={v} 超出 OU 水位区间")

    raw = tick.get("raw_meta") or {}
    if isinstance(raw, str):
        try:
            raw = json.loads(raw or "{}")
        except Exception:
            raw = {}
    jc = raw.get("jingcai") or {}
    if jc.get("has_sp"):
        for k in ("sp_home", "sp_draw", "sp_away"):
            if _to_float(jc.get(k)) is None:
                warnings.append(f"竞彩 has_sp=true 但 {k} 缺失")
    elif raw.get("match_num"):
        warnings.append("有 match_num 但竞彩 SP 结构缺失")

    bf = raw.get("betfair") or {}
    if bf.get("has_data") and not bf.get("volume_total"):
        warnings.append("必发 has_data=true 但 volume_total 为 0/缺失")

    has_eu = all(eu_valid)
    has_ah = (
        ah_line is not None
        and _is_plausible_ah_water(ah_home)
        and _is_plausible_ah_water(ah_away)
    )
    if not has_eu and not has_ah:
        errors.append("欧亚市场均为空或非法")

    return {
        "ok": not errors,
        "errors": errors,
        "warnings": warnings,
    }
