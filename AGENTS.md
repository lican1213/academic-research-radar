# Academic Radar Agent Guide

Read [MOC.md](MOC.md) and [README.md](README.md) before changing anything.

## Job boundary

This repository gathers **public bibliographic metadata**. It does not make scholarly conclusions, modify manuscripts or data, fetch copyrighted full texts, or auto-publish claims. The ChatGPT daily research task independently verifies primary sources and relevance.

## Change protocol

1. State the defect or missed research signal with a reproducible fixture.
2. Run `python3 -m unittest discover -s tests -v` and `python3 -m compileall -q radar.py chinese_journals.py tests`.
3. Keep source failures visible. A fully failed scan must fail the Action, not appear as a zero-paper success.
4. Do not change dedup signatures to suppress a test failure without a concrete example. Differentiate new arXiv versions, first journal DOI, and harmless Crossref indexing churn.
5. Add concise changes and known limitations to `MOC.md`. Avoid new dependencies unless an existing source genuinely requires them.

## Research output gate

- A `prefilter_score` describes lexical topic match only, never quality or causality.
- `metadata_created_at` is not a publication date.
- Labels `ok`, `degraded`, `failed`, and `not_run` have distinct meanings.
- No project-specific unpublished materials, user credentials, abstracts, or copyrighted full texts are checked in.

## Chinese journal integrity gate

- Always monitor the nine named journals and preserve each journal's source URL, source_kind, issue, article_count and status in `data/latest.json`.
- Publisher `ok`, authoritative catalog `catalog_only`, `rss_only`, `stale_index`, `unverified` and `failed` MUST remain distinct. Do not infer 'no new articles' from `catalog_only`.
- `first_observed_at` is a website discovery event, NEVER an article publication date; leave `published_at=null` until individually verified.
- RSS must validate journal identity and article links; RSS event date is never a verified first publication date. `rss_only` is not complete TOC coverage; separately record failure for either channel. Do not bypass login, CAPTCHA or TLS verification.
- A page with only a journal name/issue must NOT be parsed as article-level coverage. A page with an unrelated external link must NOT generate a paper candidate.
- Preserve last known good catalog state when a source times out or regresses. Initial scan seeds baseline rather than re-notifying all historical papers.
- `data/chinese_seen.json` and `data/latest.json` must be committed together by the scan Action; editorial/HTML indexing gaps must be listed for daily independent research.

- Treat mixed_links as partial; current-issue snapshots retain parsed metadata, not verified link reachability. Never promote historical/unbound audit rows to normal incremental candidates. Do not update article-success time for issue-only responses. Add DOI and canonical stable article URL aliases without clearing the prior ledger. Stage 3 differentiates prefilter passes, new delivery, historical backfill and incomplete coverage.


## Stage-2/3 source and backfill contract (2026-11-19)
- For 管理世界/金融研究, use immutable independent trusted URLs only. `www.cqvip.com` is an index, not the publisher, and a verified year/issue or `index_claimed_paper_count` is **never** an article link or publication date.
- Preserve each `source_attempts` diagnostic, including when every source fails. Never downgrade TLS verification or treat DNS/timeout as no-paper evidence. Do not replace current verified source with a regressed issue.
- `catalog_only` can update last observed *issue* but cannot refresh last article-success time or invent an article identity.
- When article-detail links first recover on the SAME issue after only issue-level baseline, put those audit leads under `chinese_historical_backfill_leads`; keep `chinese_new_candidates` unchanged and `published_at=null/date_verified=false`. Do not silence the lead, falsely date it, or turn an entire historical issue into daily new papers.
- Test fixtures are not production proof. Require exact head SHA, real action run, committed latest JSON, and independently check the details before reporting article-level coverage. Stage-3 cross-source DOI/URL identities must preserve the existing issued/emitted ledger.


## PDF readback gate

- PDF success requires **actual bytes from an approved publisher**, valid PDF header and EOF, byte size and SHA256; an article abstract page, a mocked test, or mere link is not acceptance. Do not weaken TLS/cross-origin controls.
- PDF acceptance is a separate, unscheduled workflow; default output is metadata-only. **Never commit article PDFs or extracted full text into the repository.** If the user explicitly asks to receive the original documents and access is lawful, a tightly scoped, one-day ZIP artifact may temporarily contain *verified original PDFs only* for handoff via GitHub `download_workflow_artifact`. No standing public PDF archive and no bulk article text artifact. An unrelated control PDF cannot pass a journal-specific gate.
- Do not introduce text mining/RAG/LLM evaluation pipelines until one real relevant PDF is retrieved and the extraction is proven useful; link and metadata discovery must continue independently when PDFs fail.


## Publisher-HTTP exception (2026-11-19)

- The journal itself publicly advertises `http://www.jryj.org.cn`; an actual Runner confirmed HTTP200 article HTML and an explicit official PDF URL. Its HTTPS endpoint has a mismatched cert. Therefore the isolated PDF acceptance probe MAY use **only** the exact 2026-10 approved article IDs1662–1667 on that official HTTP host, with the article and PDF download paths strictly checked. No TLS validation bypass, proxy, user auth, or generic HTTP fallback.
- This HTTP exception sacrifices authenticated transport integrity. Do not describe the download as cryptographically authenticated. Check independent article bibliographic metadata, extracted title, PDF page count, SHA256 and text before recommending scholarly claims; prefer HTTPS when genuinely fixed.
- Never commit copyrighted PDF bytes or recovered full text. Default artifact is metadata-only; the user-authorized short-lived original-PDF ZIP delivery exception above requires exact six-article checksums, a one-day artifact, and actual retrieval before stating handoff success.


## Research-radar daily PDF evidence contract (2026-11-19)

- Follow the final `MOC.md` section for PR #16/#17 and actual delivered run 44474347819; earlier notes declaring PDF delivery impossible or artifacts forbidden describe **superseded historical state**.
- Current `pdf_probe.py` is a **hard-coded six-paper acceptance sample**, not a reusable journal PDF importer. Do not promise that arbitrary papers or all nine journals are download-ready. Source identity/date checks and an independent live run are required for each new paper.
- Keep daily report at 0–3 priority leads / 0–2 watch leads. For high-value P0/P1A/P1 papers, add evidence state: `metadata/abstract only`, `verified full PDF`, or `specific PDF page/table examined`. Only the last state supports claims about coefficient/identification-table details. Link the paper and cite actual page/table; do not infer causal evidence from an abstract.
- Normal daily radar is **read-only** and must not trigger GitHub code changes, new scheduled workflows, or batch-PDF uploads. A user-requested handoff can use a short-lived, authenticated GitHub artifact workflow; verify the artifact is actually retrievable and contains the expected originals. An expiring artifact cannot serve as a permanent literature source.


## Cross-publisher article-level PDF probe (2026-11-19)

- See the latest `MOC.md` cross-publisher production proof: PRs #19–#22, final run 44478691394 at exact SHA e70d4ebc924cd8609ebc4e369f5c765c67a3d06f. `pdf_candidate.py` and `tests/pdf_pilot_manifest.json` are **an opt-in, curated verified-source pilot**, NOT a generic nine-journal bulk scraper. It reads real article HTML `citation_pdf_url` or verified publisher PDF links; additional publisher hosts/aliases require actual source evidence and tight allowance checks.
- Distinguish `pdf_verified`, `text_verified`, and `table_verified`. 3/3 true for first two, **all `table_verified=false`**. A successful PDF extraction never licenses fabrication of regression table claims.
- Keep CI and real Action acceptance separate. Gate for this pilot requires two *different* publisher domains on real Github Runner with verified PDF text; an optional third failure must remain visible. New candidate/host/version requires revalidation, not copying the six legacy JRYJ article IDs or hashes.
- Main twice-daily metadata scan and ChatGPT daily report remain independent and read-only. Do not silently connect PDF requests to the scheduled scan or save copyrighted PDFs/paragraphs in the repository; user-authorized temporary original-PDF handoff uses its separately documented ephemeral workflow.
