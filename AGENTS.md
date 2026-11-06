# Academic Radar Agent Guide

Read [MOC.md](MOC.md) and [README.md](README.md) before changing anything.

## Job boundary

This repository gathers **public bibliographic metadata**. It does not make scholarly conclusions, modify manuscripts or data, fetch copyrighted full texts, or auto-publish claims. The ChatGPT daily research task independently verifies primary sources and relevance.

## Change protocol

1. State the defect or missed research signal with a reproducible fixture.
2. Run `python3 -m unittest discover -s tests -v` and `python3 -m compileall -q radar.py tests`.
3. Keep source failures visible. A fully failed scan must fail the Action, not appear as a zero-paper success.
4. Do not change dedup signatures to suppress a test failure without a concrete example. Differentiate new arXiv versions, first journal DOI, and harmless Crossref indexing churn.
5. Add concise changes and known limitations to `MOC.md`. Avoid new dependencies unless an existing source genuinely requires them.

## Research output gate

- A `prefilter_score` describes lexical topic match only, never quality or causality.
- `metadata_created_at` is not a publication date.
- Labels `ok`, `degraded`, `failed`, and `not_run` have distinct meanings.
- No project-specific unpublished materials, user credentials, abstracts, or copyrighted full texts are checked in.
