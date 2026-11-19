# 同学 Fork → 自己的 GitHub 雷达 → ChatGPT 每日研究简报

本仓库的 GitHub Actions 负责**公开论文元数据发现与去重**；ChatGPT 在**每个同学自己的账号**中建立周期任务，读取同学自己的 Fork，核验来源，并生成研究日报。**Fork 不会复制作者的 ChatGPT 定时任务、GitHub 连接授权或个人研究画像。**

## 10 分钟部署（适用于经济学/经管论文研究）

1. 打开 [lican1213/academic-research-radar](https://github.com/lican1213/academic-research-radar)，点击右上角 **Fork → Create fork**。确认地址变成 `https://github.com/你的GitHub账号/academic-research-radar`。
2. 在自己的 Fork 根目录新建 `radar_profile.json`：复制 [radar_profile.example.json](../radar_profile.example.json) 的内容，改成**自己的研究方向**。至少调整 `name`、`crossref_queries`、`keywords`；不需要 arXiv 可设 `arxiv_queries: []`，`min_keyword_hits` 一般保留2。关键词是元数据粗筛，并不是论文质量分数。**没有个人配置时沿用作者默认 P0—P4 主题，不适合直接当成你的个人雷达。**
3. GitHub Fork → **Actions**。允许工作流运行（GitHub 对公开 Fork 的定时 workflow 默认禁用）；找到 **Academic Research Radar Scan**，在必要时启用这个工作流，点击 **Run workflow** 手工运行一次。不要首先启用 PDF 示例工作流——它们只是已验证过的按需试验，并不负责每日论文发现。
4. 打开刚运行的 Actions 日志，确认数据生成和推送成功；再在 Fork 根目录检查 `data/fork_initialized.json` 内的 `repository` 是你自己的仓库，`data/latest.json` 的 `generated_at` 是**Fork 本次**运行生成、`research_profile.name` 与你的选题一致。首次扫描会清空继承自上游的 `seen.json` / `chinese_seen.json`，再建立你自己的已见基线；**不要把旧版上游 `latest.json` 视为你的运行结果**。
5. 如果 GitHub Actions 执行成功却无法提交 `data/latest.json`，进入 **Settings → Actions → General → Workflow permissions** 检查 `GITHUB_TOKEN` 是否获准写入仓库内容及分支保护规则；不要创建额外 PAT。正常工作流已声明 `contents: write`。
6. 在自己的 ChatGPT 中连接 **GitHub**（如果账号/工作区支持；设置的 Apps/Plugins 中授权**自己的 Fork**）。手动测试一句：`请读取 YOUR_ACCOUNT/academic-research-radar/main 的 data/latest.json，告诉我 generated_at、status、research_profile.name 和这次新增了几篇。` **必须确保读的是你的 Fork 而不是 lican1213 的上游仓库。**
7. 把 [ChatGPT 每日研究任务提示词](CHATGPT_DAILY_TASK_TEMPLATE.md) 复制到自己 ChatGPT 的 Scheduled/定时任务设置，填好 GitHub 用户名、论文方向和报告时间。可选择北京时间每日09:30（仓库扫描 UTC 22:17/10:17，对应北京时间06:17/18:17）。同学的 ChatGPT 定时任务需要**自己创建和授权**，Fork 不会自动帮别人创建提醒。
8. 进行一次手动验收：打开自己的 `data/latest.json`，检查是否有本人选题的候选或明确的无新增/源失败；然后让 ChatGPT 根据今天的实测数据生成一版日报。**即使候选为零，也要看到最新扫描时间及逐源健康状态。**

## 两种独立层次

- **GitHub 层：** 公开来源采集、目录状态、跨次去重、轻量关键词预筛和 `data/latest.json` 发布。默认9刊经济学期刊仍固定为原项目的九刊；自定义配置只切换 Crossref/arXiv 查询与其研究主题过滤，**不会自动重配中文九刊**。
- **ChatGPT 层：** 使用你自己的研究问题和当天可信来源来判断文献是否值得读、哪些结论可移植、识别/测度与自己的论文是否冲突。要区分题录/摘要、PDF取得、原文页码/回归表逐项核验。**不应机械转发仓库原来的 P0/P1A 排序**。

## Fork/定时任务的常见故障

| 现象 | 检查 |
|---|---|
| Fork 后一直没有定时扫描 | 在 Fork 的 Actions 中开启对应的 schedule；GitHub 默认禁用公开 Fork 的 scheduled workflows。GitHub 定时任务也可能延迟，长期无活动的公开仓库可能再次停用。 |
| `latest.json` 很旧、项目仍是作者的 P0/P1A | 确认已填写并提交 `radar_profile.json`，手动运行 **自己的 Fork**，检查 `data/fork_initialized.json` 和 `research_profile.name` |
| Action 日志里 Git Push 失败 | 检查 Fork 的 Actions workflow permissions 和分支保护；不需要上传密码或 PAT |
| ChatGPT 读不到仓库 | 授权自己的 GitHub 账号/Fork，并在定时任务中使用完整 `OWNER/REPO`；账号或工作区可能不提供对应连接功能，可暂用可访问的公开 JSON 及实时网络检索 |
| `degraded`、中文9刊有缺口 | 这表示部分来源失效；不是代码必然故障或没有新文章。日报应独立补检权威目录 |
| 想下载全部期刊 PDF | PDF 候选适配仅针对已经校验的公开出版方 URL，按需运行；不要把元数据脚本当成所有期刊全文爬虫 |

**公开仓库隐私：** Fork 通常也公开可见。不要在 `radar_profile.json`、Issues 或仓库中保存未发表稿件、私有数据、密码、API Key、导师材料或敏感个人信息。需要保密研究画像时不要把私有细节提交到公开 Fork，可只在自己 ChatGPT 对话里写具体论文设定。

**使用授权：** 当前上游仓库尚未声明明确的开源许可证；GitHub 平台内 Fork 与一般性的代码再分发授权是不同问题。请勿在未经确认时宣称本项目采用 MIT/GPL 许可。后续作者可按需要独立决定许可证。

参考：[GitHub Fork 工作流启用说明](https://docs.github.com/en/actions/how-tos/manage-workflow-runs/disable-and-enable-workflows)，[OpenAI Scheduled tasks 官方说明](https://help.openai.com/en/articles/10291617-scheduled-tasks-in-chatgpt)。
