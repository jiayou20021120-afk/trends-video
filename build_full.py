"""Build the full daily video: intro → all items → outro.

Uses make_demo.build_item_clip for each item; TTS is generated in parallel
up-front so we don't pay for asyncio.run() N times.

CLI:
    python build_full.py                 # uses today (UTC)
    python build_full.py --date 2026-05-07
    python build_full.py --md path/to/foo.md --out output/foo.mp4
"""
import argparse
import asyncio
import datetime as dt
import json
import os
import subprocess
from pathlib import Path
from typing import List, Dict
import numpy as np
from moviepy import (
    ImageClip,
    AudioFileClip,
    CompositeVideoClip,
    concatenate_videoclips,
)
from moviepy.video.fx import FadeIn, FadeOut

from parse import parse, TrendItem
import layers as L
from make_demo import (
    build_item_clip,
    build_background_clip,
    synth_tts,
    DATE,
    VOICE,
    RATE,
    FPS,
    W, H,
)


# ---------------------------------------------------------------------------
# Batch TTS
# ---------------------------------------------------------------------------

def _cache_valid(mp3_path: Path) -> bool:
    """Both the mp3 and its sidecar .json (boundaries) must exist."""
    return mp3_path.exists() and mp3_path.with_suffix(".json").exists()


async def synth_all(items: List[TrendItem], audio_dir: Path) -> List[Path]:
    audio_dir.mkdir(parents=True, exist_ok=True)
    paths = []
    tasks = []
    for it in items:
        p = audio_dir / f"narration_{it.rank:02d}.mp3"
        paths.append(p)
        if not _cache_valid(p):
            if p.exists():
                p.unlink()  # stale mp3 without sidecar — regenerate
            tasks.append(synth_tts(it.narration, p))
    if tasks:
        print(f"[tts] generating {len(tasks)} narrations in parallel ...")
        await asyncio.gather(*tasks)
    else:
        print("[tts] all narrations cached")
    return paths


async def synth_one(text: str, out_path: Path) -> None:
    if _cache_valid(out_path):
        return
    if out_path.exists():
        out_path.unlink()
    await synth_tts(text, out_path)


# ---------------------------------------------------------------------------
# Intro / Outro clips
# ---------------------------------------------------------------------------

def build_intro_clip(date: str, n_items: int, audio_path: Path) -> CompositeVideoClip:
    audio = AudioFileClip(str(audio_path))
    dur = audio.duration + 0.6

    bg = build_background_clip(dur)
    fg_img = L.render_intro(date, n_items)
    fg = (
        ImageClip(np.array(fg_img), transparent=True)
        .with_duration(dur)
        .with_effects([FadeIn(0.4), FadeOut(0.5)])
        .with_position("center")
    )
    video = CompositeVideoClip([bg, fg], size=(W, H)).with_duration(dur)
    return video.with_audio(audio.with_start(0.2))


def build_outro_clip(items: List[TrendItem], audio_path: Path,
                     top_n: int = 6) -> CompositeVideoClip:
    audio = AudioFileClip(str(audio_path))
    dur = audio.duration + 0.8

    bg = build_background_clip(dur)
    fg_img = L.render_outro(items, top_n=top_n)
    fg = (
        ImageClip(np.array(fg_img), transparent=True)
        .with_duration(dur)
        .with_effects([FadeIn(0.4), FadeOut(0.6)])
        .with_position("center")
    )
    video = CompositeVideoClip([bg, fg], size=(W, H)).with_duration(dur)
    return video.with_audio(audio.with_start(0.3))


# ---------------------------------------------------------------------------
# Main pipeline
# ---------------------------------------------------------------------------

INTRO_NARRATION = (
    "{date}，GitHub 今日热门来啦。今天的 TOP {n} 个项目，带你看清开发者风向。"
)
OUTRO_NARRATION = (
    "以上就是今日 GitHub 热门项目。关注我，每天一分钟看清开发者风向。"
)


def parse_args():
    today_utc = dt.datetime.utcnow().strftime("%Y-%m-%d")
    p = argparse.ArgumentParser(description="Build daily GitHub Trending video.")
    p.add_argument("--date", default=os.environ.get("TRENDS_DATE", today_utc),
                   help="Date string used in headers/labels (default: today UTC).")
    p.add_argument("--md", default=None,
                   help="Path to trends markdown. Defaults to data/<date>.md.")
    p.add_argument("--out", default=None,
                   help="Output mp4 path. Defaults to output/daily_<date>.mp4.")
    p.add_argument("--audio-dir", default="output/audio",
                   help="Directory to cache TTS mp3 files (per-date subfolder).")
    return p.parse_args()


def load_takes(date: str) -> Dict[int, str]:
    """Load per-rank takes from takes/<date>.json. Returns {} if not found."""
    p = Path(f"takes/{date}.json")
    if not p.exists():
        return {}
    try:
        raw = json.loads(p.read_text())
        return {int(k): v for k, v in raw.items() if v}
    except Exception:
        return {}


def merge_take_into_narration(item, take: str) -> None:
    """Append '。我的看法是，<take>' to the item's narration in-place.
    Idempotent: if the marker is already there, do nothing."""
    if not take:
        return
    marker = "我的看法是"
    if marker in item.narration:
        return
    n = item.narration.rstrip()
    if not n.endswith(("。", "！", "？", ".", "!", "?")):
        n += "。"
    item.narration = n + "我的看法是，" + take


def main():
    args = parse_args()
    date = args.date
    md_path = Path(args.md) if args.md else Path(f"data/{date}.md")
    out_mp4 = Path(args.out) if args.out else Path("output") / f"daily_{date}.mp4"
    audio_dir = Path(args.audio_dir) / date

    if not md_path.exists():
        raise SystemExit(f"[error] markdown not found: {md_path}")

    items = parse(md_path)
    print(f"[parse] {len(items)} items from {md_path}")

    # Merge takes (opinionated commentary) if available
    takes = load_takes(date)
    if takes:
        for it in items:
            if it.rank in takes:
                merge_take_into_narration(it, takes[it.rank])
        print(f"[takes] merged {sum(1 for it in items if '我的看法是' in it.narration)} takes")
    else:
        print("[takes] no takes file found — running without opinions")

    audio_dir.mkdir(parents=True, exist_ok=True)

    # 1. Batch TTS for items
    item_audio = asyncio.run(synth_all(items, audio_dir))

    # 2. Intro/Outro narrations
    intro_audio = audio_dir / "intro.mp3"
    outro_audio = audio_dir / "outro.mp3"
    intro_text = INTRO_NARRATION.format(date=date, n=len(items))

    async def synth_meta():
        await synth_one(intro_text, intro_audio)
        await synth_one(OUTRO_NARRATION, outro_audio)

    asyncio.run(synth_meta())

    # 3. Render each segment to its own mp4. This avoids the OOM that
    # concatenate_videoclips + a single write_videofile causes on a 16GB
    # ubuntu runner (8 × 4-minute 1080x1920 clips in memory is too much).
    seg_dir = Path("output/segments") / date
    seg_dir.mkdir(parents=True, exist_ok=True)

    def render_segment(clip, path: Path, label: str) -> Path:
        print(f"[render] {label} → {path}")
        path.parent.mkdir(parents=True, exist_ok=True)
        clip.write_videofile(
            str(path),
            fps=FPS,
            codec="libx264",
            audio_codec="aac",
            preset="fast",
            threads=4,
            logger=None,
            ffmpeg_params=["-pix_fmt", "yuv420p"],
        )
        try:
            clip.close()
        except Exception:
            pass
        return path

    seg_paths: List[Path] = []

    print("[build] intro ...")
    intro = build_intro_clip(date, len(items), intro_audio)
    intro = intro.with_effects([FadeIn(0.4), FadeOut(0.4)])
    seg_paths.append(render_segment(intro, seg_dir / "00_intro.mp4", "intro"))

    for i, (it, ap) in enumerate(zip(items, item_audio), 1):
        print(f"[build] item {i}/{len(items)}: {it.repo}")
        c = build_item_clip(it, date, ap)
        c = c.with_effects([FadeIn(0.25), FadeOut(0.35)])
        seg_paths.append(render_segment(c, seg_dir / f"{i:02d}_item.mp4",
                                         f"item {i}/{len(items)}"))

    print("[build] outro ...")
    outro = build_outro_clip(items, outro_audio, top_n=min(6, len(items)))
    outro = outro.with_effects([FadeIn(0.4), FadeOut(0.6)])
    seg_paths.append(render_segment(outro, seg_dir / "99_outro.mp4", "outro"))

    # 4. Stitch with ffmpeg concat demuxer — zero re-encode, near-instant.
    out_mp4.parent.mkdir(parents=True, exist_ok=True)
    list_file = seg_dir / "concat.txt"
    list_file.write_text(
        "\n".join(f"file '{p.resolve().as_posix()}'" for p in seg_paths) + "\n"
    )
    print(f"[concat] ffmpeg-stitching {len(seg_paths)} segments → {out_mp4}")
    subprocess.run(
        [
            "ffmpeg", "-y",
            "-f", "concat", "-safe", "0",
            "-i", str(list_file),
            "-c", "copy",
            "-movflags", "+faststart",
            str(out_mp4),
        ],
        check=True,
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
    )
    print(f"[done] {out_mp4}")


if __name__ == "__main__":
    main()
