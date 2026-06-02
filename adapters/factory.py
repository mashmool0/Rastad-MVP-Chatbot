from django.conf import settings


def get_llm():
    provider = settings.LLM_PROVIDER
    if provider == "mock":
        from adapters.llm.mock import MockLLMAdapter
        return MockLLMAdapter()
    if provider == "openai":
        from adapters.llm.openai import OpenAILLMAdapter
        return OpenAILLMAdapter()
    from adapters.llm.openrouter import OpenRouterLLMAdapter
    return OpenRouterLLMAdapter()


def get_embedder():
    provider = getattr(settings, "EMBEDDING_PROVIDER", "huggingface")
    if provider == "mock":
        from adapters.embedding.mock import MockEmbeddingAdapter
        return MockEmbeddingAdapter()
    if provider == "jina":
        from adapters.embedding.jina import JinaEmbeddingAdapter
        return JinaEmbeddingAdapter()
    from adapters.embedding.huggingface import HuggingFaceEmbeddingAdapter
    return HuggingFaceEmbeddingAdapter()


def build_pipeline():
    from repositories.knowledge_repository import KnowledgeRepository
    from repositories.message_repository import MessageRepository
    from repositories.user_repository import UserRepository
    from services.classifier import ClassifierService
    from services.evaluator import EvaluatorService
    from services.generator import GeneratorService
    from services.pipeline import MessagePipeline
    from services.retriever import RetrieverService

    llm = get_llm()
    embedder = get_embedder()
    knowledge_repo = KnowledgeRepository()

    return MessagePipeline(
        classifier=ClassifierService(llm),
        retriever=RetrieverService(embedder, knowledge_repo),
        evaluator=EvaluatorService(),
        generator=GeneratorService(llm),
        user_repo=UserRepository(),
        message_repo=MessageRepository(),
        knowledge_repo=knowledge_repo,
    )
