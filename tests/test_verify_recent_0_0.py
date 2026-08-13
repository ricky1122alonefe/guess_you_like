"""verify_recent_0_0.py 健壮性单测。"""

from unittest.mock import patch

import pytest

from scripts.verify_recent_0_0 import main


def test_network_unavailable_returns_exit_2():
    with patch("scripts.verify_recent_0_0._probe_500_network", return_value=(False, "HTTP 403")):
        assert main([]) == 2


def test_resolve_score_none_reports_no_fresh_score_not_genuine():
    """_resolve_score 返回 None 时只能报 MISMATCH/no fresh score，不能误报 genuine。"""
    with patch("scripts.verify_recent_0_0._probe_500_network", return_value=(True, "")), \
         patch("scripts.verify_recent_0_0.get_fixture_by_external", return_value={
             "external_id": "999999", "match_name": "测试 vs 队伍"
         }), \
         patch("scripts.verify_recent_0_0._resolve_score", return_value=None):
        assert main(["--fixture-id", "999999"]) == 1
