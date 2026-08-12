"""X盆踊ラー再評価の試作（docs/x-bonodorer-reevaluation-20260811.md の検証用）。

本番実装ではなく、告知力／コンテンツ力の2軸と地域bot判定の妥当性を実データで
確かめるための使い捨てスクリプト。本番は collect.py 側で voices 全体から計算する。

使い方:
    python3 scripts/prototype_x_bonodorer_reevaluation.py [出力ディレクトリ]

前提:
 - data/x_account_scores.json は最新のものを使うこと（ローカルが古い場合は
   `git show origin/main:data/x_account_scores.json > /tmp/scores.json` などで取り、
   環境変数 X_SCORES_FILE でそのパスを渡す）
 - data/voices.json はS3側が正本。ローカルは古い可能性がある

設計上の勘どころ:
 1. 政令市の同名区（名古屋市北区・札幌市中央区など）を23区と誤認しない
 2. 手動名簿の 優先/通常 は機械判定で外さない（人の判断を機械が巻き戻さない）
 3. 23区の盆踊り実績がゼロなら告知力に上限をかける（道頓堀・松戸などが上位に来ない）
 4. 比率は件数で縮約する（投稿1件のアカウントが満点になるのを防ぐ）
"""
import json, re, sys, math, collections, os, subprocess

REPO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, REPO)
from collection_support.tokyo23_scope import (
    TOKYO_23_RE, NON_TOKYO_PREF_RE, KNOWN_OUTSIDE_TOKYO_23_RE)

SP = sys.argv[1] if len(sys.argv) > 1 else os.path.join(REPO, 'data')
SCORES_FILE = os.environ.get('X_SCORES_FILE', os.path.join(REPO, 'data/x_account_scores.json'))
scores = json.load(open(SCORES_FILE))['accounts']
voices = json.load(open(os.path.join(REPO, 'data/voices.json')))


def gap_credits():
    """x_gap候補・レビューレーンに採用された回数を、mainの全リビジョンから数える。"""
    counter = collections.Counter()
    seen = set()
    for path in ('data/x_gap_candidates.json', 'data/x_review_lanes.json'):
        revs = subprocess.run(['git', 'log', '--format=%H', 'origin/main', '--', path],
                              cwd=REPO, capture_output=True, text=True).stdout.split()
        for rev in revs:
            p = subprocess.run(['git', 'show', rev + ':' + path], cwd=REPO,
                               capture_output=True, text=True)
            if p.returncode:
                continue
            try:
                d = json.loads(p.stdout)
            except Exception:
                continue
            if isinstance(d, dict) and 'lanes' in d:
                groups = [v for v in d['lanes'].values() if isinstance(v, list)]
            else:
                groups = [d.get('candidates') or d.get('items') or (d if isinstance(d, list) else [])]
            for g in groups:
                for it in g:
                    if not isinstance(it, dict):
                        continue
                    a = (it.get('source_author') or '').lstrip('@').lower()
                    key = (a, it.get('source_key'), it.get('candidate_kind'))
                    if a and key not in seen:
                        seen.add(key)
                        counter[a] += 1
    return counter


gap = gap_credits()
roster = json.load(open(os.path.join(REPO, 'data/x_collection_roster.json')))['accounts']
manual = {r['handle'].lstrip('@').lower(): (r.get('manual_status') or '') for r in roster}

# 政令市など、区名を持つ東京都外の市。これが本文にあれば23区判定を打ち消す。
OTHER_WARD_CITY_RE = re.compile(
    '札幌市|仙台市|さいたま市|千葉市|横浜市|川崎市|相模原市|新潟市|静岡市|浜松市|'
    '名古屋市|京都市|大阪市|堺市|神戸市|岡山市|広島市|北九州市|福岡市|熊本市')
TOKYO_PLACE_RE = re.compile(
    '浅草|上野|銀座|新宿|渋谷|池袋|麻布|六本木|築地|月島|佃|勝どき|晴海|日本橋|神田|秋葉原|'
    '錦糸町|押上|亀戸|北千住|巣鴨|高円寺|阿佐ヶ谷|下北沢|三軒茶屋|自由が丘|蒲田|大井町|'
    '五反田|目黒|恵比寿|代々木|荻窪|王子|十条|赤羽|葛西|小岩|清澄|門前仲町|深川|'
    '両国|浜町|高島平|千住|谷中|根津|白金|'
    # 区名の裸表記。政令市の同名区は OTHER_WARD_CITY_RE が先に打ち消すので安全。
    '世田谷|杉並|豊島|荒川|足立|葛飾|江戸川|板橋|練馬|中野|品川|墨田|江東|台東|文京')
BON_RE = re.compile('盆踊|盆おどり|納涼|音頭|やぐら|櫓|民踊')
DATE_RE = re.compile(r'\d{1,2}\s*[/月]\s*\d{1,2}')
OPINION_RE = re.compile(
    'と思|感じ|好き|嬉し|楽し|良かっ|よかっ|最高|素晴らし|残念|寂し|懐かし|'
    'なぜ|理由|文化|歴史|伝統|変わ|続け|工夫|課題|問題|意味|べき|かもしれ|気がする|印象|'
    '初めて|久しぶり|来年|また行|おすすめ')
FIRST_RE = re.compile('私|僕|俺|自分|わたし|うちの')
DETAIL_RE = re.compile('炭坑節|東京音頭|ダンシング|きよし|花笠|河内音頭|八木節|大東京音頭|'
                       '三宅|曲目|曲順|演目|生演奏|櫓|やぐら|太鼓|浴衣|屋台|盆唄|音頭取り|'
                       '振り付け|練習会|講習会')


def is_tokyo23_text(t):
    if OTHER_WARD_CITY_RE.search(t):
        return False
    if NON_TOKYO_PREF_RE.search(t) or KNOWN_OUTSIDE_TOKYO_23_RE.search(t):
        return False
    return bool(TOKYO_23_RE.search(t) or TOKYO_PLACE_RE.search(t))


def is_outside_text(t):
    return bool(NON_TOKYO_PREF_RE.search(t) or KNOWN_OUTSIDE_TOKYO_23_RE.search(t)
                or OTHER_WARD_CITY_RE.search(t))


F = collections.defaultdict(lambda: dict(
    n=0, bon=0, bon23=0, out=0, url=0, listy=0, op=0, first=0, detail=0,
    media=0, length=0, days=set(), texts=[]))

for v in voices:
    if v.get('source') not in ('x', 'x_whitelist'):
        continue
    h = (v.get('account') or '').lstrip('@').lower()
    if not h:
        continue
    t = v.get('text') or ''
    f = F[h]
    f['n'] += 1
    f['length'] += len(t)
    f['days'].add((v.get('date') or '')[:10])
    isbon = bool(BON_RE.search(t))
    if isbon:
        f['bon'] += 1
    if isbon and is_tokyo23_text(t):
        f['bon23'] += 1
        if len(f['texts']) < 2:
            f['texts'].append(t[:88].replace('\n', ' / '))
    if is_outside_text(t):
        f['out'] += 1
    if 'http' in t:
        f['url'] += 1
    lines = [l for l in t.splitlines() if l.strip()]
    if sum(1 for l in lines if DATE_RE.match(l.strip())) >= 3 or len(lines) >= 8:
        f['listy'] += 1
    if OPINION_RE.search(t):
        f['op'] += 1
    if FIRST_RE.search(t):
        f['first'] += 1
    if DETAIL_RE.search(t):
        f['detail'] += 1
    if v.get('media_urls'):
        f['media'] += 1

PRIOR = 5.0


def smooth(c, n, base):
    return (c + PRIOR * base) / (n + PRIOR)


def prof(h):
    f = F.get(h)
    if not f or f['n'] == 0:
        return None
    n = f['n']
    return dict(n=n, days=len(f['days']), bon23=f['bon23'], bon=f['bon'], out=f['out'],
                bon23_r=smooth(f['bon23'], n, 0.10), url_r=f['url'] / n,
                first_r=smooth(f['first'], n, 0.20), listy_r=smooth(f['listy'], n, 0.15),
                op_r=smooth(f['op'], n, 0.35), detail_r=smooth(f['detail'], n, 0.30),
                media_r=smooth(f['media'], n, 0.30), avg_len=f['length'] / n,
                texts=f['texts'])


def is_area_bot(h, p):
    if not p or p['n'] < 4:
        return False
    f = F[h]
    mechanical = f['url'] / p['n'] >= 0.8 and f['first'] / p['n'] <= 0.15
    return mechanical and p['bon23'] == 0 and (f['out'] / p['n'] >= 0.4 or f['bon'] / p['n'] < 0.5)


def announce(h):
    r = scores.get(h, {})
    p = prof(h)
    recfut = r.get('recent_future_schedule_posts', 0) or 0
    s = min(10.0, 10 * math.log1p(recfut) / math.log1p(20))
    if p:
        s += 14 * p['bon23_r']
        s -= 5 * max(0.0, p['listy_r'] - 0.3)
        # 23区の盆踊り実績が本文で確認できないなら、量だけでは上位に上げない
        if p['bon23'] == 0 and p['n'] >= 5:
            s = min(s, 8.0)
    s += 5 * min(gap.get(h, 0), 3)
    if is_area_bot(h, p):
        s -= 15
    return round(s, 2)


def voice(h):
    r = scores.get(h, {})
    p = prof(h)
    if not p or p['n'] < 3:
        return 0.0
    s = 10 * p['op_r'] * (0.5 + 0.5 * p['first_r'])
    s += 6 * p['detail_r'] + 3 * p['media_r'] + 4 * min(p['avg_len'] / 150, 1.0)
    s += 8 * p['bon23_r'] - 8 * p['listy_r'] + 3 * min(p['days'] / 10.0, 1.0)
    if (r.get('recent_posts_seen', 0) or 0) == 0:
        s -= 3
    if is_area_bot(h, p):
        s -= 10
    return round(s, 2)


cand = []
for key, row in scores.items():
    if row.get('status') == 'trusted' and (row.get('posts_seen') or 0) >= 3:
        s = row.get('usefulness_score', 0) or 0
        if s >= 6:
            cand.append((s, (row.get('handle') or '@' + key).lstrip('@').lower()))
cand.sort(key=lambda i: (-i[0], i[1]))
cur = [h for _, h in cand[:250]]
curset = set(cur)

pool = set(scores) | set(F)
ann = sorted(((announce(h), h) for h in pool), reverse=True)
voi = sorted(((voice(h), h) for h in pool), reverse=True)
A = [h for _, h in ann[:180]]
V = [h for _, h in voi[:60]]
keep_manual = [h for h, st in manual.items() if st in ('優先', '通常')]
newset = set(A) | set(V) | set(keep_manual)
bots = [h for h in pool if is_area_bot(h, prof(h))]

print('地域bot判定 %d件（うち現行250に %d件）' % (len(bots), sum(1 for h in bots if h in curset)))
print('新名簿: 告知%d + 意見%d + 手動優先/通常%d = 実人数 %d（現行250との重なり %d）' % (
    len(A), len(V), len(keep_manual), len(newset), len(newset & curset)))
print('告知と意見の両方に載る人: %d' % len(set(A) & set(V)))

print('\n--- 告知力 上位20（これからのイベントを教えてくれる） ---')
for s, h in ann[:20]:
    r = scores.get(h, {}); p = prof(h) or {}
    print('%6.2f @%-20s 現行%-5s 直近告知%3d 23区盆%2s 出口%d %s' % (
        s, h, h in curset, r.get('recent_future_schedule_posts', 0), p.get('bon23', '-'),
        gap.get(h, 0), (p.get('texts') or [''])[0][:40]))

print('\n--- コンテンツ力 上位20（盆踊りへの意見・体験） ---')
for s, h in voi[:20]:
    p = prof(h) or {}
    print('%6.2f @%-20s 現行%-5s 投稿%3s 日数%2s 意見%.2f 具体%.2f %s' % (
        s, h, h in curset, p.get('n', '-'), p.get('days', '-'), p.get('op_r', 0),
        p.get('detail_r', 0), (p.get('texts') or [''])[0][:38]))

drop = [h for h in cur if h not in newset]
add = sorted(h for h in newset if h not in curset)
print('\n入替: 外す %d / 入れる %d / 残る %d → 新名簿 %d人' % (
    len(drop), len(add), len(cur) - len(drop), len(newset)))

print('\n--- 外す候補・収集量が多い順20（節約が大きい順） ---')
for h in sorted(drop, key=lambda h: -(scores.get(h, {}).get('recent_posts_seen', 0) or 0))[:20]:
    p = prof(h) or {}
    print('  @%-20s 直近%3d件 告知%6.2f 意見%6.2f 23区盆%2s bot=%s' % (
        h, scores.get(h, {}).get('recent_posts_seen', 0), announce(h), voice(h),
        p.get('bon23', '-'), is_area_bot(h, prof(h))))

print('\n--- 新しく入れる候補・上位20 ---')
for h in sorted(add, key=lambda h: -max(announce(h), voice(h)))[:20]:
    p = prof(h) or {}
    r = scores.get(h, {})
    print('  @%-20s 告知%6.2f 意見%6.2f 直近告知%3d 23区盆%2s 出口%d %s' % (
        h, announce(h), voice(h), r.get('recent_future_schedule_posts', 0),
        p.get('bon23', '-'), gap.get(h, 0), (p.get('texts') or [''])[0][:36]))

json.dump(dict(
    announce_list=[[round(s, 2), h] for s, h in ann[:180]],
    voice_list=[[round(s, 2), h] for s, h in voi[:60]],
    manual_keep=sorted(keep_manual), bots=sorted(bots),
    drop=sorted(drop), add=add, current=cur),
    open(os.path.join(SP, 'roster_proposal.json'), 'w'), ensure_ascii=False, indent=1)
print('\n→ roster_proposal.json に書き出しました')
