# 公式根拠による2開催回の更新

レビュー: おと（Codex）、2026-10-08。内田さんの「更新してください。本番にもアップして」に基づく対象2件の更新・通常同期・本番反映。

- `event-76633c9ca1` / `occ_f31959e29f133806`: 盆踊りは2026-10-10〜11、両日15:15開始、終了時刻未確認。都立芝公園エリア芸能ステージG。10/12のスポーツ・体育祭は含めない。代表公式URLは https://www.kissport.or.jp/matsuri/2026/ 。指定された https://www.kissport.or.jp/matsuri/news/7274/ は再確認時404。公式時間表 https://admin.kissport.or.jp/matsuri-2021/wp-content/uploads/2026/09/act_Kissport2026_maturi_sainyukou_03-1024x1022.png を取得・目視照合した。
- `event-d47b9ee7b4` / `occ_2eb9d3179e731fbe`: https://shitamachi-bonodori.com/ の主催公式案内は2026-10-09〜12、上野恩賜公園竹の台広場（噴水前広場）。催事全体11:00〜21:00、最終20:00。踊り個別時刻は未確認。既存2026開催回、イベント名と共有会場IDを保持し、2025年非公式URLを当年公式URLへ置換する。

`inbox_9c8ac72573e36fed` は非公式Xの新規候補で `matched_occurrence: null`、`inbox_ba21df29b8512e94` は上記既存開催回の日付欠落によるpublication_gap。双方を確認したうえで公式根拠の既存開催更新を選んだ。再収集・新規開催作成・inbox承認は実施しない。全inbox行の原観測・pendingを保持する。

既存 `apply_change_requests.py` でdry-run、監査issues 0、verifier errors 0。全DB表比較ではevent_occurrencesの対象2行、occurrence_dates、根拠2行とリンク2行だけが変化。開催回総数不変、全inbox行不変。公開394開催回の差分は同じ2開催回だけ。`public_official_source_links.json` に開催ID・年・日付・URLが一致するレビュー2件、`public_sync_exact_approvals.json` に前後全フィールドhashを固定した対象2件だけの通常承認を追加。みなとの公式開始時刻は既存time_evidence形式で保持する。
