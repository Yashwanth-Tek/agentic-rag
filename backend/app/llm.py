"""The Claude client and its error handling."""

import logging

import anthropic

from app.config import Settings
from app.errors import AppError

log = logging.getLogger(__name__)

# Opt-in server-side retry on another model when a safety classifier declines a request.
FALLBACK_BETA = "server-side-fallback-2026-07-01"


def create_llm_client(settings: Settings) -> anthropic.Anthropic:
    return anthropic.Anthropic(
        api_key=settings.anthropic_api_key.get_secret_value(),
        timeout=settings.anthropic_timeout_seconds,
        max_retries=1,
    )


def check_llm(client: anthropic.Anthropic, model: str) -> str | None:
    """None when the key and model work, otherwise a short description of the problem."""
    try:
        client.with_options(timeout=5, max_retries=0).models.retrieve(model)
    except anthropic.AuthenticationError:
        return "The Anthropic API key was rejected."
    except anthropic.NotFoundError:
        return f"Model '{model}' isn't available to this API key."
    except anthropic.APIConnectionError:
        return "The Anthropic API isn't reachable."
    except anthropic.APIStatusError as exc:
        return f"The Anthropic API returned an error ({exc.status_code})."
    return None


def to_app_error(exc: anthropic.APIError) -> AppError:
    """Log the technical detail; give the user a message without internals."""
    log.error(
        "claude request failed",
        extra={
            "error_type": type(exc).__name__,
            "status": getattr(exc, "status_code", None),
            "request_id": getattr(exc, "request_id", None),
            "detail": str(exc)[:500],  # the API's own message; never shown to users
        },
    )
    if isinstance(exc, anthropic.RateLimitError):
        message = "The AI service is busy right now. Please try again in a moment."
        return AppError("LLM_BUSY", message, 503)
    if isinstance(
        exc,
        anthropic.AuthenticationError | anthropic.PermissionDeniedError | anthropic.NotFoundError,
    ):
        message = "The AI service isn't configured correctly. Please check the server settings."
        return AppError("LLM_MISCONFIGURED", message, 503)
    if isinstance(exc, anthropic.APITimeoutError):
        return AppError("LLM_TIMEOUT", "The AI service took too long to respond. Try again.", 504)
    if isinstance(exc, anthropic.APIConnectionError):
        return AppError("LLM_UNAVAILABLE", "The AI service is unreachable. Try again shortly.", 503)
    return AppError("LLM_FAILED", "The AI service returned an error. Please try again.", 502)
