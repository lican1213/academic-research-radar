# Academic Radar MOC

## 状态

- 版本：v0.2.0（2026-11-09；中文七刊监控扩展）
- 目标：为每日 ChatGPT 学术研究雷达提供可追溯的候选论文与跨日去重状态。
- 当前阶段：**已部署并进入运行观察期**。GitHub CI 和真实数据扫描均已通过；Crossref/arXiv、来源状态、候选清单和去重账本已实网落盘；v0.2.0 新增中文七刊逐刊目录状态监控。离线对抗式测试 34 项通过；2026-11-09 已有真实 GitHub Actions 源扫描、目录解析与数据文件落盘证据。中文七刊属于**3类状态、2刊文章级、5刊仅目录级**的有限覆盖，不可误报为完整覆盖。跨自然日的中文目录去重仍需继续观察。
- ChatGPT 调度：原 `Can Li研究情报周报` 已更新为 `Can Li学术研究每日雷达`（任务 ID `6a62e1a21e1c8191be0fdd3893473bd2`），每日北京时间 09:30，提示词已绑定本仓库 `data/latest.json`，中文七刊的目录级自动监测写入 latest，但文章级真实性与未覆盖源仍需要独立核验。

## MOC：入口

- [README](README.md)：用途、部署、数据边界
- [AGENTS](AGENTS.md)：下一轮 agent 开发约束及故障语义
- [核心脚本](radar.py)：公开 API 拉取、规范化、评分、版本去重与故障分类
- [中文七刊监控](chinese_journals.py)：官方/权威期刊目录、刊期变化、逐刊健康状态、首次观察与独立去重
- [扫描调度](.github/workflows/scan.yml)：GitHub Action 双时段执行及提交结果
- [CI](.github/workflows/ci.yml)：测试与静态编译
- [测试](tests/test_radar.py)：关键反例
- `data/latest.json`：实际最近一次运行的摘要/来源状态；`data/seen.json`：英文跨日状态；`data/chinese_seen.json`：中文目录已见账本

## 版本记录

### 2026-11-06 / v0.1.0

新增：Crossref、arXiv 两个公开源；词表预筛；DOI/arXiv ID/标题去重；版本指纹；跨次状态；来源失败报告；Actions 双时段触发；离线测试。

特意不做：自动全文抓取、未授权中文数据库采集、自动写稿、自动替换论文测度、将 API 元数据评分当作学术质量。

### 2026-11-06 / 首次实网运行审计（已修复）

- GitHub 推送触发扫描成功，真实记录 Crossref 270 条、arXiv 32 条；Crossref 9/10 查询成功，1 次 HTTP 429；去重后窗口内候选 246，预筛通过 0 条。
- 不将“Action 绿色”误判为数据质量门通过。修复：移除 Crossref `sort=created`（由相关性排序找候选，创建时间仍用过滤器控制），降低请求速率，对 429/502/503 有限次重试；新增 `prefilter_pass_count` 与不含摘要的诊断样本，用真实运行核查为何被筛掉。
- 第二次 Actions 实网扫描确认 Crossref 10/10、arXiv 4/4 查询均成功，283 个日期窗候选、56 个通过宽词法预筛，产生 30 条新候选，状态记录已落盘。
- 对抗性抽样发现，30 条有 29 条为 P1，含肯尼亚 FDI 和本地建筑业供应链等弱相关主题。这说明单关键词词法命中不足以代表学术价值，不能将这 30 条直接当成日报推荐。

### 2026-11-06 / v0.1.1 主题关联修复（已通过第三次实网复验）

- 对候选增加两轴主题门：例如 P1 要求地缘政治/AI 与跨国布局或供应链形成关联，普通 FDI 与本地建筑供应链不自动进入；P0 优先。
- 为 P0/P1/P2/P3/P4 设置候选上限 12/7/7/3/3，防止单一宽领域挤占今日研究雷达。仍由 ChatGPT 复验正式论文质量与可迁移性。
- 第三次 Actions：Crossref 10/10、arXiv 4/4 成功，294 条时间窗候选中仅 9 条通过主题门；但仅有 2 条新的 P1 候选，诊断里却出现 3 条 P0 耐心资本候选未推送。
- 根因：先前状态层把超过 30 条上限而未进入清单的论文也视作已报告，造成 P0 遗漏。修复为 `emitted` 明确记录是否进入 `new_candidates`；老状态无该字段时允许重新纳入。未送达的新版本不会提前更新已报告版本指纹。
- 新增溢出与历史状态恢复测试，共 22 项离线测试。下一次 Action 检查 P0 是否被恢复、跨次重复能否压住。

### 2026-11-06 / v0.1.2 第四次实网 Gate

- CI [42189109390](https://github.com/lican1213/academic-research-radar/actions/runs/42189109390) 通过；扫描 [42189109302](https://github.com/lican1213/academic-research-radar/actions/runs/42189109302) 成功。
- 实际输出 `status=ok`：Crossref 10/10 查询（300 条原始记录）、arXiv 4/4 查询（31 条原始记录），主题门通过 9 条；`new_candidates` 9 条，其中 P0 耐心资本 3 条、P1 跨境/供应链 6 条，原先遗漏的 P0 已恢复。
- `data/seen.json` 已写入 `emitted` 状态，按“确实进入候选清单”区分检索与交付。候选仍需每日 ChatGPT 检查期刊质量、全文证据与能否进入稿件，不把词法分数当质量分。
- 真实连续两个自然日的去重运行和第一份 09:30 日报尚未发生，继续纳入运行观察；无阻断已部署的故障。

### 2026-11-09 / v0.2.0 中文七刊覆盖缺陷修复与对抗式审计

**问题复现：** 每日 Action 实际只查询 Crossref/arXiv；`status=ok` 只说明这两类源可用，不说明《经济研究》《中国工业经济》《管理世界》《世界经济》《数量经济技术经济研究》《财经研究》《金融研究》已查。日报错误地用“中文CSSCI定向检索”替代七刊逐刊证据，出现漏报与覆盖不明。中文期刊检索需要区分“官网目录出现了文章”“期次可见但文章未取到”“源失效”“旧页面”和“真的没有新增”。

**实施：**
- 新增 `chinese_journals.py`，监控七个公开期刊目录：优先公开出版方目录（世界经济、财经研究、金融研究），其余使用国家哲社文献中心的权威目录索引，输出 `source_kind` 以免把目录平台冒充刊物官网。
- 只将可识别文章详情链接列入 `chinese_new_candidates`；官网或权威目录仅有刊期而无可验证链接标为 `catalog_only`。无法识别期次标 `unverified`，网络异常 `failed`，期次倒退 `stale_index`。逐刊状态一一写入 `data/latest.json` 与 `data/latest.md`。
- 中文目录首次采集建立基线；后续新的目录文章以 `first_observed_at` 记录**网站首次发现**，`published_at=null`，必须人工复核发表日期。独立账本 `data/chinese_seen.json`；超时/目录倒退不覆盖已有成功状态。
- 保持原Crossref/arXiv去重与主题门逻辑不变；中文监控降级会使整份最新报告标 `degraded`，但不将目录缺失伪装为“无新文献”；扫描工作流持久化新增账本。
- README、AGENTS和CI补充覆盖/故障语义及交付约束。无第三方依赖、不抓取付费正文、不假定聚合页等于出版方首页。

**独立反例测试：** 初始期次不能批量冒充新发表；次日同目录不重复；新期次文章只报一次；期次倒退不污染账本；网站超时保留已见状态；未核验的文章链接不能生成候选；网页首次发现日期绝不能冒充文章发表日期；中文源降级时英文源正常也不得宣称全覆盖。`2026-11-09` GitHub CI [42612353826](https://github.com/lican1213/academic-research-radar/actions/runs/42612353826) 显示编译成功、29项测试通过。

**审计 Gate：**
- [x] 29项离线测试与编译门通过
- [x] 七刊独立状态写入报告且保留原来源去重语义（fixture核验）
- [ ] 合并main后的真实 Action 扫描、产物回读及七刊逐站证据核验（进行中）
- [ ] 四个国家哲社目录是否提供足够可靠的文章详情链接；目前设计为目录级兜底，不得标为“文章全文已覆盖”
- [ ] 观察7天刊期变化与去重/漏报表现

**遗留边界：** 自动目录探测不能覆盖中文网络首发和搜索引擎未收录文章；当期目录没有显式发布日期时，不得从扫描时间推断正式刊出日。日常ChatGPT雷达仍须独立检索七刊官方/权威目录及文章页。

### 2026-11-09 / v0.2.1 实网复验与二轮修复（本轮结束状态）

**实网发现并已修的缺陷：**
1. **《财经研究》误报目录封面：** 第一版把 `/Article/2026/09/CN` 误当文章，`ok` 实际只得到一条“第09期”。修为仅接受 `/Article/Details/{id}/CN`；实网恢复 **11条真实文章详情链接**，并添加封面误识别测试。
2. **标题带上标导致摘要替代标题：** 第一版依赖完整文本查找，遇到标题含 `<sup>` 时找不到位置，后续抓到了指向同一URL的摘要文字。修复为基于HTML节点文本片段位置提取，并以文章详情URL去重；新增实物样式的反例测试。既有错误历史键不会作为新发表证据。
3. **期次格式 09 误判：** `2026年第09期` 未被旧正则识别，导致新文章漏报；支持前导零并回归测试。
4. **《金融研究》TLS证书错配：** GitHub runner对 `www.jryj.org.cn` 报 `CERTIFICATE_VERIFY_FAILED/Hostname mismatch`，**没有关闭SSL验证**；失败单独保留，并降级使用国家哲社文献中心期次。兜底目前仅至 **2026-07期**，属于**滞后目录**，必须人工补检权威期刊库更近期2026年第10期，不能把7月当最新。
5. **《数量经济技术经济研究》索引入口：** 修复国哲目录 `.cn` 无法识别问题，`.org` 可定位 **2026-10期**。另加入该刊编辑部官方 `https://www.jqte.net/sljjjsjjyj/ch/index.aspx` 优先采集，针对其 `2026,(10):` 格式和 `view_abstract.aspx?file_no=` 文章链接编写测试；真实GitHub runner当前 **HTTP 502**，已保留 `publisher_unavailable` 并回落到目录源，不能宣称官方文章已自动采完。
6. **日期冲突：** 《财经研究》2026(9)目录标记 `在线出版日期2026-11-03`，部分单篇详情另列 `出版日期2026-09-03`。目录上的日期统一放 `toc_online_at`，候选 `published_at=null`、`date_verified=false`，待单篇官方页面独立核验，不凭目录或首次扫描推断首发。
7. **Action写回竞态：** 多次源代码提交与正在运行的扫描并发，导致 `git push` non-fast-forward 被拒，虽采集成功但Action失败。加入有限三次 `git pull --rebase origin main` 重试，仍冲突则可见地失败而非静默丢数据。

**本轮真实结果及审计证据：**
- [PR #1 合并](https://github.com/lican1213/academic-research-radar/pull/1) 将七刊层接入主分支，后续问题依测试和实网逐项追加修复。
- [最新 CI #42614685707](https://github.com/lican1213/academic-research-radar/actions/runs/42614685707)：静态编译与 **34项测试全部通过**。覆盖期次前导零、HTML上标/摘要伪标题、目录封面伪文章、真实文章链接、新候选去重、日期口径、官方主源TLS/502失败与兜底、目录倒退、英文成功但中文降级、写回状态。
- [实网 Scan #42614638654](https://github.com/lican1213/academic-research-radar/actions/runs/42614638654)：`completed/success`，数据文件提交并回读。`generated_at=2026-11-09T12:09:28Z`，总状态**`degraded`**；Crossref 10/10成功（297原始记录）、arXiv 4/4成功（16条）。
- 中文七刊逐刊：`世界经济=ok`（2026-10，6条文章链接）、`财经研究=ok`（2026-09，11条文章链接）；`经济研究=catalog_only`（2026-09）、`中国工业经济=catalog_only`（2026-08）、`管理世界=catalog_only`（2026-10）、`数量经济技术经济研究=catalog_only`（2026-10，官方502）、`金融研究=catalog_only`（2026-07，官网TLS错配）。所以中文源整体 `degraded` 是**正确结果**，而非全源失败或没有新增论文。
- 第一次SUFE修复后的产物已成功捕捉《政府赋能企业“出海”：国家海外知识产权纠纷应对指导中心与企业对外直接投资》（DOI `10.16538/j.cnki.jfe.20260611.202`）；经日期纠正后不将2026-11-03目录标记误称单篇实际首次出版日。
- MOC、README、AGENTS及扫描产物都保留源状态与修复依据，且没有动用户论文、专利原始数据或每日任务设置。

**验收裁决：**
- [x] 主仓库合并，CI编译与34项对抗测试通过
- [x] Action实网执行成功，扫描产物与去重账本写回main
- [x] 七刊逐刊监控与异常状态可审计，正文提取2刊准确性经实网抽样核验
- [x] 目录在线日期与单篇发表日期分离；SSL失败未绕过验证
- [ ] 其余5刊尚缺可用的文章级自动接口：每日ChatGPT必须逐刊独立网络检索并标明遗漏可能性，尤其金融研究官网/目录延迟问题
- [ ] 连续7天对跨日增量、重复、漏报进行观测，未经实测不打勾

**后续维护优先级：** P0 自动覆盖不足是已知观察限制，不要用更多关键词、无来源的文章标题填补。若能取得正式公开文章页再为各刊新增专用适配器并写离线fixture；禁止基于错误的期次日期倒推文章首发或通过不安全TLS连接规避源问题。

## 验收 Gate

1. [x] GitHub CI `python3 -m unittest discover -s tests -v` 全通过（34 项），以 [42614685707](https://github.com/lican1213/academic-research-radar/actions/runs/42614685707) 为准。
2. [x] 本地语法检查通过。
3. [x] GitHub 真实网络执行完成并成功落盘；中文源有5项`catalog_only`，整体正确标记为`degraded`；不得写`ok`。
4. [ ] 同次来源去重与修订测试通过；跨自然日重复率待首轮观察。
5. [ ] ChatGPT 后续每日日报对五刊目录级缺口实际逐刊补检，待独立观察。

## 待办

- [x] 建立独立 GitHub 仓库并上传此项目。
- [x] GitHub Actions 实网运行，复核 Crossref 和 arXiv 响应与失败语义（含 429 与重试后的恢复）。
- [ ] 每日报同时读取七刊的逐刊状态，并对 catalog_only/failed 继续独立查证。
- [ ] 连续 7 天观察误报率、相关性与重复率，再微调词表；不以日推荐篇数为目标。


## 2026-11-15 / P1A 产业链协同出海

- 新增独立监控方向 P1A，与 P1 同级、P0 保持优先。研究范围：供应链伙伴所在地与海外经营节点区位匹配、销售服务与制造子公司职能、供需关系中断/持续/新建、控制权与当地经营经验、客户/供应商差异、FactSet Revere 测度及关系层面识别。
- Crossref 新增三条中英文定向查询；词法门要求供应链关系与海外布局/邻近性两轴，P1A 独立候选上限6，总上限30不变；同篇优先归入 P0，其次专门 P1A，不重复推送。中文期刊和 NBER/CEPR/RePEc 仍由日报独立补检。关注《国际贸易问题》《世界经济研究》及 customer-following FDI、buyer-supplier relationship survival、foreign affiliate location 等术语。
- 测试新增正反例与去重回归；CI 和真实扫描结果待核验，不预先标为通过。未上传未发表稿件或实证结果。

### 2026-11-15 / P1A 对抗式验收

- 初版真实扫描：`generated_at=2026-11-15T01:25:44.648101+00:00`，Crossref 13/13、388条，arXiv 4/4、9条，P1A实际捕获 DOI `10.2139/ssrn.7698161`（元数据登记候选，非已验证新论文）。中文目录1/7文章级，整体 `degraded`。
- 初版反例：customer-following FDI、foreign subsidiaries 等常见表述可能漏检；纯国内物流仓储地理邻近可能误报。PR #2 增加第四条定向检索式、词形及关系结局词，收紧邻近布局门，保留P0优先、P1A上限6和总上限30。README同步。
- [CI #43663467829](https://github.com/lican1213/academic-research-radar/actions/runs/43663467829) 原始日志：Python编译成功，40项测试均通过（含6项P1A专项）；覆盖真实类型题名、词形召回、负例、优先级、候选上限、模拟跨自然日去重及延期交付。PR [#2](https://github.com/lican1213/academic-research-radar/pull/2) 已 squash 合并至 main (`e36d7de36c3143d02da7c3c00e84ed794b5a1b9c`)，回读确认代码和测试存在。
- 原每日09:30任务已增加P1A；原时间窗、学术质量阈值、只读约束不变。未上传未发表论文或数据。
- Gate：编译、全量CI、初版实网输出、主分支合并、调度配置均通过；合并后14条查询的真实新扫描回读及连续自然日生产观察单独核验，不以模拟跨日代替生产观察。中文目录缺口按原规则独立人工补检。

- 人工实网候选复验：SSRN 2026-11-13 登记的 DOI `10.2139/ssrn.7698161` 与正式刊文 `10.1016/j.intman.2026.101340` 题名、四位作者完全相符；[出版方](https://www.sciencedirect.com/science/article/pii/S1075425326000141) 标为 2026-03 正式刊出，[大学存档原文](https://osuva.uwasa.fi/server/api/core/bitstreams/23d954f4-5821-4ad0-b83f-dded905e9ce6/content) 可检索文本注明 2026-01-23 online（PDF视觉截图受访问限制），[SSRN目录](https://papers.ssrn.com/searchresults.cfm?term=%28+++%22automotive+supplier+) 标注11-13上传及正式 DOI。该候选是旧论文重新登记，不能列为今日新增，不重复推荐；研究为土耳其7家汽车供应商定性研究，并非直接竞争性关系终止实证。此次验证候选发现与人工日期核验分离，不将登记日当发表日。


## 2026-11-15 / 中文核心期刊覆盖升级

- 真实基线 2026-11-15T01:53:14Z：中文目录仅1/7（《世界经济》7条）；《财经研究》官网改版，数量经济官网502，金融研究官网证书错配。其他目录只有期次。不能将目录存在视为文章覆盖。
- 参考 [MartyYao/Chinese-Literature-Skill](https://github.com/MartyYao/Chinese-Literature-Skill) 的公开CNKI RSS普通匿名会话方案（MIT），新增九刊独立RSS通道；新增国际贸易问题、世界经济研究；修复财经研究新版主页及无/CN文章链接，保留旧入口。RSS事件日期不等于首次发表；空XML、错误期刊、非文章/外链、失败必须显式标识；与目录共享已见标题去重，旧期次恢复不批量重发。
- CI [43683181885](https://github.com/lican1213/academic-research-radar/actions/runs/43683181885) 原始日志46项全部通过（6项新增）；[PR #3](https://github.com/lican1213/academic-research-radar/pull/3) 已合并 `8809f11c5d03274f8e1f5347cfd8fca91f2393d2`。合并后的真实RSS/目录扫描尚待产物回读；不宣称9刊均可用。
- 每日09:30任务已更新：中文九刊逐刊官网、CNKI网络首发、权威索引补检优先于弱相关英文推荐；分别报告文章级覆盖、期次和来源缺口。不改日程、论文质量阈值或未公开稿件。RSS only并非完整目录/全文覆盖。

### 2026-11-15 / 中文实网复验：Gate FAIL

- 回读 `data/latest.json generated_at=2026-11-15T05:56:39.711998+00:00`：中文2/9有文章链接，23条（世界经济7、财经研究16）；CNKI RSS 0/9，全部DNS解析 `Name or service not known`。Crossref14/14、arXiv4/4，整体仍degraded。CI46项通过不代表中文实网通过。
- 独立官方反例：扫描将《耐心资本支持与企业绿色创新质量》标为2026-09期；[出版方详情](https://qks.sufe.edu.cn/J/CJYJ/Article/Details/A0D4FFPwQu-dBL4-uLdN-7nqu-nnsVUTr60cyJ/CN) 实际为2026年第7期，DOI 10.16538/j.cnki.jfe.20260314.101。主页混合推荐/旧期文章，全局最大期次不能用于每篇文章；因此财经研究链接发现通过，但期次准确性未通过。
- 漏检反例：[国际贸易问题官网2026年第10期](https://gjmw.cbpt.cnki.net/portal/journal/portal/client/index)，[刘博聪、李磊、李川川《专利出海、创新激励与内外贸一体化》](https://gjmw.cbpt.cnki.net/portal/journal/portal/client/paper/7f6078a0cec828f7581a0bc4ff569adf)，DOI 10.13510/j.cnki.jit.2026.10.007，2026-10-25；当前自动源只见9期，未捕捉该期。国哲社[世界经济研究目录](https://ncpssd.org/journal/details?gch=91453X) 已公开展示10期题名/作者/页码，但现有解析未提取可定位文章线索。
- 下一轮：使用可访问的期刊自有公开平台/期次专页、权威目录文章级元数据和公开结构化接口；逐篇期次绑定、标题/DOI跨源去重、实际链接与日期核查；RSS保留可选渠道但不作为唯一恢复路线。验收以九刊真实文章级覆盖、上述反例修复及新CI为准。本次只记录审计证据，未修改抓取代码。

### 2026-11-15 / 中文第二轮修复（PR #4）

- 证据来源：[财经研究最新文章](https://qks.sufe.edu.cn/J/CJYJ/Article/Latest) 逐篇显示期次（09期结束后有08期），[国际贸易问题目录](https://gjmw.cbpt.cnki.net/portal/journal/portal/client/index) 与 [世界经济研究目录](https://jing.cbpt.cnki.net/portal/journal/portal/client/index) 均可独立网络核验2026年第10期；替换滞后目录为这两个首选公开出版平台，保留国哲社回退。
- 混合期次文章改从文章URL、单篇邻近文本或显式期次专页取得期次，未知保留null；不将首页最大期次赋给每篇。新增国哲社公开主题检索8组查询（参考 Chinese-Literature-Skill MIT），精确九刊匹配、链接/DOI校验、标题和DOI去重、补漏事件，与正式出版日期分离。主题查询不是逐刊完整目录，不能计入TOC覆盖成功数。RSS仍为可选补充，不绕过TLS/DNS限制。
- [CI #43690428431](https://github.com/lican1213/academic-research-radar/actions/runs/43690428431) 原始日志：编译成功、50项全量测试通过，新增4个真实反例fixture（财经研究7/9期混合、国际贸易问题专利出海链接/DOI、索引拒绝错误刊名和外域、补漏去重不伪造覆盖）。[PR #4](https://github.com/lican1213/academic-research-radar/pull/4) 已合并 main `62fd243bbdfc055bc015fc16fa157d44fcfb0bee`。
- 本轮代码回归Gate PASS；生产网络覆盖仍需以合并后 latest.json 实际字段与来源状态回读验收，不能把网页独立访问或fixture当作GitHub runner真实成功。九刊未达文章级覆盖不得整体放行。

### 2026-11-15 / PR #4 生产复验：仍未放行

- 实际 `data/latest.json` 生成于 2026-11-15T07:33:20.207643Z：中文文章链接发现4/9、53条（世界经济7、财经研究20、国际贸易问题12、世界经济研究14），不是九刊完整目录；经济研究、中国工业经济、管理世界、数量经济技术经济研究、金融研究仍catalog_only。RSS 0/9 DNS失败；国哲社主题接口4/8成功、7条原始匹配，供应链关系、对外直接投资、专利文本、人工智能四组超时。整体degraded。
- 真实反例未关闭：`data/chinese_seen.json` 的 international_trade 标记2026-10，但没有《专利出海、创新激励与内外贸一体化》标准化标题或 DOI `10.13510/j.cnki.jit.2026.10.007`；账本含多篇历史题名。首页推荐/热门文章混入，不能把该期标记及12个链接等同于当期完整目录。现有fixture正确但没有复现实网DOM。财经研究新候选实际出现2026-08期历史补漏，首发日仍未知，不应称今日新增。
- 验收：CI 50/50通过、PR #4合并和真实扫描产物落盘通过；中文覆盖、期次目录准确性及直接反例召回 Gate FAIL。下一步优先获取期次专页、结构化期次列表或可复核文章索引的真实响应，按期次逐项对照；不得仅扩大首页链接匹配或将历史推荐当最新目录。此轮复验只更新MOC，不改代码或调度。

### 2026-11-15 / PR #5：期次优先（借鉴现有开源项目）

- 阅读 [cookjohn/cnki-skills](https://github.com/cookjohn/cnki-skills/blob/main/skills/cnki-journal-toc/SKILL.md) 的刊期选择、目录容器与逐行题录提取方案；参照 [Joovo/CNKI_SPD](https://github.com/Joovo/CNKI_SPD) 年份/期次检索策略和 [MartyYao/Chinese-Literature-Skill](https://github.com/MartyYao/Chinese-Literature-Skill) 多源降级。未复制登录凭据、不绕过验证码或TLS验证、不抓付费全文。
- 两个贸易/世界经济期刊切换至 `paper_list/type_benqi` 本期目录，单篇必须有同一期次证据才进入候选，排除首页热门/历史链接；公开国哲社目录确有题名、作者、页码，支持 `toc_metadata`（只有目录定位，非直接文章链接）；独立输出 `article_link_count`、`issue_metadata_count` 和 `coverage_kind` 防止把混合页面计作整期覆盖。修正中文结构化索引路径的错误 `[^\\w]` 正则及历史空键，不清空去重账本。
- 对照真实网页：[国际贸易问题当期目次](https://gjmw.cbpt.cnki.net/portal/journal/portal/client/paper_list/type_benqi)、[经济研究国哲社目录](https://ncpssd.org/journal/details.aspx?gch=95645X)。新增4项反例测试：同一期次才接受、目录元数据不编造文章URL、中文去重键非空、补漏与日期/链接范围状态正确。
- [CI #43694052019](https://github.com/lican1213/academic-research-radar/actions/runs/43694052019) 原始日志：编译通过、54项测试全部通过；[PR #5](https://github.com/lican1213/academic-research-radar/pull/5) 已合并 main `82f3fbe7a3896b23ff20ace55c65e7faddc0594c`。继续回读生产产物；线上九刊覆盖与已知漏检反例尚未确认，不能宣布完整Gate PASS。不改日报频率或论文文件。


## 2026-11-16 / 三阶段生产修复（待 CI 与 live readback）
- 基线：run 43789706340，main d4d11ca，degraded；3/9 刊有期次绑定链接，财经研究混合期次，RSS 0/9，国哲社专题 3/8。前次 run 43739278658 数量经济技术经济研究产生29条无期次历史候选（含2022年交错DID）。
- 采集：数量经济按逐篇显式期次和 YYYYMMNN 文件编号交叉校验，无有效当期行时回退目录；每刊保存本次解析题录/链接快照（link_verified=false，非详情页实访证明）。混合链接显式 mixed_links，保留审计线索但不进入增量账本。目录仅有期次不刷新文章成功时间。
- 二阶段：保留原历史账本，已见标题补录 DOI/稳定文章链接别名；不要按相似标题盲合并。旧未知期次不会因网络恢复被推为新文；确有近期目录标记的专用当期页仍允许待核候选。日期语义不变。
- 三阶段：MD 与 JSON 区分预筛通过和本次新增，明确 NCPSSD 专题失败。每日任务须独立核验 mixed_links/toc_metadata/failed/stale_index 等缺口、复核链接与出版日期、历史补漏和真实新增分开，按研究相关性决策而非机械推送。调度不变。
- Gate: 本次修复提交不是生产放行。以 PR CI、合并后真实 run 及逐篇快照回读为准；九刊当期完整性、真实详情链接、连续七日跨日去重仍未验收。历史账本余留短标题/摘要键不直接清空或武断合并。

### PR #6 代码验收及阶段三回读
- PR [#6](https://github.com/lican1213/academic-research-radar/pull/6) 已合并至 main `f50246752d4288fe947d8896d89a5fef242d73a0`。PR [CI 43851372779](https://github.com/lican1213/academic-research-radar/actions/runs/43851372779) 原始日志：编译成功，58/58 测试通过（包括历史期次混入、混合行恢复、空期次成功时间、稳定 URL 别名四项）；主分支 CI [43851428035](https://github.com/lican1213/academic-research-radar/actions/runs/43851428035) 成功。
- 每日雷达任务契约已更新并读回确认：继续北京时间 09:30、原 P0/P1/P1A/P2/P3/P4 与评分策略；按历史提交 SHA 合并过去48小时实际候选、核验单篇日期及跨日报身份；mixed_links 等降级独立补检。实际 GitHub commits?sha=main&path=data/latest.json 查询返回 d4d11ca、a2984ce、a53e53b 等生产历史，证实可读；不把定时任务配置回读当作下一次日报已经交付。
- [合并后生产 run 43851428062](https://github.com/lican1213/academic-research-radar/actions/runs/43851428062) 当前检查状态：in_progress/pending；只有新数据实际写回、逐篇样本与官方信息一致后才可关闭相应生产门。原始中文源 DNS/TLS/HTTP 故障仍需生产证据，禁止重写历史产物或清空旧账本。
- 独立补检：财经研究 [第9期目录](https://qks.sufe.edu.cn/J/j00001/Article/2026/09) 与 [最新文章](https://qks.sufe.edu.cn/J/CJYJ/Article/Latest) 的搜索索引分别显示11篇和混合期次，实际打开专刊页一度超时；管理世界 [国哲移动端](https://m.ncpssd.cn/journal/details?gch=95499X&langType=1&nav=1) 有10期题名（未见完整作者/页码），桌面索引9期；金融研究10期存在公开转载目录，但尚未确认稳定官方详情。保留为补检路径，不伪造文章级生产覆盖。

## 2026-11-19 / 公开目录与RSS源超时修复：分阶段 Gate

- 生产基线：run [44374149332](https://github.com/lican1213/academic-research-radar/actions/runs/44374149332) completed/success，但数据 `generated_at=2026-11-18T18:51:07Z`、`status=degraded`；经济研究、中国工业经济、管理世界等国哲社目录超时，金融研究官网超时，国哲社8/8专题查询超时；九刊CNKI RSS均DNS解析失败。扫描成功不代表文章级覆盖恢复。
- 对照 [MartyYao/Chinese-Literature-Skill](https://github.com/MartyYao/Chinese-Literature-Skill)、[cookjohn/cnki-skills](https://github.com/cookjohn/cnki-skills)、[sthsci/litfeed-bot](https://github.com/sthsci/litfeed-bot)、[gitronald/citefinder](https://github.com/gitronald/citefinder) 的公开源独立状态、主备检索、有限重试与保留缓存语义；仅借鉴设计，不复制认证绕行或付费全文抓取。
- **阶段一（本PR）**：仅针对真实网络适配器增加每次扫描作用域的host级故障熔断：DNS失败后本次不对同一host重复尝试；同一host连续2次超时后本次剩余请求以`host_circuit_open`标为失败，下次Action重新探测，不产生假成功。经济研究、中国工业经济、管理世界添加已公开可访问的国哲社移动端备用目录；若仅期次/题名仍维持`catalog_only/toc_metadata`，不编造文章URL、首发日期或完整覆盖。故障时新增`last_known_issue`只作历史辅助，不当作今天成功。
- **阶段二（条件触发，未实施）**：如经真实GitHub Runner实测移动站也超时，再评估经允许使用的权威目录题录/可靠API按ISSN与单刊期次索引。采集快照保留源、期次、文章身份与精度等级；来源单独记录健康和最后成功时间，不能将搜索索引当刊期完整目录。
- **阶段三（条件触发，未实施）**：在真实文章详情可访问后再扩展DOI/正式在线日期与期刊时间轴复验、逐篇链接验证和跨日精准去重；发布前继续以论文优先级和日报人工核验为门，任何`index_event_at/first_observed_at`不自动变成发表日期。
- Gate：等待PR CI编译与对抗测试；合并后的生产run必须回读`head_sha`、`status`、逐刊`coverage_kind/article_snapshot/RSS`、失败主因与最新数据提交。即使运行缩短，也不等于9刊已恢复文章级采集。原定时任务、交易相关仓库、历史账本及用户稿件未修改。

### 2026-11-19 / PR #7 live readback 与 catalog stale 后续修复

- PR #7 squash 合并 `b2d84e0d8272ebfa82cfddff5443f98aab2957ee`；PR CI [44444217486](https://github.com/lican1213/academic-research-radar/actions/runs/44444217486) 与主分支 CI [44444303833](https://github.com/lican1213/academic-research-radar/actions/runs/44444303833) 均成功，62/62测试通过。
- 实际生产 [run 44444303838](https://github.com/lican1213/academic-research-radar/actions/runs/44444303838) completed/success、head_sha=b2d84e0d，`generated_at=2026-11-19T02:26:20Z`，数据提交 `26a65e27e0665843d02cb09a8ab83144f0871e96`。总状态仍degraded（正确）：经济研究2026-09、工业经济2026-08恢复为toc_metadata；世界经济、数量经济、国际贸易问题、世界经济研究为当期绑定链接；财经研究mixed_links；金融研究官网TLS hostname mismatch后目录仅2026-07；管理世界原目录退回2026-09而账本已有10期。CNKI RSS首次DNS失败后同host余下调用均显示host_circuit_open，不误记成功；NCPSSD专题8/8本轮恢复，可能是外部服务暂时恢复，不归功于熔断。7/9有文章或题录记录，并非9刊完整覆盖。
- 本轮追加的**目录倒退备用源**：当主目录成功响应但期次比历史成功期次旧时，尝试已配置的独立移动目录；只有备用页期次不早于历史才采纳，且继续按页实际证据保持catalog_only/toc_metadata，不将题名或刊期假报为文章详情、首发日或读到全文。备用页失败或更旧则保留stale_index，不覆盖账本。此修复独立PR/CI/生产门验收，未改调度和去重算法。

### 2026-11-19 / PR #8 生产验收结论（已实访，部分未通过）

- PR [#8](https://github.com/lican1213/academic-research-radar/pull/8) squash 合并 main `6f79baccf7b5482cae8f8ea0f4fc62398a483042`；PR [CI 44445018397](https://github.com/lican1213/academic-research-radar/actions/runs/44445018397) 与合并主分支 [CI 44445061407](https://github.com/lican1213/academic-research-radar/actions/runs/44445061407) 成功；对抗测试64/64通过。
- 真实 [生产扫描 44445061346](https://github.com/lican1213/academic-research-radar/actions/runs/44445061346) = completed/success，`head_sha=6f79bacc...`，`data/latest.json generated_at=2026-11-19T02:32:33.928317Z`，实际数据提交 `572add3b55cd8152ac5b688373b8ef57b0c710d1`。生产数据状态仍 `degraded`：四刊有当期期次绑定文章链接，经济研究11条/中国工业经济9条为 `toc_metadata`，财经研究20条混合链接，管理世界 `stale_index`（主源09期低于历史10期，移动备用源也超时），金融研究 `failed`（官网超时，上一轮官网曾TLS域名错配，备用目录仅到07期）。CNKI RSS仍全部DNS失败。
- 同次国哲社专题索引 `2/8`成功、3条匹配；2次超时后其余4项显式 `host_circuit_open`，下一次扫描会重新探测。前次PR #7生产 `8/8`成功，表明上游存在不稳定现象，不应将一次恢复归功于抓取代码，也不能保证后续必成功。
- **已通过的Gate**：代码编译、64项回归、PR与main CI、相同SHA生产Action、数据持久提交、失败状态显式暴露、历史去重账本保持。不通过的Gate：金融研究/管理世界最新文章级覆盖、CNKI RSS DNS、9刊完整当期详情链接核验、连续7日不漏不重观察。运行绿色不等于内容质量全绿。
- **阶段二计划门槛**：按刊评估另一合法权威出版/索引入口（与失效NCPSSD主域独立），每刊设置仅经实网证明可用的适配器、刊期绑定题录+作者页码、独立URL可达测试；不能拿转载目录、索引事件日期当真实发表，也不能用轮换代理、禁用TLS或抓登录/付费全文的方式伪修。
- **阶段三计划门槛**：当实际文章详情页稳定后才实现跨源canonical identity(doi+期刊文章URL+核验标题/作者)、published_online/issue/first_observed时间分离、逐篇链接回读、每日增量与48小时历史快照核验；至少7日跨次生产复验达标后再评估整体提升。保持 P0>P1A≈P1 的研究筛选阈值，ChatGPT每日独立补检不变。


## 2026-11-19 / Stage-2 independent source adapter: implementation and adversarial gates

**Evidence:** prior production run [44445061346](https://github.com/lican1213/academic-research-radar/actions/runs/44445061346), output `degraded`; 管理世界 NCPSSD returned 2026-09 while ledger has 2026-10; 金融研究 publisher TLS/timeout and NCPSSD only 2026-07. Independent public evidence: [重庆维普《管理世界》期刊](https://www.cqvip.com/journal/95499X/95499X) and [《金融研究》期刊](https://www.cqvip.com/journal/97926X/97926X) both index 2026-10; official [金融研究 current](https://www.jryj.org.cn/CN/1002-7246/current.shtml) indexed 2026-10-25 in public search (web availability is *not* Runner availability); [2026-11-09 浙江工商大学报道](https://news.zjgsu.edu.cn/17/view_23943.html) confirmed 2026-11-08 管理世界11期新刊发布, but NOT its full TOC. Do not treat a release event or search index as paper publication date.

**Open-source implementation review, not README claims:** [uw-share-lab/refaudit/src/refaudit/ratelimit.py](https://github.com/uw-share-lab/refaudit/blob/main/src/refaudit/ratelimit.py) for bounded per-host pacing/circuit, [.github/workflows/live.yml](https://github.com/uw-share-lab/refaudit/blob/main/.github/workflows/live.yml) for separating isolated CI from real upstream probe; [X-PG13/paper-digest/paper_digest/network.py](https://github.com/X-PG13/paper-digest/blob/main/paper_digest/network.py) for bounded Retry-After; [MartyYao/Chinese-Literature-Skill](https://github.com/MartyYao/Chinese-Literature-Skill) for Chinese public indexing but its use alone is NOT proof of stable GitHub-hosted reachability. No new dependencies or proxy/anti-bot bypass.

**Scope:** A narrow per-journal trusted source adapter resolver for financial_research and management_world only, with authoritative publisher first, fixed independent CQVIP catalog as issue-only contingency; public NCPSSD as last-resort. CQVIP parser checks target code, exact journal name, ISSN, explicit `目录 ... 年/月期 共N篇` and returns **zero verified article identities**. Source attempts and provenance recorded, primary/alternate stale detection uses historical issue ledger. Keeps `article_count=0, article_snapshot=[]` for catalog index; claimed count is separately labeled. Never emits index-only titles, dates or candidate papers. No edits to schedules, ranking, duplicate logic, trade or unpublished papers.

**Gates before release:** PR compile + unit test; anti-noise wrong ISSN/wrong journal/year-navigation regression, per-host outages and history-preserving tests; merge at exact SHA; main CI; real main SHA Action and new committed JSON; review official vs independent index source statuses, claimed indexed issue vs article_detail counts, 48h candidate and seen ledger consistency. Even if CQVIP is reachable, `catalog_only` is not article-level acceptance. If all alternates fail, keep `failed/stale_index`; leave independent daily journal search required.

**Stage-3 future contract:** Each source adapter later may return independently visitable paper URLs and verified title/author/DOI. Add those only on stable official article pages, with `published_online_at/issue/first_observed_at` independently tracked and one article identity across duplicate indexes; protect existing emitted history, 48h snapshots, and 7-day longitudinal gate. Do not add unnecessary queue/database/browser infrastructure.


### 2026-11-19 / PR #9 live acceptance and phase-3 backfill protection

- PR [#9](https://github.com/lican1213/academic-research-radar/pull/9) merged `f1bfa51bf27c5ac60da8022d083662d6c6a87729`; 70/70 PR regression tests and same-SHA main CI succeeded. Actual [scan run 44447352888](https://github.com/lican1213/academic-research-radar/actions/runs/44447352888) completed/success, `generated_at=2026-11-19T02:51:52.575201Z`, dataset SHA `639ee18cf06183f08b4c43f772ebac9ad969f388`, overall `degraded` (correct). This was a *real scheduled-system code push scan*, not an isolated fixture.
- Independent issue evidence **recovered**: 管理世界 NCPSSD primary timeout → CQVIP 2026-10 issue-only → NCPSSD mobile 2026-11 issue-only; selected 11期, zero article-detail links. 金融研究 publisher www TLS hostname mismatch, apex DNS failure, alternate publisher www same cert failure → CQVIP 2026-10 (claimed 12 items) → NCPSSD mobile 2026-07; selected 10期, **zero** verified article-detail links. The indexed count 12 is never `article_count` or `issue_metadata_count`. Thus issue gate PASS for these two, article-level gate FAIL. CNKI RSS remains 0/9; Crossref14/14, arXiv4/4; NCPSSD topic4/8 (four HTTP502); unrelated 世界经济 homepage DNS failed transiently this run. Do not misrepresent these as fully fixed or claim source recovery caused the internet to stabilize.
- **Post-live adversarial edge:** An issue-only baseline with zero article keys can suppress the first genuinely recovered detail links for the SAME issue. Fix in a separate PR to label such leads `event_type=issue_backfill`, `published_at=null`, `date_verified=false`, emit once, and then dedup on subsequent runs; first-ever article-level scan still seeds baseline, preventing whole-old-issue spam. Persist per-source attempt details on complete multi-source outage instead of a truncated single reason. Source adapters should eventually support exact article identities; no date inference from issue number or CQVIP index count.
- Required gates: new PR CI+main CI, main-SHA live scan+commit readback, no regression in nine-journal status, historical seen ledger, existing daily task or schedule. 7-day delivery/duplicate observation cannot be prematurely marked PASS.

**CI conflict discovered and resolved:** initial PR #10 CI [44448021628](https://github.com/lican1213/academic-research-radar/actions/runs/44448021628) correctly failed existing `test_catalog_recovery_baselines_old_same_issue` because the first attempt put recovered older details into `new_candidates`. Corrected contract: introduce separate `chinese_historical_backfill_leads` and preserve `chinese_new_candidates=[]` for same-issue history; repeat returns zero in both queues. This is a required regression defense, not a flaky test to suppress. Reported no publication date. Need re-run full CI and main-SHA production before release.


### 2026-11-19 / PR #10 final merged-head production gate

- PR [#10](https://github.com/lican1213/academic-research-radar/pull/10) squash merged `a5a090f592760746606c99e58542bd87aa598db9`. An intermediate CI **FAILED** (a real regression caught by the existing test) [44448021628](https://github.com/lican1213/academic-research-radar/actions/runs/44448021628), proving an issue-only→same-issue article backfill regression against the original historical baseline contract. The revised implementation separates `chinese_historical_backfill_leads` from `chinese_new_candidates`; [PR CI 44448200083](https://github.com/lican1213/academic-research-radar/actions/runs/44448200083) passed **72/72** and merged main CI [44448247727](https://github.com/lican1213/academic-research-radar/actions/runs/44448247727) passed.
- Final real production [run 44448247830](https://github.com/lican1213/academic-research-radar/actions/runs/44448247830) **completed/success**, `head_sha=a5a090f5...`, `generated_at=2026-11-19T02:59:49.446747Z`, committed dataset `b0000e0f9e126cc1ab04e39b3d653f59c517a37d`. Overall `status=degraded` (correct). Both `chinese_new_candidates=0` and `chinese_historical_backfill_leads=0` in this live run; empty second queue only tests real output shape, while fixture + 72 tests cover the positive recovery path. Crossref14/14 and arXiv4/4; NCPSSD topic8/8 (intermittent, previous run4/8).
- Source-specific final readback: **管理世界** 2026-11 `catalog_only`, 0 article links; attempts NCPSSD primary 09期 stale, CQVIP 10期 stale, NCPSSD mobile 11期 issue-only. **金融研究** 2026-10 `catalog_only`, index claimed 12 papers but **0 article detail links**; primary www TLS hostname mismatch, apex DNS failure, publisher home TLS mismatch; CQVIP 10期 verified issue, NCPSSD backup 07期 stale. Cross-domain fallback evidence real, not proof of complete bibliography. **世界经济** this run DNS `failed` (previously 11期 articles captured) and is a new transient deficit requiring independent daily check; 其他: 经济研究09期11条题录、工业经济08期9条题录；数量经济10期10条当期链接、国际贸易问题10期10条、世界经济研究11期9条；财经研究09期20条混合链接(11当期)，九刊RSS仍 0/9.
- **PASS**: current SHA PR and main CI, 72 tests, production head/committed data, proper TLS/DNS/source provenance, no false dates, no ledger reset; explicit old-paper backfill segregation and unchanged scheduling. **FAIL/NOT VERIFIED**: journal nine-way current-issue full article coverage, two priority journals article detail access, official TLS repair, RSS, period-relative publication dates, multi-day longitudinal nonrepeat gate. No pipeline success implies these passed.
- Next Stage-2 only when evidence supports it: seek publicly accessible and licensed publisher/article indexes that expose actual per-paper URLs for the two journals; maintain `catalog_only` until link/title/author/issue verified; do not create RSS bypass, proxy rotation or guess detail IDs. Stage-3: independently verify DOI/online issue dates, historical snapshot replay, cross-source stable identity and seven-day production observations before declaring full radar coverage. The current independent CQVIP issue-only adapter is an evidence improvement, not a substitute for journal article ingestion.

### 2026-11-19 / Ponytail-style targeted PDF acceptance proof (pending production)

- **Requirement:** 用户明确把“能从官网真实下载 PDF”列为生产验收之一，不能把 `article_link_count>0`、目录显示“正文”、模拟PDF测试或 HTTP 200 的 HTML 当作 PDF 成功。针对《金融研究》2026年10期苏继影、谭小芬、李兴申《地缘政治风险、跨境供应链与中国企业债券信用利差》，详情 `https://www.jryj.org.cn/CN/abstract/abstract1663.shtml`；公开网页索引显示正文(622KB)，但截至本次验收前 Runner 对 www 官方域名 HTTPS hostname mismatch，直接PDF链接也未从真实页面拿到。
- **Scope:** `pdf_probe.py` 一篇固定高相关目标 + 一篇独立官方公开直链 PDF 对照（华东师范大学学报 `https://xbzs.ecnu.edu.cn/CN/article/downloadArticleFile.do?attachType=PDF&id=13261`）；仓库标准库 HTTP，HTML 中只采纳经过解析的同源 HTTPS PDF href；不猜下载地址、不关闭 TLS、不跨站跳转、不抓取需认证的全文。下载至临时目录，验证PDF签名+EOF+SHA256+大小；`pdftotext`存在时尝试提取，**不将文章正文和 PDF 上传 GitHub**。固定的四分钟独立手动/代码变更触发 workflow `Academic Radar PDF Acceptance`；仅 artifact JSON 状态，目标 PDF 失败则 Action 红，不能被健康的对照源遮盖。原 `scan.yml` 不动。
- **Gate A:** 离线对抗测试包括错误PDF链接、外站和非HTTPS拒绝、伪装PDF的HTML、只含伪PDF头但无EOF、DNS/超时、确切PDF头与hash检验，不能只测Mock返回成功。
- **Gate B:** GitHub Action 在当前主分支 SHA 真实联网，核对 result JSON `target.pdf_download_verified` 为 true 才可放行。若失败要给出具体 DNS/TLS/link_missing，不强改为 green；对照 `control.pdf_download_verified` 只证明通用 downloader，可辅助排查，但不能替代目标PDF。下载失败不改变现有扫描或去重、也不产生“今日新论文”。
- **Gate C (later):** 若目标 PDF 真正取得，检查是否可提取出正文/页码/回归表，才考虑最小的本地处理和 P1A 针对性实证对照；若确需更多工具，再按需求引入依赖，不添加向量DB、LLM自动审稿、多服务调度、全量PDF持久仓储。任何人工“阅读全文”声明需要可复核的原文实证证据。


### 2026-11-19 / PR #11 real PDF gate, confirmed target failure and control success

- [PR #11](https://github.com/lican1213/academic-research-radar/pull/11) merged `ebf2b41340726b8e3e6932d5cb5c11ae276cebc1`. Main CI [44465443023](https://github.com/lican1213/academic-research-radar/actions/runs/44465443023) passed; separate real Runner [PDF run 44465442930](https://github.com/lican1213/academic-research-radar/actions/runs/44465442930) **FAILED by design** because `www.jryj.org.cn` responds with `CERTIFICATE_VERIFY_FAILED: Hostname mismatch` when accessing `/CN/abstract/abstract1663.shtml`. No target PDF URL or bytes obtained, target gate FAIL. Do not weaken TLS or infer success from screenshot/link.
- The independent publisher control (ECNU 2026 institutional opening and supply chain resilience) **actually downloaded** 1,286,268 PDF bytes with valid PDF magic+EOF and `sha256=6cf653c43e455dfc620f1e358c426e08eecc8770e33ef40f9d6fe02de76b970a`. This demonstrates GitHub-hosted Runner can download a public PDF from a healthy official source, not the targeted journal. The runner lacked `pdftotext`, so FULL TEXT extraction was `unavailable` in the first run.
- Follow-up minimal probe change: isolated PDF acceptance workflow installs PyMuPDF, extracts PDF pages and Mandarin text in memory and emits **metrics only**; public TLS certificate SAN diagnostic uses `openssl` to identify canonical hostname without content access or bypass. No changes to existing twice-daily research scan, its data, historic ledgers, ranking, or nine-journal source handling. Gate continues to fail if target PDF is not downloaded.
- Follow-up review gates: exact SHA CI, actual Runner readback of both URLs, extraction metrics if any, capture certificate subject/SAN, verify artifact contains no PDF or extracted copyright content, then update this MOC with final result. Source-level TLS remains external blocker until a fully trusted publisher-approved hostname is proven.


### 2026-11-19 / PR #12 final live PDF readback — separate target and extraction gates

- [PR #12](https://github.com/lican1213/academic-research-radar/pull/12) squash merged `1144080673ffb0128146b58aba259b74e1655850`. PR CI [44465919358](https://github.com/lican1213/academic-research-radar/actions/runs/44465919358) and same-head main CI [44465976565](https://github.com/lican1213/academic-research-radar/actions/runs/44465976565) **PASS**. Independent real PDF workflow [44465976560](https://github.com/lican1213/academic-research-radar/actions/runs/44465976560) **FAIL** exactly at `Enforce real PDF gate` because target publisher PDF not obtainable.
- Live target `https://www.jryj.org.cn/CN/abstract/abstract1663.shtml` remained `pdf_download_verified=false`, `URLError CERTIFICATE_VERIFY_FAILED: Hostname mismatch`. Public certificate diagnostic returned `subject=CN=*.magtech.org.cn` and SAN `DNS:*.magtech.org.cn, DNS:magtech.org.cn`, NOT `www.jryj.org.cn`. Thus the failure is a concrete server HTTPS identity mismatch, not a Unicode parser or PDF format problem; do not guess a substitute `magtech` hostname or disable trust checks. Publisher must correct TLS or provide an independently verified official host.
- Live official control PDF `https://xbzs.ecnu.edu.cn/CN/article/downloadArticleFile.do?attachType=PDF&id=13261` **downloaded and extracted**. 1,286,268 bytes, SHA256 `6cf653c43e455dfc620f1e358c426e08eecc8770e33ef40f9d6fe02de76b970a`; 17 real PDF pages, 17 pages with extracted text, 34,664 text characters (15,393 Chinese), 28 table-label regex hits. Those are technical extraction diagnostics, NOT proof that all 28 are distinct research tables or that their statistics were verified. No PDF or full text was committed or uploaded. Main metadata scan continues independent of PDF workflow.
- Exact verdict: (1) PDF retrieval implementation PASS on a relevant independent official source; (2) actual Chinese full-text extraction PASS on that source; (3) requested **Financial Research PDF gate FAIL** due real TLS problem; (4) scholarly analysis of coefficient tables / identification from this PDF NOT independently validated by workflow; (5) full nine-journal PDF pipeline NOT IMPLEMENTED. The red PDF workflow is intentional evidence; do not suppress it to obtain green.
- Ponytail scope/next steps: stop growing download adapters; use existing verified open-PDF sources for targeted literature reading, continue search for a **provably official, valid-TLS** Financial Research endpoint; only when target passes should article-level PDF discovery be integrated with radar candidates. No automatic copyrighted-PDF storage, RAG, new scheduled tasks, proxy rotation or TLS-disable workaround. Seven-day production stability still not evaluated.


### 2026-11-19 / PR #13 real origin diagnostic and official-HTTP six-PDF repair

- **Observed root cause, real Runner**: [run 44469550771](https://github.com/lican1213/academic-research-radar/actions/runs/44469550771) from [PR #13](https://github.com/lican1213/academic-research-radar/pull/13) with code SHA `938c2b104b6bcd99c8a472c3acbb0199c6bddf0e`. `http://www.jryj.org.cn/CN/abstract/abstract1663.shtml` returned HTTP 200, 73,671 bytes and expected paper title, containing explicit `http://www.jryj.org.cn/CN/article/downloadArticleFile.do?attachType=PDF&id=1663` link. The same official HTTP PDF URL returned 200 and `application/x-download`, with `%PDF-` magic in its first 120,000 bytes (not a whole-file verification). Issue TOC HTTP200. Apex domain DNS failed; guessed `jryj.magtech.org.cn` DNS failed, `jryj.magtech.com.cn` returned404. Earlier target HTTPS failed hostname mismatch (certificate for `*.magtech.org.cn`). **The restriction to HTTPS in `pdf_probe.py`, not evidenced anti-bot controls, prevented discovery.**
- **Repair proposal**: Existing `pdf_probe.py` and its isolated, read-only workflow only. Fixed approved six article IDs `1662..1667`; direct link obtained from each official HTML; allow HTTP *only* to journal's fixed host and paths `/CN/abstract/abstract166[2-7].shtml` or `/CN/article/downloadArticleFile.do` with PDF/id matching. Validate response same host+scheme with no off-domain redirect, PDF magic/EOF, actual bytes+SHA256, Chinese extraction and matching title/page count. No proxies, login, paywall bypass, disabling TLS verification, or source guessing. Plain HTTP itself lacks cryptographic transport authenticity: record this limitation, and switch to verified HTTPS if journal operator fixes certificate. Preserve metadata-only artifacts, never commit copyright PDF/text.
- **Adversarial gates**: Reject other IDs, off-domain HTTP, wrong PDF query, HTTP→HTTPS redirect, forged PDF/HTML response and mismatched article content. Require test suite CI, exact same SHA main CI, real GitHub six-PDF run and per-paper `pdf_download_verified`, `text_extraction`, `title_match`, `page_count_matches`. A downloaded PDF alone is not an accurate research review. No new scheduled workflow; original 06:17/18:17 GitHub scans and ChatGPT daily research task unchanged.
- **Result pending:** this development record is an acceptance plan until merged-head production response and evidence readback below. Do not record a green outcome beforehand.


### 2026-11-19 / PR #14-15 SIX JRYJ PDFs: real production gate PASS

- **Root cause verified rather than bypassed:** Journal of Financial Research's own public HTML at `http://www.jryj.org.cn` (official published HTTP link) returned HTTP200 and an explicit PDF URL in the page's script/metadata, while the `https://www.jryj.org.cn` certificate is for `*.magtech.org.cn`. Initial probe only permitted HTTPS; first corrected probe PR [#14](https://github.com/lican1213/academic-research-radar/pull/14) proved official HTML was reachable but our PDF locator was limited to `<a href>` (all six `pdf_link_not_found`, [run 44470463091](https://github.com/lican1213/academic-research-radar/actions/runs/44470463091)). This was a real regression gate, not anti-bot. PR [#15](https://github.com/lican1213/academic-research-radar/pull/15) fixed only extraction of actual publisher-provided PDF URLs from HTML/script, and enforces same host/protocol and exact article id. Neither change disables TLS validation or uses login/proxies. No other journal scan was changed.
- **FINAL PRODUCTION GATE PASS 6/6**: main merged source commit `210b9510c1db0cb1086f736a81abbd02460f0654`. [GitHub real acceptance run 44470870725](https://github.com/lican1213/academic-research-radar/actions/runs/44470870725) `completed/success`, 15 isolated PDF tests successful; overall repo CI for same SHA also success. All six 2026(10) official PDF article ids 1662-1667 were fetched **completely**, real `%PDF-` + `%%EOF` checks passed, all six were extracted in memory with PyMuPDF, full titles matched first 12 normalized CJK characters of source metadata, and page counts matched the 19/18 expected issue page spans. Artifact JSON only stores metadata, hashes, and extraction metrics, not the copyrighted PDFs or source text.
- Original official direct links follow pattern exactly confirmed from each official article HTML: `http://www.jryj.org.cn/CN/article/downloadArticleFile.do?attachType=PDF&id=1662` through `id=1667`. Total verified bytes=5,364,410 across six docs, total physical PDF pages=112.

| Article ID | verified bytes | PDF pages | extracted text chars | full SHA-256 |
|---|---:|---:|---:|---|
| 1662 | 635732 | 19 | 32335 | `65d3f9e1a861e769793b21994d53a5a3fcca23fe367b5531724235fae68eb8ca` |
| 1663 | 636040 | 19 | 35936 | `7d9123636ba35530ac71e64e047b774febecd1dba5e9d2384cf98e9d1f81b188` |
| 1664 | 1407883 | 19 | 33109 | `d98f0dc2cd3afac71928807a020d8b44270646350cba78cc722c63f6bc9decc2` |
| 1665 | 604853 | 19 | 33051 | `f4f9dd7749f29452c7a45284116049760335a5d22983d1d01de8b03a98429422` |
| 1666 | 1441534 | 18 | 28993 | `c5f3a104eacbdeeeb316555b76d2a54d561f8bdc524c134bba9d5a333176cd8e` |
| 1667 | 638368 | 18 | 32534 | `306495e4354cd6e0b6b6235f425da1ba22699268b9268eb84615fb7fa1033b42` |

- **Security limits:** HTTP was explicitly advertised by the publisher and reachable, unlike HTTPS, but is not transport-encrypted or cryptographically authenticated. Page content/embedded explicit direct link + extracted PDF title/page count provide strong *content consistency*, not authenticity against a network man-in-the-middle. Re-probe an authenticated HTTPS publisher endpoint when the operator fixes its certificate. No access-control bypass; no proxy, CAPTCHA solver, TLS verification disable, downloaded PDF in Git, or copyright text in artifacts.
- **Next research gate:** The ability to extract 112 pages does **not** prove individual regression tables/identification schemes were interpreted or audited. For P1A prioritize id1663, P1 id1665, P0 id1667; use limited page-based evidence notes (variable definitions, identification, mechanism tables), carefully cross-check against official PDF tables before changing manuscript. Current standalone PDF workflow is triggered on its code changes or manual dispatch, not added to twice-daily scans; preserve original schedule, data ledgers, and scoring.


### 2026-11-19 / 六篇《金融研究》PDF「真实交付」闭环（Ponytail gate，优先于旧版仅验收记录）

**用户验收标准更新：** 论文详情可打开、Runner 校验值成功、或生成仅含 JSON 的 Action Artifact，都**不等于**可以交付 PDF。用户要求的是六份真实原始 PDF 文件和可下载 ZIP；应将「取得原始字节 → 验证 → 临时保存 → 取回 → 交付/打开」作为完整 gate。这个用户明确要求下的**短期交付例外**覆盖本文件及 `AGENTS.md` 旧版「任何 PDF 均不得进入 Artifact」的一刀切说法；仍禁止将受版权保护的 PDF、全文或批量提取文本提交 Git、建立公开永久存储、未经授权二次发布。

**本轮真实过程（不是模拟）：**
- [PR #16](https://github.com/lican1213/academic-research-radar/pull/16) 合并提交 `f0c9e2808b497d90f32bf72526683bab03f7895a`，在现有 `pdf_probe.py` 增加 `--zip-out`：每个原文保存为本次 Runner 临时内存字节，与 [首次6/6正文验收 run 44470870725](https://github.com/lican1213/academic-research-radar/actions/runs/44470870725) 的**逐篇 SHA-256** 精确比对，任何一篇缺失/校验失败都不生成 ZIP。真正的交付 ZIP 上传为独立 Actions Artifact，`retention-days: 1`；JSON 元数据仍单独保留14天。未更改文献扫描与去重。
- 第一次交付运行 [44473449505](https://github.com/lican1213/academic-research-radar/actions/runs/44473449505) **cancelled**：前五篇下载/哈希通过，第1667篇遇临时超时，原独立工作流4分钟上限截断了 ZIP 交付；只有元数据 Artifact，**没有**交付成功。不能把 PR/CI 绿色或前五篇成功当成六篇完整交付。
- [PR #17](https://github.com/lican1213/academic-research-radar/pull/17) 合并提交 `e451a9c2379b858cf88abc5be5752633850105de`：只给独立 PDF 交付加3次有界 `TimeoutError` 重试、单次连接20秒以及12分钟作业上限；ZIP 模式不再重复请求独立对照论文，原 `.github/workflows/scan.yml` 的两次每日 cron/12分钟扫描上限未改。新增失败封闭的 ZIP 和超时测试。
- **最终验收 PASS**：[GitHub Actions run 44474347819](https://github.com/lican1213/academic-research-radar/actions/runs/44474347819) `completed/success`、`head_sha=e451a9c2379b858cf88abc5be5752633850105de`，相同 SHA 的 [main CI 44474347831](https://github.com/lican1213/academic-research-radar/actions/runs/44474347831) success。6/6 `pdf_download_verified=true`、`text_extraction=ok`、`title_match=true`、`page_count_matches=true`、`sha256_matches_previous_run=true`。总计112页、5,364,410字节原始 PDF；**内部 ZIP `JRYJ_2026_10_Six_Papers.zip` 为4,504,911字节**，随后 `actions/upload-artifact` 产生的外层 GitHub Artifact ZIP 大小4,506,284字节。校验日志 `delivery_zip_name`、`delivery_zip_bytes` 均已实网回读。
- 交付 Artifact：`JRYJ_2026_10_Six_Papers`，`artifact_id=14505487442`，来自上述 run；到期 `2026-11-20T06:46:21Z`（**仅一天**）。它已经通过 GitHub 连接器 `download_workflow_artifact` 从 Runner 拉回当前对话，并提供了 **6个单篇 PDF 与一份实际原文 ZIP** 给用户。有效期过后不可依赖同一 Artifact；需要重新进行受允许的官方来源下载及交付校验。**MOC 永远只保存源 URL/哈希/运行信息，不保存文献全文。**
- 本次6篇 ID 1662—1667的原文 SHA-256 与各篇页数详见本 MOC 上节 `SIX JRYJ PDFs: real production gate PASS`。不要把这组固定 ID、`REFERENCE_SHA256` 或标题/页码当成通用期刊下载器；新论文需要各自真实 URL、书目信息和新的原文校验基线，不应因预置哈希不同就误判合法新版文件伪造。若后续版本改变，明确“版本更新/哈希变化，待原文复核”，不得静默覆盖旧验证记录。

**供后续 Agent 执行的最小通用流程：**
1. 从 `data/latest.json`、`chinese_new_candidates`、`chinese_historical_backfill_leads`、独立官网/目录找到与 P0/P1A/P1 高度相关的文章；先核标题、作者、期次、DOI/稳定详情地址、可访问性。不要从期次或 RSS 更新日臆推发表日期，也不要因为后补 PDF 将旧文章重新推为今日新增。
2. 在**公开、允许访问**的出版方详情页查找 HTML 链接、脚本或数据属性里的**真实 PDF URL**；站点传输方式由实网确定。优先证书有效的 HTTPS；对期刊明确公开但仅支持 HTTP 的特殊站点，应逐刊限制到已证实官方域名和具体下载路径，保留 HTTP 无真实性/传输完整性保障的风险。严禁关闭 TLS 校验、登录绕行、猜文章 ID、泛化任意 HTTP/代理。
3. 下载原始 PDF 字节并核验 PDF 头尾、长度、SHA-256、题名及页数，使用 PyMuPDF 只做文字提取能力检查；**提取文字 ≠ 已独立核验回归表、系数、固定效应或机制**。需要做学术判断时检查对应 PDF 原始页面、表号和模型定义。
4. 用户**明确要求领取原文**时，才在独立临时 Actions 作业构建受限 PDF ZIP Artifact（短期保存，按出版方许可和合理使用处理）；通过 GitHub 工具取回文件，并检查 ZIP 里文件数、名称、PDF 字节/哈希、可打开性后再交付。不能只有链接、脚本、JSON 或 Action success。若只是每日研究雷达，不主动批量打包或持久上传全文。
5. 日报优先输出高价值研究信号而非下载数量。每篇标注 `仅题录/摘要`、`全文已取得`、`关键表页码已核验` 三层证据，并对 P0/P1A/P1 给出与现稿主线、测度、识别策略和竞争性贡献对应的**一个可执行建议**。若只读了摘要，不能宣称审查过回归表；若 PDF 下载失败，单独报告失败原因并继续不依赖下载的文献发现。不能自动修改现稿。

**阶段边界/成本控制：** 目前验证的是《金融研究》2026(10) 前六篇的**固定集合**，不是九刊通用 PDF 爬取、自动回归表验证、永久PDF库或日报自动编排。下一阶段只在新的高相关论文确有成功取样后，才抽取公共下载辅助函数与来源适配，避免把为一次验收写的代码膨胀成难维护的框架。PDF Artifact 1日失效是有意的最小权限策略；长期知识应留在短量研究证据卡（标题、链接、版本、页码/表号、有限摘要、审计结论），不留原文复制品。


**已同步 ChatGPT 周期任务提示词（2026-11-19）**：现有自动化 `6a62e1a21e1c8191be0fdd3893473bd2`（Can Li学术研究每日雷达）在原提示词末添加“PDF 原文证据与研究报告格式”优先条款：仅高相关 P0/P1A/P1 按需补全合法公开原文；研究结论证据标为 `题录/摘要` / `完整PDF已核验` / `对应页码和回归表已核验`；区分 PDF 技术提取成功与学术表格证据；不把旧论文后补当今日新增；不自动打包所有九刊 PDF，不重建仓库，明确用户要求时才通过短期 ZIP Artifact 交付。**已实读确认任务仍启用，频率未改变**：原 `Asia/Taipei 09:30` 每日计划和北京时间 09:30 日报均保留，GitHub metadata Action 原两次/日 cron 保持不动。任务只改变日报证据字段/阅读优先级，不自动运行新的 PDF 定时采集。
