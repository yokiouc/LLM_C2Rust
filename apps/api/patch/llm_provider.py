"""Compatibility re-export for patch LLM providers.

The maintained template backend lives in packages.repair.llm_provider.
"""

from packages.repair.llm_provider import (  # noqa: F401
    LLMProvider,
    OpenAIProvider,
    TemplateEditProvider,
    TemplateProvider,
    provider_from_env,
)

