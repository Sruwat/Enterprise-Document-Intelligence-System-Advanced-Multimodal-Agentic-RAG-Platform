from __future__ import annotations

import argparse
from pathlib import Path


LAUNCH_VALUES = {
    "QDRANT_URL": "http://localhost:6333",
    "EMBEDDING_MODEL": "BAAI/bge-m3",
    "EMBEDDING_MODEL_PATH": "./models/bge-m3",
    "RERANKER_MODEL": "BAAI/bge-reranker-v2-m3",
    "RERANKER_MODEL_PATH": "./models/bge-reranker-v2-m3",
    "QDRANT_COLLECTION": "aiwana_chunks_v2",
    "ENABLE_NAMED_VECTORS": "true",
    "ENABLE_BGE_M3_SPARSE": "false",
    "ENABLE_PERSISTENT_MEMORY": "true",
}


def main() -> None:
    args = _parse_args()
    env_path = Path(args.env)
    original = env_path.read_text(encoding="utf-8") if env_path.exists() else ""
    updated = render_env(original, LAUNCH_VALUES)
    if original == updated:
        print(f"{env_path} already uses the Aiwana launch retrieval profile.")
        return
    if args.apply:
        env_path.write_text(updated, encoding="utf-8")
        print(f"Updated {env_path} with the Aiwana launch retrieval profile.")
    else:
        print(f"Dry run for {env_path}. Pass --apply to write these non-secret settings:")
        for key, value in LAUNCH_VALUES.items():
            print(f"{key}={value}")


def render_env(content: str, values: dict[str, str]) -> str:
    seen: set[str] = set()
    output: list[str] = []
    for line in content.splitlines():
        key = _line_key(line)
        if key in values:
            output.append(f"{key}={values[key]}")
            seen.add(key)
        else:
            output.append(line)
    missing = [key for key in values if key not in seen]
    if missing and output and output[-1].strip():
        output.append("")
    output.extend(f"{key}={values[key]}" for key in missing)
    return "\n".join(output).rstrip() + "\n"


def _line_key(line: str) -> str | None:
    stripped = line.strip()
    if not stripped or stripped.startswith("#") or "=" not in stripped:
        return None
    return stripped.split("=", 1)[0].strip()


def _parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Update non-secret .env keys to Aiwana's BGE-M3/Qdrant v2 launch profile.")
    parser.add_argument("--env", default=".env", help="Path to the environment file to update.")
    parser.add_argument("--apply", action="store_true", help="Write changes. Without this flag, prints a dry run.")
    return parser.parse_args()


if __name__ == "__main__":
    main()
