#!/usr/bin/env python3
"""
네이버 블로그 검색 노출/순위 점검 스크립트

각 글마다 다음을 점검한다.
  1) 포스팅 '전체 제목'으로 검색했을 때 내 글이 몇 위에 나오는지
  2) 제목에서 뽑은 '중요 키워드'로 검색했을 때 몇 위에 나오는지
결과를 docs/results.json 에 저장한다. (대시보드 사이트가 이 파일을 읽어 표시)
누락된 글이 있으면 이메일/웹훅 알림도 보낼 수 있다.

순위 안내: 네이버가 공식 제공하는 '블로그 검색 API'의 정확도순(sim) 결과 기준 순위다.
실제 naver.com 통합검색 화면 순위와는 다를 수 있는 근사값이다.

외부 라이브러리 없이 파이썬 표준 라이브러리만 사용.
"""

import os
import re
import sys
import html
import json
import time
import smtplib
import urllib.parse
import urllib.request
from datetime import datetime, timezone, timedelta
from email.mime.text import MIMEText
from email.utils import formataddr
import xml.etree.ElementTree as ET


# ---------------- 설정 (환경 변수) ----------------
BLOG_ID = os.environ.get("NAVER_BLOG_ID", "giant7000").strip()
CLIENT_ID = os.environ.get("NAVER_CLIENT_ID", "").strip()
CLIENT_SECRET = os.environ.get("NAVER_CLIENT_SECRET", "").strip()

# 순위를 몇 위까지 찾아볼지 (100 단위 권장, 최대 1000)
MAX_RANK = int(os.environ.get("MAX_RANK", "100"))
SLEEP = float(os.environ.get("SLEEP", "0.3"))          # API 호출 간 대기
OUTPUT = os.environ.get("OUTPUT", "docs/results.json")  # 결과 저장 위치
HISTORY = os.environ.get("HISTORY", "docs/history.json")  # 추세용 누적 기록

# 알림 (선택): NOTIFY_METHOD = "email" 또는 "webhook"
NOTIFY_METHOD = os.environ.get("NOTIFY_METHOD", "").strip().lower()
SMTP_HOST = os.environ.get("SMTP_HOST", "smtp.gmail.com").strip()
SMTP_PORT = int(os.environ.get("SMTP_PORT") or "587")
SMTP_USER = os.environ.get("SMTP_USER", "").strip()
SMTP_PASS = os.environ.get("SMTP_PASS", "").strip()
MAIL_TO = os.environ.get("MAIL_TO", "").strip()
WEBHOOK_URL = os.environ.get("WEBHOOK_URL", "").strip()

KST = timezone(timedelta(hours=9))

# 키워드 자동 추출용
_PARTICLES = sorted(
    ["으로써", "으로서", "에서는", "에게서", "이라는", "라는", "으로", "에서",
     "에게", "한테", "까지", "부터", "조차", "마저", "처럼", "보다", "이라",
     "은", "는", "이", "가", "을", "를", "의", "에", "와", "과", "도", "만",
     "로", "랑", "나", "요"],
    key=len, reverse=True,
)
_STOPWORDS = {"및", "그리고", "하는", "위한", "대한", "관한", "그", "이", "저", "것", "수"}
# 블로그 제목에 흔한 '군더더기' 단어 (검색 키워드로는 부적합)
_NOISE = {"추천", "후기", "베스트", "best", "모음", "정리", "총정리", "완벽", "방법",
          "관리", "코스", "입문", "리뷰", "내돈내산", "내돈", "비교", "순위", "top",
          "가이드", "꿀팁", "팁", "신상", "처리", "해결", "사용기", "체험", "리스트",
          "가격", "비용", "공지", "이벤트", "할인"}


def strip_particle(tok: str) -> str:
    for p in _PARTICLES:
        if tok.endswith(p) and len(tok) > len(p) + 1:
            return tok[: -len(p)]
    return tok


def extract_keyword(title: str) -> str:
    """제목 앞쪽에서 의미 있는 핵심어 1~2개를 뽑아 '중요 키워드'로 사용.
    자동 추출은 완벽하지 않으므로, 중요한 글은 keywords.json 으로 직접 지정 권장."""
    cleaned = re.sub(r"[\[\]\(\)<>{}|·…“”\"'’‘!?,.~\-:;/]+", " ", title)
    out = []
    for w in cleaned.split():
        if len(w) < 2:
            continue
        if re.search(r"\d", w):          # 숫자 포함 토큰 제외 (베스트5, 3박4일 등)
            continue
        w2 = strip_particle(w)
        if len(w2) < 2 or w2 in _STOPWORDS or w2 in _NOISE:
            continue
        if w2 not in out:
            out.append(w2)
        if len(out) >= 2:                # 앞에서부터 핵심어 2개면 충분
            break
    return " ".join(out) if out else title.strip()


def extract_log_no(link: str) -> str:
    nums = re.findall(r"(\d{6,})", link)
    return nums[-1] if nums else ""


def normalize(text: str) -> str:
    text = re.sub(r"<[^>]+>", "", html.unescape(text))
    return re.sub(r"\s+", "", text).lower()


def fetch_posts_from_rss(blog_id: str):
    url = f"https://rss.blog.naver.com/{blog_id}.xml"
    req = urllib.request.Request(url, headers={"User-Agent": "Mozilla/5.0"})
    with urllib.request.urlopen(req, timeout=15) as resp:
        data = resp.read()
    root = ET.fromstring(data)
    posts = []
    for item in root.iter("item"):
        title = (item.findtext("title") or "").strip()
        link = (item.findtext("link") or "").strip()
        if title and link:
            posts.append({"title": title, "link": link, "log_no": extract_log_no(link)})
    return posts


def search_page(query: str, display: int, start: int):
    enc = urllib.parse.quote(query)
    url = (f"https://openapi.naver.com/v1/search/blog.json"
           f"?query={enc}&display={display}&start={start}&sort=sim")
    req = urllib.request.Request(url)
    req.add_header("X-Naver-Client-Id", CLIENT_ID)
    req.add_header("X-Naver-Client-Secret", CLIENT_SECRET)
    with urllib.request.urlopen(req, timeout=15) as resp:
        return json.loads(resp.read().decode("utf-8"))


def matches(post: dict, item: dict) -> bool:
    link = item.get("link", "")
    if post["log_no"] and post["log_no"] in link:
        return True
    bid = BLOG_ID.lower()
    if bid and bid in link.lower() and normalize(item.get("title", "")) == normalize(post["title"]):
        return True
    return False


def find_rank(query: str, post: dict):
    """query 로 검색했을 때 post 가 몇 위인지. 못 찾으면 None."""
    position = 0
    start = 1
    while start <= 1000 and position < MAX_RANK:
        result = search_page(query, display=100, start=start)
        items = result.get("items", [])
        if not items:
            break
        for it in items:
            position += 1
            if matches(post, it):
                return position
            if position >= MAX_RANK:
                return None
        if len(items) < 100:
            break
        start += 100
        time.sleep(SLEEP)
    return None


def load_keyword_overrides():
    """keywords.json 이 있으면 logNo -> 키워드 매핑을 읽는다 (수동 지정용)."""
    path = os.environ.get("KEYWORDS_FILE", "keywords.json")
    if os.path.exists(path):
        try:
            with open(path, encoding="utf-8") as f:
                return json.load(f)
        except Exception as e:
            print(f"[경고] keywords.json 읽기 실패: {e}")
    return {}


def build_report(missing, total):
    lines = [f"네이버 블로그 '{BLOG_ID}' 검색 노출 점검", ""]
    lines.append(f"전체 {total}건 중 {len(missing)}건이 제목 검색에서 노출되지 않았습니다.\n")
    for p in missing:
        kw = f" / 키워드 '{p['keyword']}' {p['keyword_rank']}위" if p["keyword_rank"] else " / 키워드도 미노출"
        lines.append(f"- {p['title']}{kw}\n  {p['link']}")
    return "\n".join(lines)


def send_email(report, missing_count):
    if not (SMTP_USER and SMTP_PASS and MAIL_TO):
        print("[이메일 미발송] SMTP_USER / SMTP_PASS / MAIL_TO 필요")
        return
    msg = MIMEText(report, "plain", "utf-8")
    msg["Subject"] = f"[블로그 점검] 검색 누락 {missing_count}건"
    msg["From"] = formataddr(("블로그 점검봇", SMTP_USER))
    msg["To"] = MAIL_TO
    with smtplib.SMTP(SMTP_HOST, SMTP_PORT, timeout=20) as s:
        s.starttls()
        s.login(SMTP_USER, SMTP_PASS)
        s.sendmail(SMTP_USER, [a.strip() for a in MAIL_TO.split(",") if a.strip()], msg.as_string())
    print(f"[이메일 발송 완료] → {MAIL_TO}")


def send_webhook(report):
    if not WEBHOOK_URL:
        print("[웹훅 미발송] WEBHOOK_URL 필요")
        return
    payload = {"content": report[:1900]} if "discord" in WEBHOOK_URL else {"text": report}
    req = urllib.request.Request(WEBHOOK_URL, data=json.dumps(payload).encode("utf-8"),
                                 headers={"Content-Type": "application/json"})
    with urllib.request.urlopen(req, timeout=20) as resp:
        resp.read()
    print("[웹훅 발송 완료]")


def notify(missing):
    if not missing:
        return
    report = build_report(missing, missing[0]["_total"])
    if NOTIFY_METHOD == "email":
        send_email(report, len(missing))
    elif NOTIFY_METHOD == "webhook":
        send_webhook(report)


def main():
    miss_conf = [k for k, v in {"NAVER_CLIENT_ID": CLIENT_ID,
                                "NAVER_CLIENT_SECRET": CLIENT_SECRET}.items() if not v]
    if miss_conf:
        print(f"[설정 오류] 환경 변수 필요: {', '.join(miss_conf)}")
        sys.exit(1)

    print(f"[1/3] '{BLOG_ID}' RSS에서 글 목록 수집...")
    posts = fetch_posts_from_rss(BLOG_ID)
    if not posts:
        print("[오류] RSS에서 글을 찾지 못함. 블로그 ID 확인 필요.")
        sys.exit(1)
    print(f"  -> {len(posts)}개")

    overrides = load_keyword_overrides()

    # 지난 점검 결과(있으면)를 읽어 '노출 여부'를 비교용으로 보관
    prev = load_json(OUTPUT)
    prev_exposed = {}
    if prev:
        for p in prev.get("posts", []):
            prev_exposed[extract_log_no(p.get("link", ""))] = (p.get("title_rank") is not None)
    has_prev = bool(prev_exposed)

    print(f"[2/3] 제목/키워드 검색 순위 확인 (최대 {MAX_RANK}위까지)...")
    results = []
    missing = []
    for i, post in enumerate(posts, 1):
        keyword = overrides.get(post["log_no"]) or extract_keyword(post["title"])
        try:
            title_rank = find_rank(post["title"], post)
            time.sleep(SLEEP)
            keyword_rank = find_rank(keyword, post)
        except Exception as e:
            print(f"  [{i}/{len(posts)}] 검색 실패({e}) -> 건너뜀")
            continue

        now_exposed = title_rank is not None
        key = post["log_no"]
        if not has_prev:
            change = "first"               # 첫 점검 (비교 대상 없음)
        elif key not in prev_exposed:
            change = "new_post"            # 이번에 처음 등장한 글
        elif prev_exposed[key] and not now_exposed:
            change = "dropped"             # 지난주 노출 -> 이번주 사라짐 (중요)
        elif not prev_exposed[key] and now_exposed:
            change = "exposed_now"         # 안 나오다가 새로 노출됨
        elif not now_exposed:
            change = "still_missing"       # 계속 미노출
        else:
            change = "stable"             # 노출 유지

        row = {
            "title": post["title"],
            "link": post["link"],
            "keyword": keyword,
            "title_rank": title_rank,
            "keyword_rank": keyword_rank,
            "change": change,
        }
        results.append(row)
        tr = f"{title_rank}위" if title_rank else "미노출"
        kr = f"{keyword_rank}위" if keyword_rank else "미노출"
        flag = {"dropped": " ▼사라짐", "exposed_now": " ▲노출", "new_post": " +새글"}.get(change, "")
        print(f"  [{i}/{len(posts)}] 제목:{tr:>6} | 키워드({keyword}):{kr:>6}{flag} | {post['title']}")
        if title_rank is None:
            row2 = dict(row); row2["_total"] = len(posts)
            missing.append(row2)
        time.sleep(SLEEP)

    def brief(r):
        return {"title": r["title"], "link": r["link"], "keyword": r["keyword"]}

    changes = {
        "compared_to": prev.get("checked_at") if prev else None,
        "dropped": [brief(r) for r in results if r["change"] == "dropped"],
        "exposed_now": [brief(r) for r in results if r["change"] == "exposed_now"],
        "new_posts": [brief(r) for r in results if r["change"] == "new_post"],
    }

    total = len(results)
    exposed = sum(1 for r in results if r["title_rank"])
    payload = {
        "blog_id": BLOG_ID,
        "blog_url": f"https://blog.naver.com/{BLOG_ID}",
        "checked_at": datetime.now(KST).strftime("%Y-%m-%d %H:%M KST"),
        "max_rank": MAX_RANK,
        "summary": {
            "total": total,
            "title_exposed": exposed,
            "title_missing": total - exposed,
        },
        "changes": changes,
        "posts": results,
    }

    os.makedirs(os.path.dirname(OUTPUT) or ".", exist_ok=True)
    with open(OUTPUT, "w", encoding="utf-8") as f:
        json.dump(payload, f, ensure_ascii=False, indent=2)

    # 추세용 기록 누적 (같은 날 재실행이면 마지막 항목 교체)
    today = datetime.now(KST).strftime("%Y-%m-%d")
    hist = load_json(HISTORY) or {"runs": []}
    entry = {"date": today, "checked_at": payload["checked_at"],
             "total": total, "exposed": exposed, "missing": total - exposed}
    if hist["runs"] and hist["runs"][-1].get("date") == today:
        hist["runs"][-1] = entry
    else:
        hist["runs"].append(entry)
    with open(HISTORY, "w", encoding="utf-8") as f:
        json.dump(hist, f, ensure_ascii=False, indent=2)

    print(f"[3/3] 결과 저장: {OUTPUT} (누락 {total - exposed}건, "
          f"사라짐 {len(changes['dropped'])} / 새노출 {len(changes['exposed_now'])} / 새글 {len(changes['new_posts'])})")

    # 로컬에서 바로 보도록, 데이터를 내장한 report.html 생성 후 브라우저로 열기
    report = write_standalone_report(payload)
    if report and os.environ.get("GITHUB_ACTIONS") != "true":
        path = os.path.abspath(report)
        print(f"      대시보드: {path}")
        try:
            import webbrowser
            webbrowser.open("file://" + path)
        except Exception:
            pass

    notify(missing)


def load_json(path):
    """JSON 파일을 안전하게 읽는다. 없거나 오류면 None."""
    try:
        with open(path, encoding="utf-8") as f:
            return json.load(f)
    except Exception:
        return None


def write_standalone_report(payload):
    """docs/index.html 템플릿에 결과 데이터를 끼워 넣어, 서버 없이 더블클릭으로 열 수 있는
    docs/report.html 을 만든다. (템플릿이 없으면 건너뜀)"""
    base = os.path.dirname(OUTPUT) or "."
    tpl_path = os.path.join(base, "index.html")
    if not os.path.exists(tpl_path):
        return None
    with open(tpl_path, encoding="utf-8") as f:
        tpl = f.read()
    hist = load_json(HISTORY) or {"runs": []}
    inject = ("<script>window.__RESULTS__=" + json.dumps(payload, ensure_ascii=False)
              + ";window.__HISTORY__=" + json.dumps(hist, ensure_ascii=False)
              + ";</script>\n</head>")
    out_path = os.path.join(base, "report.html")
    with open(out_path, "w", encoding="utf-8") as f:
        f.write(tpl.replace("</head>", inject, 1))
    return out_path


if __name__ == "__main__":
    main()
