from __future__ import annotations

import json
import tarfile
from pathlib import Path

from deploy.staging.build_release_bundle import (
    RUNTIME_ENTRYPOINTS,
    build_release_bundle,
)


def test_bundle_contains_runtime_entrypoints_and_built_frontend(
    tmp_path: Path,
) -> None:
    source_root = Path(__file__).resolve().parents[2]
    frontend_dist = tmp_path / "frontend-dist"
    (frontend_dist / "assets").mkdir(parents=True)
    (frontend_dist / "index.html").write_text("<main>ready</main>", encoding="utf-8")
    (frontend_dist / "assets" / "app.js").write_text("ready", encoding="utf-8")
    output = tmp_path / "release.tar"

    result = build_release_bundle(
        source_root=source_root,
        frontend_dist=frontend_dist,
        output=output,
    )

    with tarfile.open(output) as archive:
        names = set(archive.getnames())
        manifest = json.load(archive.extractfile("release-manifest.json"))

    assert set(RUNTIME_ENTRYPOINTS) <= names
    assert "frontend-dist/index.html" in names
    assert "frontend-dist/assets/app.js" in names
    assert "frontend/src/App.tsx" in names
    assert manifest["git_commit"] == result["git_commit"]
    assert len(result["archive_sha256"]) == 64


def test_bundle_rejects_missing_frontend_build(tmp_path: Path) -> None:
    source_root = Path(__file__).resolve().parents[2]
    frontend_dist = tmp_path / "missing-build"
    frontend_dist.mkdir()

    try:
        build_release_bundle(
            source_root=source_root,
            frontend_dist=frontend_dist,
            output=tmp_path / "release.tar",
        )
    except ValueError as error:
        assert str(error) == "Frontend build is missing index.html"
    else:
        raise AssertionError("Missing frontend build must be rejected")
