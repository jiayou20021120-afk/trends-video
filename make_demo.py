"""Render a v2 demo with layered animation:
- dynamic gradient background
- header bar
- spring-in rank
- repo (owner / NAME) staged entry
- language tag fade
- stars roll + gold flash
- bottom subtitle panel, sentence-by-sentence with keyword coloring
"""
import asyncio
from pathlib import Path
from typing import List
import numpy as np
from PIL import Image
import edge_tts
from moviepy import (
    ImageClip,
    ImageSequenceClip,
    AudioFileClip,
    CompositeVideoClip,
)
from moviepy.video.fx import FadeIn, FadeOut, Resize, CrossFadeIn

from parse import parse, TrendItem
import layers as L

DATE = "2026-05-07"
VOICE = "zh-CN-YunjianNeural"
RATE = "-5%"
FPS = 30
W, H = 1080, 1920


def ease_out_cubic(t: float) -> float:
    return 1 - (1 - t) ** 3


def spring_scale(t: float, peak_t: float = 0.32, settle_t: float = 0.55) -> float:
    """0 → 1.18 (overshoot) → 1.0."""
    if t < peak_t:
        return 1.18 * ease_out_cubic(t / peak_t)
    if t < settle_t:
        k = (t - peak_t) / (settle_t - peak_t)
        return 1.18 - 0.18 * ease_out_cubic(k)
    return 1.0


# ---------------------------------------------------------------------------
# Background as a list of frames (cheap animation: 24 frames over total dur)
# ---------------------------------------------------------------------------

def build_background_clip(total_dur: float) -> ImageClip:
    n = max(int(total_dur * 8), 8)  # 8 fps for the bg loop is plenty
    frames = []
    for i in range(n):
        t = (i / n) * total_dur
        img = L.render_background(t, total_dur)
        frames.append(np.array(img.convert("RGB")))
    return ImageSequenceClip(frames, fps=8).with_duration(total_dur)


# ---------------------------------------------------------------------------
# Spring-in helper for static images
# ---------------------------------------------------------------------------

def spring_in(pil_img: Image.Image, start: float, dur: float = 1.5) -> ImageClip:
    arr = np.array(pil_img)
    clip = (
        ImageClip(arr, transparent=True)
        .with_duration(dur)
        .with_start(start)
        .with_effects([
            Resize(lambda t: max(0.01, spring_scale(t))),
            FadeIn(0.18),
        ])
        .with_position("center")
    )
    return clip


def fade_in_layer(pil_img: Image.Image, start: float, dur: float, fade: float = 0.35) -> ImageClip:
    arr = np.array(pil_img)
    return (
        ImageClip(arr, transparent=True)
        .with_duration(dur)
        .with_start(start)
        .with_effects([FadeIn(fade)])
        .with_position("center")
    )


# ---------------------------------------------------------------------------
# Stars rolling (intro) → flash → static stars
# ---------------------------------------------------------------------------

def build_stars_clips(target: int, roll_start: float, roll_dur: float,
                      hold_until: float) -> List:
    """Return a list of moviepy clips for stars animation."""
    n = int(roll_dur * FPS)
    rolling_frames = []
    for i in range(n):
        progress = (i + 1) / n
        eased = ease_out_cubic(progress)
        cur = int(target * eased)
        rolling_frames.append(np.array(L.render_stars(cur).convert("RGBA")))
    rolling = (
        ImageSequenceClip(rolling_frames, fps=FPS)
        .with_duration(roll_dur)
        .with_start(roll_start)
        .with_position("center")
    )
    # final static
    static = (
        ImageClip(np.array(L.render_stars(target)), transparent=True)
        .with_duration(hold_until - (roll_start + roll_dur))
        .with_start(roll_start + roll_dur)
        .with_position("center")
    )
    # flash (golden burst)
    flash_dur = 0.5
    flash_n = int(flash_dur * FPS)
    flash_frames = []
    for i in range(flash_n):
        a = (1 - (i / flash_n)) ** 2  # quick decay
        flash_frames.append(np.array(L.render_stars(target, flash_alpha=a).convert("RGBA")))
    # NOTE: render_stars already includes the number; using the same function with alpha
    # over the static one would double-draw. Instead use only the flash diff:
    # generate flash-only frames by computing alpha on a transparent canvas.
    flash_only = []
    for i in range(flash_n):
        a = (1 - (i / flash_n)) ** 2
        # compute with value=target then subtract base by drawing flash on transparent
        canvas = L.render_stars(target, flash_alpha=a)
        base = L.render_stars(target, flash_alpha=0.0)
        # diff (keep only the bright flash pixels)
        diff = Image.alpha_composite(Image.new("RGBA", (W, H), (0, 0, 0, 0)),
                                     Image.alpha_composite(canvas, base))
        flash_only.append(np.array(diff))
    flash_clip = (
        ImageSequenceClip(flash_only, fps=FPS)
        .with_duration(flash_dur)
        .with_start(roll_start + roll_dur)
        .with_position("center")
    )
    return [rolling, flash_clip, static]


# ---------------------------------------------------------------------------
# Subtitle clips — one per sentence, sequential, with previous fading out
# ---------------------------------------------------------------------------

def build_subtitle_clips(narration: str, audio_dur: float, audio_start: float):
    sentences = L.split_sentences(narration)
    if not sentences:
        return []
    # weight by char length to approximate reading time
    total_chars = sum(len(s) for s in sentences)
    clips = []
    cursor = audio_start
    for s in sentences:
        share = len(s) / total_chars
        dur = max(1.2, audio_dur * share)
        img = L.render_subtitle(s)
        c = (
            ImageClip(np.array(img), transparent=True)
            .with_duration(dur + 0.25)
            .with_start(cursor)
            .with_effects([CrossFadeIn(0.25)])
            .with_position("center")
        )
        clips.append(c)
        cursor += dur
    return clips


# ---------------------------------------------------------------------------
# TTS
# ---------------------------------------------------------------------------

async def synth_tts(text: str, out_mp3: Path, voice: str = VOICE) -> None:
    comm = edge_tts.Communicate(text, voice, rate=RATE)
    await comm.save(str(out_mp3))


def build_item_clip(item: TrendItem, date: str, audio_path: Path) -> CompositeVideoClip:
    """Build a single-item video clip including audio. Caller owns TTS."""
    audio = AudioFileClip(str(audio_path))
    narr_dur = audio.duration

    intro_dur = 2.4
    audio_start = intro_dur - 0.2
    total = audio_start + narr_dur + 0.6

    bg = build_background_clip(total)
    header = fade_in_layer(L.render_header(date), start=0.0, dur=total, fade=0.3)
    lang = fade_in_layer(L.render_lang(item.language), start=0.9, dur=total - 0.9, fade=0.4)
    rank = spring_in(L.render_rank(item.rank), start=0.15, dur=total - 0.15)

    repo_img = L.render_repo(item.repo)
    repo = (
        ImageClip(np.array(repo_img), transparent=True)
        .with_duration(total - 0.55)
        .with_start(0.55)
        .with_effects([
            FadeIn(0.4),
            Resize(lambda t: 0.92 + 0.08 * min(1.0, t / 0.5)),
        ])
        .with_position("center")
    )

    stars_clips = build_stars_clips(item.stars_today, 1.1, 1.2, hold_until=total)
    subs = build_subtitle_clips(item.narration, narr_dur, audio_start)

    layers = [bg, header, rank, repo, lang] + stars_clips + subs
    video = CompositeVideoClip(layers, size=(W, H)).with_duration(total)
    audio_clip = audio.with_start(audio_start)
    return video.with_audio(audio_clip)


def main():
    """Single-item demo: rank=1 of the dataset."""
    items = parse(Path("data/2026-05-07.md"))
    item = items[0]
    out_dir = Path("output")
    out_dir.mkdir(exist_ok=True)
    audio_path = out_dir / f"narration_{item.rank}.mp3"
    if not audio_path.exists():
        print("[tts] synthesizing narration ...")
        asyncio.run(synth_tts(item.narration, audio_path))

    video = build_item_clip(item, DATE, audio_path)
    video = video.with_effects([FadeIn(0.3), FadeOut(0.5)])

    out_mp4 = out_dir / "demo_v2.mp4"
    print(f"[render] writing {out_mp4} ...")
    video.write_videofile(
        str(out_mp4),
        fps=FPS,
        codec="libx264",
        audio_codec="aac",
        preset="medium",
        threads=4,
        logger=None,
    )
    print(f"[done] {out_mp4}")


if __name__ == "__main__":
    main()
