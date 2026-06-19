"""Multi-provider AI profiles (DeepSeek + Doubao + Cursor + Kimi/Moonshot)."""

from __future__ import annotations

import copy
import logging
import os
from dataclasses import dataclass, field

log = logging.getLogger(__name__)

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
    alt_api_key_envs: tuple[str, ...] = field(default_factory=tuple)
    client: str = "openai"

    def resolve_api_key(self) -> str | None:
        env_names = [self.api_key_env, *self.alt_api_key_envs]
        if self.provider_id == "doubao":
            env_names.extend(["DOUBAO_API_KEY", "ARK_API_KEY"])
        elif self.provider_id == "kimi":
            env_names.extend(["KIMI_API_KEY", "MOONSHOT_API_KEY"])
        elif self.provider_id == "cursor":
            env_names.extend(["CURSOR_API_KEY"])
        elif self.provider_id == "deepseek":
            env_names.append("DEEPSEEK_API_KEY")
        seen: set[str] = set()
        for name in env_names:
            if not name or name in seen:
                continue
            seen.add(name)
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
        for name in env_names:
            if not name:
                continue
            key = getattr(secrets, name, None)
            if key:
                return key.strip()
        return None


def profile_from_entry(entry: dict) -> AiProfile:
    alts = entry.get("alt_api_key_envs") or []
    return AiProfile(
        provider_id=str(entry.get("id") or ""),
        label=str(entry.get("label") or entry.get("id") or ""),
        model=str(entry.get("model") or ""),
        base_url=str(entry.get("base_url") or ""),
        api_key_env=str(entry.get("api_key_env") or ""),
        alt_api_key_envs=tuple(str(x) for x in alts),
        client=str(entry.get("client") or "openai"),
    )


def _apply_overrides(
    prof: AiProfile,
    *,
    model: str | None = None,
    base_url: str | None = None,
) -> AiProfile:
    if not model and not base_url:
        return prof
    return AiProfile(
        provider_id=prof.provider_id,
        label=prof.label,
        model=model or prof.model,
        base_url=base_url or prof.base_url,
        api_key_env=prof.api_key_env,
        alt_api_key_envs=prof.alt_api_key_envs,
        client=prof.client,
    )


def _legacy_deepseek_profile(model: str | None = None) -> AiProfile:
    return AiProfile(
        provider_id="deepseek",
        label="DeepSeek 精算师",
        model=model or os.environ.get("DEEPSEEK_MODEL", "deepseek-chat"),
        base_url=os.environ.get("DEEPSEEK_BASE_URL", DEEPSEEK_BASE_URL),
        api_key_env="DEEPSEEK_API_KEY",
    )


def _legacy_doubao_profile(model: str | None = None) -> AiProfile:
    if not model:
        model = os.environ.get("DOUBAO_MODEL") or os.environ.get("DOUBAO_ENDPOINT")
        if not model:
            model = _local_secret("DOUBAO_MODEL")
        if not model:
            model = DOUBAO_DEFAULT_MODEL
    return AiProfile(
        provider_id="doubao",
        label="豆包 精算师",
        model=model,
        base_url=os.environ.get("DOUBAO_BASE_URL", DOUBAO_BASE_URL),
        api_key_env="DOUBAO_API_KEY",
        alt_api_key_envs=("ARK_API_KEY",),
    )


def _legacy_cursor_profile(model: str | None = None) -> AiProfile:
    if not model or model == "deepseek-chat":
        model = os.environ.get("CURSOR_MODEL") or _local_secret("CURSOR_MODEL", CURSOR_DEFAULT_MODEL)
    return AiProfile(
        provider_id="cursor",
        label="Cursor Composer",
        model=model,
        base_url=CURSOR_BASE_URL,
        api_key_env="CURSOR_API_KEY",
        client="cursor",
    )


def _legacy_kimi_profile(model: str | None = None) -> AiProfile:
    if not model:
        model = os.environ.get("KIMI_MODEL") or os.environ.get("MOONSHOT_MODEL")
        if not model:
            model = _local_secret("KIMI_MODEL") or _local_secret("MOONSHOT_MODEL")
        if not model:
            model = KIMI_DEFAULT_MODEL
    base = os.environ.get("KIMI_BASE_URL") or os.environ.get("MOONSHOT_BASE_URL") or KIMI_BASE_URL
    return AiProfile(
        provider_id="kimi",
        label="Kimi 精算师",
        model=model,
        base_url=base,
        api_key_env="MOONSHOT_API_KEY",
        alt_api_key_envs=("KIMI_API_KEY",),
    )


# Backward-compatible aliases used elsewhere in the codebase
_deepseek_profile = _legacy_deepseek_profile
_doubao_profile = _legacy_doubao_profile
_cursor_profile = _legacy_cursor_profile
_kimi_profile = _legacy_kimi_profile


def get_profile_by_id(
    provider_id: str,
    *,
    output_root: str | os.PathLike | None = None,
    model: str | None = None,
    base_url: str | None = None,
) -> AiProfile | None:
    from ai_config import entry_requires_env, load_raw_config, provider_entry, resolve_api_key

    pid = (provider_id or "").strip().lower()
    cfg = load_raw_config(output_root)
    entry = provider_entry(cfg, pid)
    if entry:
        if not entry_requires_env(entry):
            return None
        if not resolve_api_key(entry):
            return None
        prof = profile_from_entry(entry)
        return _apply_overrides(prof, model=model, base_url=base_url)

    legacy = {
        "deepseek": _legacy_deepseek_profile,
        "doubao": _legacy_doubao_profile,
        "cursor": _legacy_cursor_profile,
        "kimi": _legacy_kimi_profile,
    }.get(pid)
    if not legacy:
        return None
    prof = legacy(model)
    if not prof.resolve_api_key():
        return None
    return _apply_overrides(prof, model=model, base_url=base_url)


def get_primary_profile(
    model: str | None = None,
    base_url: str | None = None,
    *,
    output_root: str | os.PathLike | None = None,
) -> AiProfile:
    from ai_config import load_raw_config, provider_entry, resolve_api_key

    cfg = load_raw_config(output_root)
    primary_id = str(cfg.get("primary_id") or primary_provider()).strip().lower()
    entry = provider_entry(cfg, primary_id)
    if entry and resolve_api_key(entry):
        return _apply_overrides(profile_from_entry(entry), model=model, base_url=base_url)

    provider = primary_provider()
    if provider == "cursor":
        prof = _legacy_cursor_profile(model)
        return _apply_overrides(prof, model=model, base_url=base_url or prof.base_url)
    prof = _legacy_deepseek_profile(model)
    return _apply_overrides(prof, model=model, base_url=base_url or prof.base_url)


def load_profiles(
    *,
    dual: bool = False,
    primary_model: str | None = None,
    primary_base_url: str | None = None,
    secondary_model: str | None = None,
    secondary_base_url: str | None = None,
    kimi_model: str | None = None,
    output_root: str | os.PathLike | None = None,
    role: str = "predict",
) -> list[AiProfile]:
    """Return enabled profiles with valid API keys (config-driven)."""
    from ai_config import entry_requires_env, load_raw_config, resolve_api_key

    cfg = load_raw_config(output_root)
    predict_mode = str(cfg.get("predict_mode") or "multi").lower()
    if dual:
        predict_mode = "multi"

    entries = [e for e in (cfg.get("providers") or []) if e.get("enabled", True)]
    entries.sort(key=lambda e: e.get("order", 999))

    def _to_profile(entry: dict, *, model=None, base_url=None) -> AiProfile | None:
        if role not in (entry.get("roles") or []):
            return None
        if not entry_requires_env(entry):
            return None
        if not resolve_api_key(entry):
            return None
        prof = profile_from_entry(entry)
        if entry.get("id") == "doubao" and secondary_model:
            model = secondary_model
            base_url = secondary_base_url or base_url
        if entry.get("id") == "kimi" and kimi_model:
            model = kimi_model
        if entry.get("id") == cfg.get("primary_id") and primary_model:
            model = primary_model
            base_url = primary_base_url or base_url
        return _apply_overrides(prof, model=model, base_url=base_url)

    profiles: list[AiProfile] = []
    primary_id = str(cfg.get("primary_id") or "deepseek")

    if predict_mode == "primary_only" or predict_mode == "single":
        entry = next((e for e in entries if e.get("id") == primary_id), None)
        if entry:
            prof = _to_profile(entry, model=primary_model, base_url=primary_base_url)
            if prof:
                profiles.append(prof)
        if not profiles:
            primary = get_primary_profile(primary_model, primary_base_url, output_root=output_root)
            if primary.resolve_api_key():
                profiles.append(primary)
        return profiles

    for entry in entries:
        prof = _to_profile(entry)
        if prof:
            profiles.append(prof)

    if not profiles:
        primary = get_primary_profile(primary_model, primary_base_url, output_root=output_root)
        if primary.resolve_api_key():
            profiles.append(primary)
        if dual:
            db = _legacy_doubao_profile(secondary_model)
            if secondary_base_url:
                db = _apply_overrides(db, base_url=secondary_base_url)
            if db.resolve_api_key():
                profiles.append(db)

    if dual and len(profiles) <= 1:
        for pid in ("doubao", "cursor", "kimi"):
            if any(p.provider_id == pid for p in profiles):
                continue
            if pid == "kimi" and not kimi_enabled():
                continue
            legacy = {
                "doubao": lambda: _legacy_doubao_profile(secondary_model),
                "cursor": _legacy_cursor_profile,
                "kimi": lambda: _legacy_kimi_profile(kimi_model),
            }[pid]()
            if pid == "doubao" and secondary_base_url:
                legacy = _apply_overrides(legacy, base_url=secondary_base_url)
            if legacy.resolve_api_key():
                profiles.append(legacy)
            elif pid == "doubao":
                log.warning(
                    "豆包未配置：请设置 ARK_API_KEY（或 DOUBAO_API_KEY），可选 DOUBAO_MODEL（默认 %s）",
                    DOUBAO_DEFAULT_MODEL,
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
