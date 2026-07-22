"""Extract public song hints from bon-odori event text."""

import json
import re
from functools import lru_cache
from pathlib import Path

from collection_support.suppression_rules import blocked_cultural_match, is_generic_song_name

DATA_DIR = Path(__file__).resolve().parents[1] / "data"
SONG_MASTER_REGISTRATION = DATA_DIR / "song_master_initial_registration.json"
RDB_SONG_REVIEW_SOURCE = DATA_DIR / "rdb_song_review_source.json"


SONG_CONTEXT_RE = re.compile(
    r"(?:曲目表|曲目|曲順|曲|踊る曲|踊り|選曲|流れる曲|セットリスト|セトリ|演目|プログラム)"
    r"(?:は|：|:|として|に)?\s*([^。\n]{2,140})"
)
SONG_NAME_RE = re.compile(
    r"([一-龥ぁ-んァ-ヶA-Za-z0-9・ー]{2,28}"
    r"(?:音頭|おどり|踊り|小唄|甚句|節|ソーラン|八木節|盆ジョビ))"
)
KNOWN_SONG_RE = re.compile(
    r"(東京音頭|炭坑節|河内音頭|江州音頭|郡上おどり|郡上踊り|"
    r"花笠音頭|ソーラン節|大東京音頭|東京五輪音頭|ドラえもん音頭|"
    r"アンパンマン音頭|ダンシングヒーロー|ビューティフルサンデー|"
    r"おはら節|Beat It|盆ジョビ)"
)
CANDIDATE_CONTEXT_RE = re.compile(
    r"(?:曲目表|曲目|曲順|曲|踊る曲|踊り|踊った|選曲|流れる曲|流れ|セットリスト|セトリ|演目|"
    r"プログラム|告知|発表|レクチャー|練習|予習|リクエスト)"
)
CANDIDATE_SEGMENT_RE = re.compile(
    r"(?:曲目表|曲目|曲順|踊る曲|選曲|流れる曲|セットリスト|セトリ|演目|プログラム|リクエスト)"
    r"(?:は|：|:|として|に)?\s*([^。\n]{2,140})"
)

STOPWORDS = {
    "盆踊り",
    "盆おどり",
    "納涼踊り",
    "踊り大会",
    "民踊",
    "民踊大会",
    "盆踊り大会",
    "盆おどり大会",
    "盆踊り",
    "盆おどり",
}


def _norm_song(value):
    return re.sub(r"\s+", "", str(value or "")).casefold()


def _load_json(path):
    if not path.exists():
        return {}
    with path.open(encoding="utf-8") as handle:
        return json.load(handle)


@lru_cache(maxsize=1)
def master_song_names():
    """Known song names registered or reviewed in the local song sources."""
    names = set()
    registration = _load_json(SONG_MASTER_REGISTRATION)
    for bucket in ("created", "skipped"):
        for row in registration.get(bucket) or []:
            name = row.get("song_name")
            if name:
                names.add(name)

    rdb = _load_json(RDB_SONG_REVIEW_SOURCE)
    for row in rdb.get("rows") or []:
        name = row.get("canonical_song_name") or row.get("term")
        if name:
            names.add(name)

    return tuple(sorted(names, key=lambda name: (-len(name), name)))


@lru_cache(maxsize=1)
def master_song_norms():
    return {_norm_song(name) for name in master_song_names()}


def is_master_song(value):
    return _norm_song(value) in master_song_norms()


def _clean_song(value):
    value = re.sub(r"^[、。・\s]+|[、。・\s]+$", "", value or "")
    value = re.sub(r"^(?:曲目は|曲は|演目は|などの)", "", value)
    value = re.sub(r"^(?:演目|曲目|プログラム|program)[・:：]?", "", value, flags=re.IGNORECASE)
    value = re.sub(r"^回(?=[一-龥ぁ-んァ-ヶーA-Za-z0-9])", "", value)
    value = re.sub(r"^.*さん(?:の|による)", "", value)
    value = re.sub(r"^初の", "", value)
    value = re.sub(r"(?:など|ほか|他|って言う|という|と民謡|を|で)?踊り$", lambda m: "" if m.group(0) != "踊り" else m.group(0), value)
    value = value.strip(" 「」『』（）()[]【】")
    if value.endswith("など"):
        value = value[:-2]
    return value.strip()


def _add(out, value, source, explicit_list=False):
    song = _clean_song(value)
    if not song or song in STOPWORDS:
        return
    master_song = is_master_song(song)
    if re.search(r"[0-9０-９]|盆踊り|盆おどり|奉納|祭礼|例大祭", song):
        return
    # 明示的な曲目リスト内では「あさりときりみのおだいどこ音頭」のような
    # 助詞入りのご当地曲名を許可する。通常本文では文章断片の誤抽出を避ける。
    if not (master_song or explicit_list) and re.search(r"[がをにへでからの]", song):
        return
    if len(song) < 2 or len(song) > 28:
        return
    if (
        not re.search(r"(音頭|おどり|踊り|小唄|甚句|節|ソーラン|八木節|盆ジョビ|ヒーロー)$", song)
        and not KNOWN_SONG_RE.fullmatch(song)
        and not master_song
    ):
        return
    for item in out:
        if item["name"] == song:
            item["sources"].add(source)
            return
    out.append({"name": song, "sources": {source}})


def extract_song_hints(*texts):
    """Return song hints as [{name, confidence, source_count}].

    The extractor is intentionally conservative. It prefers explicit song
    contexts such as "曲目は..." and common bon-odori song-name suffixes.
    """
    found = []
    for index, text in enumerate(texts):
        if not text:
            continue
        source = f"text_{index + 1}"
        for match in KNOWN_SONG_RE.finditer(text):
            _add(found, match.group(1), source)
        for song in master_song_names():
            for match in re.finditer(re.escape(song), text):
                start = max(0, match.start() - 40)
                end = min(len(text), match.end() + 30)
                if CANDIDATE_CONTEXT_RE.search(text[start:end]):
                    _add(found, song, source)
        for context in SONG_CONTEXT_RE.finditer(text):
            segment = context.group(1)
            for match in SONG_NAME_RE.finditer(segment):
                _add(found, match.group(1), source, explicit_list=True)
        for match in SONG_NAME_RE.finditer(text):
            name = match.group(1)
            start = max(0, match.start() - 40)
            end = min(len(text), match.end() + 18)
            window = text[start:end]
            if re.search(r"(曲目|曲|踊|選曲|流れ|披露|レクチャー|練習)", window):
                _add(found, name, source)

    return [
        {
            "name": item["name"],
            "confidence": "confirmed" if len(item["sources"]) >= 2 else "hint",
            "source_count": len(item["sources"]),
        }
        for item in found
    ]


def _split_candidate_segment(segment):
    parts = re.split(r"[、,／/・\n]|(?:\s+他)|(?:\s+ほか)", segment or "")
    for part in parts:
        value = _clean_song(part)
        value = re.sub(r"^(?:からはじまり|では|は|も|と|で|を|に|が|そして)\s*", "", value)
        value = re.sub(r"(?:からはじまり|など|ほか|他)$", "", value).strip()
        if value:
            yield value


def _candidate_ok(song):
    if not song or song in STOPWORDS:
        return False
    if is_generic_song_name(song):
        return False
    if blocked_cultural_match(song):
        return False
    if re.search(
        r"[0-9０-９]{2,}|https?|t\.co|youtu\.be|盆踊り|盆おどり|開催|会場|時間|午後|午前|"
        r"行き|行っ|踊り方|様子|ご覧|コンテンツ|イベント|講習会|協議会|サークル|神輿|"
        r"奉納|祭礼|例大祭|流し踊り|今年|去年|一昨年|ちなみに|最近|毎年|見て|ずっと|"
        r"着て|中で|伝統曲|民謡歌手|難しい|嬉しそう|あたらしく|踊り好き",
        song,
    ):
        return False
    if len(song) >= 12 and re.search(r"[がをにへでからのとや]", song):
        return False
    if len(song) < 2 or len(song) > 28:
        return False
    if re.search(r"(音頭|おどり|踊り|小唄|甚句|節|ソーラン|八木節|盆ジョビ|ヒーロー)$", song):
        return True
    if KNOWN_SONG_RE.fullmatch(song):
        return True
    if KNOWN_SONG_RE.fullmatch(song):
        return True
    if re.fullmatch(r"(?:Beat It)", song):
        return True
    if re.fullmatch(r"[一-龥ぁ-んァ-ヶーA-Za-z0-9・]{3,18}", song) and re.search(
        r"(サンデー|ヒーロー|ビート|ロック|ソング|唄|歌)$", song
    ):
        return True
    return False


def extract_song_candidates(text):
    """Return broader song candidates for human review.

    This intentionally catches more than `extract_song_hints`; callers should
    keep the result in a review queue until confirmed.
    """
    if not text:
        return []
    found = []

    def add(name, reason):
        name = _clean_song(name)
        if not _candidate_ok(name):
            return
        if blocked_cultural_match(text):
            return
        for item in found:
            if item["name"] == name:
                item["reasons"].add(reason)
                return
        found.append({"name": name, "reasons": {reason}})

    for match in KNOWN_SONG_RE.finditer(text):
        start = max(0, match.start() - 28)
        end = min(len(text), match.end() + 28)
        if CANDIDATE_CONTEXT_RE.search(text[start:end]):
            add(match.group(1), "known_song_context")

    for context in CANDIDATE_SEGMENT_RE.finditer(text):
        segment = context.group(1)
        for match in SONG_NAME_RE.finditer(segment):
            add(match.group(1), "song_suffix_in_context")
        for part in _split_candidate_segment(segment):
            add(part, "split_context")

    for match in SONG_NAME_RE.finditer(text):
        start = max(0, match.start() - 40)
        end = min(len(text), match.end() + 30)
        if CANDIDATE_CONTEXT_RE.search(text[start:end]):
            add(match.group(1), "song_suffix_near_context")

    return [
        {"name": item["name"], "reasons": sorted(item["reasons"])}
        for item in found
    ]
