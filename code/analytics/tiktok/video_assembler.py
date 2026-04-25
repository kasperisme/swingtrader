from __future__ import annotations

import json
import logging
import subprocess
from pathlib import Path

from .config import (
    VIDEO_WIDTH,
    VIDEO_HEIGHT,
    VIDEO_FPS,
    VIDEO_CODEC,
    AUDIO_CODEC,
    BACKGROUND_MUSIC,
    BG_MUSIC_VOLUME,
    REPORTER_VIDEO,
    OUTPUT_DIR,
)

log = logging.getLogger(__name__)

FFMPEG = "ffmpeg"

# Ken Burns motion — one pattern per block slot (cycles if slide count differs).
# pzoom = previous zoom; on = output frame number (0-based).
def _motion_vf(slide_index: int) -> str:
    W, H = VIDEO_WIDTH, VIDEO_HEIGHT
    scale = f"scale={W * 2}:{H * 2}"
    out = f"s={W}x{H}"
    cx = "x='iw/2-(iw/zoom/2)'"
    cy = "y='ih/2-(ih/zoom/2)'"

    pan_l = "x='max(iw/2-(iw/zoom/2)-on*0.3,0)'"
    pan_r = "x='min(iw/2-(iw/zoom/2)+on*0.3,iw/2-(iw/zoom/2)+iw*0.03)'"

    patterns = [
        f"{scale},zoompan=z='min(pzoom+0.0006,1.07)':d=1:{pan_l}:{cy}:{out},setsar=1",
        f"{scale},zoompan=z='min(pzoom+0.0002,1.04)':d=1:{pan_r}:{cy}:{out},setsar=1",
        f"{scale},zoompan=z='min(pzoom+0.0003,1.05)':d=1"
        f":x='min(iw*0.03+on*0.5,iw/2-(iw/zoom/2)+iw*0.04)':{cy}:{out},setsar=1",
        f"{scale},zoompan=z='max(1.06-0.0004*on,1.0)':d=1:{pan_l}:{cy}:{out},setsar=1",
        f"{scale},zoompan=z='min(pzoom+0.0003,1.05)':d=1:{cx}"
        f":y='max(ih*0.04-on*0.05,ih/2-(ih/zoom/2))':{out},setsar=1",
        f"{scale},zoompan=z='max(1.04-0.0002*on,1.0)':d=1:{pan_r}:{cy}:{out},setsar=1",
        f"{scale},zoompan=z='min(pzoom+0.0005,1.07)':d=1:{cx}:{cy}:{out},setsar=1",
    ]
    return patterns[slide_index % len(patterns)]


# Estimate per-slide duration from word counts so slides are timed to their block length.
_WORDS_PER_SEC = 2.3

def compute_block_durations(script: dict) -> list[float]:
    from .script_generator import SCRIPT_BLOCKS
    counts = [max(len(script.get(b, "").split()), 3) for b in SCRIPT_BLOCKS]
    return [c / _WORDS_PER_SEC for c in counts]


def get_audio_duration(audio_path: Path) -> float:
    result = subprocess.run(
        [FFMPEG, "-i", str(audio_path)],
        capture_output=True, text=True,
    )
    import re
    match = re.search(r"Duration:\s*(\d+):(\d+):(\d+)\.(\d+)", result.stderr)
    if match:
        return int(match.group(1)) * 3600 + int(match.group(2)) * 60 + int(match.group(3)) + int(match.group(4)) / 100
    log.warning("Could not parse audio duration, defaulting to 75s")
    return 75.0


def assemble_video(
    slides: list[Path],
    audio_path: Path,
    captions: list[dict] | None = None,
    output_path: Path | None = None,
    slide_durations: list[float] | None = None,
) -> Path:
    output_path = output_path or OUTPUT_DIR / "tiktok_premarket.mp4"
    output_path.parent.mkdir(parents=True, exist_ok=True)

    audio_duration = get_audio_duration(audio_path)

    if slide_durations and len(slide_durations) == len(slides):
        # Scale proportionally to actual audio duration
        total_est = sum(slide_durations)
        slide_dur_list = [d * audio_duration / total_est for d in slide_durations]
    else:
        slide_dur_list = [audio_duration / len(slides)] * len(slides)

    for i, dur in enumerate(slide_dur_list):
        log.info("  Slide %d: %.1fs", i + 1, dur)

    concat_file = output_path.parent / "concat_input.txt"
    slide_clips: list[Path] = []

    for i, (slide_path, dur) in enumerate(zip(slides, slide_dur_list)):
        clip_path = output_path.parent / f"slide_{i:02d}.mp4"
        motion_vf = _motion_vf(i) + ",format=yuv420p"
        cmd = [
            FFMPEG, "-y",
            "-loop", "1",
            "-i", str(slide_path),
            "-c:v", VIDEO_CODEC,
            "-t", f"{dur:.2f}",
            "-pix_fmt", "yuv420p",
            "-vf", motion_vf,
            "-r", str(VIDEO_FPS),
            "-preset", "fast",
            "-crf", "23",
            str(clip_path),
        ]
        log.info("Encoding slide %d/%d: %s", i + 1, len(slides), slide_path.name)
        result = subprocess.run(cmd, capture_output=True, text=True)
        if result.returncode != 0:
            raise RuntimeError(f"ffmpeg slide encode failed: {result.stderr[:500]}")
        slide_clips.append(clip_path)

    with open(concat_file, "w") as f:
        for clip in slide_clips:
            f.write(f"file '{clip}'\n")

    no_captions_path = output_path.parent / "no_captions.mp4"
    cmd = [
        FFMPEG, "-y",
        "-f", "concat", "-safe", "0",
        "-i", str(concat_file),
        "-i", str(audio_path),
        "-c:v", VIDEO_CODEC,
        "-c:a", AUDIO_CODEC,
        "-pix_fmt", "yuv420p",
        "-shortest",
        "-preset", "fast",
        "-crf", "23",
        str(no_captions_path),
    ]
    log.info("Concatenating slides + audio")
    result = subprocess.run(cmd, capture_output=True, text=True)
    if result.returncode != 0:
        raise RuntimeError(f"ffmpeg concat failed: {result.stderr[:500]}")

    if captions:
        final_path = _burn_captions(no_captions_path, captions, output_path)
    else:
        final_path = output_path
        no_captions_path.rename(final_path)

    for clip in slide_clips:
        clip.unlink(missing_ok=True)
    concat_file.unlink(missing_ok=True)
    if no_captions_path.exists() and no_captions_path != final_path:
        no_captions_path.unlink(missing_ok=True)

    log.info("Final video: %s (%.1f MB)", final_path.name, final_path.stat().st_size / 1024 / 1024)
    return final_path


def _burn_captions(input_path: Path, captions: list[dict], output_path: Path) -> Path:
    srt_path = output_path.parent / "captions.srt"
    _write_srt(captions, srt_path)

    filter_complex = (
        f"subtitles={str(srt_path)}:force_style='"
        "FontName=Arial,"
        "FontSize=20,"
        "Bold=1,"
        "PrimaryColour=&H00FFFFFF,"
        "BackColour=&H90000000,"
        "BorderStyle=3,"
        "Outline=0,"
        "Shadow=0,"
        "Alignment=2,"
        "MarginV=280'"
        "'"
    )

    cmd = [
        FFMPEG, "-y",
        "-i", str(input_path),
        "-vf", filter_complex,
        "-c:v", VIDEO_CODEC,
        "-c:a", "copy",
        "-pix_fmt", "yuv420p",
        "-preset", "fast",
        "-crf", "23",
        str(output_path),
    ]
    log.info("Burning %d caption segments", len(captions))
    result = subprocess.run(cmd, capture_output=True, text=True)
    if result.returncode != 0:
        log.warning("Caption burn failed, using video without captions: %s", result.stderr[:300])
        input_path.rename(output_path)
        return output_path

    srt_path.unlink(missing_ok=True)
    return output_path


def _write_srt(captions: list[dict], path: Path) -> None:
    lines = []
    for i, cap in enumerate(captions, 1):
        start = _fmt_srt_time(cap["start"])
        end = _fmt_srt_time(cap["end"])
        lines.append(f"{i}")
        lines.append(f"{start} --> {end}")
        lines.append(cap["text"])
        lines.append("")
    path.write_text("\n".join(lines))


def _fmt_srt_time(seconds: float) -> str:
    h = int(seconds // 3600)
    m = int((seconds % 3600) // 60)
    s = int(seconds % 60)
    ms = int((seconds % 1) * 1000)
    return f"{h:02d}:{m:02d}:{s:02d},{ms:03d}"


def add_background_music(video_path: Path, music_path: Path, output_path: Path) -> Path:
    cmd = [
        FFMPEG, "-y",
        "-i", str(video_path),
        "-stream_loop", "-1",
        "-i", str(music_path),
        "-filter_complex",
        f"[1:a]volume={BG_MUSIC_VOLUME}[bg];[0:a][bg]amix=inputs=2:duration=first:dropout_transition=2[aout]",
        "-map", "0:v",
        "-map", "[aout]",
        "-c:v", "copy",
        "-c:a", AUDIO_CODEC,
        "-shortest",
        str(output_path),
    ]
    log.info("Adding background music")
    result = subprocess.run(cmd, capture_output=True, text=True)
    if result.returncode != 0:
        log.warning("BG music failed, keeping original: %s", result.stderr[:300])
        return video_path
    return output_path


def _make_pingpong(reporter_path: Path, output_path: Path) -> Path:
    """Pre-render the reporter clip as a 1:1 center-cropped ping-pong mp4."""
    cmd = [
        FFMPEG, "-y",
        "-i", str(reporter_path),
        "-filter_complex",
        "[0:v]crop=iw:iw:0:(ih-iw)/2,split[fwd1][fwd2];"
        "[fwd2]reverse[rev];[fwd1][rev]concat=n=2:v=1,setsar=1[pp]",
        "-map", "[pp]",
        "-c:v", VIDEO_CODEC,
        "-pix_fmt", "yuv420p",
        "-preset", "fast",
        "-crf", "20",
        "-an",
        str(output_path),
    ]
    result = subprocess.run(cmd, capture_output=True, text=True)
    if result.returncode != 0:
        raise RuntimeError(f"ping-pong render failed: {result.stderr[:400]}")
    return output_path


def _overlay_on_clip(clip_path: Path, output_path: Path, size: int = 810) -> Path:
    """Overlay large reporter on a single clip (no audio track)."""
    reporter_src = Path(REPORTER_VIDEO)
    if not reporter_src.exists():
        log.warning("Reporter video not found at %s — skipping hook overlay", reporter_src)
        return clip_path

    pingpong_path = output_path.parent / "_reporter_pp_hook.mp4"
    try:
        _make_pingpong(reporter_src, pingpong_path)
    except RuntimeError as e:
        log.warning("Could not create reporter ping-pong: %s", e)
        return clip_path

    rx = VIDEO_WIDTH - size - 10
    ry = VIDEO_HEIGHT - size - 180

    filter_complex = (
        f"[1:v]scale={size}:{size}:flags=lanczos,setsar=1[reporter];"
        f"[0:v][reporter]overlay=x={rx}:y={ry}:shortest=1,setsar=1[out]"
    )
    cmd = [
        FFMPEG, "-y",
        "-i", str(clip_path),
        "-stream_loop", "-1", "-i", str(pingpong_path),
        "-filter_complex", filter_complex,
        "-map", "[out]",
        "-c:v", VIDEO_CODEC,
        "-pix_fmt", "yuv420p",
        "-preset", "fast",
        "-crf", "18",
        "-shortest",
        str(output_path),
    ]
    log.info("Overlaying large reporter (%dpx) on hook clip", size)
    result = subprocess.run(cmd, capture_output=True, text=True)
    pingpong_path.unlink(missing_ok=True)

    if result.returncode != 0:
        log.warning("Reporter hook overlay failed: %s", result.stderr[:300])
        return clip_path

    return output_path


def overlay_reporter(video_path: Path, output_path: Path, start_delay: float = 0.0) -> Path:
    """Overlay the reporter ping-pong loop in the bottom-right corner."""
    reporter_src = Path(REPORTER_VIDEO)
    if not reporter_src.exists():
        log.warning("Reporter video not found at %s — skipping overlay", reporter_src)
        return video_path

    pingpong_path = output_path.parent / "_reporter_pp.mp4"
    try:
        _make_pingpong(reporter_src, pingpong_path)
    except RuntimeError as e:
        log.warning("Could not create reporter ping-pong: %s", e)
        return video_path

    rw = 270
    rh = rw
    rx = VIDEO_WIDTH - rw - 15
    ry = VIDEO_HEIGHT - rh - 265

    enable = f":enable='gte(t,{start_delay:.2f})'" if start_delay > 0 else ""
    filter_complex = (
        f"[1:v]scale={rw}:{rh}:flags=lanczos,setsar=1[reporter];"
        f"[0:v][reporter]overlay=x={rx}:y={ry}:shortest=1{enable},setsar=1[out]"
    )
    cmd = [
        FFMPEG, "-y",
        "-i", str(video_path),
        "-stream_loop", "-1", "-i", str(pingpong_path),
        "-filter_complex", filter_complex,
        "-map", "[out]",
        "-map", "0:a",
        "-c:v", VIDEO_CODEC,
        "-c:a", "copy",
        "-pix_fmt", "yuv420p",
        "-preset", "fast",
        "-crf", "23",
        str(output_path),
    ]
    log.info("Overlaying reporter (%dx%d) at (%d, %d)%s", rw, rh, rx, ry,
             f" delayed {start_delay:.1f}s" if start_delay > 0 else "")
    result = subprocess.run(cmd, capture_output=True, text=True)

    pingpong_path.unlink(missing_ok=True)

    if result.returncode != 0:
        log.warning("Reporter overlay failed: %s", result.stderr[:300])
        return video_path

    log.info("Reporter overlay complete: %s", output_path.name)
    return output_path


def assemble_from_clips(
    clips: list[Path],
    audio_path: Path,
    captions: list[dict] | None = None,
    output_path: Path | None = None,
    hook_duration: float = 0.0,
) -> Path:
    output_path = output_path or OUTPUT_DIR / "tiktok_premarket.mp4"
    output_path.parent.mkdir(parents=True, exist_ok=True)

    if clips and hook_duration > 0:
        hook_overlay = output_path.parent / "hook_with_reporter.mp4"
        clips[0] = _overlay_on_clip(clips[0], hook_overlay, size=810)

    concat_file = output_path.parent / "concat_clips.txt"
    with open(concat_file, "w") as f:
        for clip in clips:
            f.write(f"file '{clip}'\n")

    no_captions_path = output_path.parent / "no_captions_clips.mp4"
    cmd = [
        FFMPEG, "-y",
        "-f", "concat", "-safe", "0",
        "-i", str(concat_file),
        "-i", str(audio_path),
        "-c:v", VIDEO_CODEC,
        "-c:a", AUDIO_CODEC,
        "-pix_fmt", "yuv420p",
        "-shortest",
        "-preset", "fast",
        "-crf", "23",
        str(no_captions_path),
    ]
    log.info("Concatenating %d clips + audio", len(clips))
    result = subprocess.run(cmd, capture_output=True, text=True)
    if result.returncode != 0:
        raise RuntimeError(f"ffmpeg concat clips failed: {result.stderr[:500]}")

    if captions:
        final_path = _burn_captions(no_captions_path, captions, output_path)
    else:
        final_path = output_path
        no_captions_path.rename(final_path)

    concat_file.unlink(missing_ok=True)
    if no_captions_path.exists() and no_captions_path != final_path:
        no_captions_path.unlink(missing_ok=True)

    hook_temp = output_path.parent / "hook_with_reporter.mp4"
    if hook_temp.exists():
        hook_temp.unlink(missing_ok=True)

    pre_reporter = output_path.parent / output_path.name.replace(".mp4", "_pre_reporter.mp4")
    if final_path != pre_reporter:
        final_path.rename(pre_reporter)
    with_reporter = overlay_reporter(pre_reporter, output_path, start_delay=hook_duration)
    if with_reporter == output_path:
        pre_reporter.unlink(missing_ok=True)
    else:
        pre_reporter.rename(output_path)
    final_path = output_path

    log.info("Final video: %s (%.1f MB)", final_path.name,
             final_path.stat().st_size / 1024 / 1024)
    return final_path
