import json
import os
import tempfile

import collect
from collection_support.voices_s3_artifact import require_writable_local_voices


VOICES_FILE = "data/voices.json"


def _atomic_write_json(path, data):
    directory = os.path.dirname(path) or "."
    fd, tmp_path = tempfile.mkstemp(prefix=".tmp-", suffix=".json", dir=directory)
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as f:
            json.dump(data, f, ensure_ascii=False, indent=2)
            f.write("\n")
        os.replace(tmp_path, path)
    except Exception:
        try:
            os.unlink(tmp_path)
        except OSError:
            pass
        raise


def _load_voices(path=VOICES_FILE):
    if not os.path.exists(path):
        return []
    with open(path, "r", encoding="utf-8") as f:
        data = json.load(f)
    return data if isinstance(data, list) else []


def refresh_youtube_voices(path=VOICES_FILE):
    existing = _load_voices(path)
    fresh, _ = collect.collect_voices(set())
    fresh_youtube = [v for v in fresh if v.get("source") == "youtube" and v.get("url")]
    fresh_by_url = {v["url"]: v for v in fresh_youtube}

    updated = []
    updated_count = 0
    for voice in existing:
        url = voice.get("url")
        if url in fresh_by_url:
            updated.append(fresh_by_url[url])
            updated_count += 1
        else:
            updated.append(voice)

    existing_urls = {v.get("url") for v in existing if v.get("url")}
    added = [v for v in fresh_youtube if v.get("url") not in existing_urls]
    if added:
        updated = added + updated

    if updated_count or added:
        require_writable_local_voices(path)
        _atomic_write_json(path, updated)

    return {
        "fetched_youtube": len(fresh_youtube),
        "updated_existing": updated_count,
        "added_new": len(added),
        "total": len(updated),
    }


def main():
    try:
        result = refresh_youtube_voices()
    except Exception as exc:
        print(f"[youtube-refresh] エラー: {exc}")
        return 1
    print(
        "[youtube-refresh] 完了: "
        f"取得 {result['fetched_youtube']} / "
        f"既存更新 {result['updated_existing']} / "
        f"新規追加 {result['added_new']} / "
        f"累計 {result['total']}"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
