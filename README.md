# Academic Research Radar

给经济学论文使用的**文献候选发现器**。GitHub Actions 定时拉取公开元数据，保留跨次去重状态；ChatGPT 每日任务再核验官方页面、读摘要或正文，并判断是否值得进入现有论文。

这不是自动写文献综述的工具，也不替代中文期刊人工检索。它只输出**可核验的候选与来源健康状态**。

## 工作流程

```
Crossref + arXiv (公开元数据)
    -> 时间窗筛选 -> 主题打分 -> DOI/arXiv/标题去重
    -> data/latest.json / data/latest.md + data/seen.json
    -> ChatGPT 每日核对原文并筛出高价值增量
```

### 调度与时区

- Actions：每日 `22:17 UTC`、`10:17 UTC`，即北京时间次日 06:17、当日 18:17；另可手动运行。
- ChatGPT：每日北京时间 09:30 发送研究雷达，因此晨间日报使用最近一次 Actions 扫描及其后实时搜索的最新信息。
- GitHub Actions 的 `schedule` 可能延迟甚至遗漏；以记录里的实际 `generated_at` 和 `source_status` 判断新鲜度，不能把预定时间说成完成时间。

## 源和边界

| 来源 | 自动化范围 | 边界 |
|---|---|---|
| Crossref REST | 带关键词的论文与工作论文元数据，包含中文词检索 | 入库/更新时间不等于发表日；摘要不一定存在 |
| arXiv API | 创新、专利文本、AI/供应链相关新稿、版本更新 | 预印本；需要区别 v1 与 v2，不等于正式发表 |
| 中文 CSSCI、NBER、CEPR、RePEc、WIPO、USPTO、EPO | 每日 ChatGPT 根据实际检索结果人工核验 | 不虚构抓取覆盖；需要把未检索或失败源列入日报 |

默认关键词与打分只做**候选预筛**，不是论文质量评分。实际推荐需经 ChatGPT 核验：期刊官网或作者原文、作者、DOI、日期、文章内容、与当前研究设计的可迁移性。

研究主题优先级：耐心资本与国际专利布局（P0）、AI 与 OFDI/跨境供应链韧性（P1）、专利文本与突破式创新（P2）、机构投资者与创新（P3）、AI 与收入分配/生产率（P4）。该配置可在 `radar.py` 的 `QUERIES` 和 `PROJECT_TERMS` 中维护。

## 本地运行

要求 Python 3.11+，无第三方运行依赖。

```bash
python3 -m unittest discover -s tests -v
python3 radar.py --out data --lookback-days 7
```

首次运行默认回溯 7 天，已有扫描状态时默认回溯 3 天，避免因为 GitHub 定时延迟漏掉跨日更新。参数 `--lookback-days` 可用于补扫，最长 30 天。每次运行最多保留 30 个候选；同一 DOI、arXiv ID 或标准化标题合并，并对 arXiv 版本、标题与首次 DOI 出现进行变更识别。Crossref 摘要元数据小修不会触发“新论文”。`data/seen.json` 保存最近 180 天的索引以避免跨次重复推送，输出不转载论文摘要。

失败语义：单一来源不可用标记 `degraded`，全部失败标记 `failed` 并使 Action 失败；失败仍写 `latest.json` 供次日诊断。**没有新增不等于抓取失败；抓取失败也不等于没有新论文。**

## 与 ChatGPT 定时任务配合

每天先读 `data/latest.json` 的 `generated_at`、`status`、`source_status`、`new_candidates`；只把其中有 DOI/arXiv/稳定链接的元数据当作候选。随后通过期刊官网、工作论文官网、中文期刊官方页面和其他一手来源补齐覆盖。

推荐决策的门槛由 ChatGPT 日报执行：项目匹配度和可执行性优先，0—3 篇重点，0—2 篇观察，不凑数。不要把本工具的 `prefilter_score` 当成论文质量分。

## 安装到新 GitHub 仓库

建立一个空的、默认分支为 `main` 的 GitHub 仓库（私有仓库也可）。把本项目**根目录里的内容**提交到新仓库根目录，包括隐藏的 `.github` 文件夹。随后打开 Actions → Academic Research Radar Scan → Run workflow，核验它是否真正拉到了 Crossref/arXiv 的公开元数据；日志中的 `ok/degraded`、`data/latest.json` 的实际时间戳才算运行证据。

工作流使用仓库自带的 `GITHUB_TOKEN` 提交去重状态，不需要自行创建密钥。如果组织策略禁止工作流写内容，需调整仓库的 Actions 写入权限；不能把“运行成功但没有保存状态”当作通过。

## 项目维护

- 变更与问题记录：[`MOC.md`](MOC.md)
- 工作流：`.github/workflows/scan.yml`；测试：`.github/workflows/ci.yml`
- 核心逻辑：`radar.py`；纯函数测试：`tests/test_radar.py`
- 不存储受版权保护的论文全文、个人研究原始数据或私有稿件。
