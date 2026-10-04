# 競合閉店MAP（日本全国）

FamilyMart 系・LAWSON 系・セブン-イレブンの店舗位置を OpenPOI から定期取得し、47都道府県ごとに前回との差を調べます。地図と一覧は全国または都道府県別に絞り込めます。競合店が消えた時点では `MISSING`、連続して消えた場合に `CLOSED_SUSPECTED` とします。**掲載元から消えたことは閉店の証明ではありません。** `CLOSED_CONFIRMED` は根拠を登録した場合だけです。

公開先: https://competitor-closure-map.onrender.com/

## データの読み方

- OpenPOI の掲載範囲は全実店舗を網羅しません。画面の店舗数は収集できた POI 件数です。
- 初回の全国 snapshot は比較の基準を作るだけなので、実データの閉店イベントは0件です。次回以降の完全な取得と比較して初めて消失候補ができます。
- 画面の期間は**既に検知したイベントの絞り込み**です。過去の日付を入れても、過去の店舗一覧を遡って取得しません。
- 毎回同じ全国 bbox とブランド語で検索します。API 上限200件に達した範囲は再帰的に4分割し、取り切れなければ取り込み全体を失敗させます。前回に比べ1ブランド・1都道府県で収集件数が5%超（小件数では最低1件の変動を許容）減った場合も、ソース障害を疑い全体を失敗させ、閉店候補に反映しません。
- 同じ店舗を指す複数ソースの POI は店名と30m以内の位置でまとめ、元のレコード・ライセンス・出典を観測履歴に保持します。同一店舗照合も保守的な推定であり、誤判定の可能性は残ります。
- 地図の距離は閉店・消失店舗と最寄りのセブン-イレブンとの直線距離です。DBでは PostGIS geography で計算します。県境をまたいだ最寄りも対象です。

## 構成

- `collector/`: OpenPOI / CSV / fixture の収集、正規化、都道府県別差分、根拠・状態管理。
- `supabase/migrations/`: PostgreSQL 18 + PostGIS のテーブル、RLS、距離計算関数。Supabase 以外の PostGIS 対応DBでも実行できます。
- `apps/web/`: Next.js + MapLibre の読み取り専用APIと地図。ブランド複数選択、都道府県、状態、距離、期間、市区町村で絞り込みます。
- `.github/workflows/snapshot.yml`: 毎週月曜12:00 JSTの全国 snapshot。手動実行も可能です。
- `fixtures/`: 動作確認用の**架空**データ。公開版で `DATA_MODE=database` のときは使用しません。

## ローカルのデモ

```bash
npm ci
python3 -m collector build-fixture
npm run dev
```

`http://localhost:3000` を開きます。DBなしでは架空の神奈川県の店舗が1件表示されます。デモ表示は画面上にも明示します。

## 実データ運用

PostGIS 対応 PostgreSQL を準備し、サーバー専用 `DATABASE_URL` を設定します。DBパスワードを `NEXT_PUBLIC_` 付き変数やGit管理ファイルに置かないでください。

```bash
python3 -m pip install -r requirements.txt
python3 -m collector migrate
python3 -m collector snapshot --source openpoi --prefecture 全国 --snapshot-key openpoi-2026-W40
```

`--snapshot-key` は冪等性キーです。同じキーの再実行は既存 snapshot を返します。都道府県名を指定するとその県だけ取り込みますが、OpenPOI の検索は日本全国のデータを一度取得してキャッシュし、その県を抽出します。毎週の完全比較には `全国` を指定してください。CSV と fixture の既定県は神奈川県です。

OpenPOI の取得結果は、成功したブランドごとに `data/openpoi-cache/` へ同じ snapshot key で一時保存します。DB保存に失敗して再実行する場合、取得済みブランドは再ダウンロードしません。キャッシュは Git 管理対象外で、保存済み snapshot があれば DB 側の冪等性チェックを優先します。元データを取り直すときは `OPENPOI_REFRESH_CACHE=1` を指定します。ネットワーク取得中は DB の書き込みロックを保持しません。

公開Webに必要な変数は `DATA_MODE=database`、`NEXT_PUBLIC_DATA_MODE=database`、`DATABASE_URL` です。Render Blueprint は既存の `competitor-closure-map-db` から内部接続URLを参照します。GitHub Actions には同じDBの外部接続URLをリポジトリ Secret `DATABASE_URL` として登録します。ワークフローは `PGSSLMODE=require` で接続します。

**Render Free Postgres は2026年11月3日に期限を迎え、バックアップもありません。継続運用には期限前に永続DBへ移行してください。** 無料枠では長期保存を保証できません。移行時は `pg_dump` / `pg_restore` で履歴ごと移し、RenderとGitHubの接続先を更新します。

## 閉店確認とAPI

公開側は読み取り専用です。根拠登録と手動の分類はサーバー側CLIから行います。

```bash
python3 -m collector add-evidence --event-id <UUID> --type official --title '公式案内' --summary '確認内容' --source-ref 'https://...' --supports-closure --confirm --closure-date 2026-10-04
python3 -m collector set-status --event-id <UUID> --status DATA_ISSUE --reason '掲載元の欠落を確認'
```

`GET /api/closures` は `prefecture=東京都`、`brands=FAMILY_MART,LAWSON`、`status=CLOSED_BOTH`、`distance=500` などを受け付けます。`GET /api/closures/:id` は詳細と根拠、`GET /api/stores/:id/history` は観測履歴、`GET /api/health?prefecture=東京都` はDB状態・最終取得・都道府県別のブランド別店舗数を返します。最大100件/ページです。

## 検証

```bash
python3 -m unittest discover -s tests -v
npm run test:filters
npm run typecheck
npm run build
npm run test:ui
```

PostGIS の実DBテストは `DATABASE_URL` が設定されたときに実行されます。OpenPOI取得に失敗した場合はその回のデータを比較・保存しません。失敗した実行は `snapshot_runs` に記録します。

## 出典と制約

OpenPOI の `licenses`、`attributions`、raw payload、取得時刻を観測記録に保存します。[THIRD_PARTY_NOTICES.md](THIRD_PARTY_NOTICES.md) も参照してください。地図は OpenFreeMap / OpenStreetMap contributors、ブランドロゴは各権利者に帰属します。OpenPOI の Overture 元データ更新時期は JFF と異なり、掲載差分が実店舗の開閉店を直接示すものではありません。
