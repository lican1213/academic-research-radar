"""One-off anonymous CBPT journal PDF UI diagnostics. No sign-in or content archive.

Reports visible PDF controls and sanitized request/response metadata. Does not
follow paywalls, bypass CAPTCHA, save PDFs, or capture cookies/token query values.
"""
import json
import re
from pathlib import Path
from urllib.parse import urlsplit
from pdf_cbpt import TARGETS

KEYWORDS = ("pdf", "download", "fulltext", "fulltextdownload", "minio",
            "paper", "article", "file", "export", "cnki", "reader")


def shape_url(url):
    p = urlsplit(url)
    return {"host": p.hostname or "", "path": p.path[:150],
            "query_names": sorted(set(re.findall(r"(?:^|&)([A-Za-z_]+)=", p.query)))[:10]}


def visible_actions(page):
    # DOM-assisted audit to distinguish hidden template elements from visible buttons.
    return page.evaluate(r"""() => {
      const words = ['PDF', '下载本文', '中文数据', '英文数据'];
      const nodes = Array.from(document.querySelectorAll('a,button,span,div,li,input,[role=button]'));
      return nodes.filter(el => words.includes((el.innerText || el.value || '').trim()) &&
        Array.from(el.children || []).every(c => !words.includes((c.innerText || '').trim())))
        .slice(0,35).map(el => {
          const box = el.getBoundingClientRect(), style = getComputedStyle(el);
          const p = el.closest('a,button,[role=button]') || el;
          return {tag:el.tagName, text:(el.innerText||el.value||'').trim(),
            visible:!!(box.width && box.height) && style.visibility!=='hidden' && style.display!=='none',
            parent_tag:p.tagName, parent_class: String(p.className || '').slice(0,100),
            parent_href: p.getAttribute('href')?.slice(0,120) || null,
            parent_onclick: p.getAttribute('onclick')?.slice(0,160) || null};
        })
    }""")


def diagnose_one(spec):
    from playwright.sync_api import sync_playwright
    result = {"key": spec["key"], "article_url": spec["article_url"],
              "requests": [], "pdf_responses": [], "downloads": [], "ui": [],
              "download_api": []}
    with sync_playwright() as p:
        browser = p.chromium.launch(headless=True, args=["--no-sandbox"])
        ctx = browser.new_context(accept_downloads=True)
        page = ctx.new_page()
        def request(req):
            u = req.url
            parsed = urlsplit(u)
            if parsed.hostname and (parsed.hostname.endswith("cnki.net") or
                                    parsed.hostname.endswith("cbpt.cnki.net")):
                if any(k in parsed.path.lower() for k in KEYWORDS):
                    if len(result["requests"]) < 90:
                        result["requests"].append({"method":req.method, **shape_url(u)})
        def response(resp):
            content_type = resp.headers.get("content-type","").lower()
            if ("pdf" in content_type or "octet-stream" in content_type or
                ".pdf" in urlsplit(resp.url).path.lower()):
                result["pdf_responses"].append(
                    {"status":resp.status, "mime":content_type, **shape_url(resp.url)})
            if "getChinesDownloadInfoByEnglishPaper" in urlsplit(resp.url).path:
                record = {"http_status":resp.status, "mime":content_type,
                          "route":shape_url(resp.url)}
                try:
                    value = resp.json()
                    def summarize(obj, depth=0):
                        if depth >= 3:
                            return type(obj).__name__
                        if isinstance(obj,dict):
                            return {str(k)[:50]:summarize(v,depth+1)
                                    for k,v in list(obj.items())[:20]}
                        if isinstance(obj,list):
                            return [summarize(v,depth+1) for v in obj[:3]]
                        if isinstance(obj,str):
                            if obj.startswith(("http://","https://")):
                                return shape_url(obj)
                            return obj[:100] if len(obj)<150 else ("str_length:"+str(len(obj)))
                        return obj
                    record["body_shape"]=summarize(value)
                except Exception as exc:
                    record["body_parse_error"]=type(exc).__name__
                result["download_api"].append(record)
        def download(d):
            result["downloads"].append({"suggested_filename":d.suggested_filename[:100]})
        page.on("request", request)
        page.on("response", response)
        page.on("download", download)
        try:
            page.goto(spec["article_url"], wait_until="domcontentloaded", timeout=30000)
            page.wait_for_timeout(1800)
            try:
                code = page.evaluate("typeof getSpecialPDFUrl === 'function' ? getSpecialPDFUrl.toString() : ''")
                result["pdf_handler_excerpt"] = code[:1500]
            except Exception:
                result["pdf_handler_excerpt"] = "not_available"
            result["initial_buttons"] = visible_actions(page)
            result["initial_visible_pdf"] = sum(x["visible"] and x["text"]=="PDF"
                                                for x in result["initial_buttons"])
            # Only click clear, visible public PDF/download controls. No login/captcha.
            for label in ("下载本文", "PDF"):
                loc = page.get_by_text(label, exact=True)
                row={"label":label,"matching":loc.count(),"visible":sum(
                    loc.nth(i).is_visible() for i in range(min(loc.count(),15)))}
                result["ui"].append(row)
                pressed=False
                for i in range(min(loc.count(),15)):
                    el = loc.nth(i)
                    if not el.is_visible():
                        continue
                    try:
                        el.click(timeout=4000)
                        page.wait_for_timeout(1600)
                        pressed=True
                        row["clicked_index"]=i
                        row["after_buttons"]=visible_actions(page)
                        row["after_domain"]=urlsplit(page.url).hostname
                        row["download_count"]=len(result["downloads"])
                        break
                    except Exception as err:
                        row.setdefault("errors",[]).append(type(err).__name__)
                if not pressed:
                    row["result"]="no_clickable_visible_exact_label"
            # Inspect CNKI window opened by the publisher's documented null-PDF fallback.
            # Never copy v/token query values, cookies, or full article contents.
            result["cnki_fallback_pages"] = []
            for child in ctx.pages:
                if child == page:
                    continue
                entry = {"url": shape_url(child.url)}
                try:
                    child.wait_for_load_state("domcontentloaded", timeout=10000)
                    entry["url"] = shape_url(child.url)
                    if urlsplit(child.url).hostname == "kns.cnki.net":
                        body = child.locator("body").inner_text(timeout=2500)[:12000]
                        entry["title_seen"] = spec["title"][:10] in body
                        entry["login_prompt_seen"] = any(word in body for word in ("登录", "请登录", "机构登录"))
                        entry["pdf_download_controls"] = sum(child.get_by_text(word, exact=False).count()
                                                             for word in ("PDF下载", "PDF 下载", "CAJ下载"))
                        entry["body_char_count_scanned"] = len(body)
                except Exception as err:
                    entry["inspection_error"] = type(err).__name__
                result["cnki_fallback_pages"].append(entry)
            # On popup choose '中文数据' only if visible, no payment/auth.
            loc=page.get_by_text("中文数据", exact=True)
            if any(loc.nth(i).is_visible() for i in range(min(loc.count(),10))):
                for i in range(min(loc.count(),10)):
                    if loc.nth(i).is_visible():
                        try:
                            loc.nth(i).click(timeout=2000)
                            page.wait_for_timeout(1600)
                            result["chinese_data_action"]="clicked_visible"
                            result["after_chinese_buttons"]=visible_actions(page)
                            break
                        except Exception as err:
                            result["chinese_data_action"]=type(err).__name__
        except Exception as exc:
            result["error"] = type(exc).__name__+":"+str(exc)[:110]
        finally:
            browser.close()
    # Remove repeated URL patterns while preserving order and method.
    seen=set()
    result["requests"]=[x for x in result["requests"]
                        if (k:=json.dumps(x,sort_keys=True)) not in seen and not seen.add(k)]
    return result


if __name__=="__main__":
    out=[diagnose_one(s) for s in TARGETS]
    Path("wes-cbpt-ui-diagnostics.json").write_text(
        json.dumps(out,ensure_ascii=False,indent=2)+"\n",encoding="utf-8")
    for row in out:
        print(json.dumps(row,ensure_ascii=False)[:10000])
