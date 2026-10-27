from tools.configure_launch_profile import LAUNCH_VALUES, render_env


def test_render_env_updates_launch_keys_and_preserves_secrets():
    original = "\n".join(
        [
            "GROQ_API_KEY=secret",
            "EMBEDDING_MODEL=BAAI/bge-small-en-v1.5",
            "QDRANT_COLLECTION=rag_chunks",
        ]
    )

    updated = render_env(original, LAUNCH_VALUES)

    assert "GROQ_API_KEY=secret" in updated
    assert "EMBEDDING_MODEL=BAAI/bge-m3" in updated
    assert "QDRANT_COLLECTION=aiwana_chunks_v2" in updated
    assert "RERANKER_MODEL=BAAI/bge-reranker-v2-m3" in updated


def test_render_env_is_idempotent():
    original = render_env("", LAUNCH_VALUES)

    assert render_env(original, LAUNCH_VALUES) == original
