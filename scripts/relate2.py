#!/usr/bin/env python3
"""글반장 아카이브 — SIM/OPP 재계산 v2 (세부 키워드 + 본문 단어 유사도 + 새 반대 축).

v1(scripts/relate.py)과 차이
- 세부 키워드(KW, 13번째 칸)를 1순위 신호로 쓴다. 태그는 보조.
- 본문 단어 유사도(어절 자카드 + 글자 2-gram 자카드)를 더한다.
- 예비 후보를 최대 8개까지 저장한다(화면은 신고 숨김을 걸러낸 뒤 앞 2개만 노출 → 3번째 이후가 자동으로 올라온다).
- 같은 축·반대편이 없거나 공유 신호가 없으면 OPP는 빈 배열.

사용법
  python3 scripts/relate2.py --dry-run [--path index.html]
  python3 scripts/relate2.py [--path index.html]
"""
import json, re, sys, os, math

NUM, TXT, AUTH, CAT, CLA, TGS, PAIR, POLE, VIEWS, REL, SIM, OPP = range(12)
KW = 12
KEEP = 8

DATA_RE = re.compile(r'(<script id="data" type="application/json">)(.*?)(</script>)', re.S)
PARTICLES = ('에서는', '에게는', '이라고', '라는', '으로는', '에서', '에게', '부터', '까지', '처럼',
             '보다', '마다', '조차', '밖에', '이나', '라도', '으로', '로서', '로써',
             '은', '는', '이', '가', '을', '를', '의', '에', '도', '로', '와', '과', '만', '나', '든')


def norm_text(s):
    return re.sub(r'[^0-9A-Za-z\uAC00-\uD7A3]+', '', s or '')


def words(s):
    out = set()
    for w in re.split(r'[\s,.\'"“”‘’·…!?()\[\]{}:;—–-]+', s or ''):
        w = re.sub(r'[^0-9A-Za-z\uAC00-\uD7A3]', '', w)
        if len(w) < 2:
            continue
        for p in PARTICLES:
            if len(w) > len(p) + 1 and w.endswith(p):
                w = w[:-len(p)]
                break
        if len(w) >= 2:
            out.add(w)
    return out


def bigrams(s):
    t = norm_text(s)
    return {t[i:i + 2] for i in range(len(t) - 1)} if len(t) > 1 else set()


def jac(a, b):
    if not a or not b:
        return 0.0
    return len(a & b) / len(a | b)


def load(path):
    html = open(path, encoding='utf-8').read()
    m = DATA_RE.search(html)
    if not m:
        raise SystemExit('data 스크립트를 찾지 못했습니다: ' + path)
    return html, m, json.loads(m.group(2))


IGNORE_KW = {'나자신'}   # 모든 문장에 붙어 변별력이 없는 키워드는 점수에서 뺀다


def kw_of(it):
    raw = it[KW] if len(it) > KW and isinstance(it[KW], list) else []
    return {x for x in raw if x not in IGNORE_KW}


def compute(items):
    n = len(items)
    tags = [set(it[TGS]) if isinstance(it[TGS], list) else set() for it in items]
    kws = [kw_of(it) for it in items]
    wd = [words(it[TXT]) for it in items]
    bg = [bigrams(it[TXT]) for it in items]
    texts = [norm_text(it[TXT]) for it in items]
    by_cat, by_axis = {}, {}
    for i, it in enumerate(items):
        by_cat.setdefault(it[CAT], []).append(i)
        by_axis.setdefault(it[PAIR], [[], []])[min(1, max(0, it[POLE]))].append(i)

    sim, opp = [], []
    for i, it in enumerate(items):
        out = []
        for j in by_cat[it[CAT]]:
            if j == i or texts[j] == texts[i]:
                continue
            shk = len(kws[i] & kws[j])
            s = (2.6 * jac(kws[i], kws[j]) + 0.8 * shk
                 + 1.4 * jac(tags[i], tags[j]) + 0.5 * min(2, len(tags[i] & tags[j]))
                 + 0.5 * (items[j][PAIR] == it[PAIR] and items[j][POLE] == it[POLE])
                 + 2.0 * (0.5 * jac(wd[i], wd[j]) + 0.5 * jac(bg[i], bg[j]))
                 + (items[j][REL] or 0) / 3000)
            out.append((s, items[j][REL] or 0, -j, j))
        out.sort(reverse=True)
        picks = [x[3] for x in out[:KEEP]]
        sim.append(picks)

        chosen = set(picks)
        out2 = []
        for j in by_axis[it[PAIR]][1 - min(1, max(0, it[POLE]))]:
            if j == i or j in chosen or texts[j] == texts[i]:
                continue
            shk = len(kws[i] & kws[j])
            sht = len(tags[i] & tags[j])
            if shk + sht < 1:
                continue
            s = (2.0 * shk + 1.6 * jac(kws[i], kws[j])
                 + 1.2 * sht + 0.8 * jac(tags[i], tags[j])
                 + 0.8 * (items[j][CAT] == it[CAT])
                 + 0.8 * (0.5 * jac(wd[i], wd[j]) + 0.5 * jac(bg[i], bg[j]))
                 + (items[j][REL] or 0) / 4000)
            out2.append((s, shk + sht, items[j][REL] or 0, -j, j))
        out2.sort(reverse=True)
        opp.append([x[4] for x in out2[:KEEP]])
    return sim, opp


def stats(items, sim, opp):
    tags = [set(it[TGS]) if isinstance(it[TGS], list) else set() for it in items]
    kws = [kw_of(it) for it in items]
    sj, sk, sc, sn = [], [], 0, 0
    oj, ok, oa, oc, on = [], [], 0, 0, 0
    for i, it in enumerate(items):
        for j in sim[i]:
            sj.append(jac(tags[i], tags[j]))
            sk.append(jac(kws[i], kws[j]))
            sc += items[j][CAT] == it[CAT]
            sn += 1
        for j in opp[i]:
            oj.append(jac(tags[i], tags[j]))
            ok.append(jac(kws[i], kws[j]))
            oa += (items[j][PAIR] == it[PAIR] and items[j][POLE] != it[POLE])
            oc += items[j][CAT] == it[CAT]
            on += 1
    f = lambda v: round(sum(v) / len(v), 4) if v else 0
    return {
        'sim_n': sn, 'sim_tag_jaccard': f(sj), 'sim_kw_jaccard': f(sk),
        'sim_cat_match': round(100 * sc / sn, 2) if sn else 0,
        'sim_items_8': sum(1 for s in sim if len(s) == KEEP),
        'opp_n': on, 'opp_tag_jaccard': f(oj), 'opp_kw_jaccard': f(ok),
        'opp_axis_match': round(100 * oa / on, 2) if on else 0,
        'opp_cat_match': round(100 * oc / on, 2) if on else 0,
        'opp_empty': sum(1 for o in opp if not o),
        'opp_3plus': sum(1 for o in opp if len(o) >= 3),
    }


def main():
    args = sys.argv[1:]
    dry = '--dry-run' in args
    path = '/workspace/projects/banjang/index.html'
    if '--path' in args:
        path = args[args.index('--path') + 1]
    html, m, D = load(path)
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
    open(path, 'w', encoding='utf-8').write(out)
    print('WROTE', path, len(out), 'bytes')


if __name__ == '__main__':
    main()
