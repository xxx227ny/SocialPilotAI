from pathlib import Path


def test_real_product_video_contract_reuses_existing_composition_and_enhancement() -> (
    None
):
    root = Path(__file__).parents[1] / "app"
    route = (root / "api/v1/routes/product_marketing_videos.py").read_text("utf-8")
    registry = (root / "execution/runtime_registry.py").read_text("utf-8")
    panel = (
        Path(__file__).parents[2]
        / "frontend/src/components/video/RealProductVideoPanel.tsx"
    ).read_text("utf-8")
    assert "video.product_image.render.v1" in (
        root / "services/product_image_render_service.py"
    ).read_text("utf-8")
    assert "tts.voiceover.generate.v1" in (
        root / "services/voiceover_generation_service.py"
    ).read_text("utf-8")
    assert "ProductImageRenderV1Handler" in registry
    assert "VoiceoverGenerateV1Handler" in registry
    assert "WanxProductImageGenerateV1Handler" in registry
    assert "/wanx-image-jobs" in route and "/voiceover-jobs" in route
    assert 'version.source_type != "QWEN_GENERATED"' in route
    assert 'version.created_by_kind != "QWEN_PROVIDER"' in route
    assert "preflightVideoComposition" in panel
    assert "preflightCompositionEnhancement" in panel
    assert "latest" not in panel.lower()
