# LMAPI 知识网页 · Prompt Caching / Prefix

「前缀稳定为什么能省钱」——一个单文件、离线可开、可交互的知识网页。
网页上**所有数字都来自真实 API 调用的实测**，原始数据与探针脚本都在本仓库里，可照着复现。

- 子任务：C（Prompt Caching / Prefix）
- 课程：大模型与自然语言处理 · 第 2 次课实验（20260922）
- 线上地址：见仓库 Settings → Pages，或 <https://fuk-wang.github.io/lmapi-prompt-cache/>
- 实测模型：`deepseek-flash`　实测日期：2026-09-22

## 这个网页在讲什么

缓存命中按**前缀**匹配：从第一个 token 逐个比对，一直比到第一个不同的位置——那个位置之前的
token 全部命中，之后的全部要重算。我们用自己的 API key 做了 14 次真实调用，得到三条结论：

| 结论 | 实测证据 |
|---|---|
| 首次请求全 miss，第二轮复用前缀直接命中 90.5% | `hit=0 → 2432`（prompt 2665 → 2687） |
| 前缀中段改一个词，命中率从 91.3% 掉到 0% | `返利结构`→`返利机制`，`hit=0 / miss=2665` |
| 命中长度 ≈ 第一个差异出现的位置，且全是 64 的整数倍 | 11%→128、31%→640、51%→1152、76%→1792、96%→2304 |

成本侧：本次实验 14 次调用实花 `$0.002307`；若完全命中不了缓存要 `$0.005355`。
场景推算（2432 token 前缀 × 100 次请求）：无缓存 `$0.042480` vs 前缀稳定 `$0.006730`（0.16x）。

## 文件结构

```
index.html          ← 交付物：单文件知识网页（CSS/JS 全内联，不依赖 CDN、离线可开）
prompt-log.md       ← 交付物：至少 2 轮「规格 → 失败 → 迭代」的真实记录
AGENTS.md           ← 交付物：给 Agent 的项目规格（指令区 / 数据区分离）
experiments/
  cache_probe.py    ← 实测探针：真实调用 DeepSeek，打印 usage 里的命中字段
  aggregate.py      ← 把原始 JSON 汇总成 research/experiment-log.md（含官方单价换算）
  results-*.json    ← 原始数据（网页上每个数字都能在这里找到出处）
research/
  deepseek-kv_cache-zh.txt / -en.txt   ← 一手文档存档（抓取于 2026-09-22）
  experiment-log.md                    ← 实测日志 + 成本模型
```

## 自己复现一遍

```bash
# 1. 配 key（本仓库不保存任何密钥）
cp .env.example .env        # 填入自己的 DeepSeek API key

# 2. 跑实测（14 次调用，花费约 $0.002）
python experiments/cache_probe.py deepseek-flash all
python experiments/cache_probe.py deepseek-flash position

# 3. 汇总成报告
python experiments/aggregate.py     # → research/experiment-log.md

# 4. 看网页（离线也行）
双击 index.html，或： python -m http.server 8000
```

缓存是否命中取决于服务端当时的存活状态，绝对值会有出入；「改一个词命中归零」和
「命中值都是 64 的整数倍」这两条规律是稳定的。

探针脚本读取 key 的顺序：环境变量 `DEEPSEEK_API_KEY` → 本目录 `.env` → 本机 Hermes 的 `~/.hermes/.env`。
**不要把 `.env` 提交进仓库**（已在 `.gitignore` 里）。

## 一手资料

- DeepSeek 上下文硬盘缓存：<https://api-docs.deepseek.com/zh-cn/guides/kv_cache>
- DeepSeek 模型与定价：<https://api-docs.deepseek.com/quick_start/pricing>
- Anthropic Prompt caching：<https://docs.claude.com/en/docs/build-with-claude/prompt-caching>
- 反刍用的源码（本机 hermes-agent 安装目录）：`agent/prompt_caching.py`、`agent/prompt_cache_boundary.py`、
  `agent/skill_commands.py`、仓库根 `AGENTS.md`
