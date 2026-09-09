# R2・曲目年越し修正の本番反映

2026-09-09 / おと（Codex）

内田さんの「本番反映まで進めて」を受け、PR #265と#264をmergeし、正本の再取得、
公開投影の再生成、site同期、S3/CloudFrontへのデプロイ、本番照合を完了した。

## 反映したもの

- PR #265（曲目年越し）merge: `8424f0751feec050251ec77038edbd74d2842a38`
- PR #264（R2）merge: `30a743fe7032688a3195fec25249ba96ad0d8e1f`
- collector公開データ: `1fda725ee1509b06176682771eeb3dd15e010997`
- site同期後・デプロイ対象: `0f4e650fbe1fa917bb87f41237711b9b84bf3b5a`

公開件数は387件。13過去カードの155曲で確率・根拠表示を補正した。
曲名・順序・曲数、その他の開催項目、内部source mapは維持した。正本DBへの書き込みは行っていない。

## 検査

- [正本取得run 34340430748](https://github.com/uryoutamomo/bon-odori-collector/actions/runs/34340430748)
  のDB・manifest・7補助入力を復号後に照合。DB checksum、SQLite integrity/FK、入力不変を確認した。
- 修正済み・R2前のcapture commit `e901348` とR2を追加patchなしで比較。
  `original_parity` で9ケース×4出力、計36比較がbyte一致。比較したPython 630ファイルはmerge後と一致した。
- 統合テスト1,900件、公開データ関連81件、site 44件が成功。既存のmutation検証に加え、独立レビューで
  公開候補の全13カード・155曲と、曲目以外に差分が無いことを確認した。
- 生JSON同期ガード・公開ガード・snapshot build・hygiene scan・SEO auditはpass。
  白金台どんぐり児童遊園とにっぽり炭坑節まつりの2件は、旧exact承認hashとの不一致が曲目だけに限定される
  ことを確認。既存のsongs-only規則による警告を保持し、承認台帳を書き換えなかった。

## 実行と本番確認

1. [Sync public data 34341211180](https://github.com/uryoutamomo/bon-odori-site/actions/runs/34341211180)
   を `deploy_after_sync=false` で実行。同期後のJSONはcollectorの検証済み生成物とbyte一致した。
2. 同期後site mainから
   [Deploy static site 34341419526](https://github.com/uryoutamomo/bon-odori-site/actions/runs/34341419526)
   を実行。テスト・両ガード・build/scan/SEO・S3同期・CloudFront invalidationが成功した。
   完了は2026-09-09 19:41 JST。
3. 通常の公開URLから取得した `data/events_public.json`、`index.html`、`app.js` が、
   同じsite commitから再構築したsnapshotとbyte一致した。
4. ブラウザで387件表示、検索、白金台どんぐり児童遊園の詳細を確認。
   「2025年実績・今年未確認」と11曲の「五分五分」を確認し、console warning/errorは0件だった。

公開JSONのbyte SHA-256:
`5b2848a5ae1a75c4054dc4f26be959375446206bd6f8a2b4a262ddf7011831d0`

公開JSONのcanonical SHA-256:
`2bbc4a12399543cc146e034b869c7767e827261f6cbdf7dd7f8cd7bd1d46c2f2`

site builderは従来どおり公開用の整形・field処理を行うため、collector生JSONとのbyte一致は要求しない。
公開前後のsnapshot比較では、変更は同じ13カードの曲目だけ。曲目の確率・basis・basis_label・confidenceは
collector候補と一致し、他イベント項目と曲名は本番反映前から不変だった。

ローカル証跡は `bonsuke-r2-release-20260909/`。取得bundle、比較・生成・guardのJSON、
テストログ、本番照合結果、画面確認、反映前の公開データを保持した。
日付境界のfixture検証は保存済みDBの投影比較であり、2027年の日次運用を実行したという意味ではない。
