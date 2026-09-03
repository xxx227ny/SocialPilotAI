"""Build a self-contained, secret-free staging release archive."""

from __future__ import annotations

import argparse
import hashlib
import io
import json
import subprocess
import tarfile
from pathlib import Path

RUNTIME_ENTRYPOINTS = ("server_app.py", "server_runtime.py", "server_worker.py")


def _run_git(source_root: Path, *args: str) -> str:
    result = subprocess.run(
        ["git", *args],
        cwd=source_root,
        check=True,
        capture_output=True,
        text=True,
        encoding="utf-8",
    )
    return result.stdout.strip()


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def build_release_bundle(
    *,
    source_root: Path,
    frontend_dist: Path,
    output: Path,
    revision: str = "HEAD",
) -> dict[str, object]:
    source_root = source_root.resolve()
    frontend_dist = frontend_dist.resolve()
    output = output.resolve()
    if not (frontend_dist / "index.html").is_file():
        raise ValueError("Frontend build is missing index.html")

    commit = _run_git(source_root, "rev-parse", "--verify", f"{revision}^{{commit}}")
    for name in RUNTIME_ENTRYPOINTS:
        if not (source_root / "deploy" / "staging" / name).is_file():
            raise ValueError(f"Missing staging runtime entrypoint: {name}")

    output.parent.mkdir(parents=True, exist_ok=True)
    subprocess.run(
        [
            "git",
            "archive",
            "--format=tar",
            f"--output={output}",
            commit,
        ],
        cwd=source_root,
        check=True,
    )

    with tarfile.open(output, "a") as archive:
        for name in RUNTIME_ENTRYPOINTS:
            archive.add(
                source_root / "deploy" / "staging" / name,
                arcname=name,
                recursive=False,
            )
        archive.add(frontend_dist, arcname="frontend-dist", recursive=True)
        manifest = {
            "format": 1,
            "git_commit": commit,
            "frontend_index_sha256": _sha256(frontend_dist / "index.html"),
            "runtime_entrypoints": list(RUNTIME_ENTRYPOINTS),
        }
        payload = json.dumps(manifest, indent=2, sort_keys=True).encode("utf-8")
        info = tarfile.TarInfo("release-manifest.json")
        info.mode = 0o640
        info.size = len(payload)
        archive.addfile(info, io.BytesIO(payload))

    return {
        **manifest,
        "archive": str(output),
        "archive_sha256": _sha256(output),
    }


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Build a tracked-source staging release with runtime entrypoints."
    )
    parser.add_argument("--source-root", type=Path, required=True)
    parser.add_argument("--frontend-dist", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--revision", default="HEAD")
    args = parser.parse_args()
    result = build_release_bundle(
        source_root=args.source_root,
        frontend_dist=args.frontend_dist,
        output=args.output,
        revision=args.revision,
    )
    print(json.dumps(result, sort_keys=True))


if __name__ == "__main__":
    main()
