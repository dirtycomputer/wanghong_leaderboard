"""Request policy for the participant-side OpenRouter proxy.

Every participant request must pass ``enforce_request`` before it is
forwarded upstream. The policy is intentionally strict and defaults to
refusal — anything that could reach post-cutoff knowledge (``:online``
suffix, OpenRouter web plugin, generic tool calls, server tools,
provider fallback) is rejected.

The same module is reused by internal callers (e.g. the Gemma
contamination canary) so that one set of rules is enforced everywhere.
"""

from __future__ import annotations

import os
import re
from dataclasses import dataclass
from typing import Any

GEMMA_MODEL_ID = "google/gemma-4-31b-it"

_FORBIDDEN_REQUEST_KEYS: tuple[str, ...] = (
    "tools",
    "tool_choice",
    "tool_results",
    "functions",
    "function_call",
    "web_search_options",
    "response_format_tools",
)

_SERVER_TOOL_PATTERN = re.compile(r"openrouter:(web_search|web_fetch|file_search)")


class PolicyViolation(ValueError):
    """Raised when a request would violate the time-capsule policy."""


@dataclass(frozen=True)
class PolicyDecision:
    """Result of enforcing the policy on a request body.

    ``request`` is a deep-copied, normalized version of the input with
    safe defaults injected (provider pinning, disabled web plugin).
    """

    request: dict[str, Any]


def enforce_request(body: dict[str, Any]) -> PolicyDecision:
    """Validate and normalize an OpenRouter chat completions request.

    Raises :class:`PolicyViolation` on any disallowed field. Returns a
    :class:`PolicyDecision` with a normalized request that callers may
    forward to OpenRouter.
    """
    if not isinstance(body, dict):
        raise PolicyViolation("request body must be a JSON object")

    out = _shallow_copy(body)

    _check_model(out)
    _check_forbidden_keys(out)
    _check_plugins(out)
    _check_server_tools_in_messages(out)

    out["plugins"] = [{"id": "web", "enabled": False}]
    out["provider"] = safe_provider_envelope(out.get("provider"))

    return PolicyDecision(request=out)


def safe_provider_envelope(existing: Any | None) -> dict[str, Any]:
    """Build the provider routing envelope.

    Pins ``allow_fallbacks: false`` and ``data_collection: "deny"`` and,
    when ``GEMMA_PROVIDER_SLUG`` is set in the environment, restricts
    selection to that single provider. Any participant-supplied
    provider field is ignored on purpose so that submissions cannot
    route to an upstream that ignores other policy fields.
    """
    pinned = os.environ.get("GEMMA_PROVIDER_SLUG", "").strip()
    envelope: dict[str, Any] = {
        "allow_fallbacks": False,
        "require_parameters": True,
        "data_collection": "deny",
    }
    if pinned:
        envelope["only"] = [pinned]
    return envelope


def _shallow_copy(body: dict[str, Any]) -> dict[str, Any]:
    return {k: v for k, v in body.items()}


def _check_model(body: dict[str, Any]) -> None:
    model = body.get("model")
    if not isinstance(model, str) or not model:
        raise PolicyViolation("model is required")
    if model != GEMMA_MODEL_ID:
        raise PolicyViolation(
            f"model {model!r} is not allowed; only {GEMMA_MODEL_ID!r} may be used"
        )


def _check_forbidden_keys(body: dict[str, Any]) -> None:
    for key in _FORBIDDEN_REQUEST_KEYS:
        if key in body and body[key] not in (None, [], {}):
            raise PolicyViolation(
                f"request field {key!r} is forbidden; the participant proxy "
                "does not allow tool-call or web-search payloads"
            )


def _check_plugins(body: dict[str, Any]) -> None:
    plugins = body.get("plugins")
    if plugins is None:
        return
    if not isinstance(plugins, list):
        raise PolicyViolation("plugins must be a list")
    for plugin in plugins:
        if not isinstance(plugin, dict):
            raise PolicyViolation("each plugin entry must be a JSON object")
        plugin_id = plugin.get("id")
        if plugin_id != "web":
            raise PolicyViolation(
                f"plugin {plugin_id!r} is not allowed; only the web plugin may "
                "appear and it must be explicitly disabled"
            )
        if plugin.get("enabled", True):
            raise PolicyViolation(
                "the web plugin must be passed with enabled=false; "
                "the participant proxy never permits online browsing"
            )


def _check_server_tools_in_messages(body: dict[str, Any]) -> None:
    messages = body.get("messages")
    if not isinstance(messages, list):
        return
    for msg in messages:
        if not isinstance(msg, dict):
            continue
        content = msg.get("content")
        if isinstance(content, str) and _SERVER_TOOL_PATTERN.search(content):
            raise PolicyViolation(
                "messages may not reference openrouter server tools "
                "(web_search / web_fetch / file_search)"
            )
        if isinstance(content, list):
            for part in content:
                if (
                    isinstance(part, dict)
                    and isinstance(part.get("text"), str)
                    and _SERVER_TOOL_PATTERN.search(part["text"])
                ):
                    raise PolicyViolation(
                        "messages may not reference openrouter server tools "
                        "(web_search / web_fetch / file_search)"
                    )
