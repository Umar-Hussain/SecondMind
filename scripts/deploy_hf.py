"""Deploy SecondMind to a Hugging Face Space (Docker SDK, free CPU hardware).

    hf auth login                      # once, with your own write token
    # ...or put HF_TOKEN=<write token> in .env (git-ignored; used only to talk to Hugging Face)
    python scripts/deploy_hf.py                        # -> DaniilDubov/secondmind
    python scripts/deploy_hf.py --space me/my-space

What it does

1. Creates the Space if needed (``sdk=docker``).
2. Copies the secrets (LLM key, Lichess token, contact email, admin login, token-signing key) from your local
   ``.env`` into the Space's encrypted *secrets* (never into a file or the image).
3. Uploads the code (no .env, databases, node_modules, engine binary or caches) with the Space README.

The Space then builds the Dockerfile and serves the app at https://<user>-<space>.hf.space
"""

from __future__ import annotations

import argparse
import shutil
import tempfile
from pathlib import Path

from huggingface_hub import HfApi

ROOT = Path(__file__).resolve().parents[1]
SECRETS = ("LLM_API_KEY", "LICHESS_TOKEN", "CHESSCOM_CONTACT_EMAIL", "ADMIN_USERNAME", "ADMIN_PASSWORD", "SECRET_KEY")
INCLUDE = ["Dockerfile", ".dockerignore", "requirements.txt", "pyproject.toml",
           "backend/**", "frontend/**", "scripts/**"]
EXCLUDE = ["**/node_modules/**", "**/dist/**", "frontend/public/stockfish/**", "**/__pycache__/**",
           "backend/data/cache/**", "*.db", "*.log", ".env"]


def read_env() -> dict[str, str]:
    values: dict[str, str] = {}
    env = ROOT / ".env"
    if env.exists():
        for line in env.read_text(encoding="utf-8").splitlines():
            if "=" in line and not line.lstrip().startswith("#"):
                k, v = line.split("=", 1)
                values[k.strip()] = v.strip()
    return values


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--space", default="DaniilDubov/secondmind")
    ap.add_argument("--private", action="store_true", help="create the Space as private")
    args = ap.parse_args()

    env = read_env()
    # Token from `hf auth login`, or from HF_TOKEN in the git-ignored .env (never uploaded).
    api = HfApi(token=env.get("HF_TOKEN") or None)
    print(f"Logged in as {api.whoami()['name']}")
    api.create_repo(args.space, repo_type="space", space_sdk="docker", private=args.private, exist_ok=True)

    if not env.get("SECRET_KEY"):
        # A fixed signing key keeps people logged in across Space restarts.
        import secrets as _secrets

        env["SECRET_KEY"] = _secrets.token_hex(32)
    for key in SECRETS:
        if env.get(key):
            api.add_space_secret(args.space, key, env[key])
            print(f"secret set: {key}")
        else:
            print(f"secret missing in .env (skipped): {key}")

    # Upload the code plus the Space README (the GitHub README stays as it is).
    with tempfile.TemporaryDirectory() as tmp:
        readme = Path(tmp) / "README.md"
        shutil.copy(ROOT / "deploy" / "hf_space_README.md", readme)
        api.upload_file(path_or_fileobj=str(readme), path_in_repo="README.md", repo_id=args.space,
                        repo_type="space", commit_message="Space README")
    api.upload_folder(folder_path=str(ROOT), repo_id=args.space, repo_type="space",
                      allow_patterns=INCLUDE, ignore_patterns=EXCLUDE,
                      commit_message="Deploy SecondMind")
    user, name = args.space.split("/")
    print(f"Uploaded. The Space is building: https://huggingface.co/spaces/{args.space}")
    print(f"App URL once built: https://{user.lower()}-{name.lower()}.hf.space")


if __name__ == "__main__":
    main()
