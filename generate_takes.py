"""Generate one short opinionated take per project, saved to takes/<date>.json.

Two backends:
  1. Local `claude` CLI (preferred — no API key needed, used in local dev where
     Claude Code is installed)
  2. Anthropic SDK + ANTHROPIC_API_KEY env var (fallback for CI / GitHub Actions)

If neither is available the script exits with code 0 and writes an empty file
so the downstream video build can still proceed.

Each take is a 35-55 char Chinese sentence in a "pragmatist" tone — only cares
about whether the project is usable tomorrow, when it will actually be useful,
and what blockers stand in the way.
"""
import argparse
import json
import os
import shutil
import subprocess
import sys
import time
from pathlib import Path

from parse import parse, TrendItem


PROMPT_TEMPLATE = """你是写技术评论十年的资深开发者。给你一个今日 GitHub 热门项目，
用 35-55 字写一句"实用主义判断"——只关心：明天我能用上吗？什么时候能真正派上用场？要解决什么才能用？

要求：
- 一句话，35-55 字，最多 60 字
- 不要"前景广阔""值得关注""惊艳"这种废话
- 直接给判断：能不能用、要多久才能用、卡在什么地方
- 用中文，语气克制、口语化
- 不带感叹号，不要前缀（不要"看法："这种引导语）
- 输出只包含这句评论本身，不要任何前后说明

项目信息：
名称：{repo}
语言：{language}
今日新增 stars：{stars_today}
简介：{description}
中文讲述：{narration}

直接给评论："""


def _clean(text: str) -> str:
    text = " ".join(text.split())
    return text.strip("\"'`*“”«» ")


def _generate_via_claude_cli(prompt: str, timeout: int = 90) -> str:
    result = subprocess.run(
        ["claude", "-p", prompt],
        capture_output=True,
        text=True,
        timeout=timeout,
    )
    if result.returncode != 0:
        raise RuntimeError(f"claude CLI exit={result.returncode}: "
                           f"{result.stderr.strip()[:200]}")
    return _clean(result.stdout)


def _generate_via_sdk(prompt: str) -> str:
    """Fallback for CI: use Anthropic SDK with ANTHROPIC_API_KEY."""
    import anthropic  # only imported when used
    client = anthropic.Anthropic()
    msg = client.messages.create(
        model="claude-sonnet-4-5",
        max_tokens=200,
        messages=[{"role": "user", "content": prompt}],
    )
    parts = [b.text for b in msg.content if getattr(b, "type", None) == "text"]
    return _clean("".join(parts))


def _pick_backend() -> str:
    """Return 'cli' | 'sdk' | 'none' depending on what's available."""
    if shutil.which("claude"):
        return "cli"
    if os.environ.get("ANTHROPIC_API_KEY"):
        return "sdk"
    return "none"


def generate_take(item: TrendItem, backend: str, retries: int = 2,
                  timeout: int = 90) -> str:
    """Return a single-line take. backend is 'cli' or 'sdk'."""
    prompt = PROMPT_TEMPLATE.format(
        repo=item.repo,
        language=item.language or "未知",
        stars_today=item.stars_today,
        description=item.description or "(无简介)",
        narration=item.narration,
    )
    last_err = None
    for attempt in range(retries + 1):
        try:
            if backend == "cli":
                text = _generate_via_claude_cli(prompt, timeout=timeout)
            else:
                text = _generate_via_sdk(prompt)
            if 12 <= len(text) <= 160:
                return text
            last_err = f"length out of range: {len(text)} chars"
        except subprocess.TimeoutExpired:
            last_err = f"timeout after {timeout}s"
        except Exception as e:
            last_err = f"{type(e).__name__}: {e}"
        time.sleep(2)
    raise RuntimeError(f"generate_take failed: {last_err}")


def main():
    p = argparse.ArgumentParser()
    p.add_argument("--date", required=True, help="YYYY-MM-DD")
    p.add_argument("--md", default=None,
                   help="Path to trends markdown. Defaults to data/<date>.md.")
    p.add_argument("--out", default=None,
                   help="Output JSON path. Defaults to takes/<date>.json.")
    p.add_argument("--force", action="store_true",
                   help="Regenerate even if cached.")
    args = p.parse_args()

    md_path = Path(args.md) if args.md else Path(f"data/{args.date}.md")
    out_path = Path(args.out) if args.out else Path(f"takes/{args.date}.json")
    out_path.parent.mkdir(parents=True, exist_ok=True)

    if not md_path.exists():
        sys.exit(f"[error] markdown not found: {md_path}")

    items = parse(md_path)
    print(f"[parse] {len(items)} items from {md_path}")

    cached = {}
    if out_path.exists() and not args.force:
        try:
            cached = json.loads(out_path.read_text())
            cached = {int(k): v for k, v in cached.items()}
        except Exception:
            cached = {}

    # Pick LLM backend: prefer local claude CLI, then SDK, else bail gracefully.
    pending = [it for it in items if not (it.rank in cached and cached[it.rank])]
    backend = _pick_backend() if pending else "cached"
    if backend == "none":
        print("[warn] no claude CLI and no ANTHROPIC_API_KEY — writing empty takes",
              file=sys.stderr)
        out_path.write_text(json.dumps({}, ensure_ascii=False, indent=2))
        return
    if backend in ("cli", "sdk"):
        print(f"[backend] using {'local claude CLI' if backend == 'cli' else 'Anthropic SDK'}")

    takes: dict = {}
    for it in items:
        if it.rank in cached and cached[it.rank]:
            takes[it.rank] = cached[it.rank]
            print(f"[take] {it.rank}. {it.repo:40s}  cached")
            continue
        print(f"[take] {it.rank}. {it.repo:40s}  generating ...", flush=True)
        try:
            take = generate_take(it, backend=backend)
            takes[it.rank] = take
            print(f"       → {take}")
        except Exception as e:
            print(f"       FAIL: {e}", file=sys.stderr)
            takes[it.rank] = ""

    out_path.write_text(json.dumps(takes, ensure_ascii=False, indent=2))
    print(f"[done] wrote {out_path}")


if __name__ == "__main__":
    main()
