# 競合閉店MAP（神奈川県 MVP）

FamilyMart 系・LAWSON 系の店舗スナップショットを時系列で比較し、前回は存在して最新では消えた店舗を検知するアプリです。**消失は閉店確定を意味しません。** 根拠を確認したイベントだけを `CLOSED_CONFIRMED` にします。確認済み閉店と最寄りのセブン-イレブンの直線距離を地図と一覧に表示します。既定条件は **100m 以内**です。

fixture の店舗、住所、閉店根拠はすべて架空のデモデータです。実際の閉店情報として利用しないでください。

Render に公開する場合は `render.yaml` の無料 Web Service 設定を使用します。DB のない公開版は `fixtures/demo_state.json` の架空データで起動します。

## アーキテクチャ

- `collector/`: Python 3.9+。Fixture / CSV / OpenPOI アダプター、正規化、同一店舗照合、差分・状態遷移。実データの書き込みは PostgreSQL の単一トランザクションです。
- `supabase/migrations/`: PostgreSQL + PostGIS のテーブル、RLS、距離計算関数。geography Point と GiST index を使用します。
- `apps/web/`: Next.js App Router + TypeScript + MapLibre GL JS。読み取り専用 API と地図 UI。fixture モードなら DB は不要です。
- `fixtures/`: 再現可能な2時点データと、架空の手動確認根拠。

状態は `PRESENT`、`MISSING`、`CLOSED_SUSPECTED`、`CLOSED_CONFIRMED`、`REOPENED` 等に分離しています。1回目の欠落は既定で `MISSING`、2回目で `CLOSED_SUSPECTED` です。`MISSING_THRESHOLD=1` に変更できます。実データでの `CLOSED_CONFIRMED` は手動根拠によってのみ設定します。

## DB なしで起動

必要環境: Node.js 20.9+、npm、Python 3.9+。地図タイルの表示にはインターネット接続が必要です。タイル取得に失敗しても一覧と詳細は使用できます。

```bash
npm ci
python3 -m collector build-fixture
npm run dev
```

`http://localhost:3000` を開きます。fixture は `data/fixture-state.json` に生成されます。このファイルは Git の管理対象外です。`GET /api/health` はモードと最新の成功 snapshot を返します。
ローカル生成ファイルがない場合は、Git 管理の `fixtures/demo_state.json` を読みます。

デモでは Snapshot 001 に Seven A、45m 先の Lawson X、108m 先の FamilyMart Y が存在します。Snapshot 002 では Lawson X が消え、まず `MISSING` になります。その後、**架空の** evidence fixture を登録して `CLOSED_CONFIRMED` にした状態が UI に出ます。

## Supabase / PostgreSQL + PostGIS

Supabase の新規プロジェクトまたは PostGIS を使える PostgreSQL を用意します。会社のデータ・認証情報は使用しません。

1. Supabase SQL Editor で `supabase/migrations/202610040001_initial.sql` を実行します。冒頭の `create extension if not exists postgis;` が PostGIS を有効化します。権限が足りない環境では管理者が extension を有効化してください。
2. migration にブランド別名の初期値が含まれます。別環境で別名だけ再投入する場合は、冪等な `supabase/seed.sql` を実行できます。
3. サーバー専用の `DATABASE_URL` を設定します。DB パスワードや service role key を `NEXT_PUBLIC_` 付き変数に入れないでください。
4. `python3 -m pip install -r requirements.txt` で collector の DB ドライバーを入れます。
5. 次のようにスナップショットを実行します。`--snapshot-key` は同じ取り込みの再実行時に同じ値を使用します。

```bash
export DATABASE_URL='postgresql://...'
python3 -m collector snapshot --source fixture --file fixtures/snapshot_001.json --snapshot-key fixture-001 --observed-at 2026-06-01T00:00:00Z
python3 -m collector snapshot --source fixture --file fixtures/snapshot_002.json --snapshot-key fixture-002 --observed-at 2026-06-15T00:00:00Z
```

Web から DB を読む場合は `cp .env.example apps/web/.env.local` の後、`DATA_MODE=database`、`DATABASE_URL=...`、`NEXT_PUBLIC_DATA_MODE=database` を設定して `npm run dev` します。DB 資格情報は Next.js の server route だけで使用します。ブラウザから DB テーブルへ直接接続せず、RLS を有効化して匿名ロールにテーブル権限を付けていません。

PostGIS の `ST_Distance` / geography が最寄り距離をメートルで算出し、100m 判定を保存します。fixture 単独モードでは再現性のため Python の球面距離で表示します。実 DB の境界判定は PostGIS が正です。

## OpenPOI 実データ取得

API 仕様は [OpenPOI 公式ドキュメント](https://docs.openpoiapi.com/) の `/v1/search` で確認しています。`q`、`bbox`、最大 `limit=200`、レスポンスの `results` / `licenses` / `attributions` を使用します。API キーは不要です。

```bash
python3 -m collector snapshot --source openpoi --snapshot-key openpoi-2026-10-04
```

神奈川県を覆う bbox から始め、200件に達した領域は4分割して再検索します。最大深度でも200件なら**失敗**させ、欠落したデータを完全な snapshot として保存しません。各ブランド語で検索し、都道府県・ブランド判定後に重複を除去します。OpenPOI には安定店舗 ID がないため、同一性はブランド、住所、30m 以内と店名類似度で保守的に判定します。OpenPOI の網羅性や更新頻度は元データに依存します。データソースから消えても閉店とは判断できません。

`CsvSource` は `name,address,lat,lng,prefecture,city,source_store_id` 列の UTF-8 CSV を受け取ります。`--source csv --file path.csv` で実行できます。

実データの閉店確認はサーバー側 CLI から根拠を追加します。公開書き込み API はありません。

```bash
python3 -m collector add-evidence --event-id <UUID> --type manual --title '現地確認' --summary '確認内容' --supports-closure --confirm --closure-date 2026-10-04
python3 -m collector set-status --event-id <UUID> --status RELOCATED --reason '移転を確認'
```

## API と画面

- `GET /api/closures`: 状態・ブランド・50/100/300m・市区町村・期間・ページで絞り込み。既定は確認済みかつ100m以内。最大100件/ページ。raw payload は返しません。
- `GET /api/closures/:id`: 詳細、閉店前の最終観測、根拠。
- `GET /api/stores/:id/history`: 店舗の観測履歴。
- `GET /api/map/events?bbox=minLng,minLat,maxLng,maxLat`: 表示領域のイベント。
- `GET /api/health`: DB 疎通と最新成功 snapshot。

地図のスタイルは `NEXT_PUBLIC_MAP_STYLE_URL` で変更できます。既定は OpenFreeMap の Liberty style です。地図上の×は競合のイベント、選択中の7は最寄り Seven、破線は両店間を示します。選択時に100m 円を描画します。距離は直線距離で、道路移動距離ではありません。

## テストとビルド

```bash
python3 -m unittest discover -s tests -v
npm run build
npm run test:ui
```

UI テストはインストール済みの Google Chrome を使用します。Chrome がない環境では Playwright の browser をインストールして `playwright.config.ts` の `channel` を調整してください。

## デプロイ

任意の Next.js 対応環境で `npm ci && npm run build`、起動に `npm run start` を指定します。fixture モードでは起動前に `python3 -m collector build-fixture` が必要です。永続運用は Supabase/PostgreSQL を設定し、collector を**別のサーバー側ジョブ**として手動実行してください。スケジューラや配信先は未確定です。

## Attribution / License

OpenPOI レコードの `licenses`、`attributions`、raw payload、取得時刻は観測情報として保持します。実データの再配布・表示時はレコードごとの出典を確認してください。[THIRD_PARTY_NOTICES.md](THIRD_PARTY_NOTICES.md) に Overture / Foursquare 等の参照先を記載しています。地図には OpenFreeMap / OpenStreetMap contributors の出典を表示します。

## Known limitations

- OpenPOI の位置ずれ、欠落、閉業施設の残存があり得ます。閉店の真偽を自動判断しません。
- 元レコードに都道府県も住所の都道府県表記もない場合、安全側で除外します。県境付近の網羅性が落ちる可能性があります。
- 独自 canonical matching は慎重な推定であり、同住所・似た名前の別店舗を必ず区別できるとは限りません。
- fixture モードの距離は PostGIS ではありません。実 DB への migration・PostGIS 実行は接続先が必要です。
- API は最大100件/ページです。地図の bbox API もページ指定で続きを取得します。

## Assumptions / Open Issues

- 定義書の `OpenPOI` は `https://api.openpoiapi.com` のサービスを指すものとして公式仕様を確認しました。
- 神奈川県を覆う bbox は近隣都県も含むため、返却された `prefecture` または住所で神奈川県に限定します。県境形状による厳密な行政界判定ではありません。
- デモの根拠は架空です。実運用の根拠登録はサーバー側 CLI から行い、一般公開の書き込み API は設けません。
- Supabase プロジェクトとデプロイ先が未指定のため、接続先固有の設定・本番公開は未実施です。
- Web の DB 接続は Supabase client library ではなく、サーバー専用 PostgreSQL 接続を使用します。匿名クライアントのテーブル権限を付与せず、PostGIS クエリと RLS を一か所で扱うためです。
