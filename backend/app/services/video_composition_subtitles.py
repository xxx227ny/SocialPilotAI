from __future__ import annotations

import textwrap

from app.schemas.video_composition_enhancement import (
    SubtitleCueInput,
    SubtitleStyleInput,
)


def _timestamp(milliseconds: int) -> str:
    hours, remainder = divmod(milliseconds, 3_600_000)
    minutes, remainder = divmod(remainder, 60_000)
    seconds, millis = divmod(remainder, 1000)
    return f"{hours:02}:{minutes:02}:{seconds:02}.{millis:03}"


def _ass_timestamp(milliseconds: int) -> str:
    centiseconds = (milliseconds + 5) // 10
    hours, remainder = divmod(centiseconds, 360_000)
    minutes, remainder = divmod(remainder, 6_000)
    seconds, centis = divmod(remainder, 100)
    return f"{hours}:{minutes:02}:{seconds:02}.{centis:02}"


def _wrapped_text(cue: SubtitleCueInput, style: SubtitleStyleInput) -> list[str]:
    return textwrap.wrap(
        cue.text,
        width=style.max_chars_per_line,
        break_long_words=True,
        break_on_hyphens=False,
    )


def _escape_ass_text(value: str) -> str:
    return (
        value.replace("\\", r"\\")
        .replace("{", r"\{")
        .replace("}", r"\}")
    )


def _render_ass_document(
    events: list[tuple[int, int, list[str]]],
    *,
    font_size: int,
    bottom_margin: int,
    outline_width: int,
) -> bytes:
    lines = [
        "[Script Info]",
        "ScriptType: v4.00+",
        "PlayResX: 1080",
        "PlayResY: 1920",
        "WrapStyle: 2",
        "ScaledBorderAndShadow: yes",
        "YCbCr Matrix: TV.709",
        "",
        "[V4+ Styles]",
        (
            "Format: Name, Fontname, Fontsize, PrimaryColour, SecondaryColour, "
            "OutlineColour, BackColour, Bold, Italic, Underline, StrikeOut, "
            "ScaleX, ScaleY, Spacing, Angle, BorderStyle, Outline, Shadow, "
            "Alignment, MarginL, MarginR, MarginV, Encoding"
        ),
        (
            "Style: Default,Arial,"
            f"{font_size},&H00FFFFFF,&H000000FF,&H00000000,&H64000000,"
            "0,0,0,0,100,100,0,0,1,"
            f"{outline_width},0,2,54,54,{bottom_margin},1"
        ),
        "",
        "[Events]",
        (
            "Format: Layer, Start, End, Style, Name, MarginL, MarginR, "
            "MarginV, Effect, Text"
        ),
    ]
    for start_ms, end_ms, text_lines in events:
        text = r"\N".join(_escape_ass_text(item) for item in text_lines)
        lines.append(
            "Dialogue: 0,"
            f"{_ass_timestamp(start_ms)},{_ass_timestamp(end_ms)},"
            f"Default,,0,0,0,,{text}"
        )
    content = ("\n".join(lines) + "\n").encode("utf-8")
    if b"\xef\xbf\xbd" in content:
        raise ValueError("SUBTITLE_ENCODING_INVALID")
    return content


def _parse_webvtt_timestamp(value: str) -> int:
    hours, minutes, remainder = value.split(":", 2)
    seconds, milliseconds = remainder.split(".", 1)
    if not all(
        part.isdigit()
        for part in (hours, minutes, seconds, milliseconds)
    ) or len(milliseconds) != 3:
        raise ValueError("SUBTITLE_FORMAT_INVALID")
    return (
        int(hours) * 3_600_000
        + int(minutes) * 60_000
        + int(seconds) * 1000
        + int(milliseconds)
    )


def render_ass_from_webvtt(
    content: bytes,
    *,
    font_size: int,
    bottom_margin: int,
    outline_width: int,
) -> bytes:
    try:
        decoded = content.decode("utf-8")
    except UnicodeDecodeError as exc:
        raise ValueError("SUBTITLE_ENCODING_INVALID") from exc
    lines = decoded.splitlines()
    if not lines or lines[0] != "WEBVTT":
        raise ValueError("SUBTITLE_FORMAT_INVALID")
    index = 1
    events: list[tuple[int, int, list[str]]] = []
    while index < len(lines):
        while index < len(lines) and not lines[index]:
            index += 1
        if index >= len(lines):
            break
        if not lines[index].isdigit():
            raise ValueError("SUBTITLE_FORMAT_INVALID")
        index += 1
        if index >= len(lines) or " --> " not in lines[index]:
            raise ValueError("SUBTITLE_FORMAT_INVALID")
        start, end = lines[index].split(" --> ", 1)
        index += 1
        text_lines: list[str] = []
        while index < len(lines) and lines[index]:
            text_lines.append(lines[index])
            index += 1
        if not text_lines:
            raise ValueError("SUBTITLE_FORMAT_INVALID")
        events.append(
            (
                _parse_webvtt_timestamp(start),
                _parse_webvtt_timestamp(end),
                text_lines,
            )
        )
    if not events:
        raise ValueError("SUBTITLE_FORMAT_INVALID")
    return _render_ass_document(
        events,
        font_size=font_size,
        bottom_margin=bottom_margin,
        outline_width=outline_width,
    )


def render_webvtt(
    cues: list[SubtitleCueInput], style: SubtitleStyleInput
) -> bytes:
    blocks = ["WEBVTT", ""]
    for cue in sorted(cues, key=lambda item: item.sequence):
        wrapped = "\n".join(_wrapped_text(cue, style))
        blocks.extend(
            [
                str(cue.sequence),
                f"{_timestamp(cue.start_ms)} --> {_timestamp(cue.end_ms)}",
                wrapped,
                "",
            ]
        )
    content = "\n".join(blocks).encode("utf-8")
    if b"\xef\xbf\xbd" in content:
        raise ValueError("SUBTITLE_ENCODING_INVALID")
    return content


def render_ass(
    cues: list[SubtitleCueInput], style: SubtitleStyleInput
) -> bytes:
    events = [
        (cue.start_ms, cue.end_ms, _wrapped_text(cue, style))
        for cue in sorted(cues, key=lambda item: item.sequence)
    ]
    return _render_ass_document(
        events,
        font_size=style.font_size,
        bottom_margin=style.bottom_margin,
        outline_width=style.outline_width,
    )
