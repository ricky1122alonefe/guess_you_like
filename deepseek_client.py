"""DeepSeek API client (OpenAI-compatible)."""

from __future__ import annotations

import json
import os
import subprocess
from typing import Any

import requests

DEFAULT_BASE_URL = "https://api.deepseek.com"
DEFAULT_MODEL = "deepseek-chat"

try:
    from local_secrets import DEEPSEEK_API_KEY as _LOCAL_KEY
except ImportError:
    _LOCAL_KEY = None

try:
    from local_secrets import OPENAI_API_KEY as _LOCAL_OPENAI_KEY
except ImportError:
    _LOCAL_OPENAI_KEY = None

try:
    from local_secrets import CURSOR_API_KEY as _LOCAL_CURSOR_KEY
except ImportError:
    _LOCAL_CURSOR_KEY = None


def _get_api_key(explicit: str | None = None, *, base_url: str | None = None) -> str:
    if explicit:
        return explicit
    url = (base_url or "").lower()
    if url == "cursor-sdk":
        key = os.environ.get("CURSOR_API_KEY") or _LOCAL_CURSOR_KEY
        if key:
            return key
        raise DeepSeekError("请设置 CURSOR_API_KEY")
    if "volces.com" in url or "volcengine" in url:
        for env in ("DOUBAO_API_KEY", "ARK_API_KEY"):
            key = os.environ.get(env)
            if key:
                return key
        try:
            from local_secrets import DOUBAO_API_KEY, ARK_API_KEY
            if DOUBAO_API_KEY:
                return DOUBAO_API_KEY
            if ARK_API_KEY:
                return ARK_API_KEY
        except ImportError:
            pass
    if "moonshot.cn" in url or "moonshot.ai" in url:
        for env in ("MOONSHOT_API_KEY", "KIMI_API_KEY"):
            key = os.environ.get(env)
            if key:
                return key
        try:
            from local_secrets import MOONSHOT_API_KEY, KIMI_API_KEY
            if MOONSHOT_API_KEY:
                return MOONSHOT_API_KEY
            if KIMI_API_KEY:
                return KIMI_API_KEY
        except ImportError:
            pass
    key = os.environ.get("DEEPSEEK_API_KEY") or _LOCAL_KEY
    if not key and base_url and "openai" in url:
        key = os.environ.get("OPENAI_API_KEY") or _LOCAL_OPENAI_KEY
    if not key:
        raise DeepSeekError(
            "请设置 API Key：DeepSeek→DEEPSEEK_API_KEY；豆包→ARK_API_KEY；"
            "Kimi→MOONSHOT_API_KEY（base_url https://api.moonshot.cn/v1）"
        )
    return key


def _chat_cursor_sdk(
    messages: list[dict[str, str]],
    *,
    api_key: str,
    model: str,
    timeout: int,
) -> str:
    try:
        from cursor_sdk import Agent, AgentOptions, LocalAgentOptions
    except ImportError:
        return _chat_cursor_node(
            messages,
            api_key=api_key,
            model=model,
            timeout=timeout,
        )

    prompt_parts = []
    for msg in messages:
        role = msg.get("role", "user")
        content = msg.get("content", "")
        prompt_parts.append(f"[{role}]\n{content}")
    prompt_parts.append("只返回符合要求的纯 JSON，不要 markdown 代码块。")
    prompt = "\n\n".join(prompt_parts)

    result = Agent.prompt(
        prompt,
        AgentOptions(
            api_key=api_key,
            model=model,
            local=LocalAgentOptions(cwd=os.getcwd()),
        ),
    )
    status = getattr(result, "status", "")
    if status and status not in ("finished", "completed", "success"):
        raise DeepSeekError(f"Cursor SDK 运行失败: {status} {getattr(result, 'error', '')}")
    text = getattr(result, "result", None) or getattr(result, "text", None)
    if callable(text):
        text = text()
    if not text:
        raise DeepSeekError("Cursor SDK 返回为空")
    return str(text)


def _chat_cursor_node(
    messages: list[dict[str, str]],
    *,
    api_key: str,
    model: str,
    timeout: int,
) -> str:
    script = os.path.join(os.path.dirname(__file__), "scripts", "cursor_chat.mjs")
    if not os.path.isfile(script):
        raise DeepSeekError("缺少 Cursor Node bridge: scripts/cursor_chat.mjs")
    payload = {
        "messages": messages,
        "apiKey": api_key,
        "model": model,
        "cwd": os.getcwd(),
    }
    proc = subprocess.run(
        ["node", script],
        input=json.dumps(payload, ensure_ascii=False),
        text=True,
        capture_output=True,
        timeout=timeout,
        env={**os.environ, "CURSOR_API_KEY": api_key, "CURSOR_MODEL": model},
    )
    if proc.returncode != 0:
        err = proc.stderr.strip() or proc.stdout.strip()
        raise DeepSeekError(f"Cursor SDK 错误: {err[:500]}")
    try:
        data = json.loads(proc.stdout)
    except json.JSONDecodeError as exc:
        raise DeepSeekError(f"Cursor SDK 输出无法解析: {proc.stdout[:500]}") from exc
    if not data.get("ok"):
        raise DeepSeekError(f"Cursor SDK 运行失败: {data}")
    text = data.get("text")
    if not text:
        raise DeepSeekError("Cursor SDK 返回为空")
    return str(text)


class DeepSeekError(RuntimeError):
    pass


def chat(
    messages: list[dict[str, str]],
    *,
    api_key: str | None = None,
    model: str = DEFAULT_MODEL,
    base_url: str = DEFAULT_BASE_URL,
    temperature: float = 0.3,
    timeout: int = 120,
    max_tokens: int = 4096,
    top_p: float | None = None,
    json_mode: bool = True,
) -> str:
    key = _get_api_key(api_key, base_url=base_url)
    if (base_url or "").lower() == "cursor-sdk":
        return _chat_cursor_sdk(
            messages,
            api_key=key,
            model=model,
            timeout=timeout,
        )

    url = f"{base_url.rstrip('/')}/chat/completions"

    def _post(with_json_mode: bool) -> requests.Response:
        body: dict[str, Any] = {
            "model": model,
            "messages": messages,
            "temperature": temperature,
            "max_tokens": max_tokens,
        }
        if top_p is not None:
            body["top_p"] = top_p
        if with_json_mode:
            body["response_format"] = {"type": "json_object"}
        return requests.post(
            url,
            headers={
                "Authorization": f"Bearer {key}",
                "Content-Type": "application/json",
            },
            json=body,
            timeout=timeout,
        )

    resp = _post(with_json_mode=json_mode)
    if resp.status_code >= 400 and json_mode:
        # 部分模型/接入点不支持 response_format，关闭 JSON 模式重试一次
        resp = _post(with_json_mode=False)
    if resp.status_code >= 400:
        raise DeepSeekError(f"DeepSeek API 错误 {resp.status_code}: {resp.text[:500]}")

    data = resp.json()
    try:
        return data["choices"][0]["message"]["content"]
    except (KeyError, IndexError, TypeError) as exc:
        raise DeepSeekError(f"无法解析 DeepSeek 响应: {json.dumps(data, ensure_ascii=False)[:500]}") from exc
