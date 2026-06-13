# キーボード判定UI メモ

## 目的

JSON候補リストを、ブラウザ上で高速に人手判定するためのローカルHTMLを生成する。
今回の用語集v2レビューで使った操作感を、他の候補レビューにも流用できるようにした。

## 追加したもの

- `build_keyboard_review_ui.py`
  - 任意のJSON配列から、キーボード操作中心のレビューHTMLを生成する汎用ビルダー。
  - `--rows-key` でJSON内の配列位置を指定できる。
  - `--term-field`、`--category-field`、`--summary-fields`、`--detail-fields` で表示項目を指定できる。
  - `--decisions` と `--exclude-decided` で、既存判定済み行を除外できる。

## 操作

- `j` / `k`: 次・前へ移動
- `1`: 採用
- `2`: 不採用
- `3`: まとめ
- `4`: 保留
- `n`: メモ欄へ移動
- `Esc`: メモ欄から戻る
- `u`: 未判定だけ表示
- `a`: 全部表示
- `e`: JSONを書き出し

## 用語集v2での実行例

```bash
python3 build_keyboard_review_ui.py \
  --input data/glossary_v2_oto123_merged_terms.json \
  --rows-key candidates \
  --out data/glossary_v2_oto123_keyboard_review_ui.html \
  --title 用語集v2キーボード判定UI \
  --term-field term \
  --category-field category \
  --summary-fields interpretation,type,confidence,source_agent \
  --detail-fields reason,evidence_text,evidence_url \
  --key-fields term,category,type,evidence_url \
  --download-name glossary_v2_oto123_keyboard_review_decisions.json \
  --storage-key glossary-v2-oto123-keyboard-review-v1
```

## 判定済みを除外する例

```bash
python3 build_keyboard_review_ui.py \
  --input data/glossary_v2_oto123_merged_terms.json \
  --rows-key candidates \
  --out data/glossary_v2_oto123_unreviewed_review_ui.html \
  --decisions /Users/ryotauchida/Downloads/glossary_v2_oto123_review_decisions.json \
  --exclude-decided
```

## 運用メモ

- 判定結果はブラウザのlocalStorageに保持される。
- 書き出しボタンまたは `e` キーでJSONをダウンロードする。
- 別案件で使う場合は `--storage-key` を案件ごとに変える。変えないと同じブラウザ内で判定状態が混ざる。

署名: おと（Codex）
