import hashlib
from dataclasses import replace
from pathlib import Path
from unittest.mock import patch

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient
from pydantic import ValidationError

from app.api.v1.routes.execution_jobs import create_execution_job
from app.api.v1.routes.video_compositions import router as composition_router
from app.core.config import Settings, get_settings
from app.core.exceptions import AppError, register_exception_handlers
from app.db.session import get_db
from app.models import (
    ExecutionJob,
    Product,
    VideoComposition,
    VideoCompositionArtifact,
    VideoCompositionAudioArtifact,
    VideoCompositionEnhancement,
    VideoCompositionEnhancementArtifact,
    VideoCompositionSubtitleArtifact,
    VideoProject,
)
from app.schemas.execution import ExecutionJobCreate
from app.schemas.video_composition_enhancement import (
    SubtitleCueInput,
    VideoCompositionEnhancementPreflightRequest,
    VideoCompositionEnhancementSubmitRequest,
)
from app.services.video_composition_enhancement_ffmpeg import (
    EnhancementFFmpegInput,
    VideoCompositionEnhancementFFmpeg,
    VideoCompositionEnhancementFFmpegError,
)
from app.services.video_composition_enhancement_job_service import (
    VideoCompositionEnhancementJobService,
)
from app.services.video_composition_enhancement_preflight import (
    VideoCompositionEnhancementPreflightService,
)
from app.services.video_composition_enhancement_probe import (
    EnhancementMedia,
    VideoCompositionEnhancementProbe,
    VideoCompositionEnhancementProbeError,
)
from app.services.video_composition_subtitles import (
    render_ass,
    render_ass_from_webvtt,
    render_webvtt,
)


def _settings(root: Path) -> Settings:
    return Settings(
        _env_file=None,
        enable_video_composition_enhancement=True,
        video_artifact_storage_root=str(root),
        video_composition_temp_root=str(root / "temp"),
    )


def _sha(content: bytes) -> str:
    return hashlib.sha256(content).hexdigest()


def _source(db_session, root: Path):
    product = Product(
        name="Enhancement Product",
        category="Test",
        description="Safe local enhancement",
        selling_points=["Deterministic"],
        target_markets=["USA"],
    )
    db_session.add(product)
    db_session.flush()
    project = VideoProject(
        product_id=product.id,
        marketing_strategy_id=1,
        copy_matrix_id=1,
        platform="TikTok",
        title="Composition",
        concept="Three shots",
        duration_seconds=15,
        aspect_ratio="9:16",
        scenes=[],
        cta="Test",
        status="planned",
    )
    db_session.add(project)
    db_session.flush()
    composition = VideoComposition(
        product_id=product.id,
        video_project_id=project.id,
        input_digest="1" * 64,
        source_chain_digest="2" * 64,
        idempotency_key="stage3a-source",
        version_number=1,
        status="SUCCEEDED",
    )
    db_session.add(composition)
    db_session.flush()
    video = b"fake-stage3a-video"
    video_path = root / "stage3a.mp4"
    video_path.write_bytes(video)
    artifact = VideoCompositionArtifact(
        composition_id=composition.id,
        storage_path=video_path.name,
        content_type="video/mp4",
        size_bytes=len(video),
        sha256=_sha(video),
        duration_ms=15000,
        width=1080,
        height=1920,
        fps_numerator=30,
        fps_denominator=1,
        video_codec="h264",
        pixel_format="yuv420p",
        audio_codec="aac",
        audio_sample_rate=48000,
        container="mp4",
        source_chain_digest=composition.source_chain_digest,
    )
    db_session.add(artifact)
    db_session.flush()
    voice = _audio(
        db_session,
        root,
        product.id,
        project.id,
        composition.id,
        "voiceover",
        b"RIFFvoice",
    )
    music = _audio(
        db_session, root, product.id, project.id, composition.id, "music", b"RIFFmusic"
    )
    db_session.commit()
    return product, project, composition, artifact, voice, music


def _audio(db_session, root, product_id, project_id, composition_id, kind, content):
    path = root / f"{kind}.wav"
    path.write_bytes(content)
    artifact = VideoCompositionAudioArtifact(
        product_id=product_id,
        video_project_id=project_id,
        composition_id=composition_id,
        kind=kind,
        storage_path=path.name,
        content_type="audio/wav",
        size_bytes=len(content),
        sha256=_sha(content),
        duration_ms=15000,
    )
    db_session.add(artifact)
    db_session.flush()
    return artifact


def _request(composition, source, voice, music=None):
    return VideoCompositionEnhancementPreflightRequest(
        composition_id=composition.id,
        source_artifact_id=source.id,
        voiceover_artifact_id=voice.id,
        music_artifact_id=music.id if music else None,
        cues=[
            SubtitleCueInput(sequence=1, start_ms=0, end_ms=5000, text="你好 World"),
            SubtitleCueInput(sequence=2, start_ms=5000, end_ms=10000, text="安全字幕"),
            SubtitleCueInput(
                sequence=3,
                start_ms=10000,
                end_ms=15000,
                text="Final cue",
            ),
        ],
    )


def test_enhancement_preflight_freezes_sources_without_writes(
    db_session, tmp_path
) -> None:
    product, _, composition, source, voice, music = _source(db_session, tmp_path)
    before = {
        model: db_session.query(model).count()
        for model in (VideoCompositionEnhancement, ExecutionJob)
    }
    result = VideoCompositionEnhancementPreflightService(
        db_session, _settings(tmp_path)
    ).run(product.id, _request(composition, source, voice, music))
    assert result.ready is True
    assert result.voiceover.sha256 == voice.sha256
    assert result.music is not None and result.music.sha256 == music.sha256
    assert result.input_digest != result.preflight_digest
    assert result.parameters.target_lufs_milli == -14000
    assert result.parameters.true_peak_millidb == -1000
    assert not db_session.new and not db_session.dirty and not db_session.deleted
    assert {
        model: db_session.query(model).count()
        for model in (VideoCompositionEnhancement, ExecutionJob)
    } == before


def test_enhancement_preflight_rejects_changed_audio_before_ffmpeg(
    db_session, tmp_path
) -> None:
    product, _, composition, source, voice, _ = _source(db_session, tmp_path)
    (tmp_path / voice.storage_path).write_bytes(b"changed")
    with pytest.raises(AppError) as error:
        VideoCompositionEnhancementPreflightService(
            db_session, _settings(tmp_path)
        ).run(product.id, _request(composition, source, voice))
    assert error.value.status_code == 409


@pytest.mark.parametrize("failure", ["missing", "digest", "type", "path"])
def test_enhancement_preflight_rejects_unsafe_audio_artifact(
    db_session, tmp_path, failure
) -> None:
    product, _, composition, source, voice, _ = _source(db_session, tmp_path)
    if failure == "missing":
        (tmp_path / voice.storage_path).unlink()
    elif failure == "digest":
        voice.sha256 = "0" * 64
    elif failure == "type":
        voice.content_type = "audio/mpeg"
    else:
        voice.storage_path = "../outside.wav"
    db_session.flush()
    with pytest.raises(AppError) as error:
        VideoCompositionEnhancementPreflightService(
            db_session, _settings(tmp_path)
        ).run(product.id, _request(composition, source, voice))
    assert error.value.status_code == 409


@pytest.mark.parametrize(
    "cues",
    [
        [
            SubtitleCueInput(sequence=1, start_ms=0, end_ms=5000, text="ok"),
            SubtitleCueInput(
                sequence=2,
                start_ms=4000,
                end_ms=6000,
                text="overlap",
            ),
        ],
        [
            SubtitleCueInput(sequence=1, start_ms=0, end_ms=5000, text="ok"),
            SubtitleCueInput(
                sequence=3,
                start_ms=5000,
                end_ms=15000,
                text="gap",
            ),
        ],
    ],
)
def test_enhancement_rejects_invalid_cue_contract(cues) -> None:
    with pytest.raises(ValidationError):
        VideoCompositionEnhancementPreflightRequest(
            composition_id=1,
            source_artifact_id=1,
            voiceover_artifact_id=1,
            cues=cues,
        )


def test_enhancement_queue_is_idempotent_and_http_stage_provider_free(
    db_session, tmp_path
) -> None:
    product, _, composition, source, voice, music = _source(db_session, tmp_path)
    settings = _settings(tmp_path)
    preflight = VideoCompositionEnhancementPreflightService(db_session, settings).run(
        product.id, _request(composition, source, voice, music)
    )
    submit = VideoCompositionEnhancementSubmitRequest(
        **_request(composition, source, voice, music).model_dump(),
        input_digest=preflight.input_digest,
        source_chain_digest=preflight.source_chain_digest,
        preflight_digest=preflight.preflight_digest,
        preflight_expires_at=preflight.expires_at,
        local_cpu_cost_confirmed=True,
    )
    first = VideoCompositionEnhancementJobService(db_session, settings).enqueue(
        product.id, submit
    )
    second = VideoCompositionEnhancementJobService(db_session, settings).enqueue(
        product.id, submit
    )
    assert second.reused is True
    assert first.enhancement.id == second.enhancement.id
    assert first.job.id == second.job.id
    assert db_session.query(VideoCompositionEnhancement).count() == 1
    assert db_session.query(ExecutionJob).count() == 1


def test_generic_execution_endpoint_rejects_enhancement_job(db_session) -> None:
    with pytest.raises(AppError) as error:
        create_execution_job(
            ExecutionJobCreate(
                job_type="video.composition.enhance.v1",
                source_type="video_composition_enhancement",
                source_id=1,
                input_digest="1" * 64,
                idempotency_key="enhancement-generic-bypass",
                cost_confirmed=True,
            ),
            db_session,
        )
    assert error.value.status_code == 409


def test_subtitle_webvtt_is_utf8_and_deterministic() -> None:
    request = _request(
        type("C", (), {"id": 1})(),
        type("A", (), {"id": 1})(),
        type("V", (), {"id": 1})(),
    )
    first = render_webvtt(request.cues, request.style)
    assert first == render_webvtt(request.cues, request.style)
    assert first.decode("utf-8").startswith("WEBVTT\n")
    assert "你好 World" in first.decode("utf-8")
    assert b"\xef\xbf\xbd" not in first
    assert "line:" not in first.decode("utf-8")
    assert "position:" not in first.decode("utf-8")
    assert "align:" not in first.decode("utf-8")


@pytest.mark.parametrize(
    "text",
    [
        "Single line",
        "Discover a smarter way to create and publish your next campaign.",
        "安全字幕与 English mixed text",
        r"unsafe {\pos(0,0)} path\\value",
    ],
)
def test_subtitle_ass_is_fixed_safe_utf8_and_deterministic(text) -> None:
    cues = [SubtitleCueInput(sequence=1, start_ms=500, end_ms=4778, text=text)]
    style = _request(
        type("C", (), {"id": 1})(),
        type("A", (), {"id": 1})(),
        type("V", (), {"id": 1})(),
    ).style
    first = render_ass(cues, style)
    decoded = first.decode("utf-8")
    assert first == render_ass(cues, style)
    assert "PlayResX: 1080" in decoded
    assert "PlayResY: 1920" in decoded
    assert "Style: Default,Arial,48," in decoded
    assert ",2,54,54,280,1" in decoded
    assert "Dialogue: 0,0:00:00.50,0:00:04.78," in decoded
    assert "{\\pos(0,0)}" not in decoded
    assert b"\xef\xbf\xbd" not in first


def test_webvtt_to_ass_preserves_cue_and_fixed_layout() -> None:
    request = _request(
        type("C", (), {"id": 1})(),
        type("A", (), {"id": 1})(),
        type("V", (), {"id": 1})(),
    )
    webvtt = render_webvtt(request.cues, request.style)
    ass = render_ass_from_webvtt(
        webvtt,
        font_size=request.style.font_size,
        bottom_margin=request.style.bottom_margin,
        outline_width=request.style.outline_width,
    ).decode("utf-8")
    assert "PlayResX: 1080" in ass
    assert "PlayResY: 1920" in ass
    assert ",2,54,54,280,1" in ass
    assert "Dialogue: 0,0:00:00.00,0:00:05.00," in ass
    assert "Dialogue: 0,0:00:05.00,0:00:10.00," in ass
    assert "Dialogue: 0,0:00:10.00,0:00:15.00," in ass


@pytest.mark.parametrize("with_music", [False, True])
def test_enhancement_ffmpeg_builds_frozen_mix_graph(tmp_path, with_music) -> None:
    video = tmp_path / "source.mp4"
    voice = tmp_path / "voice.wav"
    music = tmp_path / "music.wav"
    subtitle = tmp_path / "subtitles.vtt"
    output = tmp_path / "output.mp4"
    for path in (video, voice, music):
        path.write_bytes(b"x")
    subtitle.write_bytes(
        render_webvtt(
            [SubtitleCueInput(sequence=1, start_ms=0, end_ms=15000, text="字幕")],
            _request(
                type("C", (), {"id": 1})(),
                type("A", (), {"id": 1})(),
                type("V", (), {"id": 1})(),
            ).style,
        )
    )

    def fake_run(command, **kwargs):
        if command[-2:] == ["null", "-"]:
            return type(
                "Result",
                (),
                {
                    "returncode": 0,
                    "stdout": b"",
                    "stderr": (
                        b'{"input_i":"-20.51","input_tp":"-6.98",'
                        b'"input_lra":"21.90","input_thresh":"-37.17",'
                        b'"target_offset":"2.83"}'
                    ),
                },
            )()
        output.write_bytes(b"result")
        return type("Result", (), {"returncode": 0, "stdout": b"", "stderr": b""})()

    with patch("subprocess.run", side_effect=fake_run) as run:
        VideoCompositionEnhancementFFmpeg("ffmpeg", 30).render(
            EnhancementFFmpegInput(
                video=video,
                voiceover=voice,
                music=music if with_music else None,
                subtitle=subtitle,
                voiceover_gain_millidb=0,
                music_gain_millidb=-18000,
                ducking_reduction_millidb=12000,
                target_lufs_milli=-14000,
                true_peak_millidb=-1000,
                font_size=48,
                bottom_margin=280,
                outline_width=3,
                voiceover_natural_duration_ms=11440,
            ),
            output,
        )
    assert run.call_count == 2
    analysis_command = run.call_args_list[0].args[0]
    analysis_graph = analysis_command[analysis_command.index("-filter_complex") + 1]
    first_input = analysis_command.index("-i")
    second_input = analysis_command.index("-i", first_input + 1)
    assert analysis_command[first_input + 1] == str(video)
    assert analysis_command[second_input + 1] == str(voice)
    assert analysis_command[-4:] == ["[measure]", "-f", "null", "-"]
    assert "print_format=json" in analysis_graph
    assert "[1:a]" in analysis_graph
    assert ("[2:a]" in analysis_graph) is with_music
    command = run.call_args_list[1].args[0]
    graph = command[command.index("-filter_complex") + 1]
    assert "loudnorm=" not in graph
    assert "volume=6.510dB" in graph
    assert "alimiter=limit=0.891251:level=false" in graph
    assert "subtitles=filename='subtitles.ass':original_size=1080x1920" in graph
    assert "force_style" not in graph
    burn_subtitle = tmp_path / "subtitles.ass"
    assert burn_subtitle.is_file()
    assert "PlayResX: 1080" in burn_subtitle.read_text(encoding="utf-8")
    assert "PlayResY: 1920" in burn_subtitle.read_text(encoding="utf-8")
    assert ("sidechaincompress" in graph) is with_music
    assert (
        "[voice_source]asplit=2[voice][voice_sidechain]" in analysis_graph
    ) is with_music
    assert ("[music][voice_sidechain]sidechaincompress" in analysis_graph) is with_music
    assert ("[voice_source]asplit=2[voice][voice_sidechain]" in graph) is with_music
    assert ("[music][voice_sidechain]sidechaincompress" in graph) is with_music
    assert "anullsrc" not in graph
    assert "atrim=0:11.440,atempo=0.817143" in graph


def test_enhancement_ffmpeg_analysis_failure_never_encodes(tmp_path) -> None:
    video = tmp_path / "source.mp4"
    voice = tmp_path / "voice.wav"
    subtitle = tmp_path / "subtitles.vtt"
    output = tmp_path / "output.mp4"
    for path in (video, voice):
        path.write_bytes(b"x")
    subtitle.write_bytes(
        render_webvtt(
            [SubtitleCueInput(sequence=1, start_ms=0, end_ms=15000, text="字幕")],
            _request(
                type("C", (), {"id": 1})(),
                type("A", (), {"id": 1})(),
                type("V", (), {"id": 1})(),
            ).style,
        )
    )

    with (
        patch(
            "subprocess.run",
            return_value=type(
                "Result",
                (),
                {"returncode": 1, "stdout": b"", "stderr": b"safe failure"},
            )(),
        ) as run,
        pytest.raises(
            VideoCompositionEnhancementFFmpegError,
            match="ENHANCEMENT_LOUDNESS_ANALYSIS_FAILED",
        ),
    ):
        VideoCompositionEnhancementFFmpeg("ffmpeg", 30).render(
            EnhancementFFmpegInput(
                video=video,
                voiceover=voice,
                music=None,
                subtitle=subtitle,
                voiceover_gain_millidb=0,
                music_gain_millidb=-18000,
                ducking_reduction_millidb=12000,
                target_lufs_milli=-14000,
                true_peak_millidb=-1000,
                font_size=48,
                bottom_margin=280,
                outline_width=3,
            ),
            output,
        )
    assert run.call_count == 1
    analysis_command = run.call_args.args[0]
    assert analysis_command[analysis_command.index("-i") + 1] == str(video)
    assert analysis_command[-2:] == ["null", "-"]
    assert not output.exists()


def _valid_enhancement_media() -> EnhancementMedia:
    return EnhancementMedia(
        duration_ms=15000,
        width=1080,
        height=1920,
        fps_numerator=30,
        fps_denominator=1,
        video_codec="h264",
        video_profile="high",
        pixel_format="yuv420p",
        audio_codec="aac",
        audio_profile="lc",
        audio_sample_rate=48000,
        audio_channels=2,
        container="mov,mp4,m4a,3gp,3g2,mj2",
        measured_lufs_milli=-14000,
        measured_true_peak_millidb=-1000,
        audio_video_sync_offset_ms=0,
        longest_black_segment_ms=0,
    )


@pytest.mark.parametrize(
    ("field", "value", "failed_check"),
    [
        ("duration_ms", 15035, "duration"),
        ("audio_profile", "he-aac", "audio_profile"),
        ("measured_lufs_milli", -17000, "integrated_loudness"),
        ("measured_true_peak_millidb", -600, "true_peak"),
        ("audio_video_sync_offset_ms", 35, "sync"),
        ("longest_black_segment_ms", 35, "black_segment"),
    ],
)
def test_enhancement_qa_rejects_invalid_media_contract(
    field, value, failed_check
) -> None:
    media = _valid_enhancement_media()
    invalid = replace(media, **{field: value})
    with pytest.raises(
        VideoCompositionEnhancementProbeError,
        match=f"ENHANCEMENT_OUTPUT_CONTRACT_FAILED:{failed_check}",
    ):
        VideoCompositionEnhancementProbe("ffprobe", "ffmpeg", 30).validate(
            invalid,
            -14000,
            -1000,
        )


def test_enhancement_artifact_get_head_and_range_are_exact(
    db_session, tmp_path
) -> None:
    product, project, composition, source, voice, _ = _source(db_session, tmp_path)
    enhancement = VideoCompositionEnhancement(
        product_id=product.id,
        video_project_id=project.id,
        composition_id=composition.id,
        source_artifact_id=source.id,
        voiceover_artifact_id=voice.id,
        input_digest="3" * 64,
        source_chain_digest="4" * 64,
        idempotency_key="enhancement-content",
        subtitle_cues_json=[
            {"sequence": 1, "start_ms": 0, "end_ms": 15000, "text": "字幕"}
        ],
        subtitle_style_json={
            "font_size": 48,
            "max_chars_per_line": 18,
            "bottom_margin": 280,
            "outline_width": 3,
        },
        voiceover_gain_millidb=0,
        music_gain_millidb=-18000,
        ducking_reduction_millidb=12000,
        target_lufs_milli=-14000,
        true_peak_millidb=-1000,
        status="SUCCEEDED",
    )
    db_session.add(enhancement)
    db_session.flush()
    subtitle_content = "WEBVTT\n\n1\n00:00:00.000 --> 00:00:15.000\n字幕\n".encode()
    subtitle_path = tmp_path / "enhancement-subtitles.vtt"
    subtitle_path.write_bytes(subtitle_content)
    subtitle = VideoCompositionSubtitleArtifact(
        enhancement_id=enhancement.id,
        storage_path=subtitle_path.name,
        content_type="text/vtt; charset=utf-8",
        size_bytes=len(subtitle_content),
        sha256=_sha(subtitle_content),
        format="webvtt",
        cue_count=1,
    )
    db_session.add(subtitle)
    db_session.flush()
    video_content = b"enhanced-video-content"
    video_path = tmp_path / "enhancement.mp4"
    video_path.write_bytes(video_content)
    artifact = VideoCompositionEnhancementArtifact(
        enhancement_id=enhancement.id,
        subtitle_artifact_id=subtitle.id,
        storage_path=video_path.name,
        content_type="video/mp4",
        size_bytes=len(video_content),
        sha256=_sha(video_content),
        duration_ms=15000,
        width=1080,
        height=1920,
        fps_numerator=30,
        fps_denominator=1,
        video_codec="h264",
        video_profile="high",
        pixel_format="yuv420p",
        audio_codec="aac",
        audio_profile="lc",
        audio_sample_rate=48000,
        audio_channels=2,
        container="mp4",
        measured_lufs_milli=-14000,
        measured_true_peak_millidb=-1000,
        audio_video_sync_offset_ms=0,
        longest_black_segment_ms=0,
        subtitle_format="webvtt",
        subtitle_cue_count=1,
        subtitle_sha256=subtitle.sha256,
        source_chain_digest=enhancement.source_chain_digest,
    )
    db_session.add(artifact)
    db_session.commit()

    def override_db():
        yield db_session

    audit_app = FastAPI()
    audit_app.include_router(composition_router, prefix="/api/v1")
    register_exception_handlers(audit_app)
    audit_app.dependency_overrides[get_db] = override_db
    audit_app.dependency_overrides[get_settings] = lambda: _settings(tmp_path)
    before = (
        db_session.query(VideoCompositionEnhancement).count(),
        db_session.query(VideoCompositionEnhancementArtifact).count(),
    )
    with TestClient(audit_app, raise_server_exceptions=False) as client:
        metadata = client.get(
            f"/api/v1/video-composition-enhancement-artifacts/{artifact.id}"
        )
        full = client.get(
            f"/api/v1/video-composition-enhancement-artifacts/{artifact.id}/content"
        )
        head = client.head(
            f"/api/v1/video-composition-enhancement-artifacts/{artifact.id}/content"
        )
        partial = client.get(
            f"/api/v1/video-composition-enhancement-artifacts/{artifact.id}/content",
            headers={"Range": "bytes=0-3"},
        )
        missing = client.get(
            "/api/v1/video-composition-enhancement-artifacts/999999/content"
        )
        subtitle_full = client.get(
            f"/api/v1/video-composition-subtitle-artifacts/{subtitle.id}/content"
        )
        subtitle_head = client.head(
            f"/api/v1/video-composition-subtitle-artifacts/{subtitle.id}/content"
        )
        subtitle_partial = client.get(
            f"/api/v1/video-composition-subtitle-artifacts/{subtitle.id}/content",
            headers={"Range": "bytes=0-9"},
        )
        missing_subtitle_head = client.head(
            "/api/v1/video-composition-subtitle-artifacts/999999/content"
        )
    assert metadata.status_code == 200
    assert full.status_code == 200 and full.content == video_content
    assert head.status_code == 200
    assert partial.status_code == 206 and partial.content == video_content[:4]
    assert missing.status_code == 404
    assert subtitle_full.status_code == 200
    assert subtitle_full.content == subtitle_content
    assert subtitle_head.status_code == 200
    assert subtitle_head.content == b""
    assert subtitle_head.headers["content-length"] == str(len(subtitle_content))
    assert subtitle_head.headers["content-type"] == "text/vtt; charset=utf-8"
    assert subtitle_head.headers["accept-ranges"] == "bytes"
    assert subtitle_head.headers["x-content-type-options"] == "nosniff"
    assert subtitle_partial.status_code == 206
    assert subtitle_partial.content == subtitle_content[:10]
    assert subtitle_partial.headers["content-range"] == (
        f"bytes 0-9/{len(subtitle_content)}"
    )
    assert missing_subtitle_head.status_code == 404
    assert missing_subtitle_head.content == b""
    assert "storage_path" not in metadata.text
    assert before == (
        db_session.query(VideoCompositionEnhancement).count(),
        db_session.query(VideoCompositionEnhancementArtifact).count(),
    )

    subtitle_path.unlink()
    with TestClient(audit_app, raise_server_exceptions=False) as client:
        missing_file = client.head(
            f"/api/v1/video-composition-subtitle-artifacts/{subtitle.id}/content"
        )
    assert missing_file.status_code == 404
    assert missing_file.content == b""
    assert str(tmp_path) not in missing_file.text

    subtitle.storage_path = "../outside.vtt"
    db_session.commit()
    with TestClient(audit_app, raise_server_exceptions=False) as client:
        unsafe_path = client.head(
            f"/api/v1/video-composition-subtitle-artifacts/{subtitle.id}/content"
        )
    assert unsafe_path.status_code == 404
    assert unsafe_path.content == b""
    assert str(tmp_path) not in unsafe_path.text
