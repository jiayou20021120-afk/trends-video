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

def pad_audio(audio, lead: float, total: float):
    """Return an audio clip of length `total` with `audio` placed at offset `lead`,
    silence-padded before and after. Fixes the mp4 audio-stream-shorter-than-video
    problem that caused subtitles to lag voice when segments were concat'd with
    ffmpeg `-c copy`."""
    import numpy as np
    from moviepy.audio.AudioClip import AudioArrayClip
    from moviepy import concatenate_audioclips

    fps = int(getattr(audio, "fps", None) or 44100)
    # Detect channel count from the audio clip
    try:
        sample = audio.get_frame(0)
        nchan = sample.shape[-1] if hasattr(sample, "shape") and sample.ndim > 0 else 1
    except Exception:
        nchan = 2
    nchan = max(1, int(nchan))

    parts = []
    if lead > 0:
        n = max(1, int(lead * fps))
        parts.append(AudioArrayClip(np.zeros((n, nchan), dtype=np.float32), fps=fps))
    parts.append(audio)
    tail = total - lead - audio.duration
    if tail > 1.0 / fps:
        n = max(1, int(tail * fps))
        parts.append(AudioArrayClip(np.zeros((n, nchan), dtype=np.float32), fps=fps))

    if len(parts) == 1:
        return parts[0]
    return concatenate_audioclips(parts)


def build_background_clip(total_dur: float, palette_id: int = 0,
                          category: str = None) -> ImageClip:
    # 6 fps background loop — eye barely notices below 8 fps for blob drifts,
    # and this cuts ~25% of background-frame encode work on the CI runner.
    bg_fps = 6
    n = max(int(total_dur * bg_fps), 6)
    frames = []
    for i in range(n):
        t = (i / n) * total_dur
        img = L.render_background(t, total_dur, palette_id=palette_id,
                                  category=category)
        frames.append(np.array(img.convert("RGB")))
    return ImageSequenceClip(frames, fps=bg_fps).with_duration(total_dur)


# ---------------------------------------------------------------------------
# Entry-mode helpers — make adjacent items feel different.
# ---------------------------------------------------------------------------

ENTRY_MODES = ["spring", "slide", "zoom"]


def make_rank_clip(rank: int, total: float, mode: str = "spring") -> ImageClip:
    img = np.array(L.render_rank(rank))
    base = ImageClip(img, transparent=True).with_duration(total - 0.15).with_start(0.15)
    if mode == "slide":
        # drop in from above
        def pos(t):
            if t < 0.4:
                return ("center", int(- 220 * (1 - t / 0.4)))
            return ("center", 0)
        return base.with_position(pos).with_effects([FadeIn(0.25)])
    if mode == "zoom":
        return (
            base
            .with_effects([
                Resize(lambda t: 1.6 - 0.6 * ease_out_cubic(min(1.0, t / 0.5))),
                FadeIn(0.25),
            ])
            .with_position("center")
        )
    # spring (default)
    return (
        base
        .with_effects([
            Resize(lambda t: max(0.01, spring_scale(t))),
            FadeIn(0.18),
        ])
        .with_position("center")
    )


def make_repo_clip(item: TrendItem, total: float, mode: str = "spring") -> ImageClip:
    img = np.array(L.render_repo(item.repo))
    base = ImageClip(img, transparent=True).with_duration(total - 0.55).with_start(0.55)
    if mode == "slide":
        def pos(t):
            if t < 0.5:
                return (int(900 * (1 - t / 0.5)), 0)
            return (0, 0)
        return base.with_position(pos).with_effects([FadeIn(0.3)])
    if mode == "zoom":
        return (
            base
            .with_effects([
                FadeIn(0.3),
                Resize(lambda t: 1.4 - 0.4 * ease_out_cubic(min(1.0, t / 0.5))),
            ])
            .with_position("center")
        )
    # spring (default)
    return (
        base
        .with_effects([
            FadeIn(0.4),
            Resize(lambda t: 0.92 + 0.08 * min(1.0, t / 0.5)),
        ])
        .with_position("center")
    )


def build_streak_clip(start: float, dur: float = 0.55) -> ImageClip:
    """Horizontal white-gold streak that sweeps over the stars line."""
    n = int(dur * FPS)
    frames = []
    for i in range(n):
        progress = (i + 1) / n
        frames.append(np.array(L.render_streak(progress)))
    return (
        ImageSequenceClip(frames, fps=FPS)
        .with_duration(dur)
        .with_start(start)
        .with_position((0, 0))
    )


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

def _split_long(sentence: str, max_chars: int = 38):
    """Break an over-long sentence at the first comma after max_chars/2 chars."""
    if len(sentence) <= max_chars:
        return [sentence]
    for i, ch in enumerate(sentence):
        if ch in "，,；;" and i >= max_chars // 2:
            return [sentence[: i + 1].strip(), sentence[i + 1 :].strip()]
    return [sentence]


def build_subtitle_clips(narration: str, audio_dur: float, audio_start: float,
                          boundaries: list = None):
    """Build subtitle clips. If boundaries are provided (from edge-tts
    SentenceBoundary events), use them for precise timing. Otherwise fall back
    to char-length-weighted estimation."""
    if boundaries:
        # Subtitle should be fully visible ~100ms BEFORE the corresponding audio.
        # We do that by starting 150ms early and fading in over 50ms.
        LEAD = 0.15
        FADE = 0.05
        clips = []
        for b in boundaries:
            parts = _split_long(b["text"])
            if len(parts) == 1:
                t0 = audio_start + b["start"] - LEAD
                d = b["duration"] + 0.20 + LEAD
                img = L.render_subtitle(parts[0])
                clip = (
                    ImageClip(np.array(img), transparent=True)
                    .with_duration(d)
                    .with_start(t0)
                    .with_effects([CrossFadeIn(FADE)])
                    .with_position("center")
                )
                clips.append(clip)
            else:
                # Inside-sentence split: distribute by character count, weighting
                # ASCII chars (English/digits) 2x because edge-tts speaks them slower.
                def weight(s: str) -> float:
                    return sum(2.0 if ch.isascii() and ch.strip() else 1.0 for ch in s)
                weights = [weight(p) for p in parts]
                total_w = sum(weights) or 1
                t = audio_start + b["start"] - LEAD
                first = True
                for i, part in enumerate(parts):
                    share = weights[i] / total_w
                    d = b["duration"] * share
                    img = L.render_subtitle(part)
                    last = i == len(parts) - 1
                    extra = (0.20 + LEAD) if last else 0.0
                    lead_for_this = LEAD if first else 0.0
                    clip = (
                        ImageClip(np.array(img), transparent=True)
                        .with_duration(d + extra + lead_for_this)
                        .with_start(t if first else t - 0.0)
                        .with_effects([CrossFadeIn(FADE)])
                        .with_position("center")
                    )
                    clips.append(clip)
                    t += d
                    first = False
        return clips

    # Fallback: estimated timing
    sentences = L.split_sentences(narration)
    if not sentences:
        return []
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
    """Synthesize mp3 + a sidecar .json file with precise per-sentence timing
    (edge-tts SentenceBoundary events). The .json is consumed by build_item_clip
    to align subtitles to audio.
    """
    import json as _json
    out_json = out_mp3.with_suffix(".json")
    boundaries = []
    comm = edge_tts.Communicate(text, voice, rate=RATE)
    with open(out_mp3, "wb") as f:
        async for chunk in comm.stream():
            if chunk["type"] == "audio":
                f.write(chunk["data"])
            elif chunk["type"] == "SentenceBoundary":
                boundaries.append({
                    "text": chunk["text"],
                    "start": chunk["offset"] / 1e7,
                    "duration": chunk["duration"] / 1e7,
                })
    out_json.write_text(_json.dumps(boundaries, ensure_ascii=False, indent=2))


def load_boundaries(mp3_path: Path):
    """Load sidecar boundaries; empty list if none."""
    import json as _json
    p = mp3_path.with_suffix(".json")
    if not p.exists():
        return []
    return _json.loads(p.read_text())


def build_item_clip(item: TrendItem, date: str, audio_path: Path,
                    palette_id: int = None, entry_mode: str = None,
                    category: str = None, hook: str = None) -> CompositeVideoClip:
    """Build a single-item video clip including audio. Caller owns TTS.

    When `category` is given (one of L.CATEGORY_PALETTES keys), the background
    color set and a sparse theme decoration are picked based on it.
    Otherwise palette_id cycles per rank like before.

    `hook` (国产/官方/开源/爆款/论文 or None) draws an eye-catching chip in the
    top-right.
    """
    if palette_id is None:
        palette_id = (item.rank - 1) % len(L.PALETTES)
    if entry_mode is None:
        entry_mode = ENTRY_MODES[(item.rank - 1) % len(ENTRY_MODES)]

    boundaries = load_boundaries(audio_path)
    audio = AudioFileClip(str(audio_path))
    narr_dur = audio.duration

    intro_dur = 2.4
    audio_start = intro_dur - 0.2
    total = audio_start + narr_dur + 0.6

    bg = build_background_clip(total, palette_id=palette_id, category=category)
    header = fade_in_layer(L.render_header(date), start=0.0, dur=total, fade=0.3)
    lang = fade_in_layer(L.render_lang(item.language), start=0.9, dur=total - 0.9, fade=0.4)

    # Sparse theme decoration (one static layer behind the main content)
    extra_layers = []
    if category:
        deco = fade_in_layer(L.render_decoration(category), start=0.3,
                             dur=total - 0.3, fade=0.6)
        extra_layers.append(deco)

    rank = make_rank_clip(item.rank, total, mode=entry_mode)
    repo = make_repo_clip(item, total, mode=entry_mode)

    stars_roll_start = 1.1
    stars_roll_dur = 1.2
    stars_clips = build_stars_clips(item.stars_today, stars_roll_start, stars_roll_dur,
                                     hold_until=total)
    streak = build_streak_clip(start=stars_roll_start + stars_roll_dur)

    # Hook chip in the corner (no-op if hook is None)
    if hook:
        hook_clip = (
            ImageClip(np.array(L.render_hook(hook)), transparent=True)
            .with_duration(total - 0.7)
            .with_start(0.7)
            .with_effects([FadeIn(0.35), Resize(lambda t: 0.85 + 0.15 * min(1.0, t / 0.4))])
            .with_position("center")
        )
        extra_layers.append(hook_clip)

    subs = build_subtitle_clips(item.narration, narr_dur, audio_start, boundaries)

    layers = [bg] + extra_layers[:1] + [header, rank, repo, lang] + stars_clips + [streak] + extra_layers[1:] + subs
    video = CompositeVideoClip(layers, size=(W, H)).with_duration(total)
    full_audio = pad_audio(audio, lead=audio_start, total=total)
    return video.with_audio(full_audio)


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
