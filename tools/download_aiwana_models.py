from __future__ import annotations

import argparse
from pathlib import Path

from huggingface_hub import snapshot_download


MODELS = {
    "BAAI/bge-m3": Path("models/bge-m3"),
    "BAAI/bge-reranker-v2-m3": Path("models/bge-reranker-v2-m3"),
}


def main() -> None:
    args = _parse_args()
    selected = MODELS
    if args.model:
        selected = {repo_id: target for repo_id, target in MODELS.items() if args.model.lower() in repo_id.lower() or args.model.lower() in target.name.lower()}
        if not selected:
            raise SystemExit(f"No configured Aiwana model matches {args.model!r}.")
    for repo_id, target in selected.items():
        target.mkdir(parents=True, exist_ok=True)
        print(f"Downloading {repo_id} -> {target}")
        snapshot_download(
            repo_id=repo_id,
            local_dir=target,
            local_dir_use_symlinks=False,
            resume_download=True,
            max_workers=args.max_workers,
        )
    print("Aiwana v2 models are ready. Update .env to the bge-m3 profile, then run tools/migrate_aiwana_v2.py.")


def _parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Download Aiwana launch retrieval models from Hugging Face.")
    parser.add_argument("--model", help="Download one configured model, for example bge-m3 or reranker.")
    parser.add_argument("--max-workers", type=int, default=4, help="Parallel Hugging Face download workers.")
    return parser.parse_args()


if __name__ == "__main__":
    main()
