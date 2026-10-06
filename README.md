# 競合閉店MAP（日本全国）

FamilyMart 系・LAWSON 系・セブン-イレブンの店舗位置を OpenPOI から定期取得し、47都道府県ごとに前回との差を調べます。地図と一覧は全国または都道府県別に絞り込めます。競合店が消えた時点では `MISSING`、連続して消えた場合に `CLOSED_SUSPECTED` とします。**掲載元から消えたことは閉店の証明ではありません。** `CLOSED_CONFIRMED` は根拠を登録した場合だけです。

公開先: https://competitor-closure-map.onrender.com/

現在のアプリ版: **v0.4.5**。画面左上に版数を表示し、`GET /api/version` で版数とデプロイコミットを確認できます。機能を変更する際は package/lock の版数、画面表示、README を合わせて更新します。

公開版は **収録店舗マップ** を初期表示します。地図の表示範囲では件数マーカーにまとめ、拡大すると個別のブランドロゴで表示します。右側の実店舗一覧はブランド・都道府県・市区町村・店名/住所で検索できます。**閉店・消失シグナル** に切り替えると、時系列差分から検知したイベントだけを表示します。収録店舗は営業中と確認済みという意味ではありません。
収録店舗マップでは **観測期間 開始・終了** を指定できます。期間を指定しないと現在収録されている店舗、指定すると期間中に一度でもOpenPOIで観測された店舗を一覧と地図に表示します。期間内に複数回観測した場合、店名・住所・位置には期間内の最新記録を使います。両端の日付を含み、日付は日本時間です。現在は収録されていない店舗も過去の観測期間には表示されます。記録がない期間の店舗や、その日に実際に営業していたかどうかは判定できません。
都道府県を選ぶと、県名と座標が矛盾する少数のPOIに画面が引きずられないよう、収録店の座標分布の1〜99パーセンタイルへ地図を寄せます。外れ値をDBから削除する処理ではありません。

店舗詳細の「Googleマップで店舗を照合」は[Google Maps URLs](https://developers.google.com/maps/documentation/urls/get-started)で別画面の検索を開きます。APIキーは不要で、Googleの検索結果はアプリに取り込みません。[Places APIの検索](https://developers.google.com/maps/documentation/places/web-service/nearby-search)は1リクエスト最大20件で、[利用条件](https://cloud.google.com/maps-platform/terms/maps-service-terms)はPlacesデータをOpenFreeMapのような他社地図と組み合わせて表示することや、店舗マスタとして長期保存することを制限します。そのためGoogle Placesを全国の永続的な店舗マスタ・閉店履歴の代替として使っていません。Google Maps上の表示と、このアプリのOpenPOI収録数は一致しません。

## データの読み方

- OpenPOI の掲載範囲は全実店舗を網羅しません。画面の店舗数は収集できた POI 件数です。
- LAWSON系は、OpenPOIのOverture由来でカテゴリが `convenience_store` のPOIだけを店舗候補として数え、店名表記からローソン、ローソンストア100、ナチュラルローソン、ローソン・スリーエフ、LAWSON+toksに分けます。ATM、ロッカー、食品営業許可・届出由来の候補などは店舗数から除外します。
- 画面にはLAWSON候補数とローソングループ公式総数を同時に表示します。公式総数にはナチュラルローソン、ローソンストア100などが含まれます。候補数が公式総数に近いことは数の規模の照合であり、1店ずつ公式名簿と一致することや営業中であることを証明しません。元データの制約と判定根拠は[ローソン件数調査](docs/lawson-count-audit-2026-10-07.md)を参照してください。特に、最寄りセブンは収録された店舗内だけの暫定値です。
- 初回の全国 snapshot は比較の基準を作るだけなので、実データの閉店イベントは0件です。2026年10月4日より前の全国店舗の観測履歴は保存されていません。たとえば2024年から2年間を選んでも、過去2年間の閉店を遡及検索できません。0件は閉店がなかった証拠ではありません。閉店・消失シグナル画面と `GET /api/health` に観測開始日と観測日数を表示します。
- 閉店・消失シグナルの期間は**既に検知したイベントの絞り込み**です。収録店舗マップの観測期間は**保存済みの観測履歴からの検索**です。どちらも取得前の過去データを新たに復元するものではありません。
- 毎回同じ全国 bbox とブランド語で検索します。API 上限200件に達した範囲は再帰的に4分割し、取り切れなければ取り込み全体を失敗させます。前回に比べ1ブランド・1都道府県で収集件数が5%超（小件数では最低1件の変動を許容）減った場合も、ソース障害を疑い全体を失敗させ、閉店候補に反映しません。
- 同じ店舗を指す複数ソースの POI は店名と30m以内の位置でまとめ、元のレコード・ライセンス・出典を観測履歴に保持します。同一店舗照合も保守的な推定であり、誤判定の可能性は残ります。
- 地図の距離は閉店・消失店舗と最寄りのセブン-イレブンとの直線距離です。DBでは PostGIS geography で計算します。県境をまたいだ最寄りも対象です。

## 構成

- `collector/`: OpenPOI / CSV / fixture の収集、正規化、都道府県別差分、根拠・状態管理。
- PostgreSQL運用からGoogle Sheets運用へ切り替える移行コマンドを備えます。Sheetsでは「Stores」に1店舗1行の現在台帳、「Changes」に初回登録・店舗情報変更・消失/再登場だけを記録し、イベント・根拠・取得履歴も別タブで保持します。毎週の同一店舗を重複行として追加しません。
- `supabase/migrations/`: PostgreSQL 18 + PostGIS のテーブル、RLS、距離計算関数。Supabase 以外の PostGIS 対応DBでも実行できます。
- `apps/web/`: Next.js + MapLibre の読み取り専用APIと地図。ブランド複数選択、都道府県、状態、距離、期間、市区町村で絞り込みます。Sheetsの店舗台帳は必要な列だけを15,000行単位で読み、API応答を処理後に破棄します。ヘルスチェックは取得履歴から件数を集計し、68,000件の店舗行を読み込みません。
- `.github/workflows/snapshot.yml`: 毎週月曜12:00 JSTの全国 snapshot。手動実行も可能です。
- `fixtures/`: 動作確認用の**架空**データ。公開版で `DATA_MODE=database` のときは使用しません。

## ローカルのデモ

```bash
npm ci
python3 -m collector build-fixture
npm run dev
```

`http://localhost:3000` を開きます。DBなしでは架空の神奈川県の店舗が1件表示されます。デモ表示は画面上にも明示します。

## 本番データ運用

公開Webと週次収集は Google Sheets を共有台帳として使用します。Render は `DATA_MODE=sheets` で読み取り、GitHub Actions は `STORAGE_MODE=sheets` で同じシートを更新します。2026年10月6日の取得までは広い名称検索によるデータで、LAWSONの26,942件にはATM・ロッカー等が混在していました。v0.4.5では店舗候補の条件を変更し、次の全国取得で旧候補を閉店扱いせず対象外へ移します。移行時の23,795店・94件と、それまでの取得履歴は監査できるよう残します。

店舗台帳のほか、`Changes`（初回登録・変更・消失/再登場のみ）、`ClosureEvents`（閉店シグナル）、`Evidence`（根拠）、`SnapshotRuns`（都道府県別取得履歴）を保存します。Webアプリは読み取りスコープ、GitHub Actionsは更新スコープで同じ専用サービスアカウントを使います。スプレッドシートはサービスアカウントにのみ共有し、「リンクを知っている全員」には公開しません。

全国取得は毎週月曜12:00（日本時間）に実行します。手動実行も GitHub の Actions から行えます。スプレッドシートが本番データの保存先なので、旧 Render Free Postgres が2026年11月3日に期限を迎えても、Sheets 接続設定が有効であればアプリのデータは影響を受けません。PostgreSQL は切替前のコピーで、以後の取得では更新されません。

表示件数は OpenPOI が返した店舗候補で、チェーン各社が公表する営業中店舗数や個々の店舗一致を保証しません。POIデータには誤分類・欠落・重複の可能性があり、閉店・消失も公式な閉店確定を意味しません。0件は閉店がなかった証拠ではありません。

## 閉店確認とAPI

公開側は読み取り専用です。根拠登録と手動の分類はサーバー側CLIから行います。

```bash
python3 -m collector add-evidence --event-id <UUID> --type official --title '公式案内' --summary '確認内容' --source-ref 'https://...' --supports-closure --confirm --closure-date 2026-10-04
python3 -m collector set-status --event-id <UUID> --status DATA_ISSUE --reason '掲載元の欠落を確認'
```

`GET /api/closures` は `prefecture=東京都`、`brands=FAMILY_MART,LAWSON`、`status=CLOSED_BOTH`、`distance=500` などを受け付けます。`GET /api/closures/:id` は詳細と根拠、`GET /api/stores/:id/history` は観測履歴、`GET /api/health?prefecture=東京都` はSheets接続状態・最終取得・都道府県別のブランド別店舗数を返します。最大100件/ページです。
`GET /api/stores`、`GET /api/stores/map`、`GET /api/stores/:id` は `from=2026-10-04&to=2026-10-04` を受け付けます。片端だけの指定も可能です。開始日が終了日より後、または無効な日付の場合は400を返します。地図APIは期間条件とブランド・地域・店名条件を一覧と同じように適用します。

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
