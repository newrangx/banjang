#!/usr/bin/env python3
"""index.html 내장 문장 데이터에서 admin.html용 경량 인덱스(quotes_map.json)를 만든다.

관리자 페이지가 인용문 한 줄을 얻으려고 index.html(1.1MB)을 통째로 받아
DOMParser로 파싱하던 것을, 문장번호 → [본문, 저자] JSON 한 파일로 대체한다.
중복 번호는 index.html과 같은 규칙(첫 등장 우선)으로 처리한다.

사용법: python3 scripts/build_quotes_map.py
"""
import json
import os
import re

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
SRC = os.path.join(ROOT, 'index.html')
OUT = os.path.join(ROOT, 'quotes_map.json')
DATA_RE = re.compile(r'<script id="data" type="application/json">(.*?)</script>', re.S)


def main():
    html = open(SRC, encoding='utf-8').read()
    m = DATA_RE.search(html)
    if not m:
        raise SystemExit('data 스크립트를 찾지 못했습니다')
    items = json.loads(m.group(1))['items']
    out = {}
    for it in items:
        if it[0] not in out:
            out[str(it[0])] = [it[1], it[2]]
    body = json.dumps(out, ensure_ascii=False, separators=(',', ':'))
    open(OUT, 'w', encoding='utf-8').write(body)
    print('WROTE', OUT, len(out), 'quotes,', len(body), 'bytes')


if __name__ == '__main__':
    main()
