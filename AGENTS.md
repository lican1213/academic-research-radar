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

- Always monitor the seven named journals and preserve each journal's source URL, source_kind, issue, article_count and status in `data/latest.json`.
- Publisher `ok`, authoritative catalog `catalog_only`, `stale_index`, `unverified` and `failed` MUST remain distinct. Do not infer 'no new articles' from `catalog_only`.
- `first_observed_at` is a website discovery event, NEVER an article publication date; leave `published_at=null` until individually verified.
- A page with only a journal name/issue must NOT be parsed as article-level coverage. A page with an unrelated external link must NOT generate a paper candidate.
- Preserve last known good catalog state when a source times out or regresses. Initial scan seeds baseline rather than re-notifying all historical papers.
- `data/chinese_seen.json` and `data/latest.json` must be committed together by the scan Action; editorial/HTML indexing gaps must be listed for daily independent research.
