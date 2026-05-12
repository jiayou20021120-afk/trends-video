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


PROMPT_TEMPLATE = """你是写技术评论十年的资深开发者。分析这个 GitHub 项目，只输出严格 JSON 一行：

{{"take": "35-55字实用主义判断", "category": "ai_agent|cli_tool|web_frontend|finance|research|tool", "hook": "官方|国产|开源|爆款|论文|null"}}

字段规则：

take —— 一句话 35-55 字（最多 60）：
- 只关心明天能不能用、要多久才能用、卡在什么地方
- 不要"前景广阔""值得关注""惊艳"这种废话
- 中文，语气克制、口语化，不带感叹号，不要前缀

category —— 二选一最贴合的：
- ai_agent: LLM/AI agent/RAG/embeddings/TTS/语音/扩散等 AI 项目
- cli_tool: 终端工具/TUI/CLI/shell 增强
- web_frontend: 前端框架/UI 库/设计工具/网页
- finance: 量化/交易/金融分析
- research: 论文复现/研究代码
- tool: 通用工具/库/SDK/其他

hook —— 选一个最强卖点或 null（没明显卖点就 null）：
- 官方: anthropic/google/microsoft/aws/openai/meta/apple/bytedance 等大厂出品
- 国产: 中国公司/中国开发者主导（字节/阿里/腾讯/百度/智谱/科大讯飞/Moonshot/DeepSeek/MiniMax 等）
- 开源: 强调开源/免费/MIT/Apache 商用友好
- 爆款: 今日 stars 涨幅 ≥ 3000
- 论文: 配套论文研究代码

项目：
名称：{repo}
语言：{language}
今日新增 stars：{stars_today}
简介：{description}
中文讲述：{narration}

只输出 JSON 一行，无任何前后文字、不要 markdown 代码块标记："""


_VALID_CATEGORIES = {"ai_agent", "cli_tool", "web_frontend", "finance", "research", "tool"}
_VALID_HOOKS = {"官方", "国产", "开源", "爆款", "论文", None}


def _clean(text: str) -> str:
    text = " ".join(text.split())
    return text.strip("\"'`*“”«» ")


def _extract_json(raw: str) -> dict:
    """Parse model output: strip code fences, find first {...} object, json.loads."""
    s = raw.strip()
    # strip ```json ... ``` if model wrapped it
    if s.startswith("```"):
        s = s.split("\n", 1)[-1] if "\n" in s else s
        if s.endswith("```"):
            s = s[: -3]
        s = s.strip()
    # find outermost { ... }
    start = s.find("{")
    end = s.rfind("}")
    if start < 0 or end < 0 or end < start:
        raise ValueError(f"no JSON object in: {raw[:200]}")
    obj = json.loads(s[start : end + 1])

    take = _clean(str(obj.get("take", "")))
    category = obj.get("category") or "tool"
    if category not in _VALID_CATEGORIES:
        category = "tool"
    hook = obj.get("hook")
    if isinstance(hook, str):
        hook = hook.strip().strip("\"'`")
        if hook.lower() in ("null", "none", ""):
            hook = None
    if hook not in _VALID_HOOKS:
        hook = None
    return {"take": take, "category": category, "hook": hook}


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
    return result.stdout


def _generate_via_sdk(prompt: str) -> str:
    """Fallback for CI: use Anthropic SDK with ANTHROPIC_API_KEY."""
    import anthropic  # only imported when used
    client = anthropic.Anthropic()
    msg = client.messages.create(
        model="claude-sonnet-4-5",
        max_tokens=300,
        messages=[{"role": "user", "content": prompt}],
    )
    parts = [b.text for b in msg.content if getattr(b, "type", None) == "text"]
    return "".join(parts)


def _pick_backend() -> str:
    """Return 'cli' | 'sdk' | 'none' depending on what's available."""
    if shutil.which("claude"):
        return "cli"
    if os.environ.get("ANTHROPIC_API_KEY"):
        return "sdk"
    return "none"


def generate_take(item: TrendItem, backend: str, retries: int = 2,
                  timeout: int = 90) -> dict:
    """Return {'take', 'category', 'hook'} for one project. backend ∈ {'cli','sdk'}."""
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
                raw = _generate_via_claude_cli(prompt, timeout=timeout)
            else:
                raw = _generate_via_sdk(prompt)
            obj = _extract_json(raw)
            if 12 <= len(obj["take"]) <= 160:
                return obj
            last_err = f"take length out of range: {len(obj['take'])} chars"
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

    cached: dict = {}
    if out_path.exists() and not args.force:
        try:
            raw_cache = json.loads(out_path.read_text())
            # Accept legacy string-only entries; promote to {'take': ...} so we still
            # regenerate to get category/hook fields.
            for k, v in raw_cache.items():
                if isinstance(v, dict) and v.get("take") and "category" in v:
                    cached[int(k)] = v
        except Exception:
            cached = {}

    pending = [it for it in items if not (it.rank in cached and cached[it.rank].get("take"))]
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
        if it.rank in cached and cached[it.rank].get("take"):
            takes[it.rank] = cached[it.rank]
            c = cached[it.rank]
            print(f"[take] {it.rank}. {it.repo:40s}  cached  [{c['category']}]"
                  + (f" hook={c['hook']}" if c.get("hook") else ""))
            continue
        print(f"[take] {it.rank}. {it.repo:40s}  generating ...", flush=True)
        try:
            obj = generate_take(it, backend=backend)
            takes[it.rank] = obj
            hook_str = f" hook={obj['hook']}" if obj.get("hook") else ""
            print(f"       [{obj['category']}]{hook_str}")
            print(f"       → {obj['take']}")
        except Exception as e:
            print(f"       FAIL: {e}", file=sys.stderr)
            takes[it.rank] = {"take": "", "category": "tool", "hook": None}

    out_path.write_text(json.dumps(takes, ensure_ascii=False, indent=2))
    print(f"[done] wrote {out_path}")


if __name__ == "__main__":
    main()
