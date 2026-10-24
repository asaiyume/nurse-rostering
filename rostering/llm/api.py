"""Small OpenAI-compatible client; credentials are attached only to HTTP headers."""

import json
import os
import time
import urllib.error
import urllib.request
from urllib.parse import urlparse


class APIError(RuntimeError):
    pass


def request_response(config: dict, payload: dict, timeout: int = 180) -> tuple[dict, float]:
    routes = {"responses": "/responses", "chat_completions": "/chat/completions"}
    if config.get("api_style") not in routes:
        raise ValueError("Unsupported API style")
    url = config["base_url"].rstrip("/") + routes[config["api_style"]]
    if urlparse(url).scheme != "https":
        raise ValueError("API base_url must use HTTPS")
    key = os.environ.get(config["api_key_env"])
    if not key:
        raise APIError(f"Set {config['api_key_env']} in your shell")
    request = urllib.request.Request(
        url, data=json.dumps(payload).encode(),
        headers={"Authorization": "Bearer " + key, "Content-Type": "application/json"},
        method="POST",
    )
    started = time.perf_counter()
    try:
        # There are no automatic retries: each baseline run is one recorded request.
        with urllib.request.urlopen(request, timeout=timeout) as response:
            result = json.load(response)
    except urllib.error.HTTPError as error:
        raise APIError(f"API request failed (HTTP {error.code}); body omitted") from None
    except (urllib.error.URLError, TimeoutError, OSError, ValueError):
        raise APIError("Connection failed or response was not valid JSON") from None
    if not isinstance(result, dict):
        raise APIError("API response must be an object")
    return result, time.perf_counter() - started


def output_text(response: dict) -> str:
    if "choices" in response:
        choices = response.get("choices") or []
        return (choices[0].get("message", {}).get("content") or "") if choices else ""
    return "".join(
        part.get("text", "")
        for item in response.get("output", []) if item.get("type") == "message"
        for part in item.get("content", []) if part.get("type") == "output_text"
    )


def completed(response: dict) -> bool:
    if "choices" in response:
        return bool(response["choices"]) and response["choices"][0].get("finish_reason") == "stop"
    return response.get("status") == "completed"


def response_status(response: dict) -> str | None:
    if "choices" in response:
        return response["choices"][0].get("finish_reason") if response["choices"] else None
    return response.get("status")


def token_usage(response: dict) -> dict:
    usage = response.get("usage") or {}
    if "prompt_tokens" in usage:
        return {"input_tokens": usage.get("prompt_tokens", 0), "output_tokens": usage.get("completion_tokens", 0), "total_tokens": usage.get("total_tokens", 0)}
    return usage
