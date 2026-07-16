"""Config loading and profile merge."""

from graphrag.config import load_settings
from graphrag.config.settings import Settings


def test_default_profile_loads():
    settings, secrets = load_settings(profile="local")
    assert isinstance(settings, Settings)
    assert settings.llm.provider == "ollama"  # from local.yaml
    assert settings.embeddings.provider == "ollama"
    assert settings.embeddings.model == "bge-m3:latest"


def test_config_dir_from_env(tmp_path, monkeypatch):
    # Installed away from the repo (site-packages, as in the Docker image), the
    # profiles can't be found by walking up from this module — GRAPHRAG_CONFIG_DIR
    # is what points at them.
    (tmp_path / "default.yaml").write_text("app:\n  corpus: from-env-dir\n", encoding="utf-8")
    monkeypatch.setenv("GRAPHRAG_CONFIG_DIR", str(tmp_path))
    settings, _ = load_settings(profile="local")
    assert settings.app.corpus == "from-env-dir"


def test_api_profile_overrides_default():
    settings, _ = load_settings(profile="api")
    assert settings.llm.provider == "anthropic"
    assert settings.llm.model == "claude-opus-4-8"
    assert settings.embeddings.provider == "voyage"


def test_rich_embedding_knobs_present():
    settings, _ = load_settings(profile="local")
    emb = settings.embeddings
    # The fine-grained controls the user asked for must survive the merge.
    for field in ("batch_size", "normalize", "max_seq_length", "query_prefix", "pooling"):
        assert hasattr(emb, field)


def test_tenancy_defaults():
    settings, _ = load_settings(profile="api")
    t = settings.tenancy
    assert t.enabled is True
    assert t.default_user == "default"
    assert t.per_tenant_database is False  # Community-safe default
    assert t.max_active_tenants > 0
