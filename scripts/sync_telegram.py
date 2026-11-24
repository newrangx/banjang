#!/usr/bin/env python3
"""글반장 텔레그램(t.me/banjang9) 최신 글 → Supabase `telegram_posts` 동기화.

- 공개 미리보기(t.me/s/<채널>)만 읽습니다. 로그인·API 키 불필요.
- 지원 글 유형: 텍스트 / 사진 1장 / 사진 여러 장(앨범) / 짧은 영상(썸네일+재생시간)
- 영상은 텔레그램 웹 미리보기가 mp4 주소를 주지 않으므로 썸네일과 원문 링크만 저장합니다.
- Supabase에는 `ingest_telegram_posts(p_key, p_posts)` RPC로 넣습니다(키 검증).

사용 예:
  BANJANG_SYNC_KEY=... python3 sync_telegram.py            # 최근 1페이지 동기화
  python3 sync_telegram.py --key ... --pages 2             # 2페이지(약 20건)
  python3 sync_telegram.py --dry-run                       # 전송 없이 파싱 결과만 출력
"""
import argparse
import html
import json
import os
import re
import sys
import time
import urllib.error
import urllib.request

CHANNEL = "banjang9"
SB_URL = os.environ.get("SUPABASE_URL", "https://ecwrolumnuajrkqmzeds.supabase.co").rstrip("/")
SB_KEY = os.environ.get("SUPABASE_KEY", "sb_publishable_GWhczqZ14Jir3UytthydNg_9BBUNhCD")
UA = "Mozilla/5.0 (compatible; banjang-sync/1.0; +https://newrangx.github.io/banjang/)"

MSG_SPLIT = re.compile(r'<div class="tgme_widget_message\b')
POST_RE = re.compile(r'data-post="([A-Za-z0-9_]+)/(\d+)"')
TEXT_RE = re.compile(r'<div class="tgme_widget_message_text[^"]*"[^>]*>(.*?)</div>', re.S)
TIME_RE = re.compile(r'<time[^>]*datetime="([^"]+)"')
BG_RE = re.compile(r"background-image:url\('([^']+)'\)")
GROUP_RE = re.compile(r'tgme_widget_message_grouped_wrap')
VIDEO_RE = re.compile(r'tgme_widget_message_video_player')
VIDTHUMB_RE = re.compile(r'<i class="tgme_widget_message_video_thumb" style="background-image:url\(\'([^\']+)\'\)')
DUR_RE = re.compile(r'message_video_duration[^>]*>([^<]+)<')
VIEWS_RE = re.compile(r'tgme_widget_message_views[^>]*>([^<]+)<')


def fetch(url, retries=3):
    last = None
    for i in range(retries):
        try:
            req = urllib.request.Request(url, headers={"User-Agent": UA, "Accept-Language": "ko,en"})
            with urllib.request.urlopen(req, timeout=25) as r:
                return r.read().decode("utf-8", "replace")
        except (urllib.error.URLError, TimeoutError) as e:  # noqa: PERF203
            last = e
            time.sleep(2 + i * 2)
    raise SystemExit(f"텔레그램 페이지를 읽지 못했습니다: {last}")


def strip_html(s):
    s = re.sub(r"<br\s*/?>", "\n", s)
    s = re.sub(r"</p>", "\n", s)
    s = re.sub(r"<[^>]+>", "", s)
    s = html.unescape(s)
    s = s.replace("\u200b", "")
    return "\n".join(line.rstrip() for line in s.split("\n")).strip()


def parse_page(page):
    out = []
    chunks = MSG_SPLIT.split(page)[1:]
    for chunk in chunks:
        m = POST_RE.search(chunk)
        if not m:
            continue
        channel, msg_id = m.group(1), int(m.group(2))

        is_video = bool(VIDEO_RE.search(chunk))
        photos = []
        if not is_video or GROUP_RE.search(chunk):  # 그룹 안 사진 + 영상 혼합도 수집
            for style in re.findall(r'class="tgme_widget_message_photo_wrap[^"]*"[^>]*style="[^"]*"', chunk):
                b = BG_RE.search(style)
                if b:
                    photos.append({"type": "photo", "url": b.group(1)})
            if not photos:
                for b in BG_RE.finditer(chunk):
                    pass
        media = []
        if is_video:
            v = VIDTHUMB_RE.search(chunk)
            d = DUR_RE.search(chunk)
            if v:
                media.append({"type": "video", "url": v.group(1), "duration": (d.group(1).strip() if d else "")})
        media.extend(photos)

        if is_video:
            kind = "video"
        elif len(photos) >= 2:
            kind = "album"
        elif len(photos) == 1:
            kind = "photo"
        else:
            kind = "text"

        tm = TEXT_RE.search(chunk)
        body = strip_html(tm.group(1)) if tm else ""
        t = TIME_RE.search(chunk)
        views = VIEWS_RE.search(chunk)

        if not body and not media:
            continue  # 서비스 메시지·빈 글 제외
        out.append({
            "msg_id": msg_id,
            "kind": kind,
            "body": body,
            "media": media,
            "duration": (media[0].get("duration") or "") if kind == "video" and media else "",
            "post_url": f"https://t.me/{channel}/{msg_id}",
            "posted_at": t.group(1) if t else None,
            "views": strip_html(views.group(1)) if views else "",
        })
    # 오래된 글 → 최신 글 순으로 정렬
    out.sort(key=lambda x: x["msg_id"])
    return out


def collect(pages):
    posts = {}
    url = f"https://t.me/s/{CHANNEL}"
    for _ in range(max(1, pages)):
        page = fetch(url)
        got = parse_page(page)
        if not got:
            break
        for p in got:
            posts[p["msg_id"]] = p
        before = min(p["msg_id"] for p in got)
        url = f"https://t.me/s/{CHANNEL}?before={before}"
        time.sleep(1)
    return [posts[k] for k in sorted(posts)]


def push(posts, key):
    payload = json.dumps({"p_key": key, "p_posts": posts}).encode("utf-8")
    req = urllib.request.Request(
        f"{SB_URL}/rest/v1/rpc/ingest_telegram_posts",
        data=payload,
        headers={"apikey": SB_KEY, "Content-Type": "application/json"},
        method="POST",
    )
    with urllib.request.urlopen(req, timeout=30) as r:
        return json.loads(r.read().decode("utf-8") or "0")


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--pages", type=int, default=1, help="가져올 미리보기 페이지 수(1페이지≈11건)")
    ap.add_argument("--limit", type=int, default=0, help="최신 N건만 전송(0=전체)")
    ap.add_argument("--key", default=os.environ.get("BANJANG_SYNC_KEY", ""), help="Supabase sync key")
    ap.add_argument("--dry-run", action="store_true")
    args = ap.parse_args()

    posts = collect(args.pages)
    if args.limit:
        posts = posts[-args.limit:]
    summary = {}
    for p in posts:
        summary[p["kind"]] = summary.get(p["kind"], 0) + 1
    print(f"수집 {len(posts)}건 · 유형 {summary} · 최신 #{posts[-1]['msg_id'] if posts else '-'}")

    if args.dry_run:
        print(json.dumps(posts[-3:], ensure_ascii=False, indent=1))
        return
    if not posts:
        print("새로 저장할 글이 없습니다.")
        return
    if not args.key:
        raise SystemExit("sync key가 없습니다. --key 또는 BANJANG_SYNC_KEY 로 넘겨 주세요.")
    try:
        n = push(posts, args.key)
    except urllib.error.HTTPError as e:
        raise SystemExit(f"Supabase 저장 실패: HTTP {e.code} {e.read().decode('utf-8', 'replace')[:300]}")
    print(f"Supabase 반영 {n}건")


if __name__ == "__main__":
    main()
