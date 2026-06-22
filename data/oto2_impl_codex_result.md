おとです。Master RDB のローカル再ビルドと検証まで完了しました。deploy / push / Notion 同期 / 公開 JSON の wholesale deploy はしていません。作業前後の `git status --short` も確認済みです。

結果は [data/oto_impl_handoff.md](/Users/ryotauchida/bon-odori-collector/data/oto_impl_handoff.md) に残しました。

要点:
- `python3 build_master_rdb.py` から post-build 生成まで実行
- `python3 audit_master_rdb.py`: `issues=0`
- `source_snapshot_drift` / `source_count_drift` は解消
- readiness: collector/site とも 182 件、common diffs 0
- public sync guard: pass
- `PYTHONPATH=. pytest`: 338 passed

注意点として、素の `pytest` は import path の問題で collection error になりました。repo root を入れた `PYTHONPATH=. pytest` では全件通っています。