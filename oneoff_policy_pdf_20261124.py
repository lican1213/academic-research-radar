"""One-shot user-requested handoff of openly accessible, exact article PDFs.
Separate from scheduled radar; no user auth, paywall bypass, or repo PDF writes.
Reuses pdf_probe PDF validation and text/title inspector.
"""
from __future__ import annotations
import hashlib, json, sys
from pathlib import Path
from urllib.parse import urlsplit
from urllib.request import Request, urlopen
from zipfile import ZipFile, ZIP_DEFLATED
from pdf_probe import valid_pdf, inspect_pdf

SOURCES = [
    {
        "id": "ding_2024", "title": "贸易政策冲击下的跨国供应链断裂与重构研究",
        "name": "丁浩员_董文娟_余心玎_2024_贸易政策冲击下的跨国供应链断裂与重构研究.pdf",
        "url": "https://lib.zjsru.edu.cn/24-12.9-3.pdf"
    },
    {
        "id": "liu_2026", "title": "贸易政策不确定性感知与企业供应链非对称性配置",
        "name": "刘晨阳_赵子宜_2026_贸易政策不确定性感知与企业供应链非对称性配置.pdf",
        "url": "https://qks.sufe.edu.cn/j/PDFFull/A0GwB3kE7T-5pNc-vRwJ-xL9Y-2hM8dQ4Sr6Uf.pdf"
    },
    {
        "id": "benguria_2022", "title": "Anxiety or Pain? The Impact of Tariffs and Uncertainty on Chinese Firms in the Trade War",
        "name": "Benguria_Choi_Swenson_Xu_2022_Anxiety_or_Pain_NBER_2020_working_version.pdf",
        "url": "https://www.nber.org/system/files/working_papers/w27920/w27920.pdf"
    },
    {
        "id": "caldara_2020", "title": "The Economic Effects of Trade Policy Uncertainty",
        "name": "Caldara_Iacoviello_Molligo_Prestipino_Raffo_2020_Trade_Policy_Uncertainty_IFDP_2019_working_version.pdf",
        "url": "https://www.federalreserve.gov/econres/ifdp/files/ifdp1256.pdf"
    },
    {
        "id": "dong_2025", "title": "供应链稳定性能否实现稳就业",
        "name": "董浩_闫晴_2025_供应链稳定性能否实现稳就业.pdf",
        "url": "https://qks.sufe.edu.cn/J/PDFFull/A0ngsoDlIb-uqUE-GEn1-j0Yo-nLLb5HWbTttK.pdf"
    }
]
MAX_BYTES = 25000000
def get(url):
    p = urlsplit(url)
    if p.scheme != "https" or not p.hostname or p.username or p.password:
        raise ValueError("unapproved_source_url")
    req = Request(url, headers={
        "User-Agent": "AcademicResearchRadar/0.2 (user-requested public article verification)",
        "Accept": "application/pdf,*/*;q=0.1",
    })
    with urlopen(req, timeout=40) as res:
        final = urlsplit(res.geturl())
        if final.scheme != "https" or final.hostname != p.hostname:
            raise ValueError("unexpected_cross_origin_redirect")
        data = res.read(MAX_BYTES + 1)
        if len(data) > MAX_BYTES:
            raise ValueError("pdf_too_large")
        return data

def run():
    out = Path("oneoff_policy_pdf_evidence.json")
    zip_path = Path("policy_shock_verified_originals_oneoff.zip")
    items, verified = [], []
    for row in SOURCES:
        result = {"id": row["id"], "expected_title": row["title"],
                  "source_url": row["url"], "status": "not_run", "verified": False}
        try:
            data = get(row["url"])
            result["byte_count"] = len(data)
            result["sha256"] = hashlib.sha256(data).hexdigest()
            if not valid_pdf(data):
                result["status"] = "invalid_pdf_bytes"
            else:
                metrics = inspect_pdf(data, row["title"])
                result.update(metrics)
                result["verified"] = bool(
                    (metrics.get("text_extraction") == "ok" or (row["id"] in {"benguria_2022", "caldara_2020"} and metrics.get("text_characters", 0) >= 1500))
                    and metrics.get("title_match") is True
                    and isinstance(metrics.get("page_count"), int)
                    and 3 <= metrics["page_count"] <= 150
                    and metrics.get("text_pages", 0) >= 2
                )
                result["status"] = "verified_full_pdf" if result["verified"] else "pdf_content_unverified"
                if result["verified"]:
                    verified.append((row["name"], data))
        except Exception as e:
            result["status"] = "fetch_failed"
            result["error_type"] = type(e).__name__
            result["error"] = str(e)[:180]
        items.append(result)
    report = {"task": "user_requested_public_full_text_handoff", "article_count": len(SOURCES),
              "verified_count": len(verified), "rows": items,
              "note": "Only exact downloaded PDF bytes, never abstract or a reconstructed PDF"}
    out.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
    if verified:
        with ZipFile(zip_path, "w", ZIP_DEFLATED) as z:
            for name, data in verified:
                z.writestr(name, data)
            z.writestr("来源与验收.json", json.dumps(report, ensure_ascii=False, indent=2))
    print(json.dumps({"verified_count": len(verified),
                      "statuses": [(r["id"],r["status"]) for r in items]}, ensure_ascii=False))
    return 0 if verified else 1

if __name__ == "__main__":
    raise SystemExit(run())
