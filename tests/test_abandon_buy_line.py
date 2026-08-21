"""放弃/观望态：详情主推荐行不得显示「竞彩可购：主胜」。

场景 1427956（巴列卡诺VS阿拉维斯）：judgment=放弃，summary 已 scrub 为
【当前建议】放弃，但 predict_row.竞彩推荐 / jingcai_pick_info 仍残留主胜，
导致 final_recommendation_cn → 主胜 → UI「竞彩可购：主胜」。
"""
from analysis.market.three_lane import scrub_abandon_summary
from jingcai_pick import final_recommendation_cn
from score_models import scrub_zero_percent_scores
from web_ui import _pred_card


def _fixture_1427956_abandoned() -> dict:
    """真实 1427956（巴列卡诺VS阿拉维斯）放弃态 fixture：
    judgment=放弃，但 predict_row / jingcai_pick_info 残留主胜（AI 回写后未同步），
    likely_scores_detail 全 0.0% 且 likely_scores 仅裸比分「2-1」（无有效概率）。
    """
    return {
        "fixture_id": "1427956",
        "match": "巴列卡诺VS阿拉维斯",
        "home_team": "巴列卡诺",
        "away_team": "阿拉维斯",
        "league_name": "西甲",
        "judgment": "放弃·变数过大",
        "result_1x2_cn": "主胜",
        "summary": "【赛事概率】初盘亚盘+欧赔融合相似 55487/55487 场：主胜 43.9%、平 26.4%、客胜 29.7% → 赛事本身倾向 主胜。【参考研判】主胜（欧赔+亚盘+历史）。【竞彩可购】主胜，竞彩SP 主2.07/平2.84/客3.4 → 隐含主胜。比分 2-1(0.0%)、1-1(0.0%)。",
        "predict_row": {
            "预测日期": "2026-08-21",
            "比赛": "巴列卡诺VS阿拉维斯",
            "赛果预测": "主胜",
            "胜平负": "主胜",
            "推荐比分": "2-1(0.0%)、1-1(0.0%)",
            "亚盘": "受让0.25",
            "大小球": "2.25",
            "置信度": "低",
            "竞彩玩法": "胜平负",
            "竞彩推荐": "主胜",
            "竞彩SP": 2.07,
        },
        "jingcai_pick_info": {
            "jingcai_market": "sp",
            "jingcai_market_label": "胜平负",
            "jingcai_pick": "home",
            "jingcai_pick_cn": "主胜",
            "jingcai_pick_display": "主胜",
            "jingcai_sp": 2.07,
            "jingcai_reason": "竞彩胜平负可购主胜，与欧亚参考研判一致",
        },
        "likely_scores_detail": ["2-1(0.0%)", "1-1(0.0%)"],
        "likely_scores": ["2-1"],
    }


def test_final_recommendation_cn_respects_abandoned_judgment():
    """judgment 含「放弃」时优先返回放弃，即使残留竞彩推荐主胜。"""
    pred = _fixture_1427956_abandoned()
    assert final_recommendation_cn(pred) == "放弃"


def test_final_recommendation_cn_respects_watch_cn():
    """result_1x2_cn=观望（无 judgment）时返回观望。"""
    pred = _fixture_1427956_abandoned()
    pred["judgment"] = None
    pred["result_1x2_cn"] = "观望"
    assert final_recommendation_cn(pred) == "观望"


def test_final_recommendation_cn_respects_skip_result():
    """result_1x2=skip 时返回观望。"""
    pred = _fixture_1427956_abandoned()
    pred["judgment"] = None
    pred["result_1x2_cn"] = "主胜"
    pred["result_1x2"] = "skip"
    assert final_recommendation_cn(pred) == "观望"


def test_final_recommendation_cn_keeps_pick_when_not_abandoned():
    """非放弃态不受影响：残留主胜仍正常返回主胜（不误伤）。"""
    pred = _fixture_1427956_abandoned()
    pred["judgment"] = None
    assert final_recommendation_cn(pred) == "主胜"


def test_scrub_abandon_syncs_row_and_info():
    """scrub_abandon_summary 同步 predict_row 与 jingcai_pick_info（不 flip 方向）。"""
    pred = _fixture_1427956_abandoned()
    scrub_abandon_summary(pred)
    row = pred["predict_row"]
    assert row["竞彩推荐"] == "放弃"
    assert row["胜平负"] == "放弃"
    assert pred["final_pick_cn"] == "放弃"
    info = pred["jingcai_pick_info"]
    assert info["jingcai_pick"] == "skip"
    assert info["buyable"] is False
    assert "【竞彩可购】" not in pred["summary"]
    assert "【当前建议】放弃" in pred["summary"]
    # 参考研判方向保留（不删欧赔参考数据），但标注非可购，避免与放弃同页拧巴
    assert "【参考研判】欧亚倾向主胜（非可购）" in pred["summary"]
    assert "【参考研判】主胜（欧赔+亚盘+历史）" not in pred["summary"]


def test_scrub_zero_scores_clears_bare_likely_scores():
    """detail 全 0.0% 被清空时，无有效概率的裸比分 likely_scores 一并清空。"""
    pred = _fixture_1427956_abandoned()
    scrub_zero_percent_scores(pred)
    assert pred["likely_scores_detail"] == []
    assert pred["likely_scores"] == []
    assert "0.0%" not in pred["predict_row"]["推荐比分"]


def test_pred_card_abandoned_shows_current_advice_not_buyable_home():
    """真实 1427956 pred：详情主推荐行含「当前建议：放弃」，不含「竞彩可购：主胜」。"""
    pred = _fixture_1427956_abandoned()
    html = _pred_card(pred)
    assert "当前建议：</strong>放弃" in html
    assert "竞彩可购：主胜" not in html
    # 无有效概率的裸比分「2-1」不展示（detail 清空后）
    assert "2-1" not in html


def test_pred_card_abandoned_buy_line_no_sp_and_muted_sp_ref():
    """放弃态收口：当前建议行同行无 SP / 竞彩玩法；SP 另起 muted 行；参考研判标（非可购）。"""
    pred = _fixture_1427956_abandoned()
    html = _pred_card(pred)
    assert "当前建议：</strong>放弃" in html
    # 当前建议行（第一个 <p> 段）同行不拼 SP、不拼竞彩玩法
    seg = html.split("当前建议：", 1)[1].split("</p>", 1)[0]
    assert "SP" not in seg
    assert "胜平负" not in seg
    # SP 信息保留在 muted 行，明确「仅供参考」
    assert "盘口 SP 仅供参考：胜平负 SP 2.07" in html
    # 参考研判降权为 muted 且标（非可购），不删欧赔参考数据
    assert "参考研判：</strong>欧亚倾向主胜（非可购）" in html
    # 头部 pick 行不带 SP / 玩法 tag
    assert "放弃</strong> · SP" not in html
    assert "竞彩可购：主胜" not in html
