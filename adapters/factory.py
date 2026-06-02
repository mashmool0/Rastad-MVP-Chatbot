from django.conf import settings


def get_llm():
    if settings.LLM_PROVIDER == "mock":
        from adapters.llm.mock import MockLLMAdapter
        return MockLLMAdapter()
    from adapters.llm.openrouter import OpenRouterLLMAdapter
    return OpenRouterLLMAdapter()


def get_embedder():
    if getattr(settings, "EMBEDDING_PROVIDER", "jina") == "mock":
        from adapters.embedding.mock import MockEmbeddingAdapter
        return MockEmbeddingAdapter()
    from adapters.embedding.jina import JinaEmbeddingAdapter
    return JinaEmbeddingAdapter()


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
