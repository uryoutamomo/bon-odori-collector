"""Build yearly event-song evidence and prediction snapshots."""

import hashlib
import json
import math
import re
from collections import defaultdict
from datetime import datetime, timezone
from pathlib import Path

from event_model.event_series_normalization import series_event_name
from collection_support.event_evidence import dancer_key


DATA = Path("data")
YOUTUBE_REVIEW = DATA / "youtube_song_candidates_review.json"
YOUTUBE_SETLIST_OCCURRENCES = DATA / "youtube_setlist_occurrences.json"
PUBLIC_EVENTS = DATA / "public" / "events_public.json"
MANUAL_EVIDENCE = DATA / "song_evidence_manual.json"
PREDICTION_PARAMS = DATA / "prediction_params.json"
OUT_OCCURRENCES = DATA / "song_occurrences.json"
OUT_PUBLIC = DATA / "public" / "event_song_occurrences_public.json"
OUT_SNAPSHOT = DATA / "song_prediction_snapshots.json"

ISO_DATE_RE = re.compile(r"(20\d{2})[-/年](\d{1,2})[-/月](\d{1,2})日?")
JP_DATE_RE = re.compile(r"(20\d{2})年\s*(\d{1,2})月\s*(\d{1,2})日")
EN_DATE_RE = re.compile(
    r"\b(January|February|March|April|May|June|July|August|September|October|November|December)"
    r"\s+(\d{1,2})(?:st|nd|rd|th)?[,]?\s+(20\d{2})\b",
    re.IGNORECASE,
)
EN_MONTHS = {
    "january": 1,
    "february": 2,
    "march": 3,
    "april": 4,
    "may": 5,
    "june": 6,
    "july": 7,
    "august": 8,
    "september": 9,
    "october": 10,
    "november": 11,
    "december": 12,
}
SETLIST_RE = re.compile(r"(?:曲目|曲順|セットリスト|セトリ|演目|プログラム)")
ANNOUNCED_RE = re.compile(r"(?:曲目表|プログラム|演目|曲目|曲順|予定|告知|発表|踊ります)")
OBSERVED_RE = re.compile(r"(?:行われました|開催された|様子|踊った|踊りました|お届けします|動画|YouTube)")

DEFAULT_PREDICTION_PARAMS = {
    "reliability": {
        "official_setlist": 0.95,
        "semi_official_setlist": 0.80,
        "regular_advance_mention": 0.55,
        "complete_numbered_video": 0.95,
        "partial_impression": 0.70,
        "curated_public_song": 0.80,
        "public_event_hint": 0.40,
        "unknown": 0.50,
    },
    "decay_rate": 0.75,
    "prior_probability": 0.15,
    "combination": "independent_noisy_or",
}


def load_json(path, default):
    path = Path(path)
    if not path.exists():
        return default
    with path.open(encoding="utf-8") as handle:
        return json.load(handle)


def prediction_params():
    params = DEFAULT_PREDICTION_PARAMS.copy()
    raw = load_json(PREDICTION_PARAMS, {})
    params.update({k: v for k, v in raw.items() if k != "reliability"})
    reliability = dict(DEFAULT_PREDICTION_PARAMS["reliability"])
    reliability.update(raw.get("reliability") or {})
    params["reliability"] = reliability
    return params


def normalize_name(value):
    return re.sub(r"\s+", "", str(value or "")).casefold()


YOUTUBE_SETLIST_CANONICAL_FIXES = (
    {
        "match": "マロニエまつり盆踊り大会 2 ヒューリック浅草橋ビル前(全曲ver)",
        "event_name": "浅草橋マロニエまつり盆踊り",
        "venue": "ヒューリック浅草橋ビル前",
    },
)


def canonicalize_youtube_setlist_event(event_name, venue):
    for fix in YOUTUBE_SETLIST_CANONICAL_FIXES:
        if fix["match"] in event_name:
            return fix["event_name"], fix["venue"]
    return event_name, venue


def occurrence_id(event_name, venue, year):
    raw = f"{normalize_name(series_event_name(event_name))}\0{normalize_name(venue)}\0{year}"
    return hashlib.sha256(raw.encode("utf-8")).hexdigest()[:16]


def evidence_id(url, song_name, event_name, year):
    raw = f"{url or ''}\0{normalize_name(song_name)}\0{normalize_name(series_event_name(event_name))}\0{year}"
    return hashlib.sha256(raw.encode("utf-8")).hexdigest()[:20]


def parse_event_date(*texts, fallback_year=None):
    for text in texts:
        if not text:
            continue
        for pattern in (JP_DATE_RE, ISO_DATE_RE):
            match = pattern.search(str(text))
            if match:
                y, m, d = [int(part) for part in match.groups()]
                return f"{y:04d}-{m:02d}-{d:02d}"
        match = EN_DATE_RE.search(str(text))
        if match:
            month_name, day, year = match.groups()
            month = EN_MONTHS[month_name.casefold()]
            return f"{int(year):04d}-{month:02d}-{int(day):02d}"
    if fallback_year:
        return f"{int(fallback_year):04d}-01-01"
    return None


def evidence_kind(text, source=""):
    text = str(text or "")
    source = str(source or "")
    if ANNOUNCED_RE.search(text) and not OBSERVED_RE.search(text):
        return "announced"
    if source == "youtube" or OBSERVED_RE.search(text):
        return "observed"
    return "hint"


def has_complete_setlist(text, song_count=0):
    text = str(text or "")
    numbered = re.findall(r"(?:^|\n)\s*[0-9０-９]{1,2}\s*[\.．、]?\s*[^\n]{2,40}", text)
    return bool(SETLIST_RE.search(text) and (song_count >= 3 or len(numbered) >= 3))


def speaker_key(value):
    value = str(value or "").strip()
    return value or "unknown"


def speaker_dancer_key(value):
    value = str(value or "").strip()
    if not value.startswith("@"):
        return ""
    return dancer_key(value)


def empty_prediction_block(target):
    return {
        "target": target,
        "status": "not_calculated",
        "probability": None,
        "basis": "not_implemented",
        "basis_label": "未計算",
        "evidence": [],
    }


def observation_act(ev):
    if ev.get("kind") == "announced":
        return "announce"
    text = str(ev.get("text") or "")
    if re.search(r"(?:行った|行ってきた|参加した|踊った|踊ってきた)", text):
        return "attend"
    return "observe"


def build_observations(occurrence):
    grouped = {}
    for song in occurrence.get("songs", {}).values():
        for ev in song.get("evidence", []):
            key = ev.get("dancer_key") or ""
            speaker = speaker_key(ev.get("speaker"))
            actor = key or speaker
            if not actor:
                continue
            act = observation_act(ev)
            obs_key = (actor, act)
            observation = grouped.setdefault(obs_key, {
                "dancer_key": key,
                "speaker": speaker,
                "act": act,
                "targets": set(),
                "evidence_ids": set(),
                "evidence_urls": set(),
                "first_observed_at": "",
                "last_observed_at": "",
            })
            observation["targets"].add("songs")
            if ev.get("id"):
                observation["evidence_ids"].add(ev["id"])
            if ev.get("url"):
                observation["evidence_urls"].add(ev["url"])
            observed_at = ev.get("observed_at") or ev.get("date") or ""
            if observed_at:
                if not observation["first_observed_at"] or observed_at < observation["first_observed_at"]:
                    observation["first_observed_at"] = observed_at
                if observed_at > observation["last_observed_at"]:
                    observation["last_observed_at"] = observed_at

    rows = []
    for observation in grouped.values():
        rows.append({
            "dancer_key": observation["dancer_key"],
            "speaker": observation["speaker"],
            "act": observation["act"],
            "targets": sorted(observation["targets"]),
            "evidence_ids": sorted(observation["evidence_ids"]),
            "evidence_urls": sorted(observation["evidence_urls"])[:5],
            "first_observed_at": observation["first_observed_at"],
            "last_observed_at": observation["last_observed_at"],
        })
    rows.sort(key=lambda row: (row["dancer_key"] or row["speaker"], row["act"]))
    return rows


def reliability_for_evidence(ev, params=None):
    params = params or prediction_params()
    value = ev.get("reliability")
    if value is not None:
        return max(0.0, min(1.0, float(value)))
    key = ev.get("reliability_key")
    if key:
        return float(params["reliability"].get(key, params["reliability"]["unknown"]))
    if ev.get("kind") == "announced":
        return float(params["reliability"]["official_setlist"])
    if ev.get("kind") == "observed" and ev.get("setlist_complete"):
        return float(params["reliability"]["complete_numbered_video"])
    if ev.get("kind") == "observed":
        return float(params["reliability"]["partial_impression"])
    if ev.get("source") == "events_public":
        return float(params["reliability"]["public_event_hint"])
    return float(params["reliability"]["unknown"])


def noisy_or(reliabilities):
    miss = 1.0
    for reliability in reliabilities:
        miss *= 1.0 - max(0.0, min(1.0, float(reliability)))
    return 1.0 - miss


def evidence_role(observed_at=None, event_start=None, kind=None):
    if observed_at and event_start:
        return "prediction" if str(observed_at) < str(event_start) else "result"
    if kind == "observed":
        return "result"
    return "prediction"


def evidence_view_for_year(evidence_items, occ_year):
    """Return evidence as seen from a given occurrence year.

    過去年の証拠は当年予測の「根拠付き継承」として role=prediction に降格し
    inherited フラグを付ける（前年実績を確定情報に見せないため。較正の
    result 教師にも混入させない）。未来年の証拠は当年には使わない。
    """
    view = []
    for ev in evidence_items:
        year = ev.get("year")
        if year is None or year > occ_year:
            continue
        if year < occ_year:
            inherited = dict(ev)
            inherited["role"] = "prediction"
            inherited["inherited"] = True
            inherited["source_year"] = year
            view.append(inherited)
        else:
            view.append(ev)
    return view


def prediction_probability(evidence_items, target_year, params=None):
    """Return probability and label for one event-song relation.

    Prediction evidence uses reliability composition:
    P = 1 - product(1 - reliability_i). Past evidence decays by elapsed year.
    """
    params = params or prediction_params()
    if not evidence_items:
        return {
            "probability": 0,
            "basis": "no_evidence",
            "basis_label": "根拠なし",
        }
    current = [ev for ev in evidence_items if ev.get("year") == target_year]
    current_predictions = [ev for ev in current if ev.get("role") != "result"]
    if current_predictions:
        probability = round(noisy_or(reliability_for_evidence(ev, params) for ev in current_predictions) * 100)
        kinds = {ev.get("kind") for ev in current_predictions}
        speakers = {speaker_key(ev.get("speaker")) for ev in current_predictions}
        if "announced" in kinds:
            basis = "current_announced"
            label = "今年告知"
        else:
            basis = "current_hint"
            label = "今年ヒント"
        return {
            "probability": max(1, min(99, probability)),
            "basis": basis,
            "basis_label": label,
            "speaker_count": len(speakers),
        }
    if any(ev.get("kind") == "observed" for ev in current):
        probability = round(noisy_or(reliability_for_evidence(ev, params) for ev in current) * 100)
        return {"probability": max(1, min(99, probability)), "basis": "current_observed", "basis_label": "今年実測"}

    past = [ev for ev in evidence_items if ev.get("year") and ev.get("year") < target_year]
    if past:
        by_year = {}
        for evidence in past:
            by_year.setdefault(evidence["year"], []).append(evidence)
        annual_probabilities = []
        annual_kinds = []
        for evidence_year in sorted(by_year):
            annual_evidence = by_year[evidence_year]
            base = noisy_or(reliability_for_evidence(ev, params) for ev in annual_evidence)
            annual_speakers = {speaker_key(ev.get("speaker")) for ev in annual_evidence}
            speaker_factor = min(1.0, 0.65 + 0.15 * max(1, len(annual_speakers)))
            annual_probabilities.append(
                base
                * (float(params["decay_rate"]) ** (target_year - evidence_year))
                * speaker_factor
            )
            annual_kinds.append(
                max(
                    (ev.get("kind") for ev in annual_evidence),
                    key=lambda value: {"announced": 3, "observed": 2, "hint": 1}.get(value, 0),
                )
            )
        probability = round(noisy_or(annual_probabilities) * 100)
        source_years = sorted(by_year)
        latest_year = source_years[-1]
        speakers = {speaker_key(ev.get("speaker")) for ev in past}
        if len(set(annual_kinds)) == 1:
            kind_label = {
                "announced": "告知",
                "observed": "実測",
                "hint": "ヒント",
            }.get(annual_kinds[-1], "実績")
        else:
            kind_label = "実績"
        year_label = "・".join(str(year) for year in source_years)
        return {
            "probability": max(5, min(90, probability)),
            "basis": "past_evidence",
            "basis_label": f"{year_label}年{kind_label}",
            "latest_year": latest_year,
            "source_years": source_years,
            "speaker_count": len(speakers),
        }
    return {
        "probability": round(float(params["prior_probability"]) * 100),
        "basis": "prior",
        "basis_label": "階層prior未設定",
    }


def _add_evidence(grouped, event_name, venue, song_name, event_date, kind, speaker,
                  url="", text="", setlist_complete=False, source="", observed_at=None,
                  event_start=None, reliability=None, reliability_key=None, role=None):
    if not event_date:
        return
    event_name = series_event_name(event_name)
    year = int(event_date[:4])
    role = role or evidence_role(observed_at=observed_at, event_start=event_start, kind=kind)
    if reliability is None:
        reliability = reliability_for_evidence({
            "kind": kind,
            "source": source,
            "setlist_complete": setlist_complete,
            "reliability_key": reliability_key,
        })
    key = (event_name, venue, year, song_name)
    grouped[key].append({
        "id": evidence_id(url, song_name, event_name, year),
        "kind": kind,
        "role": role,
        "setlist_complete": bool(setlist_complete),
        "speaker": speaker_key(speaker),
        "dancer_key": speaker_dancer_key(speaker),
        "url": url or "",
        "date": event_date,
        "event_start": event_start or "",
        "observed_at": observed_at or "",
        "year": year,
        "source": source or "",
        "reliability": reliability,
        "reliability_key": reliability_key or "",
        "text": re.sub(r"\s+", " ", str(text or "")).strip()[:240],
    })


def occurrences_from_youtube_review(review):
    grouped = defaultdict(list)
    for event in review.get("events", []):
        event_name = series_event_name(event.get("event_name") or "")
        venue = event.get("venue") or ""
        sample_text = "\n".join(event.get("sample_titles") or [])
        for song in event.get("songs", []):
            titles = song.get("sample_titles") or []
            text = "\n".join(titles) or sample_text
            event_date = parse_event_date(text)
            kind = evidence_kind(text, "youtube")
            setlist_complete = (event.get("song_count") or 0) >= 3 or has_complete_setlist(
                text, event.get("song_count") or 0
            )
            urls = song.get("urls") or []
            if not urls:
                urls = [""]
            for url in urls:
                _add_evidence(
                    grouped,
                    event_name,
                    venue,
                    song.get("name") or "",
                    event_date,
                    kind,
                    "youtube",
                    url=url,
                    text=text,
                    setlist_complete=setlist_complete,
                    source="youtube_review",
                )
    return grouped


def occurrences_from_youtube_setlists(data):
    grouped = defaultdict(list)
    for occurrence in data.get("occurrences", []):
        event_date = occurrence.get("event_date")
        if not event_date:
            continue
        event_name = series_event_name(occurrence.get("canonical_event_name") or occurrence.get("event_name_hint") or "")
        venue = occurrence.get("canonical_venue") or occurrence.get("venue") or ""
        event_name, venue = canonicalize_youtube_setlist_event(event_name, venue)
        source_by_url = {
            item.get("url"): item
            for item in occurrence.get("source_videos") or []
            if item.get("url")
        }
        accounts = occurrence.get("accounts") or []
        setlist_complete = (occurrence.get("song_count") or 0) >= 3
        for song in occurrence.get("setlist") or []:
            url = song.get("url") or ""
            source_video = source_by_url.get(url) or {}
            speaker = source_video.get("account") or (accounts[0] if accounts else "youtube")
            observed_at = source_video.get("published_at") or event_date
            text = " / ".join(
                part for part in [
                    occurrence.get("event_name_hint"),
                    occurrence.get("venue"),
                    event_date,
                    song.get("title"),
                ] if part
            )
            _add_evidence(
                grouped,
                event_name,
                venue,
                song.get("title") or "",
                event_date,
                "observed",
                speaker,
                url=url,
                text=text,
                setlist_complete=setlist_complete,
                source="youtube_setlist_occurrence",
                observed_at=observed_at,
                event_start=event_date,
                reliability_key="complete_numbered_video" if setlist_complete else "partial_impression",
                role="result",
            )
    return grouped


def occurrences_from_public_events(events):
    grouped = defaultdict(list)
    for event in events:
        event_name = series_event_name(event.get("name") or "")
        venue = event.get("venue") or ""
        event_date = event.get("date")
        text = "\n".join(x for x in [event.get("description"), event.get("detail")] if x)
        if not event_date:
            continue
        for song in event.get("songs") or []:
            reliability_key = (
                "official_setlist"
                if song.get("confidence") == "confirmed"
                else "curated_public_song"
            )
            _add_evidence(
                grouped,
                event_name,
                venue,
                song.get("name") or "",
                event_date,
                "hint",
                "public_event_snapshot",
                text=text,
                setlist_complete=False,
                source="events_public",
                reliability_key=reliability_key,
            )
    return grouped


def occurrences_from_manual_evidence(manual):
    grouped = defaultdict(list)
    for item in manual.get("evidence", []):
        songs = item.get("songs") or []
        text = item.get("text") or "\n".join(songs)
        event_date = item.get("event_date") or parse_event_date(text, fallback_year=item.get("year"))
        for song_name in songs:
            _add_evidence(
                grouped,
                series_event_name(item.get("event_name") or ""),
                item.get("venue") or "",
                song_name,
                event_date,
                item.get("kind") or evidence_kind(text, item.get("source")),
                item.get("speaker") or item.get("account") or "manual",
                url=item.get("url") or "",
                text=text,
                setlist_complete=item.get("setlist_complete", len(songs) >= 3),
                source=item.get("source") or "manual",
                observed_at=item.get("observed_at"),
                event_start=item.get("event_start"),
                reliability=item.get("reliability"),
                reliability_key=item.get("reliability_key"),
                role=item.get("role"),
            )
    return grouped


def merge_grouped(*grouped_maps):
    merged = defaultdict(list)
    seen = set()
    for grouped in grouped_maps:
        for key, rows in grouped.items():
            for row in rows:
                dedupe = row.get("id")
                if dedupe in seen:
                    continue
                seen.add(dedupe)
                merged[key].append(row)
    return merged


def build_occurrences(target_year=None, generated_at=None):
    target_year = target_year or datetime.now(timezone.utc).year
    generated_at = generated_at or datetime.now(timezone.utc).isoformat()
    review = load_json(YOUTUBE_REVIEW, {})
    youtube_setlists = load_json(YOUTUBE_SETLIST_OCCURRENCES, {})
    events = load_json(PUBLIC_EVENTS, [])
    manual = load_json(MANUAL_EVIDENCE, {})
    params = prediction_params()
    youtube_grouped = (
        occurrences_from_youtube_setlists(youtube_setlists)
        if youtube_setlists.get("occurrences")
        else occurrences_from_youtube_review(review)
    )
    grouped = merge_grouped(
        youtube_grouped,
        occurrences_from_public_events(events),
        occurrences_from_manual_evidence(manual),
    )

    # シリーズ（イベント×会場を年抜きで正規化したキー）単位に証拠を横断集約し、
    # 前年実績を当年 occurrence の予測根拠として継承できるようにする。
    # occurrence の単位（occ_key）は従来どおり年込みで保持する。
    series_song_evidence = defaultdict(list)
    series_all_songs = defaultdict(set)
    occ_units = {}
    for (event_name, venue, year, song_name), evidence in grouped.items():
        series = (normalize_name(series_event_name(event_name)), normalize_name(venue))
        series_song_evidence[(series, song_name)].extend(evidence)
        series_all_songs[series].add(song_name)
        occ_key = occurrence_id(event_name, venue, year)
        unit = occ_units.setdefault(occ_key, {
            "event_name": event_name,
            "venue": venue,
            "year": year,
            "series": series,
            "current_songs": set(),
        })
        unit["current_songs"].add(song_name)

    # 公開イベントに開催日がある年は、曲証拠がまだ空でも occurrence を作る。
    # これにより、2026年公式日程だけがある開催回へ過去年の曲実績を継承できる。
    for event in events:
        event_name = series_event_name(event.get("name") or "")
        venue = event.get("venue") or ""
        event_date = event.get("date") or ""
        if not event_name or not venue or not re.match(r"^\d{4}-\d{2}-\d{2}$", event_date):
            continue
        year = int(event_date[:4])
        occ_key = occurrence_id(event_name, venue, year)
        occ_units.setdefault(occ_key, {
            "event_name": event_name,
            "venue": venue,
            "year": year,
            "series": (normalize_name(event_name), normalize_name(venue)),
            "current_songs": set(),
        })

    occurrences = {}
    for occ_key, unit in occ_units.items():
        year = unit["year"]
        series = unit["series"]
        occurrence = occurrences.setdefault(occ_key, {
            "occurrence_id": occ_key,
            "event_name": unit["event_name"],
            "venue": unit["venue"],
            "year": year,
            "predictions": {
                "existence": empty_prediction_block("existence"),
                "date": empty_prediction_block("date"),
            },
            "observations": [],
            "songs": {},
        })
        # 当年（予測対象年）の occurrence には同シリーズの過去曲も継承候補として載せる。
        # 過去 occurrence は実績なので、その年に観測された曲だけを保持する。
        if year == target_year:
            song_names = set(unit["current_songs"]) | series_all_songs[series]
        else:
            song_names = set(unit["current_songs"])
        for song_name in song_names:
            view = evidence_view_for_year(series_song_evidence[(series, song_name)], year)
            if not view:
                continue
            speakers = sorted({speaker_key(ev.get("speaker")) for ev in view})
            occurrence["songs"][song_name] = {
                "song_name": song_name,
                "evidence_count": len(view),
                "speaker_count": len(speakers),
                "speakers": speakers,
                "evidence": sorted(view, key=lambda ev: (ev.get("date") or "", ev.get("url") or "")),
                "prediction": prediction_probability(view, year, params=params),
            }

    rows = []
    for occurrence in occurrences.values():
        occurrence["observations"] = build_observations(occurrence)
        occurrence["songs"] = sorted(
            occurrence["songs"].values(),
            key=lambda row: (-row["prediction"]["probability"], row["song_name"]),
        )
        rows.append(occurrence)
    rows.sort(key=lambda row: (row["year"], row["venue"], row["event_name"]))
    return {
        "generated_by": "build_song_occurrences.py",
        "generated_at": generated_at,
        "target_year": target_year,
        "prediction_params": {
            "decay_rate": params["decay_rate"],
            "prior_probability": params["prior_probability"],
            "combination": params["combination"],
        },
        "occurrence_count": len(rows),
        "song_relation_count": sum(len(row["songs"]) for row in rows),
        "occurrences": rows,
    }


def public_rows(occurrence_data):
    rows = []
    for occurrence in occurrence_data.get("occurrences", []):
        rows.append({
            "occurrence_id": occurrence["occurrence_id"],
            "event_name": occurrence["event_name"],
            "venue": occurrence["venue"],
            "year": occurrence["year"],
            "songs": [
                {
                    "name": song["song_name"],
                    "probability": song["prediction"]["probability"],
                    "basis": song["prediction"]["basis"],
                    "basis_label": song["prediction"]["basis_label"],
                    "evidence_count": song["evidence_count"],
                    "speaker_count": song["speaker_count"],
                    "setlist_complete": any(ev.get("setlist_complete") for ev in song["evidence"]),
                    "prediction_reliability": [
                        ev.get("reliability") for ev in song["evidence"] if ev.get("role") == "prediction"
                    ],
                    "evidence_urls": [ev.get("url") for ev in song["evidence"] if ev.get("url")][:5],
                }
                for song in occurrence.get("songs", [])
            ],
        })
    return rows


def prediction_snapshot(occurrence_data):
    generated_at = occurrence_data.get("generated_at")
    target_year = occurrence_data.get("target_year")
    snapshots = []
    for occurrence in occurrence_data.get("occurrences", []):
        for song in occurrence.get("songs", []):
            snapshots.append({
                "snapshot_id": hashlib.sha256(
                    f"{occurrence['occurrence_id']}\0{song['song_name']}\0{generated_at}".encode("utf-8")
                ).hexdigest()[:20],
                "predicted_at": generated_at,
                "target_year": target_year,
                "occurrence_id": occurrence["occurrence_id"],
                "event_name": occurrence["event_name"],
                "venue": occurrence["venue"],
                "song_name": song["song_name"],
                "probability": song["prediction"]["probability"],
                "basis": song["prediction"]["basis"],
                "basis_label": song["prediction"]["basis_label"],
                "evidence_count": song["evidence_count"],
                "speaker_count": song["speaker_count"],
                "prediction_reliability": [
                    ev.get("reliability") for ev in song["evidence"] if ev.get("role") == "prediction"
                ],
            })
    return {
        "generated_by": "build_song_occurrences.py",
        "generated_at": generated_at,
        "target_year": target_year,
        "snapshot_count": len(snapshots),
        "snapshots": snapshots,
    }
