"""结果预测：五源融合 → 1X2 预测（必发 + 欧赔 + 亚盘 + 历史相似 + 近期战绩）。"""

from analysis.result_forecast.context import build_result_forecast_context
from analysis.result_forecast.engine import forecast, forecast_for_match

__all__ = ["build_result_forecast_context", "forecast", "forecast_for_match"]
