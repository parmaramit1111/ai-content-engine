"""Provider abstractions for external AI services (ARCHITECTURE §4.2).

Only create abstractions that protect the application/domain layer from a real
external dependency. See ARCHITECTURE §4.2 for details.
"""

from content_engine.providers.base import TextGenerationProvider
from content_engine.providers.results import GenerationResult, GenerationUsage

__all__ = [
    "GenerationResult",
    "GenerationUsage",
    "TextGenerationProvider",
]
