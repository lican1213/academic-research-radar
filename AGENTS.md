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
- PDF acceptance is a separate read-only, unscheduled workflow; metadata or metrics may be retained as an artifact, **no publisher PDF or extracted text in repository/artifact**. A successful unrelated control PDF cannot pass the targeted journal gate.
- Do not introduce text mining/RAG/LLM evaluation pipelines until one real relevant PDF is retrieved and the extraction is proven useful; link and metadata discovery must continue independently when PDFs fail.


## Publisher-HTTP exception (2026-11-19)

- The journal itself publicly advertises `http://www.jryj.org.cn`; an actual Runner confirmed HTTP200 article HTML and an explicit official PDF URL. Its HTTPS endpoint has a mismatched cert. Therefore the isolated PDF acceptance probe MAY use **only** the exact 2026-10 approved article IDs1662–1667 on that official HTTP host, with the article and PDF download paths strictly checked. No TLS validation bypass, proxy, user auth, or generic HTTP fallback.
- This HTTP exception sacrifices authenticated transport integrity. Do not describe the download as cryptographically authenticated. Check independent article bibliographic metadata, extracted title, PDF page count, SHA256 and text before recommending scholarly claims; prefer HTTPS when genuinely fixed.
- Never commit or upload copyrighted PDF bytes or recovered full text. Metadata-only artifact and fail-closed six-article acceptance are mandatory.
