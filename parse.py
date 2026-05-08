"""Parse trends markdown into structured items."""
import re
from pathlib import Path
from dataclasses import dataclass, asdict
import json


@dataclass
class TrendItem:
    rank: int
    repo: str           # owner/name
    url: str
    language: str
    stars_today: int
    description: str    # 英文 简介
    narration: str      # 中文讲述（用作 TTS 文本）


def parse(md_path: Path) -> list[TrendItem]:
    text = md_path.read_text(encoding="utf-8")
    blocks = re.split(r"^## \d+\.\s*", text, flags=re.MULTILINE)[1:]
    items: list[TrendItem] = []
    for i, block in enumerate(blocks, 1):
        repo_line, *rest = block.strip().splitlines()
        repo = repo_line.strip()
        joined = "\n".join(rest)
        url = re.search(r"链接：\s*(\S+)", joined)
        lang = re.search(r"语言：\s*([^\n]+)", joined)
        stars = re.search(r"今日新增：\s*([\d,]+)", joined)
        desc = re.search(r"简介：\s*([^\n]+)", joined)
        narr = re.search(r"\*\*中文讲述\*\*：\s*([^\n]+)", joined)
        items.append(TrendItem(
            rank=i,
            repo=repo,
            url=url.group(1) if url else "",
            language=lang.group(1).strip() if lang else "",
            stars_today=int(stars.group(1).replace(",", "")) if stars else 0,
            description=desc.group(1).strip() if desc else "",
            narration=narr.group(1).strip() if narr else "",
        ))
    return items


if __name__ == "__main__":
    import sys
    items = parse(Path(sys.argv[1]))
    print(json.dumps([asdict(x) for x in items], ensure_ascii=False, indent=2))
