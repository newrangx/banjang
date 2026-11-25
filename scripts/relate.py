#!/usr/bin/env python3
"""글반장 아카이브 — 비슷한 문장(SIM) / 반대 관점 문장(OPP) 재계산.

index.html 안의 <script id="data"> JSON을 읽어 각 문장의 SIM(6개)·OPP(최대 6개)
인덱스를 규칙 기반으로 다시 계산하고, 같은 파일에 그대로 되쓴다.
(JSON은 한 줄 직렬화를 유지한다 — 포맷이 바뀌면 파일 크기가 커진다.)

규칙
- SIM: 같은 카테고리 안에서만 후보.
       score = 3*태그자카드 + 0.6*공유태그수 + 0.5*(같은 축·같은 편) + 관련도/2000
- OPP: 같은 축(pair)의 반대편(pole)만 후보. 공유 태그가 1개 이상인 후보만 쓴다.
       score = 2.0*공유태그수 + 1.5*태그자카드 + 0.8*(같은 카테고리) + 관련도/4000
       후보가 없으면 빈 배열 → 화면에서 '반대 관점' 섹션을 숨긴다(사실이 아닌 문구를 띄우지 않는다).
- SIM에 들어간 문장은 OPP에서 제외한다(같은 문장이 양쪽에 뜨지 않게).
- 본문이 같은 문장(중복 원고)은 SIM 후보에서 제외한다.

사용법
  python3 scripts/relate.py            # 재계산해서 index.html에 반영
  python3 scripts/relate.py --dry-run  # 계산만 하고 전/후 지표 출력
"""
import json
import re
import sys
import os

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
PATH = os.path.join(ROOT, 'index.html')
DATA_RE = re.compile(r'(<script id="data" type="application/json">)(.*?)(</script>)', re.S)
NUM, TXT, AUTH, CAT, CLA, TGS, PAIR, POLE, VIEWS, REL, SIM, OPP = range(12)


def load(path=PATH):
    html = open(path, encoding='utf-8').read()
    m = DATA_RE.search(html)
    if not m:
        raise SystemExit('data 스크립트를 찾지 못했습니다: ' + path)
    return html, m, json.loads(m.group(2))


def norm_text(s):
    return re.sub(r'[^0-9A-Za-z\uAC00-\uD7A3]+', '', s or '')


def jaccard(a, b):
    if not a or not b:
        return 0.0
    return len(a & b) / len(a | b)


def compute(items):
    n = len(items)
    tags = [set(it[TGS]) if isinstance(it[TGS], list) else set() for it in items]
    texts = [norm_text(it[TXT]) for it in items]
    by_cat, by_axis = {}, {}
    for i, it in enumerate(items):
        by_cat.setdefault(it[CAT], []).append(i)
        by_axis.setdefault(it[PAIR], [[], []])[it[POLE]].append(i)

    sim = []
    for i, it in enumerate(items):
        out = []
        for j in by_cat[it[CAT]]:
            if j == i or texts[j] == texts[i]:
                continue
            sh = len(tags[i] & tags[j])
            s = (3 * jaccard(tags[i], tags[j]) + 0.6 * sh
                 + (0.5 if items[j][PAIR] == it[PAIR] and items[j][POLE] == it[POLE] else 0)
                 + (items[j][REL] or 0) / 2000)
            out.append((s, items[j][REL] or 0, -j, j))
        out.sort(reverse=True)
        sim.append([x[3] for x in out[:6]])

    opp = []
    for i, it in enumerate(items):
        chosen = set(sim[i])
        out = []
        for j in by_axis[it[PAIR]][1 - it[POLE]]:
            if j == i or j in chosen or texts[j] == texts[i]:
                continue
            sh = len(tags[i] & tags[j])
            if sh < 1:
                continue
            s = (2.0 * sh + 1.5 * jaccard(tags[i], tags[j])
                 + (0.8 if items[j][CAT] == it[CAT] else 0)
                 + (items[j][REL] or 0) / 4000)
            out.append((s, sh, items[j][REL] or 0, -j, j))
        out.sort(reverse=True)
        opp.append([x[4] for x in out[:6]])
    return sim, opp


def stats(items, sim, opp):
    tags = [set(it[TGS]) if isinstance(it[TGS], list) else set() for it in items]
    sj, sc, sn = [], 0, 0
    oj, oa, oc, on = [], 0, 0, 0
    for i, it in enumerate(items):
        for j in sim[i]:
            sj.append(jaccard(tags[i], tags[j]))
            sc += items[j][CAT] == it[CAT]
            sn += 1
        for j in opp[i]:
            oj.append(jaccard(tags[i], tags[j]))
            oa += (items[j][PAIR] == it[PAIR] and items[j][POLE] != it[POLE])
            oc += items[j][CAT] == it[CAT]
            on += 1
    return {
        'sim_n': sn,
        'sim_tag_jaccard': round(sum(sj) / sn, 4) if sn else 0,
        'sim_cat_match': round(100 * sc / sn, 2) if sn else 0,
        'sim_items_with_6': sum(1 for s in sim if len(s) == 6),
        'sim_shared_tag_pct': round(100 * sum(1 for i, it in enumerate(items) for j in sim[i] if tags[i] & tags[j]) / sn, 2) if sn else 0,
        'opp_n': on,
        'opp_tag_jaccard': round(sum(oj) / on, 4) if on else 0,
        'opp_axis_match': round(100 * oa / on, 2) if on else 0,
        'opp_cat_match': round(100 * oc / on, 2) if on else 0,
        'opp_empty_items': sum(1 for o in opp if not o),
        'opp_items_with_3plus': sum(1 for o in opp if len(o) >= 3),
    }


def main():
    dry = '--dry-run' in sys.argv
    html, m, D = load()
    items = D['items']
    before = stats(items, [it[SIM] for it in items], [it[OPP] for it in items])
    sim, opp = compute(items)
    after = stats(items, sim, opp)
    print('BEFORE', json.dumps(before, ensure_ascii=False))
    print('AFTER ', json.dumps(after, ensure_ascii=False))
    if dry:
        return
    for i, it in enumerate(items):
        it[SIM] = sim[i]
        it[OPP] = opp[i]
    body = json.dumps(D, ensure_ascii=False, separators=(',', ':'))
    out = html[:m.start(2)] + body + html[m.end(2):]
    open(PATH, 'w', encoding='utf-8').write(out)
    print('WROTE', PATH, len(out), 'bytes')


if __name__ == '__main__':
    main()
