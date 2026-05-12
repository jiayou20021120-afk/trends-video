"""Per-element PIL renderers. Each returns an RGBA PIL.Image at canvas size 1080x1920
unless otherwise noted, so they can be stacked as moviepy ImageClips with .with_position("center").
"""
from __future__ import annotations
import math
import os
from pathlib import Path
from typing import List, Tuple, Optional
from PIL import Image, ImageDraw, ImageFont, ImageFilter

W, H = 1080, 1920

# Palette
FG = (235, 240, 248, 255)
MUTED = (148, 158, 175, 255)
ACCENT = (255, 188, 60, 255)         # gold for stars
BLUE = (88, 166, 255, 255)
PURPLE = (188, 140, 255, 255)
GREEN = (110, 220, 160, 255)
LANG_BG = (40, 48, 60, 220)


def _find_first(*paths: str) -> Optional[str]:
    for p in paths:
        if os.path.exists(p):
            return p
    return None


# Cross-platform CJK font discovery — env var override > macOS > Ubuntu.
FONT_HEI = os.environ.get("FONT_HEI") or _find_first(
    "/System/Library/Fonts/Hiragino Sans GB.ttc",                   # macOS
    "/usr/share/fonts/opentype/noto/NotoSansCJK-Regular.ttc",       # Ubuntu fonts-noto-cjk
    "/usr/share/fonts/truetype/noto/NotoSansCJK-Regular.ttc",
    "/usr/share/fonts/truetype/wqy/wqy-zenhei.ttc",                 # Ubuntu fallback
    "/usr/share/fonts/truetype/wqy/wqy-microhei.ttc",
)
FONT_BOLD = os.environ.get("FONT_BOLD") or _find_first(
    "/System/Library/Fonts/STHeiti Medium.ttc",                     # macOS
    "/usr/share/fonts/opentype/noto/NotoSansCJK-Bold.ttc",          # Ubuntu fonts-noto-cjk
    "/usr/share/fonts/truetype/noto/NotoSansCJK-Bold.ttc",
    "/usr/share/fonts/truetype/wqy/wqy-zenhei.ttc",                 # Ubuntu fallback
    "/usr/share/fonts/truetype/wqy/wqy-microhei.ttc",
)
if FONT_HEI is None or FONT_BOLD is None:
    raise RuntimeError(
        "No CJK font found. On Ubuntu run: sudo apt-get install fonts-noto-cjk. "
        "Or set FONT_HEI / FONT_BOLD env vars to font file paths."
    )


def F(path: str, size: int) -> ImageFont.FreeTypeFont:
    return ImageFont.truetype(path, size)


# ---------------------------------------------------------------------------
# Background — dynamic gradient with two slowly drifting blobs of color.
# ---------------------------------------------------------------------------

# Per-item color palettes — cycled by rank so adjacent items feel different.
# Kept for the intro/outro (no category context there).
PALETTES = [
    {"name": "neon",   "blob_a": (120, 70, 200, 90),  "blob_b": (50, 120, 220, 80)},
    {"name": "ocean",  "blob_a": (40, 160, 180, 90),  "blob_b": (80, 200, 140, 75)},
    {"name": "ember",  "blob_a": (220, 110, 60, 90),  "blob_b": (190, 60, 140, 75)},
]


# Per-category palette — each project gets a visual identity matching its kind.
CATEGORY_PALETTES = {
    "ai_agent":    {"blob_a": (140, 80, 220, 100), "blob_b": (60, 130, 240, 85)},   # AI purple/blue
    "cli_tool":    {"blob_a": (40, 200, 130, 100), "blob_b": (30, 110, 80, 80)},    # terminal green
    "web_frontend":{"blob_a": (110, 200, 240, 95), "blob_b": (220, 130, 220, 80)},  # cyan/pink
    "finance":     {"blob_a": (220, 160, 70, 95),  "blob_b": (210, 70, 80, 80)},    # gold/red
    "research":    {"blob_a": (180, 150, 90, 90),  "blob_b": (90, 120, 180, 75)},   # parchment/blue
    "tool":        {"blob_a": (110, 100, 160, 90), "blob_b": (160, 90, 130, 75)},   # neutral plum
}


def palette_for(rank: int) -> dict:
    return PALETTES[(rank - 1) % len(PALETTES)]


def palette_for_category(category: str) -> dict:
    return CATEGORY_PALETTES.get(category, CATEGORY_PALETTES["tool"])


def render_background(t: float, total: float,
                      palette_id: int = 0,
                      category: str = None) -> Image.Image:
    """Animated dark gradient. If `category` is given, picks the category palette;
    otherwise falls back to PALETTES[palette_id]."""
    base = Image.new("RGBA", (W, H), (10, 12, 20, 255))

    if category is not None:
        pal = palette_for_category(category)
    else:
        pal = PALETTES[palette_id % len(PALETTES)]
    phase = (t / max(total, 1.0)) * math.tau
    blob_layer = Image.new("RGBA", (W, H), (0, 0, 0, 0))
    bd = ImageDraw.Draw(blob_layer)

    cx_a = int(W * 0.3 + 240 * math.cos(phase))
    cy_a = int(H * 0.25 + 180 * math.sin(phase * 1.1))
    bd.ellipse([cx_a - 600, cy_a - 600, cx_a + 600, cy_a + 600],
               fill=pal["blob_a"])

    cx_b = int(W * 0.7 + 240 * math.cos(phase + math.pi))
    cy_b = int(H * 0.75 + 180 * math.sin(phase * 1.2 + 1.0))
    bd.ellipse([cx_b - 700, cy_b - 700, cx_b + 700, cy_b + 700],
               fill=pal["blob_b"])

    # Heavy blur for soft glow
    blob_layer = blob_layer.filter(ImageFilter.GaussianBlur(radius=120))
    base = Image.alpha_composite(base, blob_layer)

    # Subtle vignette
    vign = Image.new("RGBA", (W, H), (0, 0, 0, 0))
    vd = ImageDraw.Draw(vign)
    vd.ellipse([-200, -200, W + 200, H + 200], fill=(0, 0, 0, 0))
    # rectangle border darken
    for i in range(60):
        a = int(120 * (i / 60) ** 2)
        vd.rectangle([i, i, W - i, H - i], outline=(0, 0, 0, a))
    base = Image.alpha_composite(base, vign)

    return base


# ---------------------------------------------------------------------------
# Header — top banner with brand label + date
# ---------------------------------------------------------------------------

# ---------------------------------------------------------------------------
# Hook chip — eye-catching badge in the top-right corner (国产/官方/开源/爆款/论文)
# ---------------------------------------------------------------------------

HOOK_STYLES = {
    # bg, fg, marker (unicode glyph that works without an emoji font)
    "国产": ((228, 50, 50, 240),  (255, 245, 240, 255), "★"),
    "官方": ((45, 130, 230, 240), (240, 248, 255, 255), "◆"),
    "开源": ((50, 190, 110, 240), (240, 255, 245, 255), "◇"),
    "爆款": ((255, 100, 30, 240), (255, 248, 235, 255), "▲"),
    "论文": ((180, 130, 70, 240), (255, 250, 240, 255), "§"),
}


def render_hook(hook: str) -> Image.Image:
    """Render a hook chip in the top-right corner. Returns transparent if no hook."""
    img = Image.new("RGBA", (W, H), (0, 0, 0, 0))
    if not hook or hook not in HOOK_STYLES:
        return img
    bg, fg, glyph = HOOK_STYLES[hook]
    d = ImageDraw.Draw(img)
    fnt = F(FONT_BOLD, 56)
    label = f"{glyph}  {hook}"
    tw = int(d.textlength(label, font=fnt))
    pad_x, pad_y = 32, 18
    box_w = tw + pad_x * 2
    box_h = 56 + pad_y * 2
    x0 = W - 60 - box_w
    y0 = 230
    # subtle shadow
    shadow = Image.new("RGBA", (W, H), (0, 0, 0, 0))
    ImageDraw.Draw(shadow).rounded_rectangle(
        [x0 + 6, y0 + 8, x0 + box_w + 6, y0 + box_h + 8],
        radius=26, fill=(0, 0, 0, 120),
    )
    shadow = shadow.filter(ImageFilter.GaussianBlur(radius=8))
    img = Image.alpha_composite(img, shadow)
    d = ImageDraw.Draw(img)
    d.rounded_rectangle([x0, y0, x0 + box_w, y0 + box_h], radius=26, fill=bg)
    d.text((x0 + pad_x, y0 + pad_y - 4), label, font=fnt, fill=fg)
    return img


# ---------------------------------------------------------------------------
# Category decoration — sparse, theme-appropriate flourishes around the canvas
# ---------------------------------------------------------------------------

def _draw_neural_net(d, w, h, color):
    """Scattered dots + thin connecting lines — feels like a neural network."""
    import random
    rng = random.Random(42)
    points = []
    for _ in range(14):
        x = rng.randint(40, w - 40)
        y = rng.choice([rng.randint(180, 360), rng.randint(1140, 1340)])
        points.append((x, y))
    for x, y in points:
        d.ellipse([x - 5, y - 5, x + 5, y + 5], fill=color)
    # connect close pairs
    for i, p in enumerate(points):
        for q in points[i + 1 : i + 4]:
            dx, dy = p[0] - q[0], p[1] - q[1]
            if dx * dx + dy * dy < 180 * 180:
                d.line([p, q], fill=(color[0], color[1], color[2], 90), width=2)


def _draw_terminal(d, w, h, color):
    """Faint terminal prompt markers >_ in corners."""
    fnt = F(FONT_BOLD, 64)
    for x, y in [(60, 220), (60, 1300), (w - 200, 220), (w - 200, 1300)]:
        d.text((x, y), ">_", font=fnt, fill=color)


def _draw_grid(d, w, h, color):
    """Faint horizontal/vertical guide lines — UI grid feel."""
    for y in range(220, 1360, 110):
        d.line([(60, y), (w - 60, y)], fill=color, width=2)
    for x in range(60, w - 60, 220):
        d.line([(x, 220), (x, 1360)], fill=color, width=2)


def _draw_candles(d, w, h, color):
    """Thin candlestick-style vertical bars across the middle band."""
    import random
    rng = random.Random(7)
    base_y = 1280
    for i in range(18):
        x = 60 + i * 56
        height = rng.randint(20, 90)
        d.rectangle([x, base_y - height, x + 14, base_y + 4], fill=color)
        d.line([(x + 7, base_y - height - 14), (x + 7, base_y + 18)],
               fill=color, width=1)


def _draw_research(d, w, h, color):
    """Greek letters and brackets scattered along the edges."""
    glyphs = ["σ", "Σ", "λ", "∫", "θ", "π", "∇", "α", "β"]
    import random
    rng = random.Random(13)
    fnt = F(FONT_BOLD, 70)
    for g in glyphs:
        x = rng.randint(40, w - 100)
        y = rng.choice([rng.randint(220, 360), rng.randint(1180, 1340)])
        d.text((x, y), g, font=fnt, fill=color)


def _draw_tool(d, w, h, color):
    """Minimal circle/ring marks — generic tool aesthetic."""
    import random
    rng = random.Random(5)
    for _ in range(8):
        cx = rng.randint(40, w - 40)
        cy = rng.choice([rng.randint(200, 380), rng.randint(1160, 1340)])
        r = rng.randint(14, 28)
        d.ellipse([cx - r, cy - r, cx + r, cy + r], outline=color, width=3)


_DECOR_DRAWERS = {
    "ai_agent": _draw_neural_net,
    "cli_tool": _draw_terminal,
    "web_frontend": _draw_grid,
    "finance": _draw_candles,
    "research": _draw_research,
    "tool": _draw_tool,
}


def render_decoration(category: str) -> Image.Image:
    """Sparse theme-appropriate marks behind the main content. Single static image
    rendered once per category — cached implicitly by call site."""
    img = Image.new("RGBA", (W, H), (0, 0, 0, 0))
    drawer = _DECOR_DRAWERS.get(category, _draw_tool)
    color = (255, 255, 255, 38)  # very subtle — won't fight foreground
    drawer(ImageDraw.Draw(img), W, H, color)
    return img


def render_header(date: str) -> Image.Image:
    img = Image.new("RGBA", (W, H), (0, 0, 0, 0))
    d = ImageDraw.Draw(img)

    # Soft bar background (semi-transparent)
    d.rounded_rectangle([40, 60, W - 40, 200], radius=24,
                        fill=(20, 24, 34, 200))

    # Glow accent bar on the left
    d.rounded_rectangle([60, 88, 76, 172], radius=8, fill=BLUE)

    d.text((100, 80), "GH TRENDING", font=F(FONT_BOLD, 56), fill=(180, 220, 255, 255))
    d.text((100, 144), date, font=F(FONT_HEI, 36), fill=MUTED)
    return img


# ---------------------------------------------------------------------------
# Rank — large gradient "#N" centered at top-third
# ---------------------------------------------------------------------------

def render_rank(rank: int) -> Image.Image:
    """Render '#N' as a single big number with a vertical blue→purple gradient."""
    img = Image.new("RGBA", (W, H), (0, 0, 0, 0))
    d = ImageDraw.Draw(img)
    text = f"#{rank}"
    fnt = F(FONT_BOLD, 320)
    bbox = d.textbbox((0, 0), text, font=fnt)
    tw, th = bbox[2] - bbox[0], bbox[3] - bbox[1]
    x = (W - tw) // 2
    y = 240

    # Render text in white onto a mask, then apply gradient
    mask = Image.new("L", (tw, th + 40), 0)
    md = ImageDraw.Draw(mask)
    md.text((-bbox[0], -bbox[1]), text, font=fnt, fill=255)

    # Gradient strip
    grad = Image.new("RGBA", (tw, th + 40), (0, 0, 0, 0))
    gd = ImageDraw.Draw(grad)
    for j in range(th + 40):
        ratio = j / (th + 40)
        r = int(BLUE[0] + (PURPLE[0] - BLUE[0]) * ratio)
        g = int(BLUE[1] + (PURPLE[1] - BLUE[1]) * ratio)
        b = int(BLUE[2] + (PURPLE[2] - BLUE[2]) * ratio)
        gd.line([(0, j), (tw, j)], fill=(r, g, b, 255))
    grad.putalpha(mask)

    # Soft glow
    glow = grad.filter(ImageFilter.GaussianBlur(radius=14))
    img.paste(glow, (x, y), glow)
    img.paste(grad, (x, y), grad)
    return img


# ---------------------------------------------------------------------------
# Repo — owner/ small grey, name big white bold (the SHORT NAME emphasis)
# ---------------------------------------------------------------------------

def render_repo(repo: str, max_width: int = W - 120) -> Image.Image:
    img = Image.new("RGBA", (W, H), (0, 0, 0, 0))
    d = ImageDraw.Draw(img)

    if "/" in repo:
        owner, name = repo.split("/", 1)
    else:
        owner, name = "", repo

    y = 620
    # owner/  (small grey)
    if owner:
        owner_fnt = F(FONT_HEI, 42)
        d.text((60, y), owner + " /", font=owner_fnt, fill=MUTED)
        y += 60

    # name  (big white bold, auto shrink)
    size = 110
    while size > 56:
        nf = F(FONT_BOLD, size)
        if d.textlength(name, font=nf) <= max_width:
            break
        size -= 6
    nf = F(FONT_BOLD, size)
    d.text((60, y), name, font=nf, fill=FG)
    return img


# ---------------------------------------------------------------------------
# Language tag
# ---------------------------------------------------------------------------

def render_lang(lang: str) -> Image.Image:
    img = Image.new("RGBA", (W, H), (0, 0, 0, 0))
    if not lang:
        return img
    d = ImageDraw.Draw(img)
    fnt = F(FONT_HEI, 38)
    w = d.textlength(lang, font=fnt)
    box_w = int(w + 56)
    y = 830
    d.rounded_rectangle([60, y, 60 + box_w, y + 70], radius=22, fill=LANG_BG)
    # accent dot
    d.ellipse([84, y + 24, 116, y + 56], fill=BLUE)
    d.text((130, y + 12), lang, font=fnt, fill=(220, 230, 250, 255))
    return img


# ---------------------------------------------------------------------------
# Stars — counter (with optional flash overlay)
# ---------------------------------------------------------------------------

def render_streak(progress: float) -> Image.Image:
    """A horizontal white streak that sweeps left→right across the stars line.
    progress ∈ [0, 1] sets the streak's center X. Returns a transparent canvas."""
    img = Image.new("RGBA", (W, H), (0, 0, 0, 0))
    if progress <= 0 or progress >= 1:
        return img
    d = ImageDraw.Draw(img)
    cx = int(progress * (W + 400) - 200)
    cy = 1100
    streak_w = 280
    streak_h = 18
    # core bright bar
    d.rectangle([cx - streak_w, cy - streak_h, cx + streak_w, cy + streak_h],
                fill=(255, 245, 200, 220))
    # broader soft halo
    halo = Image.new("RGBA", (W, H), (0, 0, 0, 0))
    hd = ImageDraw.Draw(halo)
    hd.rectangle([cx - streak_w * 1.6, cy - streak_h * 4,
                  cx + streak_w * 1.6, cy + streak_h * 4],
                 fill=(255, 220, 140, 80))
    halo = halo.filter(ImageFilter.GaussianBlur(radius=22))
    img = Image.alpha_composite(img, halo)
    img = Image.alpha_composite(img, Image.alpha_composite(
        Image.new("RGBA", (W, H), (0, 0, 0, 0)),
        img,
    ))
    # blur the core slightly for smoothness
    return img.filter(ImageFilter.GaussianBlur(radius=2))


def render_stars(value: int, flash_alpha: float = 0.0) -> Image.Image:
    img = Image.new("RGBA", (W, H), (0, 0, 0, 0))
    d = ImageDraw.Draw(img)

    label_fnt = F(FONT_HEI, 38)
    d.text((60, 950), "今日新增", font=label_fnt, fill=MUTED)

    num = f"+{value:,}"
    nf = F(FONT_BOLD, 220)
    d.text((60, 990), num, font=nf, fill=ACCENT)

    unit_fnt = F(FONT_HEI, 56)
    nw = d.textlength(num, font=nf)
    d.text((60 + nw + 24, 1130), "stars", font=unit_fnt, fill=ACCENT)

    if flash_alpha > 0:
        flash = Image.new("RGBA", (W, H), (0, 0, 0, 0))
        fd = ImageDraw.Draw(flash)
        # radial-ish gold flash centered on the stars number
        cx, cy = 60 + int(nw / 2), 1100
        for r in range(700, 0, -30):
            a = int(180 * flash_alpha * (1 - r / 700) ** 2)
            fd.ellipse([cx - r, cy - r, cx + r, cy + r], fill=(255, 220, 120, a))
        flash = flash.filter(ImageFilter.GaussianBlur(radius=30))
        img = Image.alpha_composite(img, flash)
    return img


# ---------------------------------------------------------------------------
# Subtitle — bottom panel, sentence-by-sentence with highlight keywords.
# ---------------------------------------------------------------------------

HIGHLIGHT_COLORS = {
    # keyword -> (R, G, B)
    "Anthropic": (255, 188, 60),
    "Claude": (88, 166, 255),
    "GitHub": (200, 220, 255),
    "AI": (255, 188, 60),
    "金融": (255, 188, 60),
    "开源": (110, 220, 160),
    "Rust": (255, 140, 60),
    "Python": (110, 220, 160),
}


def split_sentences(narration: str) -> List[str]:
    """Split Chinese narration into rhythm-friendly chunks."""
    raw = []
    buf = ""
    for ch in narration:
        buf += ch
        if ch in "。！？!?":
            raw.append(buf.strip())
            buf = ""
    if buf.strip():
        raw.append(buf.strip())
    # also break overly long sentences at the first comma after 24 chars
    out: List[str] = []
    for s in raw:
        if len(s) > 36:
            for i, ch in enumerate(s):
                if ch in "，,；;" and i > 22:
                    out.append(s[: i + 1].strip())
                    out.append(s[i + 1 :].strip())
                    break
            else:
                out.append(s)
        else:
            out.append(s)
    return [s for s in out if s]


def _wrap(d: ImageDraw.ImageDraw, text: str, fnt, max_w: int) -> List[str]:
    lines, line = [], ""
    for ch in text:
        trial = line + ch
        if d.textlength(trial, font=fnt) > max_w and line:
            lines.append(line)
            line = ch
        else:
            line = trial
    if line:
        lines.append(line)
    return lines


# ---------------------------------------------------------------------------
# Intro & Outro layers
# ---------------------------------------------------------------------------

def _gradient_text(text: str, fnt: ImageFont.FreeTypeFont,
                   c_top: Tuple[int, int, int], c_bot: Tuple[int, int, int]) -> Image.Image:
    """Render text as a vertical gradient on a transparent canvas (just the text bbox)."""
    dummy = ImageDraw.Draw(Image.new("RGBA", (10, 10)))
    bbox = dummy.textbbox((0, 0), text, font=fnt)
    tw, th = bbox[2] - bbox[0], bbox[3] - bbox[1]
    pad = 20
    canvas_w, canvas_h = tw + pad * 2, th + pad * 2

    mask = Image.new("L", (canvas_w, canvas_h), 0)
    md = ImageDraw.Draw(mask)
    md.text((pad - bbox[0], pad - bbox[1]), text, font=fnt, fill=255)

    grad = Image.new("RGBA", (canvas_w, canvas_h), (0, 0, 0, 0))
    gd = ImageDraw.Draw(grad)
    for j in range(canvas_h):
        ratio = j / max(canvas_h - 1, 1)
        r = int(c_top[0] + (c_bot[0] - c_top[0]) * ratio)
        g = int(c_top[1] + (c_bot[1] - c_top[1]) * ratio)
        b = int(c_top[2] + (c_bot[2] - c_top[2]) * ratio)
        gd.line([(0, j), (canvas_w, j)], fill=(r, g, b, 255))
    grad.putalpha(mask)
    return grad


def render_intro(date: str, n_items: int) -> Image.Image:
    """Cover page foreground."""
    img = Image.new("RGBA", (W, H), (0, 0, 0, 0))
    d = ImageDraw.Draw(img)

    # Top accent
    d.rounded_rectangle([(W - 280) // 2, 380, (W + 280) // 2, 432], radius=22,
                        fill=(20, 24, 34, 220))
    d.text((0, 388), "GH TRENDING", font=F(FONT_BOLD, 38), fill=BLUE,
           anchor=None)
    # Center-position the badge text manually
    badge_fnt = F(FONT_BOLD, 38)
    badge_text = "GH TRENDING"
    bw = d.textlength(badge_text, font=badge_fnt)
    # Re-clear and redraw to center properly
    img2 = Image.new("RGBA", (W, H), (0, 0, 0, 0))
    d = ImageDraw.Draw(img2)
    d.rounded_rectangle([(W - int(bw) - 80) // 2, 380, (W + int(bw) + 80) // 2, 442],
                        radius=24, fill=(20, 24, 34, 220))
    d.text(((W - int(bw)) // 2, 388), badge_text, font=badge_fnt, fill=BLUE)

    # Big title: "今日热门"
    title_fnt = F(FONT_BOLD, 240)
    title = "今日热门"
    grad_title = _gradient_text(title, title_fnt, BLUE[:3], PURPLE[:3])
    gx = (W - grad_title.width) // 2
    gy = 540
    glow = grad_title.filter(ImageFilter.GaussianBlur(radius=20))
    img2.paste(glow, (gx, gy), glow)
    img2.paste(grad_title, (gx, gy), grad_title)

    # Sub: "GitHub" in small white
    gh_fnt = F(FONT_BOLD, 80)
    gh_text = "GitHub"
    gw = d.textlength(gh_text, font=gh_fnt)
    d2 = ImageDraw.Draw(img2)
    d2.text(((W - gw) // 2, 480), gh_text, font=gh_fnt, fill=(220, 230, 250, 255))

    # Date + count line
    info_fnt = F(FONT_HEI, 56)
    info = f"{date}   ·   TOP {n_items}"
    iw = d2.textlength(info, font=info_fnt)
    d2.text(((W - iw) // 2, 1080), info, font=info_fnt, fill=ACCENT)

    # Tagline
    tag_fnt = F(FONT_HEI, 42)
    tag = "每日扫描，开发者风向"
    tw2 = d2.textlength(tag, font=tag_fnt)
    d2.text(((W - tw2) // 2, 1200), tag, font=tag_fnt, fill=MUTED)

    return img2


def render_outro(items, top_n: int = 6) -> Image.Image:
    """Outro: TOP N recap list + CTA."""
    img = Image.new("RGBA", (W, H), (0, 0, 0, 0))
    d = ImageDraw.Draw(img)

    # Title
    title_fnt = F(FONT_BOLD, 100)
    t = "今日榜单回顾"
    tw = d.textlength(t, font=title_fnt)
    d.text(((W - tw) // 2, 220), t, font=title_fnt, fill=FG)

    # Sub
    sub_fnt = F(FONT_HEI, 44)
    sub = f"TOP {min(top_n, len(items))}"
    sw = d.textlength(sub, font=sub_fnt)
    d.text(((W - sw) // 2, 360), sub, font=sub_fnt, fill=ACCENT)

    # List rows
    row_h = 150
    y = 470
    rank_fnt = F(FONT_BOLD, 80)
    name_fnt = F(FONT_BOLD, 52)
    star_fnt = F(FONT_BOLD, 52)
    owner_fnt = F(FONT_HEI, 28)

    for it in items[:top_n]:
        # row background
        d.rounded_rectangle([60, y, W - 60, y + row_h - 24], radius=22,
                            fill=(18, 22, 32, 200))
        # rank
        d.text((90, y + 25), f"{it.rank}", font=rank_fnt, fill=BLUE)

        # owner / name
        owner, name = it.repo.split("/", 1) if "/" in it.repo else ("", it.repo)
        if owner:
            d.text((220, y + 22), owner + " /", font=owner_fnt, fill=MUTED)
        # auto-shrink name
        size = 52
        while size > 28:
            nf = F(FONT_BOLD, size)
            if d.textlength(name, font=nf) <= W - 480:
                break
            size -= 4
        nf = F(FONT_BOLD, size)
        d.text((220, y + 56), name, font=nf, fill=FG)

        # stars right-aligned
        s = f"+{it.stars_today:,}"
        sw = d.textlength(s, font=star_fnt)
        d.text((W - 90 - sw, y + 35), s, font=star_fnt, fill=ACCENT)

        y += row_h

    # CTA
    cta_fnt = F(FONT_BOLD, 60)
    cta = "关注我  每日不错过"
    cw = d.textlength(cta, font=cta_fnt)
    d.text(((W - cw) // 2, 1720), cta, font=cta_fnt, fill=FG)

    arrow_fnt = F(FONT_BOLD, 50)
    arrow = "→"
    aw = d.textlength(arrow, font=arrow_fnt)
    d.text(((W - aw) // 2, 1820), arrow, font=arrow_fnt, fill=ACCENT)

    return img


def render_subtitle(sentence: str) -> Image.Image:
    """Render a bottom subtitle panel with the current sentence.

    Sentences starting with '我的看法' get a distinct gold treatment so the
    opinion segment visually separates from the description segment.
    """
    img = Image.new("RGBA", (W, H), (0, 0, 0, 0))
    d = ImageDraw.Draw(img)

    is_take = sentence.lstrip().startswith("我的看法")

    if is_take:
        panel_fill = (38, 28, 12, 225)        # warm dark amber
        stripe_color = ACCENT                  # gold
        default_text = ACCENT
        prefix_label = "看法"
    else:
        panel_fill = (15, 18, 26, 215)
        stripe_color = PURPLE
        default_text = FG
        prefix_label = None

    # Panel
    top = 1380
    d.rounded_rectangle([40, top, W - 40, H - 60], radius=28, fill=panel_fill)
    d.rounded_rectangle([60, top + 28, 76, top + 92], radius=8, fill=stripe_color)

    # Optional little corner tag for the take panel
    if prefix_label:
        tag_fnt = F(FONT_BOLD, 32)
        tag_w = int(d.textlength(prefix_label, font=tag_fnt) + 32)
        d.rounded_rectangle([W - 60 - tag_w, top + 28, W - 60, top + 80],
                            radius=18, fill=(255, 200, 80, 255))
        d.text((W - 60 - tag_w + 16, top + 36), prefix_label,
               font=tag_fnt, fill=(40, 28, 8, 255))

    fnt = F(FONT_HEI, 50)
    max_w = W - 160
    lines = _wrap(d, sentence, fnt, max_w)

    y = top + 40
    line_h = 76
    for line in lines:
        x = 100
        i = 0
        while i < len(line):
            # On take panels, skip keyword coloring — keep all text in gold
            if not is_take:
                matched = False
                for kw, color in HIGHLIGHT_COLORS.items():
                    if line[i : i + len(kw)] == kw:
                        d.text((x, y), kw, font=fnt, fill=color + (255,))
                        x += int(d.textlength(kw, font=fnt))
                        i += len(kw)
                        matched = True
                        break
                if matched:
                    continue
            d.text((x, y), line[i], font=fnt, fill=default_text)
            x += int(d.textlength(line[i], font=fnt))
            i += 1
        y += line_h
        if y > H - 140:
            break
    return img
