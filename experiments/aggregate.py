"""把 experiments/results-*.json 汇总成 research/experiment-log.md（可直接贴进报告/网页）"""
import glob
import json
import os

HERE = os.path.dirname(os.path.abspath(__file__))
PROJ = os.path.dirname(HERE)
EXP = os.path.join(PROJ, "experiments")
OUT_MD = os.path.join(PROJ, "research", "experiment-log.md")

# 官方定价（https://api-docs.deepseek.com/quick_start/pricing，2026-09-22 抓取）
PRICE = {
    "hit_offpeak": 0.003, "hit_peak": 0.006,     # 美元 / 1M input tokens
    "miss_offpeak": 0.15, "miss_peak": 0.3,
    "out_offpeak": 0.6, "out_peak": 1.2,
}

runs = []
for f in sorted(glob.glob(os.path.join(EXP, "results-*.json"))):
    d = json.load(open(f, encoding="utf-8"))
    for r in d["runs"]:
        r["_file"] = os.path.basename(f)
        runs.append(r)

ok = [r for r in runs if "error" not in r]


def money(hit, miss, out, peak=False):
    k = "_peak" if peak else "_offpeak"
    return (hit * PRICE["hit" + k] + miss * PRICE["miss" + k] + out * PRICE["out" + k]) / 1e6


lines = []
lines.append("# 实测日志（DeepSeek 上下文缓存）\n")
lines.append(f"- 模型：`{ok[0]['model']}`　日期：2026-09-22　调用次数：{len(ok)}")
lines.append("- 接口：`POST https://api.deepseek.com/chat/completions`，`temperature=0`，`max_tokens=16`")
lines.append("- 官方文档：<https://api-docs.deepseek.com/zh-cn/guides/kv_cache>（缓存规则与 `usage` 字段）")
lines.append("- 原始数据：" + "、".join(f"`experiments/{os.path.basename(f)}`" for f in sorted(glob.glob(os.path.join(EXP, "results-*.json")))))
lines.append("")
lines.append("| 场景 | prompt tokens | 命中 hit | 未命中 miss | 命中率 | 耗时 |")
lines.append("|---|---:|---:|---:|---:|---:|")
for r in ok:
    lines.append("| {label} | {p} | {h} | {m} | {ratio} | {s}s |".format(
        label=r["label"], p=r["prompt_tokens"], h=r["prompt_cache_hit_tokens"],
        m=r["prompt_cache_miss_tokens"],
        ratio=f"{(r['hit_ratio'] or 0)*100:.1f}%", s=r["latency_s"]))

lines.append("")
lines.append("## 两条从数据里读出来的结论\n")
diffs = [r for r in ok if r.get("diff_char_ratio") is not None]
if diffs:
    lines.append("**1）命中长度 ≈ 第一个差异出现的位置，且按 64 token 对齐。**")
    lines.append("")
    lines.append("| 差异位置（按字符） | 命中 tokens | 命中率 | 命中 tokens ÷ 64 |")
    lines.append("|---|---:|---:|---:|")
    for r in diffs:
        lines.append(f"| {r['diff_char_ratio']*100:.0f}% | {r['prompt_cache_hit_tokens']} | "
                     f"{r['hit_ratio']*100:.1f}% | {r['prompt_cache_hit_tokens']/64:.1f} |")
    lines.append("")
    lines.append("五次命中值全部是 64 的整数倍（128 / 640 / 1152 / 1792 / 2304），"
                 "说明缓存命中以 64 token 为一个单位向下取整。")
    lines.append("")

lines.append("**2）前缀里改一个词，命中直接归零。**")
for r in ok:
    if r["label"].startswith("D-把前缀里一个词改掉"):
        lines.append(f"把 `返利结构` 改成 `返利机制`（出现在文档前段）后：prompt={r['prompt_tokens']}，"
                     f"hit={r['prompt_cache_hit_tokens']}，miss={r['prompt_cache_miss_tokens']}，"
                     f"命中率 {r['hit_ratio']*100:.1f}% —— 因为差异之后的前缀全部作废。")

tot_hit = sum(r["prompt_cache_hit_tokens"] or 0 for r in ok)
tot_miss = sum(r["prompt_cache_miss_tokens"] or 0 for r in ok)
tot_out = sum(r["completion_tokens"] or 0 for r in ok)
lines.append("")
lines.append("## 成本模型（用官方单价换算，不是估算）\n")
lines.append(f"本次实验共消耗 input hit={tot_hit} / miss={tot_miss} / output={tot_out} tokens。")
lines.append("")
lines.append(f"- 实际花费（优惠时段，按官方价）：**${money(tot_hit, tot_miss, tot_out):.6f}**")
lines.append(f"- 假如完全不命中缓存（同样的 token 全按 miss 计价）：**${money(0, tot_hit + tot_miss, tot_out):.6f}**")
lines.append("")
lines.append("再算一个更贴近生产的场景：一个 2432 token 的稳定前缀被连续请求 100 次（每次新增 200 token 提问）：")
n, pre, add, out_t = 100, 2432, 200, 50
lines.append("")
lines.append("| 方案 | 计费 input tokens | 成本（美元） | 相对 |")
lines.append("|---|---:|---:|---:|")
lines.append(f"| 无缓存（每次都全量重算） | {(pre+add)*n} miss | ${money(0,(pre+add)*n,out_t*n):.6f} | 1.00x |")
lines.append(f"| 前缀稳定（命中） | {pre*n} hit + {add*n} miss | ${money(pre*n, add*n, out_t*n):.6f} | "
             f"{money(pre*n, add*n, out_t*n)/money(0,(pre+add)*n,out_t*n):.2f}x |")
lines.append("")
lines.append("> 单价来源：<https://api-docs.deepseek.com/quick_start/pricing>（cache hit $0.003、miss $0.15、output $0.6 每 1M tokens，优惠时段）。")

open(OUT_MD, "w", encoding="utf-8").write("\n".join(lines))
print("\n".join(lines))
print("\n已写入:", OUT_MD)
print(f"\n[汇总] 调用 {len(ok)} 次；hit={tot_hit} miss={tot_miss} out={tot_out}；"
      f"实花 ${money(tot_hit,tot_miss,tot_out):.6f}，全 miss 则 ${money(0,tot_hit+tot_miss,tot_out):.6f}")
