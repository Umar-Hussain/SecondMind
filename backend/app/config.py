"""Application settings.

All configuration comes from environment variables (or a local ``.env`` file)
through pydantic-settings, so no secret is ever hard-coded. Thresholds used by
the chess rules in the specification (section 8) also live here so they can be
tuned without touching code.
"""

from __future__ import annotations

from functools import lru_cache
from pathlib import Path

from pydantic import field_validator
from pydantic_settings import BaseSettings, SettingsConfigDict

# Repository root: backend/app/config.py -> parents[2]
ROOT_DIR = Path(__file__).resolve().parents[2]
BACKEND_DIR = ROOT_DIR / "backend"
DATA_DIR = BACKEND_DIR / "data"
FIXTURES_DIR = DATA_DIR / "fixtures"
CORPUS_DIR = DATA_DIR / "corpus"


class Settings(BaseSettings):
    """Typed settings loaded from the environment."""

    model_config = SettingsConfigDict(
        env_file=str(ROOT_DIR / ".env"),
        env_file_encoding="utf-8",
        extra="ignore",
    )

    # --- LLM provider ------------------------------------------------------
    # "groq" (free tier, default), "ollama" (free, local), "openai_compat" (any
    # OpenAI-style endpoint via LLM_BASE_URL), or "anthropic" (Claude, paid).
    llm_provider: str = "groq"
    llm_api_key: str = ""
    llm_base_url: str = ""  # empty = the provider's default URL
    llm_model: str = ""  # empty = the provider's default model
    anthropic_api_key: str = ""
    anthropic_model: str = "claude-opus-5-5"
    # Extra free models tried in order when the main one is rate limited or down.
    # Entries separated by ";" (or new lines), each "provider|model|api_key" where provider
    # is groq, gemini, openrouter, mistral, cerebras or a full https:// base URL. Example:
    #   gemini|gemini-2.5-flash|KEY1; mistral|mistral-small-latest|KEY2
    llm_fallbacks: str = ""
    llm_cooldown_s: int = 60  # how long a rate-limited model rests before it is tried again

    # --- Accounts ---------------------------------------------------------------
    secret_key: str = ""  # signs login tokens; empty = random key saved under data/cache
    admin_username: str = ""  # admin account created/updated at startup
    admin_password: str = ""  # set it yourself in .env; never committed

    # --- External services -------------------------------------------------
    lichess_token: str = ""
    chesscom_contact_email: str = ""

    # --- Engine ------------------------------------------------------------
    stockfish_path: str = "engine/stockfish/stockfish-windows-x86-64-universal.exe"
    stockfish_threads: int = 2
    stockfish_hash_mb: int = 128
    engine_depth: int = 16  # default depth for single positions (explanations, recommendations)
    # Batch analysis of a user's games: depth 12 finds the opening mistakes above the 80 cp
    # threshold at a fraction of the time of depth 16.
    analysis_depth: int = 12
    judged_moves_after_theory: int = 3  # own moves checked after a game leaves known theory

    # --- Storage -----------------------------------------------------------
    database_url: str = f"sqlite:///{(ROOT_DIR / 'repertoire.db').as_posix()}"

    @field_validator("database_url")
    @classmethod
    def _default_db(cls, v: str) -> str:
        """An empty DATABASE_URL means the repo-root SQLite file, whatever the working directory."""
        return v or f"sqlite:///{(ROOT_DIR / 'repertoire.db').as_posix()}"

    # --- Fixture / offline mode --------------------------------------------
    offline: bool = False
    record_fixtures: bool = False

    # --- Chess rule thresholds ----------------------------
    mistake_threshold_cp: int = 80     # leak / deviation "mistake" cutoff
    harmless_threshold_cp: int = 30    # deviation considered harmless
    repertoire_issue_cp: int = 50      # repertoire move worse than best by this
    max_loss_cp: int = 30              # recommender: acceptable loss vs best
    min_master_games: int = 50         # recommender: minimum master sample
    recommender_multipv: int = 5
    opening_plies: int = 20            # "opening phase" for leak mining
    respect_gambits: bool = True

    # --- Agent -------------------------------------------------------------
    agent_max_steps: int = 15

    @property
    def stockfish_abspath(self) -> Path:
        """Resolve the Stockfish path relative to the repository root."""
        p = Path(self.stockfish_path)
        return p if p.is_absolute() else ROOT_DIR / p

    @property
    def llm_enabled(self) -> bool:
        """The LLM layer is active only when its provider is usable.

        Hosted providers need a key; a local Ollama server needs none.
        """
        provider = self.llm_provider.lower()
        if provider == "anthropic":
            return bool(self.anthropic_api_key)
        if provider == "ollama":
            return True
        return bool(self.llm_api_key)

    @property
    def llm_fallback_list(self) -> list[tuple[str, str, str]]:
        """Parsed ``llm_fallbacks``: [(base_url, model, api_key)], bad entries skipped."""
        out = []
        for raw in self.llm_fallbacks.replace("\n", ";").split(";"):
            parts = [p.strip() for p in raw.split("|")]
            if len(parts) != 3 or not all(parts):
                continue
            provider, model, key = parts
            url = PROVIDER_URLS.get(provider.lower(), provider if provider.startswith("http") else "")
            if url:
                out.append((url.rstrip("/"), model, key))
        return out

    @property
    def llm_settings(self) -> tuple[str, str, str]:
        """(base_url, model, api_key) for OpenAI-compatible providers, with defaults per provider."""
        defaults = {
            "groq": ("https://api.groq.com/openai/v1", "openai/gpt-oss-120b"),
            "ollama": ("http://localhost:11434/v1", "qwen2.5:7b"),
            "openai_compat": ("", ""),
        }
        url, model = defaults.get(self.llm_provider.lower(), ("", ""))
        return (self.llm_base_url or url).rstrip("/"), self.llm_model or model, self.llm_api_key


# OpenAI-compatible endpoints of free providers usable in LLM_FALLBACKS.
PROVIDER_URLS = {
    "groq": "https://api.groq.com/openai/v1",
    "gemini": "https://generativelanguage.googleapis.com/v1beta/openai",
    "openrouter": "https://openrouter.ai/api/v1",
    "mistral": "https://api.mistral.ai/v1",
    "cerebras": "https://api.cerebras.ai/v1",
}


@lru_cache
def get_settings() -> Settings:
    """Return a cached Settings instance (one per process)."""
    return Settings()
