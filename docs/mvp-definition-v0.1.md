# 競合閉店MAP MVP 要件定義・実装定義書 v0.1

## 0. Codexへの最上位指示

この定義書に基づき、まず「神奈川県版MVP」を完成させること。

- 未確認のAPI仕様、DOM構造、公式店舗検索API、料金、利用規約を推測して実装しない。
- 外部データ取得に失敗しても、fixture（テスト用固定データ）でアプリ全体を起動・確認できる状態にする。
- 「店舗がデータソースから消えた」ことと「閉店が確定した」ことを厳密に分離する。
- MVPではBigQueryおよび会社データを一切利用しない。
- MVPの対象地域は神奈川県のみ。
- MVPの対象競合はFamilyMart系とLAWSON系。最寄り比較対象はSeven-Eleven。
- 距離条件の既定値は100m。100mを超える店舗は既定の閉店一覧には含めない。
- 実装の過程で仕様変更が必要になった場合、勝手に変更せず README の「Assumptions / Open Issues」に記録する。
- 最初から過剰なAI機能、認証、全国対応、売上分析を作らない。MVPの受入条件を優先する。

---

## 1. プロジェクト概要

### 1.1 仮称

**競合閉店MAP / Competitor Closure Map**

### 1.2 目的

FamilyMart・LAWSONの店舗マスタを時系列で保持し、前回取得時点には存在したが最新取得時点では存在しない店舗を自動検知する。

消失店舗について閉店・移転・改装・データ欠落などの状態を管理し、閉店が確認された店舗のうちSeven-Elevenから100m以内にある店舗を地図と一覧で可視化する。

### 1.3 このアプリが解く課題

従来の「閉店記事を検索する」方式では以下を取りこぼす。

- ニュースにならない小規模店舗の閉店
- 地域メディアに掲載されない閉店
- 閉店日が検索結果に出ない店舗
- 検索エンジンにインデックスされない店舗

本アプリは「閉店情報を探す」のではなく、**営業店舗マスタの時系列差分から消失を先に検知し、その後で閉店理由を確認する**方式とする。

---

## 2. MVPスコープ

### 2.1 対象地域

- 神奈川県

### 2.2 対象ブランド

#### 競合

FamilyMart family:
- ファミリーマート
- FamilyMart
- ファミマ!! 等、FamilyMart系列と合理的に判定できる店舗

LAWSON family:
- ローソン
- LAWSON
- ローソンストア100
- ナチュラルローソン
- LAWSON+toks
- ローソン・スリーエフ
- その他LAWSON系列と合理的に判定できる店舗

#### 比較対象

- セブン-イレブン / Seven-Eleven

ブランド判定はコードに直書きせず、設定ファイルまたはDBのbrand_aliasesで変更可能にする。

### 2.3 MVPで実装する機能

1. 神奈川県内の対象店舗を取得してスナップショット保存
2. 前回スナップショットとの差分検知
3. 消失店舗をclosure candidateとして登録
4. 閉店ステータス管理
5. Seven-Elevenとの直線距離計算
6. 100m以内判定
7. 地図表示
8. 閉店一覧表示
9. 店舗クリック時の詳細表示
10. 閉店前（最終確認時点）の店舗情報表示
11. フィルター
12. fixtureを利用した再現可能なテスト

### 2.4 MVPで実装しないもの

- BigQuery
- 社内売上データ
- 全国対応
- 売上影響分析
- AIによる自動閉店判定
- 自動Web検索による閉店根拠収集
- メール・Teams・Slack通知
- 開店検知
- 跡地テナント検知
- ユーザーアカウント
- 複雑な管理画面

DB設計上は将来拡張できるようにしてよいが、UI/処理は作り込まない。

---

## 3. 最重要の業務ロジック

### 3.1 基本フロー

```text
[Snapshot N]
FamilyMart / LAWSON / Seven-Eleven 現行店舗取得
        ↓
正規化・名寄せ
        ↓
店舗マスタ＋スナップショット保存
        ↓
[Snapshot N-1] と比較
        ↓
前回あり / 今回なし
        ↓
MISSING（消失候補）
        ↓
閉店理由を確認
  ├─ CLOSED_CONFIRMED
  ├─ CLOSED_SUSPECTED
  ├─ RELOCATED
  ├─ TEMPORARY_CLOSED
  ├─ RENAMED
  └─ DATA_ISSUE
        ↓
CLOSED_CONFIRMED または CLOSED_SUSPECTED
        ↓
最寄りSeven-Elevenとの距離計算
        ↓
100m以内
        ↓
競合閉店MAPに表示
```

### 3.2 「消失」と「閉店」を混同しない

以下を別ステータスにする。

- `PRESENT`: 最新スナップショットに存在
- `MISSING`: 前回存在したが最新には存在しない
- `CLOSED_SUSPECTED`: 閉店の可能性が高いが根拠不足
- `CLOSED_CONFIRMED`: 閉店が確認済み
- `RELOCATED`: 移転
- `TEMPORARY_CLOSED`: 改装等による一時休業
- `RENAMED`: 店名変更・ブランド表記変更
- `DATA_ISSUE`: データソース側欠落・誤登録等
- `REOPENED`: 一度消失後、再度検出

地図のデフォルト表示は `CLOSED_CONFIRMED`。
UIで `CLOSED_SUSPECTED` を追加表示できるようにする。
`MISSING` 単独では「閉店」と表示しない。

### 3.3 誤検知抑制

店舗同一性は以下の優先順位で照合する。

1. データソースが安定した店舗IDを提供する場合は店舗ID一致
2. ブランドファミリー一致 + 正規化住所一致
3. ブランドファミリー一致 + 距離30m以内 + 店名類似度が閾値以上
4. 上記に一致しない場合は別店舗として扱う

同一店舗と確信できない場合に自動マージしない。

### 3.4 連続欠落

1回の欠落のみでは原則 `MISSING`。

将来的には以下を設定可能にする。

- `missing_threshold = 2`（2回連続欠落で `CLOSED_SUSPECTED` に昇格）

ただしMVPではテスト容易性のため、ステータス昇格ルールは関数として分離し、設定値で1または2に変更できること。

---

## 4. データ取得方針

### 4.1 Data Source Adapter方式

データ取得処理を特定サイトに密結合させない。

Python側に次のインターフェースを設ける。

```python
class StoreSource:
    def fetch_stores(self, prefecture: str, brand_family: str) -> list[RawStore]:
        ...
```

MVPで最低限実装するadapter:

- `OpenPoiSource`
- `FixtureSource`
- `CsvSource`

将来追加予定:

- `FamilyMartOfficialSource`
- `LawsonOfficialSource`
- その他の正式に利用可能な店舗データソース

公式サイトを取得するadapterは、利用規約・技術仕様・アクセス方法を確認してから実装する。DOM/APIを推測して作らない。

### 4.2 OpenPOIの利用

MVPのbootstrapおよびPOI照合に利用する。

利用する主な機能:

- 施設検索
- bbox検索
- center + radius検索
- 最大200件/レスポンス
- APIキー不要

OpenPOIに安定した店舗IDがない場合は、独自のcanonical identityを生成する。

### 4.3 神奈川県全域取得時の200件制限対策

単一クエリで県内全店舗を取ったとみなさない。

**recursive bbox partitioning** を実装する。

アルゴリズム:

1. 神奈川県全体を覆うbboxから開始
2. ブランドキーワードごとに検索
3. 結果件数がlimit未満なら採用
4. 結果件数がlimitと同数の場合、打ち切りの可能性があるためbboxを4分割
5. 子bboxで再検索
6. 十分小さいbboxになるまで繰り返す
7. 全結果を正規化・重複排除

`limit == 200` を「全件取得できた」と解釈しない。

### 4.4 生データ保存

OpenPOI由来レコードは以下も必ず保存する。

- source
- licenses
- attributions
- raw payload
- fetched_at

表示画面にはOpenPOIの出典表記を設置する。

---

## 5. 距離判定

### 5.1 DB

Supabase PostgreSQL + PostGISを使用する。

位置情報は単なるlat/lngだけでなく、PostGIS geography Pointでも保持する。

推奨:

```sql
location geography(Point, 4326)
```

### 5.2 100m判定

アプリ側の単純な緯度経度差ではなくPostGISで計算する。

概念:

```sql
ST_DWithin(competitor.location, seven.location, 100)
ST_Distance(competitor.location, seven.location)
```

- 単位: meter
- 既定距離: 100m
- UIから50m / 100m / 300m等へ変更可能な設計にする

### 5.3 最寄りSeven-Eleven

閉店イベントごとに以下を取得する。

- nearest_seven_store_id
- distance_m
- within_100m boolean

100m以内に複数店舗ある場合は全件保持可能にするが、一覧では最寄り1店舗を代表表示する。

---

## 6. DB設計

PostgreSQL / Supabase。
UUIDを主キーにする。
時刻はDB内部ではUTC、UI表示はAsia/Tokyo。

### 6.1 `snapshot_runs`

| column | type | note |
|---|---|---|
| id | uuid PK | |
| source | text | openpoi / csv / fixture etc |
| prefecture | text | MVPは神奈川県 |
| started_at | timestamptz | |
| finished_at | timestamptz | nullable |
| status | text | running/succeeded/failed |
| store_count | integer | |
| error_message | text | nullable |
| metadata | jsonb | |

### 6.2 `stores`

canonical store master。

| column | type | note |
|---|---|---|
| id | uuid PK | |
| brand_family | text | FAMILY_MART / LAWSON / SEVEN_ELEVEN |
| canonical_name | text | |
| normalized_name | text | |
| address | text | |
| normalized_address | text | |
| prefecture | text | |
| city | text | |
| lat | double precision | |
| lng | double precision | |
| location | geography(Point,4326) | |
| first_seen_at | timestamptz | |
| last_seen_at | timestamptz | |
| current_presence | text | PRESENT/MISSING/etc |
| created_at | timestamptz | |
| updated_at | timestamptz | |

indexes:

- brand_family
- prefecture
- current_presence
- GIST(location)

### 6.3 `store_observations`

各スナップショットで観測した生情報。

| column | type | note |
|---|---|---|
| id | uuid PK | |
| snapshot_run_id | uuid FK | |
| store_id | uuid FK | |
| source | text | |
| source_store_id | text | nullable |
| observed_name | text | |
| observed_address | text | |
| lat | double precision | |
| lng | double precision | |
| source_category | text | nullable |
| source_business_type | text | nullable |
| licenses | jsonb | array |
| attributions | jsonb | array |
| raw_payload | jsonb | |
| observed_at | timestamptz | |

unique候補:

- `(snapshot_run_id, store_id, source)`

### 6.4 `closure_events`

| column | type | note |
|---|---|---|
| id | uuid PK | |
| store_id | uuid FK | 閉店・消失した競合 |
| detected_at | timestamptz | 最初に消失検知した日時 |
| last_seen_at | timestamptz | 閉店前に最後に存在を確認した日時 |
| status | text | MISSING/CLOSED_SUSPECTED/CLOSED_CONFIRMED/... |
| closure_date | date | nullable |
| reason | text | nullable |
| confidence | text | LOW/MEDIUM/HIGH |
| nearest_seven_store_id | uuid FK | nullable |
| distance_m | numeric | nullable |
| within_100m | boolean | |
| last_observation_id | uuid FK | 閉店前情報への参照 |
| created_at | timestamptz | |
| updated_at | timestamptz | |

1店舗に複数イベントが必要になった場合に備え、stores側へ閉店情報を直接埋め込まない。

### 6.5 `event_evidence`

MVPでは手動入力またはfixtureでよい。将来の自動調査に備える。

| column | type | note |
|---|---|---|
| id | uuid PK | |
| closure_event_id | uuid FK | |
| evidence_type | text | official/web/local_media/manual/source_diff |
| title | text | |
| source_ref | text | URL等。nullable |
| evidence_date | date | nullable |
| summary | text | |
| supports_closure | boolean | |
| created_at | timestamptz | |

### 6.6 `brand_aliases`

| column | type |
|---|---|
| id | uuid PK |
| brand_family | text |
| alias | text |
| enabled | boolean |

初期seedをmigrationに入れる。

---

## 7. Snapshot差分処理

### 7.1 snapshot実行

CLI例（名称は変更可）:

```bash
python -m collector snapshot --prefecture kanagawa --source openpoi
```

処理:

1. `snapshot_runs`をrunningで作成
2. FamilyMart取得
3. LAWSON取得
4. Seven-Eleven取得
5. 正規化
6. canonical storeとのmatching
7. `store_observations`保存
8. first_seen/last_seen更新
9. 前回snapshotと差分比較
10. 消失候補作成/更新
11. 再出現店舗はREOPENEDまたはPRESENTへ更新
12. nearest Seven計算
13. snapshot_runsをsucceededに更新

途中失敗時はtransactionまたは再実行安全性を担保する。

### 7.2 冪等性

同一snapshotを再実行してもclosure eventが重複生成されないこと。

### 7.3 last seen

閉店前情報として表示するのは、消失直前の `store_observations`。

これを削除・上書きしない。

---

## 8. WebアプリUI

### 8.1 技術

- Next.js（App Router）
- TypeScript
- MapLibre GL JS
- Supabase client/server libraries
- Tailwind CSS（または同等。依存を増やしすぎない）

### 8.2 画面構成

Desktop first。

```text
┌────────────────────────────────────────────────────────────┐
│ 競合閉店MAP  神奈川県    [期間] [ブランド] [距離] [状態] │
├──────────────────────────────────┬─────────────────────────┤
│                                  │ 閉店・候補一覧          │
│              MAP                 │                         │
│                                  │ [LAWSON] 古淵駅前店     │
│        ● Seven                   │ 2026/06/15              │
│        × Closed competitor       │ Sevenまで45m            │
│           ─45m─                  │ ─────────────────────  │
│                                  │ [FamilyMart] ○○店       │
│                                  │ Sevenまで72m            │
│                                  │                         │
└──────────────────────────────────┴─────────────────────────┘
```

目安:

- Map: 65〜70%
- List: 30〜35%
- 高さ: viewportいっぱい

### 8.3 地図

表示要素:

- 閉店競合マーカー
- 選択店舗に対応するSeven-Elevenマーカー
- 両店舗を結ぶ線
- 距離表示
- 100m radius circle（選択時のみ）

大量のSeven-Elevenを常時表示して地図を埋めない。

閉店競合のマーカーをクリックすると一覧側の該当店舗を選択する。
一覧をクリックすると地図をflyToし、該当マーカーを選択する。

### 8.4 一覧

表示:

- ブランド
- 店舗名
- 市区町村
- status
- 閉店日（確認できた場合）
- last seen
- 最寄りSeven-Eleven
- 距離m
- confidence

並び順の既定:

1. detected_at desc
2. distance_m asc

### 8.5 店舗詳細

一覧またはマーカークリックで詳細panel/drawerを表示。

#### header

- 店舗名
- ブランド
- status badge
- confidence

#### 閉店情報

- closure_date
- detected_at
- last_seen_at
- reason

#### 閉店前情報

`last_observation`から表示。

- 当時の店舗名
- 住所
- 緯度経度
- データソース
- 最終観測日
- source category/business type（存在する場合のみ）

OpenPOIに存在しない電話番号・営業時間等を推測して表示しない。

#### Seven-Eleven情報

- 店舗名
- 住所
- 距離
- 100m以内/外

#### 根拠

`event_evidence`を時系列で表示。

- source_diff
- official
- local_media
- manual
等

### 8.6 filter

MVP:

- ブランド: All / FamilyMart / LAWSON
- status: Confirmed / Suspected / Missing
- 距離: 50 / 100 / 300m
- 市区町村
- 期間: detected_atまたはclosure_date

filterとMap/Listは常に同期する。

### 8.7 空状態・エラー

必ず用意する。

- 条件に該当なし
- DB接続失敗
- Map style取得失敗
- データ取得処理失敗
- latest snapshotが存在しない

---

## 9. API / Server Layer

MVPでは独立したFastAPIサーバーは必須にしない。
Next.js server route / server action + Supabaseで構成し、collectorのみPythonとする。

推奨read API:

```text
GET /api/closures
GET /api/closures/:id
GET /api/stores/:id/history
GET /api/map/events?bbox=...&status=...&brand=...
GET /api/health
```

write APIは公開しない。

collectorはservice roleまたはDB接続情報をserver-sideのみで使用する。

---

## 10. セキュリティ

- Supabase service role keyをブラウザへ絶対に公開しない
- `.env`をGit commitしない
- `.env.example`のみcommit
- 公開Webは基本read-only
- 書き込みはcollector/serverのみ
- RLSを有効化する
- raw payloadに不要な個人情報を追加収集しない
- 会社の認証情報・会社DB・会社APIを利用しない

---

## 11. 地図

MapLibre GL JSを採用する。

Map style providerは環境変数で交換可能にする。

```text
NEXT_PUBLIC_MAP_STYLE_URL
```

開発時の既定候補としてOpenFreeMapのMapLibre対応styleを使用してよいが、providerをコードに強く依存させない。

地図providerとOpenPOI双方のattributionを適切に表示する。

---

## 12. OpenPOI利用時の必須事項

OpenPOIについて以下を前提にする。

- 認証不要
- 検索結果のDB保存が可能
- `licenses` / `attributions`を一緒に保存する
- POI位置ずれが存在し得る
- 閉業施設が残存する場合がある
- 網羅性は元データに依存する
- JFF由来とOverture由来で更新頻度が異なる

したがってOpenPOIのみを「閉店の真実」とみなさない。

UI footerまたはAboutにOpenPOI出典を表示。
Apache-2.0 / Foursquare由来データのNOTICE要件に備え、`THIRD_PARTY_NOTICES.md`を作成する。

---

## 13. リポジトリ構成

推奨:

```text
competitor-closure-map/
├─ apps/
│  └─ web/
│     ├─ app/
│     ├─ components/
│     ├─ lib/
│     └─ public/
├─ collector/
│  ├─ sources/
│  │  ├─ base.py
│  │  ├─ openpoi.py
│  │  ├─ fixture.py
│  │  └─ csv_source.py
│  ├─ normalization/
│  ├─ matching/
│  ├─ diff/
│  ├─ db/
│  └─ cli.py
├─ fixtures/
│  ├─ snapshot_001.json
│  └─ snapshot_002.json
├─ supabase/
│  ├─ migrations/
│  └─ seed.sql
├─ tests/
├─ docs/
│  └─ architecture.md
├─ .env.example
├─ README.md
├─ THIRD_PARTY_NOTICES.md
└─ docker-compose.yml   # 必要な場合のみ。必須ではない
```

Codespacesでの開発を想定し、必要なら`.devcontainer`を追加する。

---

## 14. Fixtureによる必須シナリオ

外部APIを待たず、Codexが最初にこれを通す。

### Snapshot 001

- Seven A: 神奈川県内、営業中
- Lawson X: Seven Aから45m、営業中
- FamilyMart Y: Seven Aから108m、営業中

### Snapshot 002

- Seven A: 存在
- Lawson X: 消失
- FamilyMart Y: 存在

期待値:

- Lawson X → `MISSING`
- Lawson X closure event作成
- Lawson X とSeven Aの距離 ≒45m
- `within_100m = true`
- FamilyMart Yにはclosure eventを作らない

次にevidence fixtureを追加:

- Lawson Xに閉店根拠を追加
- status → `CLOSED_CONFIRMED`
- closure_dateを設定

UI期待値:

- MapにLawson Xを表示
- 右一覧にLawson X表示
- クリックするとSeven Aとの線と距離表示
- 詳細にSnapshot 001時点のLawson X情報表示

別fixtureで108mの閉店店を作り、100m filterでは表示されないことを確認する。

---

## 15. テスト

最低限:

### Unit

- brand normalize
- name normalize
- address normalize
- canonical matching
- diff detection
- repeated missing
- reopened detection
- 100m boundary
- 99.9m → true
- 100.0m → true
- 100.1m → false

### Integration

- snapshot 1 → snapshot 2 → closure event生成
- 同一snapshot再実行で重複なし
- last observationが保持される
- nearest Sevenが正しく保存される

### UI

- filterでMap/Listが同期
- list clickでmap focus
- marker clickでlist選択
- detail drawerにlast observation表示

---

## 16. パフォーマンス

神奈川県MVPでは過剰最適化しない。

ただし以下は必須。

- PostGIS spatial index
- Mapはviewport/bbox単位で取得できるAPI
- 一覧はpaginationまたは上限設定
- raw payloadを一覧APIで毎回返さない

全国化時にそのままスケールできる構造を意識する。

---

## 17. ログ・監視

collector実行時に最低限記録:

- source
- start/end
- fetched count
- normalized count
- matched count
- new count
- missing count
- reopened count
- closure candidate count
- errors

Web側:

- `/api/health`
- DB疎通
- latest successful snapshot timestamp

---

## 18. READMEに必ず記載

1. プロジェクト目的
2. アーキテクチャ
3. 必要環境
4. Supabaseセットアップ
5. PostGIS有効化手順
6. migration実行
7. fixtureでの起動方法
8. OpenPOI実データ取得方法
9. snapshot差分実行方法
10. Web起動方法
11. デプロイ方法（確定している範囲のみ）
12. Attribution / License
13. Known limitations
14. Assumptions / Open Issues

---

## 19. 環境変数

例:

```text
NEXT_PUBLIC_SUPABASE_URL=
NEXT_PUBLIC_SUPABASE_ANON_KEY=
SUPABASE_SERVICE_ROLE_KEY=
DATABASE_URL=
NEXT_PUBLIC_MAP_STYLE_URL=
OPENPOI_BASE_URL=
APP_TIMEZONE=Asia/Tokyo
DEFAULT_PREFECTURE=神奈川県
DEFAULT_DISTANCE_METERS=100
MISSING_THRESHOLD=2
```

秘密情報はserver-only。

---

## 20. MVP受入条件（Definition of Done）

以下を全て満たしたらMVP完成。

### Data

- [ ] fixtureの2時点snapshotを取り込める
- [ ] 神奈川県のOpenPOI snapshotを実行できる
- [ ] FamilyMart / LAWSON / Seven-Elevenを正規化できる
- [ ] snapshotを時系列保存できる
- [ ] 前回あり→今回なしを検知できる
- [ ] 同一店舗名変更による誤検知を一定程度抑止できる
- [ ] closure eventを重複なく作成できる
- [ ] 閉店前のlast observationを保持できる

### Geo

- [ ] PostGISで最寄りSevenを取得できる
- [ ] 100m以内を正しく判定できる
- [ ] 100.1mが除外されるテストが通る

### UI

- [ ] 地図が表示される
- [ ] 右側に閉店一覧が表示される
- [ ] 一覧クリック→地図が該当店へ移動
- [ ] markerクリック→該当一覧選択
- [ ] 競合店とSevenを同時表示
- [ ] 両店間の距離表示
- [ ] 詳細panelで閉店前情報を表示
- [ ] brand/status/distance/municipality filterが動く
- [ ] Confirmedのみ表示可能
- [ ] Suspectedも追加表示可能

### Quality

- [ ] 外部APIなしでもfixtureで起動できる
- [ ] READMEだけで第三者が再現できる
- [ ] `.env`がcommitされていない
- [ ] service role keyがclient bundleに含まれない
- [ ] OpenPOI attributionが表示される
- [ ] unit/integration testsが通る

---

## 21. 開発順序

Codexは以下の順序で進める。

### Step 1
Repository scaffold + README + env example

### Step 2
Supabase migration + PostGIS + seed brand aliases

### Step 3
FixtureSource + snapshot保存

### Step 4
正規化・matching・diff detection

### Step 5
PostGIS nearest Seven / 100m判定

### Step 6
fixtureベースのAPI

### Step 7
Map + list UI

### Step 8
detail drawer + last observation

### Step 9
filter

### Step 10
OpenPoiSource + recursive bbox partition

### Step 11
神奈川県の実データsnapshot

### Step 12
tests / docs / error handling

**OpenPOI実接続を最初に作らないこと。まずfixtureでエンドツーエンドを完成させ、その後実データへ切り替える。**

---

## 22. 将来ロードマップ（MVP完成後）

### Phase 2: 検知精度向上

- FamilyMart公式データadapter
- LAWSON公式データadapter
- 2ソース以上の照合
- 自動evidence収集
- 閉店/移転/改装分類
- 閉店日推定
- 管理画面

### Phase 3: 全国化

- 都道府県選択
- 全国snapshot
- clustering
- 全国検索
- weekly scheduled collection
- change alert

### Phase 4: 商圏インテリジェンス

- 開店検知
- 跡地店舗検知
- 周辺業態変化
- 時系列商圏マップ
- 競合撤退機会スコア
- AIによる閉店理由/商圏変化要約

### Phase 5: 会社環境へ接続する場合

個人MVPとは明確に分離して検討する。

- BigQuery
- Seven-Eleven社内店舗マスタ
- 売上/客数
- 閉店前後分析
- カテゴリー影響
- OFC向け情報提供

会社データ接続は、権限・情報管理・社内規定を確認してから別プロジェクトとして設計する。

---

## 23. 設計原則

このプロジェクトで最も重要なのは次の5点。

1. **記事を探すのではなく、店舗マスタ差分から変化を発見する。**
2. **消失 ≠ 閉店。**
3. **閉店前情報を時系列で残す。**
4. **距離判定はPostGISで機械的に行い、100m条件を恣意的に広げない。**
5. **データ取得源をadapter化し、将来より信頼性の高い公式ソースへ差し替えられるようにする。**
