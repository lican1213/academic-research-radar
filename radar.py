"""Daily candidate finder for economics research; metadata is not a paper review."""

from __future__ import annotations

import argparse
import hashlib
import html
import json
import re
import time
import unicodedata
import urllib.error
import urllib.parse
import urllib.request
import xml.etree.ElementTree as ET
from datetime import datetime, timedelta, timezone
from html.parser import HTMLParser
from pathlib import Path


QUERIES = [
    "patient capital innovation",
    "institutional investors patent innovation",
    "international patent family",
    "patent PCT national phase",
    "geopolitical risk foreign direct investment",
    "supply chain resilience multinational firms",
    "patent text embedding innovation",
    "耐心资本 创新",
    "国际专利 布局",
    "跨境供应链 韧性",
]

ARXIV_QUERIES = [
    'all:patent AND (all:embedding OR all:semantic)',
    'all:innovation AND all:patent',
    'all:"supply chain" AND (all:resilience OR all:geopolitical)',
    'all:"artificial intelligence" AND (all:wages OR all:productivity)',
]

PROJECT_TERMS = {
    "P0": {
        "patient capital": 23, "long-term investor": 17,
        "institutional investor": 15, "intellectual property": 13,
        "international patent": 25, "patent family": 23,
        "pct national phase": 32, "patent grant": 15,
        "耐心资本": 26, "机构投资者": 15, "专利国际": 27,
        "专利族": 19, "知识产权": 12, "patent": 7,
    },
    "P1": {
        "geopolitical risk": 23, "foreign direct investment": 23,
        "overseas subsidiary": 25, "supply chain resilience": 28,
        "global value chain": 16, "multinational": 11,
        "地缘政治": 23, "跨境布局": 24, "海外子公司": 25,
        "供应链韧性": 28, "对外直接投资": 23,
    },
    "P2": {
        "patent embedding": 27, "patent text": 23,
        "prior art retrieval": 24, "patent similarity": 25,
        "breakthrough innovation": 20, "disruptive innovation": 15,
        "patent citation": 14, "cross-lingual": 14,
        "专利文本": 25, "突破式创新": 22, "渐进式创新": 19,
    },
    "P3": {
        "institutional ownership": 20, "corporate governance": 16,
        "digital transformation": 14, "investor horizon": 20,
        "企业创新": 15, "机构持股": 20,
    },
    "P4": {
        "ai wage": 22, "artificial intelligence productivity": 22,
        "labor share": 15, "income inequality": 15,
        "新质生产力": 16, "劳动收入": 20,
    },
}

ATOM = "{http://www.w3.org/2005/Atom}"
KEEP_DAYS = 180
MAX_CANDIDATES = 30
PROJECT_CAPS = {"P0": 12, "P1": 7, "P2": 7, "P3": 3, "P4": 3}


class _TextExtractor(HTMLParser):
    def __init__(self) -> None:
        super().__init__()
        self.bits: list[str] = []

    def handle_data(self, data: str) -> None:
        self.bits.append(data)


def strip_html(value: str) -> str:
    parser = _TextExtractor()
    parser.feed(html.unescape(value))
    return re.sub(r"\s+", " ", " ".join(parser.bits)).strip()


def normalize_title(title: str) -> str:
    title = unicodedata.normalize("NFKC", title).casefold()
    return re.sub(r"[^\w]+", "", title, flags=re.UNICODE).replace("_", "")


def iso_date(value: object) -> str | None:
    if not value:
        return None
    if isinstance(value, dict):
        parts = value.get("date-parts", [[]])
        if not parts or not parts[0]:
            return None
        nums = parts[0]
        try:
            return f"{int(nums[0]):04d}-{int(nums[1]) if len(nums) > 1 else 1:02d}-{int(nums[2]) if len(nums) > 2 else 1:02d}"
        except (TypeError, ValueError, IndexError):
            return None
    try:
        return datetime.fromisoformat(str(value).replace("Z", "+00:00")).date().isoformat()
    except ValueError:
        return None


def first_date(item: dict, fields: tuple[str, ...]) -> str | None:
    for field in fields:
        date = iso_date(item.get(field))
        if date:
            return date
    return None


def canonical_arxiv_id(url: str) -> tuple[str, str]:
    raw = url.split("/abs/")[-1].split("/pdf/")[-1].split("?")[0]
    match = re.search(r"(\d{4}\.\d{4,5}|[a-z.\-]+/\d{7})(v\d+)?$", raw, re.I)
    if not match:
        return raw, "v1"
    return match.group(1), match.group(2) or "v1"


def crossref_item(item: dict) -> dict | None:
    titles = item.get("title") or []
    title = strip_html(str(titles[0])) if titles else ""
    doi = str(item.get("DOI") or "").strip().lower()
    if not title or not doi:
        return None
    authors = []
    for author in item.get("author") or []:
        name = " ".join(str(author.get(x, "")).strip() for x in ("given", "family")).strip()
        if name:
            authors.append(name)
    outlet = item.get("container-title") or []
    created = first_date(item, ("created",))
    published = first_date(item, ("published-online", "published", "issued", "published-print"))
    return {
        "id": "doi:" + doi,
        "title": title,
        "authors": authors[:12],
        "url": "https://doi.org/" + doi,
        "doi": doi,
        "source": "crossref",
        "sources": ["crossref"],
        "venue": str(outlet[0]) if outlet else "",
        "type": str(item.get("type") or ""),
        "published_at": published,
        "metadata_created_at": created,
        "event_at": created,
        "event_type": "crossref_registration",
        "version": "",
        "abstract": strip_html(str(item.get("abstract") or ""))[:1800],
    }


def arxiv_items(payload: bytes) -> list[dict]:
    root = ET.fromstring(payload)
    items = []
    for entry in root.findall(ATOM + "entry"):
        title = " ".join((entry.findtext(ATOM + "title") or "").split())
        url = entry.findtext(ATOM + "id") or ""
        if not title or not url:
            continue
        ident, version = canonical_arxiv_id(url)
        authors = [" ".join((a.findtext(ATOM + "name") or "").split())
                   for a in entry.findall(ATOM + "author")]
        items.append({
            "id": "arxiv:" + ident,
            "title": title,
            "authors": [a for a in authors if a][:12],
            "url": "https://arxiv.org/abs/" + ident,
            "doi": "",
            "source": "arxiv",
            "sources": ["arxiv"],
            "venue": "arXiv",
            "type": "preprint",
            "published_at": iso_date(entry.findtext(ATOM + "published")),
            "metadata_created_at": None,
            "event_at": iso_date(entry.findtext(ATOM + "updated")),
            "event_type": "arxiv_version_update",
            "version": version,
            "abstract": " ".join((entry.findtext(ATOM + "summary") or "").split())[:1800],
        })
    return items


def prefilter(item: dict) -> dict:
    title = item["title"].casefold()
    abstract = (item.get("abstract") or "").casefold()
    combined = title + " " + abstract
    def any_term(*terms: str) -> bool:
        return any(term in combined for term in terms)

    patent = any_term("patent", "intellectual property", "专利", "知识产权")
    long_capital = any_term("patient capital", "long-term investor", "investor horizon", "耐心资本")
    investor = any_term("institutional investor", "institutional ownership", "机构投资者", "机构持股")
    innovation = any_term("innovation", "r&d", "研发", "创新")
    crossborder = any_term("international", "global", "cross-border", "foreign", "overseas", "pct", "多国", "国际", "海外", "跨境")
    fdi = any_term("foreign direct investment", "ofdi", "overseas subsidiary", "跨境布局", "海外子公司", "对外直接投资")
    supply = any_term("supply chain", "global value chain", "供应链", "产业链")
    shock = any_term("geopolitical", "trade war", "tariff", "geoeconomic", "地缘政治", "贸易摩擦")
    ai = any_term("artificial intelligence", "generative ai", "machine learning", "人工智能", "大模型")
    eligibility = {
        "P0": (patent and (crossborder or investor or long_capital or any_term("patent family", "专利族")))
              or (long_capital and innovation),
        "P1": (shock and (fdi or supply)) or (ai and (fdi or supply))
              or (supply and any_term("resilience", "韧性") and crossborder),
        "P2": (patent and any_term("embedding", "semantic", "text", "similarity", "prior art", "claim", "retrieval", "citation", "突破", "颠覆", "文本", "相似度"))
              or any_term("突破式创新", "breakthrough innovation", "disruptive innovation"),
        "P3": investor and innovation,
        "P4": ai and any_term("wage", "labor", "income", "productivity", "收入", "劳动", "生产率"),
    }
    scored = {}
    for project, terms in PROJECT_TERMS.items():
        value = sum(weight for term, weight in terms.items() if term in title)
        value += sum(weight // 3 for term, weight in terms.items() if term not in title and term in abstract)
        scored[project] = value
    eligible = [project for project in PROJECT_TERMS if eligibility[project]]
    best = eligible[0] if eligible else max(scored, key=lambda p: scored[p])
    item = dict(item)
    item["project"] = best
    item["eligible"] = bool(eligible)
    item["prefilter_score"] = min(100, 22 + scored[best])
    return item


def fingerprint(item: dict) -> str:
    # Exclude metadata timestamps and abstracts: indexing churn is not a paper revision.
    content = "\0".join((normalize_title(item["title"]), item.get("version") or ""))
    return hashlib.sha256(content.encode("utf-8")).hexdigest()[:20]


def identity_keys(item: dict) -> list[str]:
    result = [item["id"]]
    norm = normalize_title(item["title"])
    if norm:
        result.append("title:" + norm)
    return result


def consolidate(items: list[dict]) -> list[dict]:
    grouped: dict[str, dict] = {}
    for item in items:
        key = normalize_title(item["title"]) or item["id"]
        previous = grouped.get(key)
        if previous is None:
            grouped[key] = item
            continue
        # Prefer the journal's canonical DOI while preserving the preprint source.
        preferred = item if item.get("doi") and not previous.get("doi") else previous
        other = previous if preferred is item else item
        preferred = dict(preferred)
        preferred["sources"] = sorted(set(preferred["sources"] + other["sources"]))
        preferred["alternate_ids"] = sorted(set(
            preferred.get("alternate_ids", []) + other.get("alternate_ids", []) + [other["id"]]
        ))
        if other.get("version") and not preferred.get("version"):
            preferred["version"] = other["version"]
        if len(other.get("abstract") or "") > len(preferred.get("abstract") or ""):
            preferred["abstract"] = other["abstract"]
        if other.get("event_at") and (not preferred.get("event_at") or other["event_at"] > preferred["event_at"]):
            preferred["event_at"] = other["event_at"]
            preferred["event_type"] = other["event_type"]
        grouped[key] = preferred
    return list(grouped.values())


def select_new(items: list[dict], seen: dict, now: datetime, *, limit: int = MAX_CANDIDATES) -> tuple[list[dict], dict]:
    state = dict(seen)
    new = []
    selected_by_project = {project: 0 for project in PROJECT_CAPS}
    for item in sorted(items, key=lambda p: (list(PROJECT_CAPS).index(p["project"]), -p["prefilter_score"], p["title"])):
        if not item.get("eligible") or item["prefilter_score"] < 40:
            continue
        keys = identity_keys(item) + item.get("alternate_ids", [])
        old = next((state[k] for k in keys if k in state), None)
        emitted_before = bool(old and old.get("emitted", False))
        title_norm = normalize_title(item["title"])
        version = item.get("version") or (old.get("version", "") if old else "")
        doi = item.get("doi") or (old.get("doi", "") if old else "")
        record = {"fingerprint": fingerprint({**item, "version": version}),
                  "title_norm": title_norm, "version": version, "doi": doi,
                  "last_seen": now.date().isoformat(), "emitted": emitted_before}
        updated_version = bool(old and item.get("version") and old.get("version") and item["version"] != old["version"])
        changed_title = bool(old and old.get("title_norm") and old["title_norm"] != title_norm)
        newly_published = bool(old and "doi" in old and item.get("doi") and not old.get("doi"))
        legacy_changed = bool(old and "title_norm" not in old and old.get("fingerprint") != record["fingerprint"])
        must_emit = not emitted_before or updated_version or changed_title or newly_published or legacy_changed
        can_emit = selected_by_project[item["project"]] < PROJECT_CAPS[item["project"]] and len(new) < limit
        if must_emit and can_emit:
            item = {k: v for k, v in item.items() if k != "abstract"}
            item["change"] = ("new" if not old else "newly_selected" if not emitted_before
                              else "formal_publication_or_doi_added" if newly_published
                              else "new_version" if updated_version else "title_revision")
            new.append(item)
            selected_by_project[item["project"]] += 1
            record["emitted"] = True
        elif must_emit and old:
            # Keep last emitted version/DOI until the revision is actually surfaced.
            record = dict(old)
            record["last_seen"] = now.date().isoformat()
            record.setdefault("emitted", False)
        for key in keys:
            state[key] = record
    cutoff = (now.date() - timedelta(days=KEEP_DAYS)).isoformat()
    state = {k: v for k, v in state.items() if v.get("last_seen", "") >= cutoff}
    return new[:limit], state


def get_url(url: str, *, timeout: int = 20) -> bytes:
    req = urllib.request.Request(url, headers={"User-Agent": "AcademicResearchRadar/0.1 (public metadata researcher)", "Accept": "application/json,application/atom+xml"})
    for attempt in range(3):
        try:
            with urllib.request.urlopen(req, timeout=timeout) as response:
                return response.read()
        except urllib.error.HTTPError as error:
            if error.code not in (429, 502, 503) or attempt == 2:
                raise
            # Rate-limit responses can occur on shared GitHub runner IPs.
            retry_after = error.headers.get("Retry-After") if error.headers else None
            try:
                pause = min(8.0, max(1.0, float(retry_after))) if retry_after else 2.0 ** (attempt + 1)
            except ValueError:
                pause = 2.0 ** (attempt + 1)
            time.sleep(pause)
    raise AssertionError("unreachable")


def fetch_crossref(since: str, get=get_url) -> tuple[list[dict], dict]:
    all_items = []
    errors = []
    ok = 0
    for query in QUERIES:
        params = urllib.parse.urlencode({
            "query.bibliographic": query, "filter": "from-created-date:" + since,
            "rows": 30, "select": "DOI,title,author,created,published-online,published,published-print,issued,container-title,abstract,type",
        })
        try:
            data = json.loads(get("https://api.crossref.org/works?" + params))
            records = data["message"]["items"]
            all_items.extend(row for obj in records if (row := crossref_item(obj)))
            ok += 1
        except (OSError, ValueError, KeyError, TypeError, ET.ParseError) as exc:
            errors.append(f"{query}: {type(exc).__name__}: {str(exc)[:120]}")
        time.sleep(0.75)  # Leave headroom for shared-runner rate limiting.
    return all_items, {"status": "ok" if not errors else "degraded" if ok else "failed",
                       "queries_ok": ok, "queries_total": len(QUERIES),
                       "records": len(all_items), "errors": errors}


def fetch_arxiv(since: str, get=get_url) -> tuple[list[dict], dict]:
    all_items = []
    errors = []
    ok = 0
    for n, query in enumerate(ARXIV_QUERIES):
        if n:
            time.sleep(3)  # arXiv asks for a 3s interval between requests.
        params = urllib.parse.urlencode({"search_query": query, "start": 0, "max_results": 30,
                                         "sortBy": "lastUpdatedDate", "sortOrder": "descending"})
        try:
            all_items.extend(item for item in arxiv_items(get("https://export.arxiv.org/api/query?" + params))
                             if item["event_at"] and item["event_at"] >= since)
            ok += 1
        except (OSError, ValueError, KeyError, TypeError, ET.ParseError) as exc:
            errors.append(f"{query}: {type(exc).__name__}: {str(exc)[:120]}")
    return all_items, {"status": "ok" if not errors else "degraded" if ok else "failed",
                       "queries_ok": ok, "queries_total": len(ARXIV_QUERIES),
                       "records": len(all_items), "errors": errors}


def markdown_report(report: dict) -> str:
    result = ["# Academic Research Radar — " + report["generated_at"], "",
              f"**Status:** {report['status']}; **New or changed candidates:** {len(report['new_candidates'])}", "",
              "This is metadata triage, not a verified reading or recommendation.", ""]
    for name, status in report["source_status"].items():
        result.append(f"- {name}: {status['status']}; {status['queries_ok']}/{status['queries_total']} queries; {status['records']} records")
        for error in status["errors"]:
            result.append(f"  - Error: {error}")
    if "chinese_journals" in report:
        result.extend(["", "## 中文七刊逐刊监测（仅公开目录，非文章审读）", ""])
        for journal in report["chinese_journals"].values():
            result.append(
                f"- [{journal['journal']}]({journal['url']}): {journal['status']}; "
                f"来源={journal['source_kind']}; 期次={journal.get('issue') or '未核验'}; "
                f"可解析文章={journal['article_count']}; {journal.get('reason', '')}"
            )
        result.extend(["", "### 本次首次观察到的中文目录文章（不等于今日发表）", ""])
        for item in report.get("chinese_new_candidates", []):
            result.append(f"- [{item['title']}]({item['url']}) — {item['journal']} "
                          f"{item['issue']}; 首次观察 {item['first_observed_at']}; "
                          f"目录在线标记 {item.get('toc_online_at') or '无'}（非论文发表日期）; "
                          "单篇论文发表日期待核验")
        if not report.get("chinese_new_candidates"):
            result.append("本次无新目录文章；若存在 catalog_only/unverified/failed，则不能宣称已覆盖全部中文论文。")
    result.extend(["", "## New or revised candidates", ""])
    for item in report["new_candidates"]:
        safe_title = item["title"].replace("[", r"\[").replace("]", r"\]")
        result.append(f"- [{safe_title}]({item['url']}) — {item['project']}, prefilter {item['prefilter_score']}, {item['event_type']} {item['event_at']}, {item['change']}")
    if not report["new_candidates"]:
        result.append("None passed the metadata prefilter. This does not imply no relevant papers exist.")
    result.append("")
    return "\n".join(result)


def run(out: Path, now: datetime, lookback_days: int | None = None,
        crossref=fetch_crossref, arxiv=fetch_arxiv, chinese=None) -> dict:
    out.mkdir(parents=True, exist_ok=True)
    seen_file = out / "seen.json"
    if seen_file.exists():
        seen = json.loads(seen_file.read_text(encoding="utf-8"))
        if not isinstance(seen, dict):
            raise ValueError("seen.json is not an object")
    else:
        seen = {}
    days = lookback_days if lookback_days is not None else (3 if seen else 7)
    since = (now.date() - timedelta(days=days)).isoformat()
    cross_items, cross_status = crossref(since)
    arxiv_items_result, arxiv_status = arxiv(since)
    sources = {"crossref": cross_status, "arxiv": arxiv_status}
    chinese_result = None
    if chinese is not None:
        chinese_result = chinese(out, now)
        sources["chinese_journals"] = chinese_result["source_status"]
    successful = sum(status["queries_ok"] for status in sources.values())
    total = sum(status["queries_total"] for status in sources.values())
    status = ("failed" if successful == 0 else
              "ok" if successful == total and all(s["status"] == "ok" for s in sources.values())
              else "degraded")
    candidates = consolidate([prefilter(item) for item in cross_items + arxiv_items_result])
    # Crossref registered date and arXiv updated date are events, not a shared publication date.
    candidates = [item for item in candidates if item.get("event_at") and since <= item["event_at"] <= now.date().isoformat()]
    ranked = sorted((item for item in candidates if item.get("eligible")),
                    key=lambda p: (list(PROJECT_CAPS).index(p["project"]), -p["prefilter_score"], p["title"]))
    new, state = select_new(candidates, seen, now)
    report = {
        "generated_at": now.isoformat(), "status": status, "since": since,
        "source_status": sources, "scanned_candidates": len(candidates),
        "prefilter_pass_count": sum(item["eligible"] and item["prefilter_score"] >= 40 for item in candidates),
        "prefilter_diagnostics": [{
            "title": item["title"], "project": item["project"],
            "score": item["prefilter_score"], "source": item["source"],
            "event_at": item["event_at"], "url": item["url"]
        } for item in ranked[:12] if item["prefilter_score"] >= 40],
        "new_candidates": new, "note": "Metadata candidates only; verify paper content and bibliographic dates at primary sources."
    }
    if chinese_result is not None:
        report["chinese_journals"] = chinese_result["source_status"]["journals"]
        report["chinese_new_candidates"] = chinese_result["new_candidates"]
        report["note"] += " Chinese catalog first_seen is NOT publication date; incomplete catalogs require manual checking."
    (out / "latest.json").write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    (out / "latest.md").write_text(markdown_report(report), encoding="utf-8")
    # On complete outage keep the old seen state; recovered sources must still be discoverable.
    if successful:
        seen_file.write_text(json.dumps(state, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    return report


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--out", type=Path, default=Path("data"))
    parser.add_argument("--lookback-days", type=int)
    args = parser.parse_args()
    if args.lookback_days is not None and not 1 <= args.lookback_days <= 30:
        parser.error("--lookback-days must be from 1 to 30")
    from chinese_journals import scan_chinese_journals
    report = run(args.out, datetime.now(timezone.utc), args.lookback_days,
                 chinese=scan_chinese_journals)
    print(json.dumps({k: v for k, v in report.items() if k != "new_candidates"}, ensure_ascii=False))
    return 2 if report["status"] == "failed" else 0


if __name__ == "__main__":
    raise SystemExit(main())
