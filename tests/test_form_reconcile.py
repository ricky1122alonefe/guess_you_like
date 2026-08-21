"""近况变数与赛前桌 recent_status 消矛盾测试。"""
import pytest

from analysis.rules.output import reconcile_form_variables


def _pred(match_variables, prematch_desk=None, recent_form=None):
    pred = {"match_variables": list(match_variables)}
    if prematch_desk is not None:
        pred["prematch_desk"] = prematch_desk
    if recent_form is not None:
        pred["recent_form"] = recent_form
    return pred


def _recent_status_desk(home_line: str, away_line: str) -> dict:
    return {
        "dimensions": [
            {
                "id": "recent_status",
                "evidence": [home_line, away_line],
            }
        ]
    }


def _recent_form(home_wdl="", away_wdl=""):
    data = {}
    if home_wdl:
        data["home"] = {"label": "主队", "form_str": home_wdl, "source": "club_form"}
    if away_wdl:
        data["away"] = {"label": "客队", "form_str": away_wdl, "source": "club_form"}
    return data


def test_home_bad_form_conflict_with_high_ratio_removed():
    """主队取分率≥60% 时删除「主队近况不佳」类变数（以赛前桌为准）。"""
    pred = _pred(
        ["主队近况不佳（负）", "客队定位球战术不错"],
        prematch_desk=_recent_status_desk(
            "主队：近10场场均进2.1球，进攻火力强；近期取分率约70%",
            "客队：近10场取分率约50%",
        ),
    )
    reconcile_form_variables(pred)
    assert "主队近况不佳" not in pred["match_variables"]
    assert "客队定位球战术不错" in pred["match_variables"]


def test_away_bad_form_conflict_with_high_ratio_removed():
    """客队取分率≥60% 时删除「客队状态差」。"""
    pred = _pred(
        ["主队近5场 胜、胜、平", "客队状态差（连败）"],
        prematch_desk=_recent_status_desk(
            "主队：近10场取分率约55%",
            "客队：近10场场均进2.0球，状态稳定；近期取分率约68%",
        ),
    )
    reconcile_form_variables(pred)
    assert "客队状态差" not in pred["match_variables"]
    assert any("主队近5场" in v for v in pred["match_variables"])


def test_low_ratio_keeps_bad_form():
    """取分率<60%（一致）→ 保留原说法。"""
    pred = _pred(
        ["主队近况不佳（负）"],
        prematch_desk=_recent_status_desk(
            "主队：近10场取分率约30%",
            "客队：近10场取分率约60%",
        ),
    )
    reconcile_form_variables(pred)
    assert pred["match_variables"] == ["主队近况不佳（负）"]


def test_no_ratio_data_keeps_original():
    """无赛前桌取分率数据 → 不误删 AI 研判。"""
    pred = _pred(["主队近况不佳（负）"])
    reconcile_form_variables(pred)
    assert pred["match_variables"] == ["主队近况不佳（负）"]


def test_rewrite_with_club_form_wdl_when_no_conflict():
    """无赛前桌数据但有 club_form WDL → 用近5场 WDL 改写（不编造）。"""
    pred = _pred(
        ["客队近况不佳"],
        recent_form=_recent_form(away_wdl="WLWWD"),
    )
    reconcile_form_variables(pred)
    assert pred["match_variables"] == ["客队近5场 胜、负、胜、胜、平"]


def test_no_data_no_write():
    """无 club_form 也无 recent_status → 近况条保持（不写新内容，不编造）。"""
    pred = _pred(["主队近况不佳（负）"])
    reconcile_form_variables(pred)
    assert pred["match_variables"] == ["主队近况不佳（负）"]


def test_non_form_variables_untouched():
    """非近况变数（如战术、球员）一律不动。"""
    pred = _pred(
        ["主队高位逼抢积极", "主队近况不佳（负）"],
        prematch_desk=_recent_status_desk(
            "主队：近10场取分率约72%",
            "客队：近10场取分率约55%",
        ),
    )
    reconcile_form_variables(pred)
    assert "主队高位逼抢积极" in pred["match_variables"]
    assert "主队近况不佳" not in pred["match_variables"]


def test_high_impact_not_touched():
    """reconcile 只动 match_variables，high_impact 等其余字段不变。"""
    pred = _pred(
        ["主队近况不佳（负）"],
        prematch_desk=_recent_status_desk(
            "主队：近10场取分率约70%",
            "客队：近10场取分率约50%",
        ),
    )
    pred["high_impact"] = "比赛胜负手：客队反击效率"
    pred["judgment"] = "可购·主胜"
    reconcile_form_variables(pred)
    assert pred["high_impact"] == "比赛胜负手：客队反击效率"
    assert pred["judgment"] == "可购·主胜"


def test_missing_or_empty_match_variables_noop():
    assert reconcile_form_variables({}) == {}
    assert reconcile_form_variables({"match_variables": []}) == {"match_variables": []}
    assert reconcile_form_variables(None) is None
