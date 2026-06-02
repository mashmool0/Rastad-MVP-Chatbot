from django.conf import settings


def get_llm():
    if settings.LLM_PROVIDER == "mock":
        from adapters.llm.mock import MockLLMAdapter
        return MockLLMAdapter()
    from adapters.llm.openrouter import OpenRouterLLMAdapter
    return OpenRouterLLMAdapter()


def get_embedder():
    from adapters.embedding.jina import JinaEmbeddingAdapter
    return JinaEmbeddingAdapter()
