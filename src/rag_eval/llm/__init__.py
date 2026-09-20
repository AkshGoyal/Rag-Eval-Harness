"""The single boundary between this project and any model provider."""

from rag_eval.llm.budget import BudgetExceededError, BudgetGuard
from rag_eval.llm.cache import ResponseCache, cache_key
from rag_eval.llm.client import MissingCredentialsError, ModelClient, ModelError
from rag_eval.llm.transport import HttpTransport, Transport, TransportError
from rag_eval.llm.types import (
    CallRecord,
    ChatRequest,
    ChatResult,
    EmbeddingRequest,
    EmbeddingResult,
    Message,
    ModelPrice,
    Role,
    Usage,
)

__all__ = [
    "BudgetExceededError",
    "BudgetGuard",
    "CallRecord",
    "ChatRequest",
    "ChatResult",
    "EmbeddingRequest",
    "EmbeddingResult",
    "HttpTransport",
    "Message",
    "MissingCredentialsError",
    "ModelClient",
    "ModelError",
    "ModelPrice",
    "ResponseCache",
    "Role",
    "Transport",
    "TransportError",
    "Usage",
    "cache_key",
]
