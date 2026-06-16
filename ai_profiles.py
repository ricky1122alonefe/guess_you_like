"""Multi-provider AI profiles (DeepSeek + Doubao + Cursor + Kimi/Moonshot)."""

from __future__ import annotations

import copy
import os
from dataclasses import dataclass

DOUBAO_BASE_URL = "https://ark.cn-beijing.volces.com/api/v3"
DEEPSEEK_BASE_URL = "https://api.deepseek.com"
KIMI_BASE_URL = "https://api.moonshot.cn/v1"
CURSOR_BASE_URL = "cursor-sdk"
DOUBAO_DEFAULT_MODEL = "doubao-seed-2-0-lite-260428"
KIMI_DEFAULT_MODEL = "moonshot-v1-32k"
CURSOR_DEFAULT_MODEL = "composer-2.5"


def _local_secret(name: str, default=None):
    try:
        import local_secrets as secrets
    except ImportError:
        return default
    return getattr(secrets, name, default)


def primary_provider() -> str:
    val = os.environ.get("AI_PROVIDER") or _local_secret("AI_PROVIDER", "deepseek")
    return str(val or "deepseek").strip().lower()


def kimi_enabled() -> bool:
    """Kimi is opt-in via AI_ENABLE_KIMI=1 (default off — token quota)."""
    return os.environ.get("AI_ENABLE_KIMI", "").strip().lower() in ("1", "true", "yes", "on")


from jingcai_pick import final_pick_key, final_recommendation_cn

PICK_CN_TO_KEY = {"主胜": "home", "平局": "draw", "客胜": "away", "观望": "skip"}
CONF_RANK = {"高": 3, "中": 2, "低": 1}


@dataclass(frozen=True)
class AiProfile:
    provider_id: str
    label: str
    model: str
    base_url: str
    api_key_env: str

    def resolve_api_key(self) -> str | None:
        env_names = [self.api_key_env]
        if self.provider_id == "doubao":
            env_names.extend(["DOUBAO_API_KEY", "ARK_API_KEY"])
        elif self.provider_id == "kimi":
            env_names.extend(["KIMI_API_KEY", "MOONSHOT_API_KEY"])
        elif self.provider_id == "cursor":
            env_names.extend(["CURSOR_API_KEY"])
        for name in env_names:
            key = os.environ.get(name)
            if key:
                return key.strip()
        try:
            import local_secrets as secrets
        except ImportError:
            return None
        if self.provider_id == "deepseek":
            key = getattr(secrets, "DEEPSEEK_API_KEY", None)
            return key.strip() if key else None
        if self.provider_id == "doubao":
            for name in ("DOUBAO_API_KEY", "ARK_API_KEY"):
                key = getattr(secrets, name, None)
                if key:
                    return key.strip()
        if self.provider_id == "kimi":
            for name in ("MOONSHOT_API_KEY", "KIMI_API_KEY"):
                key = getattr(secrets, name, None)
                if key:
                    return key.strip()
        if self.provider_id == "cursor":
            key = getattr(secrets, "CURSOR_API_KEY", None)
            return key.strip() if key else None
        return None


def _deepseek_profile(model: str | None = None) -> AiProfile:
    return AiProfile(
        provider_id="deepseek",
        label="DeepSeek 精算师",
        model=model or os.environ.get("DEEPSEEK_MODEL", "deepseek-chat"),
        base_url=os.environ.get("DEEPSEEK_BASE_URL", DEEPSEEK_BASE_URL),
        api_key_env="DEEPSEEK_API_KEY",
    )


def _doubao_profile(model: str | None = None) -> AiProfile:
    if not model:
        model = os.environ.get("DOUBAO_MODEL") or os.environ.get("DOUBAO_ENDPOINT")
        if not model:
            try:
                import local_secrets as secrets
                _local_model = getattr(secrets, "DOUBAO_MODEL", None)
            except ImportError:
                _local_model = None
            if _local_model:
                model = _local_model.strip()
        if not model:
            model = DOUBAO_DEFAULT_MODEL
    return AiProfile(
        provider_id="doubao",
        label="豆包 精算师",
        model=model,
        base_url=os.environ.get("DOUBAO_BASE_URL", DOUBAO_BASE_URL),
        api_key_env="DOUBAO_API_KEY",
    )


def _kimi_profile(model: str | None = None) -> AiProfile:
    if not model:
        model = os.environ.get("KIMI_MODEL") or os.environ.get("MOONSHOT_MODEL")
        if not model:
            try:
                import local_secrets as secrets
                model = getattr(secrets, "KIMI_MODEL", None) or getattr(secrets, "MOONSHOT_MODEL", None)
            except ImportError:
                model = None
        if not model:
            model = KIMI_DEFAULT_MODEL
    base = (
        os.environ.get("KIMI_BASE_URL")
        or os.environ.get("MOONSHOT_BASE_URL")
        or KIMI_BASE_URL
    )
    return AiProfile(
        provider_id="kimi",
        label="Kimi 精算师",
        model=model,
        base_url=base,
        api_key_env="MOONSHOT_API_KEY",
    )


def _cursor_profile(model: str | None = None) -> AiProfile:
    if not model or model == "deepseek-chat":
        model = os.environ.get("CURSOR_MODEL") or _local_secret("CURSOR_MODEL", CURSOR_DEFAULT_MODEL)
    return AiProfile(
        provider_id="cursor",
        label="Cursor Composer",
        model=model,
        base_url=CURSOR_BASE_URL,
        api_key_env="CURSOR_API_KEY",
    )


def get_primary_profile(model: str | None = None, base_url: str | None = None) -> AiProfile:
    provider = primary_provider()
    if provider == "cursor":
        prof = _cursor_profile(model)
        return AiProfile(prof.provider_id, prof.label, prof.model, base_url or prof.base_url, prof.api_key_env)
    prof = _deepseek_profile(model)
    return AiProfile(prof.provider_id, prof.label, prof.model, base_url or prof.base_url, prof.api_key_env)


def load_profiles(
    *,
    dual: bool = False,
    primary_model: str | None = None,
    primary_base_url: str | None = None,
    secondary_model: str | None = None,
    secondary_base_url: str | None = None,
    kimi_model: str | None = None,
) -> list[AiProfile]:
    """Return enabled profiles with valid API keys.

    When dual=True, loads DeepSeek + every optional provider with a key
    (豆包、Cursor；Kimi 需 AI_ENABLE_KIMI=1).
    """
    profiles: list[AiProfile] = []

    primary = get_primary_profile(primary_model, primary_base_url)
    if primary.resolve_api_key():
        profiles.append(primary)

    if dual:
        import logging
        log = logging.getLogger(__name__)

        db = _doubao_profile(secondary_model)
        if secondary_base_url:
            db = AiProfile(
                db.provider_id, db.label, db.model, secondary_base_url, db.api_key_env,
            )
        if db.resolve_api_key():
            profiles.append(db)
        else:
            log.warning(
                "豆包未配置：请设置 ARK_API_KEY（或 DOUBAO_API_KEY），"
                "可选 DOUBAO_MODEL（默认 %s）",
                DOUBAO_DEFAULT_MODEL,
            )

        if primary.provider_id != "cursor":
            cu = _cursor_profile()
            if cu.resolve_api_key():
                profiles.append(cu)
            else:
                log.warning("Cursor 未配置：请设置 CURSOR_API_KEY（可选 CURSOR_MODEL）")

        km = _kimi_profile(kimi_model)
        if kimi_enabled():
            if km.resolve_api_key():
                profiles.append(km)
            else:
                log.warning(
                    "Kimi 已开启但未配置：请设置 MOONSHOT_API_KEY（或 KIMI_API_KEY），"
                    "可选 KIMI_MODEL（默认 %s）",
                    KIMI_DEFAULT_MODEL,
                )

    return profiles


def _pick_info(pred: dict) -> tuple[str, str, int]:
    row = pred.get("predict_row") or {}
    cn = final_recommendation_cn(pred)
    if cn in ("暂无竞彩", "—"):
        cn = "观望"
    key = final_pick_key(pred)
    if key == "skip":
        key = "skip"
    conf = row.get("置信度") or pred.get("confidence_cn") or "低"
    return cn, key, CONF_RANK.get(conf, 1)


def _apply_disagreement_out(out: dict, analyses: dict[str, dict]) -> dict:
    """When models disagree on 1X2, surface 观望 with all views preserved."""
    parts = []
    for pid, p in analyses.items():
        label = p.get("ai_provider_label") or pid
        cn, _, _ = _pick_info(p)
        conf = p.get("confidence_cn") or "低"
        parts.append(f"{label}：{cn}（{conf}）")

    n = len(analyses)
    tag = "多模型" if n > 2 else "双模型"

    out["result_1x2"] = "skip"
    out["result_1x2_cn"] = "观望"
    out["ai_consensus"] = False
    out["ai_disagreement"] = True
    out["confidence_cn"] = "低"
    out["confidence"] = "low"
    out["summary"] = f"【{tag}分歧】" + " | ".join(parts)

    row = copy.deepcopy(out.get("predict_row") or {})
    if row:
        row["胜平负"] = "观望"
        row["竞彩推荐"] = "观望"
        row["备注"] = f"{tag}分歧，建议谨慎"
        out["predict_row"] = row
    return out


def merge_multi_ai_predictions(analyses: dict[str, dict]) -> dict:
    """Merge per-provider AI outputs with explicit consensus / disagreement rules."""
    if not analyses:
        raise ValueError("无 AI 分析结果")

    if len(analyses) == 1:
        pid = next(iter(analyses))
        out = dict(analyses[pid])
        out["ai_analyses"] = analyses
        out["ai_providers"] = [pid]
        out["ai_consensus"] = True
        out["ai_disagreement"] = False
        return out

    infos = {pid: _pick_info(p) for pid, p in analyses.items()}
    directional = {pid: info for pid, info in infos.items() if info[1] != "skip"}
    skip_ids = [pid for pid, info in infos.items() if info[1] == "skip"]
    dir_keys = {info[1] for info in directional.values()}

    disagree = len(dir_keys) > 1 or (len(directional) == 1 and len(skip_ids) >= 1)

    if disagree:
        base_pid = "deepseek" if "deepseek" in analyses else next(iter(analyses))
        out = _apply_disagreement_out(dict(analyses[base_pid]), analyses)
    elif directional:
        best_pid = max(directional, key=lambda pid: infos[pid][2])
        out = dict(analyses[best_pid])
        out["ai_consensus"] = True
        out["ai_disagreement"] = False
    else:
        best_pid = max(analyses, key=lambda pid: infos[pid][2])
        out = dict(analyses[best_pid])
        out["ai_consensus"] = True
        out["ai_disagreement"] = False

    out["ai_analyses"] = analyses
    out["ai_providers"] = list(analyses.keys())
    n = len(analyses)
    out["recommendation_source"] = "ai_multi" if n > 2 else "ai_dual"

    if n > 1 and not out.get("ai_disagreement"):
        parts = []
        for pid, p in analyses.items():
            label = p.get("ai_provider_label") or pid
            pick = infos[pid][0]
            conf = p.get("confidence_cn") or "—"
            parts.append(f"{label}：{pick}（{conf}）")
        tag = "多模型一致" if n > 2 else "双模型一致"
        out["summary"] = f"【{tag}】" + " | ".join(parts) + (f"\n{out.get('summary') or ''}"[:200])

    return out
