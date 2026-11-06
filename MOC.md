# Academic Radar MOC

## 状态

- 版本：v0.1.0（2026-11-06）
- 目标：为每日 ChatGPT 学术研究雷达提供可追溯的候选论文与跨日去重状态。
- 当前阶段：离线对抗式测试 16 项通过，待安装到独立 GitHub 仓库、运行真实网络源并复核 Actions 产物。
- 当前 ChatGPT 任务：原 `Can Li研究情报周报` 已更为每日 09:30；不会把尚未部署的流水线写成已执行。

## MOC：入口

- [README](README.md)：用途、部署、数据边界
- [AGENTS](AGENTS.md)：下一轮 agent 开发约束及故障语义
- [核心脚本](radar.py)：公开 API 拉取、规范化、评分、版本去重与故障分类
- [扫描调度](.github/workflows/scan.yml)：GitHub Action 双时段执行及提交结果
- [CI](.github/workflows/ci.yml)：测试与静态编译
- [测试](tests/test_radar.py)：关键反例
- `data/latest.json`：实际最近一次运行的摘要/来源状态；`data/seen.json`：跨日状态

## 版本记录

### 2026-11-06 / v0.1.0

新增：Crossref、arXiv 两个公开源；词表预筛；DOI/arXiv ID/标题去重；版本指纹；跨次状态；来源失败报告；Actions 双时段触发；离线测试。

特意不做：自动全文抓取、未授权中文数据库采集、自动写稿、自动替换论文测度、将 API 元数据评分当作学术质量。

### 2026-11-06 / 首次实网运行审计

- GitHub 推送触发扫描成功，真实记录 Crossref 270 条、arXiv 32 条；Crossref 9/10 查询成功，1 次 HTTP 429；去重后窗口内候选 246，预筛通过 0 条。
- 不将“Action 绿色”误判为数据质量门通过。修复：移除 Crossref `sort=created`（由相关性排序找候选，创建时间仍用过滤器控制），降低请求速率，对 429/502/503 有限次重试；新增 `prefilter_pass_count` 与不含摘要的诊断样本，用真实运行核查为何被筛掉。
- 待复验：上述修复后的第二次实网扫描、来源覆盖、候选相关度与跨次去重。

## 验收 Gate

1. 本地 `python3 -m unittest discover -s tests -v` 全通过。
2. 本地语法检查通过。
3. 推到 GitHub 后，至少一次 `workflow_dispatch` 或 `push` 的真实网络执行为 `ok/degraded`，有时间戳、源计数、至少一个已核实来源；`failed` 不得当作空日报。
4. 连续两次运行不重复推送旧版本；确认版本变化可入选，标题重复且 DOI 不同不会刷屏。
5. ChatGPT 日报交叉核验官方源，中文 CSSCI 覆盖由 ChatGPT 补查，不声称 Actions 已覆盖。

## 待办

- [ ] 建立独立 GitHub 仓库并上传此项目（此环境连接没有新建仓库权限；不能挪用现有论文代码仓）。
- [ ] GitHub Actions 实网运行，复核 Crossref 和 arXiv 响应与失败语义。
- [ ] 检查首个正式日报确实读到新产物，而不是只复述上期。
- [ ] 连续 7 天观察误报率、相关性与重复率，再微调词表；不以日推荐篇数为目标。
