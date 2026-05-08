"""Render a 1080x1920 vertical card image for one trending item."""
from pathlib import Path
from typing import Optional, List
from PIL import Image, ImageDraw, ImageFont
from parse import TrendItem

W, H = 1080, 1920
BG = (13, 17, 23)              # GitHub dark bg
FG = (230, 237, 243)            # primary text
ACCENT = (255, 184, 0)          # gold for stars
MUTED = (139, 148, 158)         # muted text
LANG_BG = (33, 38, 45)          # tag bg
HEADER_GRADIENT_TOP = (88, 166, 255)
HEADER_GRADIENT_BOT = (188, 140, 255)

FONT_HEI = "/System/Library/Fonts/Hiragino Sans GB.ttc"
FONT_BOLD = "/System/Library/Fonts/STHeiti Medium.ttc"


def font(path: str, size: int) -> ImageFont.FreeTypeFont:
    return ImageFont.truetype(path, size)


def wrap_cn(draw: ImageDraw.ImageDraw, text: str, fnt: ImageFont.FreeTypeFont, max_w: int) -> List[str]:
    """Wrap CJK text by measuring char-by-char width."""
    lines, line = [], ""
    for ch in text:
        trial = line + ch
        if draw.textlength(trial, font=fnt) > max_w and line:
            lines.append(line)
            line = ch
        else:
            line = trial
    if line:
        lines.append(line)
    return lines


def render(item: TrendItem, date: str, stars_display: Optional[int] = None) -> Image.Image:
    """Render the card. stars_display lets us animate the counter (overrides item.stars_today)."""
    img = Image.new("RGB", (W, H), BG)
    d = ImageDraw.Draw(img)

    stars = stars_display if stars_display is not None else item.stars_today

    # ===== Top header bar =====
    d.rectangle([0, 0, W, 200], fill=(22, 27, 34))
    d.text((60, 70), f"GitHub TRENDING", font=font(FONT_BOLD, 56), fill=(88, 166, 255))
    d.text((60, 140), date, font=font(FONT_HEI, 36), fill=MUTED)

    # ===== Rank big number =====
    rank_str = f"#{item.rank}"
    rank_font = font(FONT_BOLD, 280)
    d.text((60, 240), rank_str, font=rank_font, fill=(48, 54, 61))  # outline-ish background

    # ===== Repo name (auto-shrink if too wide) =====
    repo = item.repo
    repo_size = 76
    while repo_size > 40:
        repo_font = font(FONT_BOLD, repo_size)
        if d.textlength(repo, font=repo_font) <= W - 120:
            break
        repo_size -= 4
    repo_font = font(FONT_BOLD, repo_size)
    d.text((60, 560), repo, font=repo_font, fill=FG)

    # ===== Language tag =====
    if item.language:
        lang_font = font(FONT_HEI, 38)
        lang_w = d.textlength(item.language, font=lang_font)
        d.rounded_rectangle([60, 670, 60 + lang_w + 50, 740], radius=20, fill=LANG_BG)
        d.text((60 + 25, 678), item.language, font=lang_font, fill=(88, 166, 255))

    # ===== Stars block (the eye-catcher) =====
    # ⭐ icon as text
    star_label_font = font(FONT_HEI, 40)
    d.text((60, 800), "今日新增", font=star_label_font, fill=MUTED)

    stars_str = f"+{stars:,}"
    stars_font = font(FONT_BOLD, 200)
    d.text((60, 850), stars_str, font=stars_font, fill=ACCENT)

    star_unit_font = font(FONT_HEI, 50)
    star_unit = "stars"
    star_unit_x = 60 + d.textlength(stars_str, font=stars_font) + 20
    d.text((star_unit_x, 970), star_unit, font=star_unit_font, fill=ACCENT)

    # ===== Divider =====
    d.rectangle([60, 1110, W - 60, 1112], fill=(48, 54, 61))

    # ===== Narration text =====
    narr_font = font(FONT_HEI, 46)
    lines = wrap_cn(d, item.narration, narr_font, W - 120)
    y = 1160
    for ln in lines:
        d.text((60, y), ln, font=narr_font, fill=FG)
        y += 70
        if y > 1750:
            break

    # ===== Bottom URL =====
    url_font = font(FONT_HEI, 32)
    d.text((60, 1830), item.url, font=url_font, fill=MUTED)

    return img


if __name__ == "__main__":
    from parse import parse
    items = parse(Path("data/2026-05-07.md"))
    img = render(items[0], "2026-05-07")
    Path("output").mkdir(exist_ok=True)
    img.save("output/card_preview.png")
    print("output/card_preview.png")
