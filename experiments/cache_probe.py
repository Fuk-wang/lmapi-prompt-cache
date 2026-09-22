"""
LMAPI 知识网页 · 子任务 C（Prompt Caching / Prefix）实测探针
目的：用真实 API 调用验证「前缀稳定 -> 缓存命中 -> 省钱」这条链路，
      产出网页上要展示的真实数字（不是示意图）。

引用的一手文档：
  DeepSeek 上下文硬盘缓存（规则 + usage 字段）
    https://api-docs.deepseek.com/zh-cn/guides/kv_cache
  Anthropic Prompt caching（显式 cache_control / TTL / 定价倍率）
    https://docs.claude.com/en/docs/build-with-claude/prompt-caching

用法：
  python cache_probe.py <model> [stage]
  stage: all(默认) | smoke | prefix | diverge
结果写入 experiments/results-<timestamp>.json
"""
import json
import os
import re
import sys
import time
import urllib.error
import urllib.request

ENV_CANDIDATES = [
    os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), ".env"),  # 项目根 .env
    os.path.expanduser(os.path.join("~", ".hermes", ".env")),                          # 本机 Hermes
    r"C:\Users\79305\AppData\Local\hermes\.env",
]
URL = "https://api.deepseek.com/chat/completions"
OUT_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "experiments")


def load_key():
    """读取顺序：环境变量 DEEPSEEK_API_KEY → 项目 .env → 本机 Hermes .env。"""
    v = os.environ.get("DEEPSEEK_API_KEY", "").strip().strip("\"'")
    if len(v) > 8:
        return v
    for path in ENV_CANDIDATES:
        if not os.path.exists(path):
            continue
        for line in open(path, encoding="utf-8", errors="ignore"):
            m = re.match(r"\s*(?:export\s+)?DEEPSEEK_API_KEY\s*=\s*(.+)", line)
            if m:
                v = m.group(1).strip().strip("\"'")
                if len(v) > 8:
                    return v
    raise SystemExit("未找到 DEEPSEEK_API_KEY：环境变量 / 项目 .env / ~/.hermes/.env 都没有")


KEY = load_key()
MODEL = sys.argv[1] if len(sys.argv) > 1 else "deepseek-flash"
STAGE = sys.argv[2] if len(sys.argv) > 2 else "all"
RESULTS = []


def ask(messages, label, max_tokens=16):
    body = json.dumps({
        "model": MODEL,
        "messages": messages,
        "max_tokens": max_tokens,
        "temperature": 0,
        "stream": False,
    }).encode("utf-8")
    req = urllib.request.Request(
        URL, data=body,
        headers={"Content-Type": "application/json",
                 "Authorization": "Bearer " + KEY},
    )
    t0 = time.time()
    try:
        with urllib.request.urlopen(req, timeout=180) as r:
            d = json.loads(r.read().decode("utf-8"))
    except urllib.error.HTTPError as e:
        body = e.read().decode("utf-8", "ignore")[:400]
        print(f"[{label}] HTTP {e.code}: {body}")
        RESULTS.append({"label": label, "error": f"HTTP {e.code}", "body": body})
        return None
    except Exception as e:
        print(f"[{label}] {type(e).__name__}: {e}")
        RESULTS.append({"label": label, "error": f"{type(e).__name__}: {e}"})
        return None
    dt = time.time() - t0
    u = d.get("usage", {}) or {}
    row = {
        "label": label,
        "model": d.get("model"),
        "prompt_tokens": u.get("prompt_tokens"),
        "prompt_cache_hit_tokens": u.get("prompt_cache_hit_tokens"),
        "prompt_cache_miss_tokens": u.get("prompt_cache_miss_tokens"),
        "completion_tokens": u.get("completion_tokens"),
        "reasoning_tokens": (u.get("completion_tokens_details") or {}).get("reasoning_tokens"),
        "latency_s": round(dt, 2),
    }
    hit, pt = row["prompt_cache_hit_tokens"], row["prompt_tokens"]
    row["hit_ratio"] = round((hit or 0) / pt, 4) if pt else None
    print(f"[{label}] prompt={pt}  hit={hit}  miss={row['prompt_cache_miss_tokens']}"
          f"  out={row['completion_tokens']}  hit_ratio={row['hit_ratio']}  {dt:.1f}s")
    RESULTS.append(row)
    return row


# ---- 构造一段稳定的长前缀（约 1500-2500 token）----
# 用固定词表拼接，保证每次运行字节完全一致，便于复现。
UNIT = ("第三季度华东区渠道库存周转天数为{}天，较上季度环比变化{}%，主因是"
        "经销商备货节奏与终端动销不匹配，建议在下一采购周期调整返利结构。")
LONG_DOC = "【内部资料·财务与渠道分析】\n" + "\n".join(
    UNIT.format(40 + (i * 7) % 60, (i * 13) % 21 - 10) for i in range(60)
)
SYSTEM = "你是一位资深的财报分析师，回答务必简短。"


def messages_with(doc=LONG_DOC, question=None, extra_turns=None):
    """extra_turns 给定时：system + 给定轮次；否则 system + (doc + question)。"""
    msgs = [{"role": "system", "content": SYSTEM}]
    if extra_turns is not None:
        return msgs + extra_turns
    msgs.append({"role": "user", "content": (doc or "") + "\n\n" + (question or "")})
    return msgs


def stage_smoke():
    ask([{"role": "user", "content": "只回答两个字：收到"}], "smoke", max_tokens=32)


def stage_prefix():
    """例一：多轮对话，第二轮完整复用第一轮前缀单元。"""
    turns = [{"role": "user", "content": LONG_DOC + "\n\n请总结这份资料的关键信息。"}]
    ask(messages_with(None, extra_turns=turns), "1-首次请求（长前缀，预期 miss）")
    turns2 = turns + [{"role": "assistant", "content": "华东区库存周转偏慢，建议调整返利结构。"},
                      {"role": "user", "content": "那华南区呢？"}]
    ask(messages_with(None, extra_turns=turns2), "2-第二轮：前缀完全复用（预期 hit）")
    turns3 = turns2 + [{"role": "assistant", "content": "华南区相对平稳。"},
                       {"role": "user", "content": "给出一个整体建议。"}]
    ask(messages_with(None, extra_turns=turns3), "3-第三轮：前缀继续增长（预期 hit 更多）")


def stage_diverge():
    """例二：改一个字，前缀不再完整匹配 -> 先 miss，之后靠公共前缀落盘再命中。"""
    ask(messages_with(None, extra_turns=[
        {"role": "user", "content": LONG_DOC + "\n\n请分析这份资料的盈利情况。"}]), "A-长文本问答第 1 次（预期 miss）")
    ask(messages_with(None, extra_turns=[
        {"role": "user", "content": LONG_DOC + "\n\n请分析这份资料的风险情况。"}]), "B-尾问换了词（前缀同，预期本次仍 miss 或部分 hit）")
    ask(messages_with(None, extra_turns=[
        {"role": "user", "content": LONG_DOC + "\n\n请分析这份资料的现金流情况。"}]), "C-第三次：公共前缀应已落盘（预期 hit）")
    changed = LONG_DOC.replace("返利结构", "返利机制", 1)
    ask(messages_with(None, extra_turns=[
        {"role": "user", "content": changed + "\n\n请分析这份资料的现金流情况。"}]), "D-把前缀里一个词改掉（预期 hit 崩塌）")


def stage_position():
    """前缀里第一个差异出现的位置 -> 命中长度。用来验证「命中只到分歧点为止」。"""
    # 先预热缓存，保证后面几次都在「已落盘」状态下做对比
    ask(messages_with(None, extra_turns=[
        {"role": "user", "content": LONG_DOC + "\n\n请分析这份资料的现金流情况。"}]), "warmup-预热（预期 hit 高）")
    for ratio in (0.10, 0.30, 0.50, 0.75, 0.95):
        idx = int(len(LONG_DOC) * ratio)
        # 从 idx 往后找第一个数字字符，改成另一个数字，制造一个「真实存在的一字之差」
        for j in range(idx, len(LONG_DOC)):
            if LONG_DOC[j].isdigit():
                newch = "9" if LONG_DOC[j] != "9" else "8"
                mutated = LONG_DOC[:j] + newch + LONG_DOC[j + 1:]
                real_ratio = round(j / len(LONG_DOC), 3)
                break
        else:
            print("找不到可替换字符"); continue
        ask(messages_with(None, extra_turns=[
            {"role": "user", "content": mutated + "\n\n请分析这份资料的现金流情况。"}],
        ), f"差异位置≈{int(real_ratio*100)}% 处改一个数字（按字符）")["label"] = f"diff@char{int(real_ratio*100)}%"
        RESULTS[-1]["diff_char_ratio"] = real_ratio


if __name__ == "__main__":
    print(f"model={MODEL}  stage={STAGE}  key=已加载(len={len(KEY)}, 不打印)\n")
    if STAGE in ("all", "smoke"):
        stage_smoke()
    if STAGE in ("all", "prefix"):
        stage_prefix()
    if STAGE in ("all", "diverge"):
        stage_diverge()
    if STAGE in ("all", "position"):
        stage_position()
    os.makedirs(OUT_DIR, exist_ok=True)
    p = os.path.join(OUT_DIR, f"results-{time.strftime('%Y%m%d-%H%M%S')}.json")
    json.dump({"model": MODEL, "stage": STAGE, "runs": RESULTS}, open(p, "w", encoding="utf-8"),
              ensure_ascii=False, indent=2)
    print("\n结果已保存:", os.path.abspath(p))
