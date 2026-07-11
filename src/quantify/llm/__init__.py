"""LLM-ready research review tools for Quantify.

The first version is intentionally model-agnostic: it turns backtest artifacts
into a structured risk review and a prompt pack that any LLM provider can use.
"""
from __future__ import annotations

from quantify.llm.client import LLMClient, LLMClientConfig, LLMNarrativeReview
from quantify.llm.reviewer import (
    LLMReviewPromptBuilder,
    ResearchSnapshot,
    ReviewFinding,
    ReviewResult,
    ReviewThresholds,
    review_report,
)

__all__ = [
    "LLMClient",
    "LLMClientConfig",
    "LLMNarrativeReview",
    "LLMReviewPromptBuilder",
    "ResearchSnapshot",
    "ReviewFinding",
    "ReviewResult",
    "ReviewThresholds",
    "review_report",
]
