# GBP・SNS投稿自動化 開発計画

## 文書の位置づけ

本書は、KARiN.NOTES の公開記事と KARiN. のサービス紹介を、
次の4つの投稿先へ展開するための開発計画である。

- GBP東京
- GBP福岡
- Instagram
- Facebook

GBP東京と GBP福岡は、1つの「GBP」にまとめない。記事ごとに、どちらへ出したかを別々に記録する。

2026-10-05 に方針を更新した。STEP 0 では管理画面、保存、履歴の土台までを実装している。Google・Instagram・Facebook への送信は未接続である。

区別して扱うもの：

- すでに実装されているもの
- 方針として本書で定めるもの
- API承認後に接続するもの
- まだ実装しないもの

関連するが、本書で上書きしないもの：

- KARiN.chatbot / RAG / Knowledge は `.cursor/rules/karin-ai-development.mdc` と `docs/KARIN_AI_SPEC.md` が正
- 集客・MEOの基本方針は `.cursor/rules/karin-seo-growth-strategy.mdc` が正
- 料金・営業時間・対応エリア・出張可否・院内施術の状況など、いま公開している KARiN. 固有の事実は `official_site_data.py` が正
- 予約の空き判定は既存の予約システムが正。投稿文へ空き枠を書かない

本書の「KARiN.NOTES」は公開ブログである。`ai_knowledge.source_type = notes`（独自AI用Knowledge）とは別物である。

---

# 1. 調査結果（2026-10-05）

## 1.1 KARiN.NOTES 管理画面

入口はスタッフ用ダッシュボードの「KARiN.NOTES 管理」。遷移先は `/admin/blogs`。

公開状態はカード上の「📝 下書き」「📢 公開」という表示である。公開への切り替えは編集画面の下書きチェックで行う。その横に「🔗 表示」、下に「✏ 編集」「🗑 削除」がある。

権限は `staff_section_required("blogs")`。管理者、受付、正規スタッフ。

## 1.2 記事の保存と公開状態

保存先は Supabase の `public.blogs`。公開判定は `draft`。`false` が公開、`true` が下書き。公開読み取りの RLS は `draft IS NOT TRUE`。

`blogs` に媒体別の投稿フラグは持たない。外部投稿は `external_posts` と `external_post_events` に置く。

## 1.3 GBPスケジュール投稿

実装されているのは、スタッフシフトから GBP 用の予定行を組み立てる処理までである。

| 処理 | 役割 |
|---|---|
| `gbp_explicit_area` | `tokyo` / `fukuoka` 以外はエリアとして扱わない |
| `gbp_schedule_label` | 投稿用ラベル。公開ページの「休」へまとめない |
| `gbp_profile_includes_shift` | その日を東京と福岡のどちらに載せるか |
| `gbp_period_key` | 半月の識別子。例 `2026-10-H1` |
| `get_gbp_period_range` | H1 は1〜15日、H2 は16日〜月末 |
| `build_gbp_schedule_entries` | 指定期間・指定プロフィールの対象日だけを日付順で返す |

入力は `staff_work_shifts`。対象スタッフは `PUBLIC_SCHEDULE_STAFF_NAME`。

- 院内かつ東京 → 東京のみ。ラベルは「東京（代々木上原）」
- 院内かつ福岡 → 福岡のみ。ラベルは「福岡（薬院）」
- 帯同 → 両方。ラベルは「トレーナー帯同」
- 休業 → 両方。ラベルは「休業」
- 未設定、シフトなし、院内でエリアなし → どちらにも含めない

検証は `scripts/test_gbp_schedule.py`。DB も Google API も使わない。

この処理は、NOTES 記事の外部投稿やサービス紹介投稿とは別のコンテンツである。STEP 0 では変更しない。

## 1.4 送信処理

GBP / Instagram / Facebook の HTTP クライアント、location ID、認証情報の利用はリポジトリにない。

送信口の関数 `publish_external_post` は STEP 0 で置いてある。呼ぶと未接続の例外になり、成功結果は返さない。管理画面のルートからは呼ばない。

サイト上の Instagram は公開プロフィールへのリンクのみ。Facebook の URL はコードベースにない。

---

# 2. 運用方針

## 2.1 週1本の NOTES を、確認してから展開する

基本ペースは KARiN.NOTES を週1本程度つくること。

1. 記事を書く
2. 公開する
3. 実際のページを見て、文章と画像を整える
4. 管理画面から、必要な投稿先だけを開く
5. 投稿先ごとの文面を確認し、必要なら直して保存する
6. API接続後は、その投稿先への送信が成功したときだけ「投稿済」にする

記事を公開しただけでは、4投稿先へは出ない。こうじさんがページを確認してから、必要なものだけ進める。

季節・特集・コラムは、必要なときだけ `feature` / `column` を使う。通常は `standard`。

## 2.2 4つの投稿先

| キー | 投稿先 | 文章 |
|---|---|---|
| `gbp_tokyo` | GBP東京 | 東京の利用者向け。短い。記事への導線 |
| `gbp_fukuoka` | GBP福岡 | 福岡の利用者向け。必要なら地域の書き方を変える |
| `instagram` | Instagram | 読みやすく、興味が続く |
| `facebook` | Facebook | Instagram より文章量を持たせ、記事の内容が分かる |

同じ文面を4つへそのまま流さない。投稿文、リンク先、必要なら画像は投稿先ごとに保存できる。

投稿文に書いてよい KARiN. 固有情報は、その記事と `official_site_data.py` にある事実まで。料金・営業時間・キャンペーン・空き状況を、材料に無いのに補わない。診断、病名、原因の断定、効果の保証を入れない。

AI による媒体別の本生成は STEP 1 以降。STEP 0 の初期文面は、タイトルと導入文から作る下書きで、投稿先ごとに文が異なる。人が直して保存する。

## 2.3 いつ「投稿済」にするか

媒体からの成功応答を受け取ったときだけ、その投稿先の `status` を `posted` にする。`external_id` と `posted_at` を同時に書く。DB も、この2つが無い `posted` を拒否する。

文面の保存、確認、API未接続、失敗、成否不明は `posted` にしない。

カードではボタンを消さない。

| 状態 | 表示例 |
|---|---|
| 未投稿 | `GBP東京` |
| 保存済み | `GBP東京 保存済` |
| 確認済みで未送信 | `GBP東京 確認済` |
| 送信中 | `GBP東京 送信中` |
| 成功 | `✓ GBP東京済` |
| 失敗 | `GBP東京 失敗` |
| 成否不明 | `GBP東京 要確認` |

福岡・Instagram・Facebook も同じ規則。色と文字の両方で区別する。

同じ記事で、次のように分かれてよい。

```text
GBP東京：投稿済
GBP福岡：未投稿
Instagram：投稿済
Facebook：未投稿
```

下書き記事の4ボタンは押せない。公開ページを確認してから開く。

## 2.4 サービス投稿

ダッシュボードのカードは1つ。「GBPサービス投稿管理」。画面の中で東京と福岡を切り替える。カードは2つに分けない。

対象は次の5つ。トレーニングとリコンディショニングは、GBP上で別サービスとして大量に管理しない。

| service_key | 表示名 | 扱い |
|---|---|---|
| `acupuncture` | 鍼灸 | 既存のアプローチ |
| `seitai_conditioning` | 整体・コンディショニング | 既存のアプローチ |
| `training_reconditioning` | トレーニング・リコンディショニング | 1つのサービス。公開ページは新設予定 |
| `beauty_acupuncture` | 美容鍼 | 公開ページは新設予定 |
| `trainer_accompany` | トレーナー帯同 | 必要なときだけ |

`official_site_data.py` の現行データでは、トレーニングは `training`、リコンディショニングは併用手段である。本書のサービス投稿カタログは、今後のサービスページに合わせた投稿対象である。公式の料金・提供状況の正本は、ページ新設時に `official_site_data.py` 側で更新する。投稿文は、その時点の公式事実を超えて効果や料金を作らない。

STEP 3 の流れ：

```text
GBPサービス投稿管理
→ 東京 / 福岡
→ サービスを選ぶ
→ 切り口候補を複数出す
→ 1つ選ぶ
→ GBP投稿文を生成
→ 確認・修正
→ その地域のGBPへ投稿
```

切り口の例（整体・コンディショニング）：「自宅で受けられる整体」「身体全体を見ながら整える」「痛いところだけにとらわれない」「スポーツ後の身体のケア」。

同じサービスを再度紹介してよい。そのときは切り口を変える。固定の順番や曜日ローテにはしない。履歴を見て、しばらく出していないサービスを次の候補にできる構造にする。

STEP 0 の画面は、地域の切り替えとサービス一覧、投稿状態の表示まで。切り口生成と送信は置かない。

---

# 3. データ

## 3.1 `external_posts`

1投稿先の現在状態。定義は `add_external_posts.sql`。

| 列 | 内容 |
|---|---|
| `source_kind` | `notes_article` または `service` |
| `blog_id` | 記事のとき。サービスでは NULL |
| `service_key` | サービスのとき。記事では NULL |
| `channel` | `gbp` / `instagram` / `facebook` |
| `gbp_profile` | GBP のとき `tokyo` または `fukuoka`。SNS では NULL |
| `status` | `draft` / `ready` / `posting` / `posted` / `failed` / `unknown` |
| `body` / `link_url` / `image_url` | 投稿先ごとに変えられる |
| `angle_label` | サービス投稿の切り口 |
| `external_id` / `posted_at` | 成功時だけ |
| `error_message` | 直近の失敗 |
| `created_by` / `created_at` / `updated_at` | 監査 |

記事の一意性：

- GBP は `(blog_id, gbp_profile)` で1行。東京と福岡は別行
- Instagram / Facebook は `(blog_id, channel)` で1行

サービス投稿は一意にしない。切り口を変えた再紹介を残せる。

`posted` は `external_id` と `posted_at` があるときだけ許す。

anon / authenticated からは読ませない。Flask の service_role だけが読み書きする。`supabase_security_rls.sql` の機密テーブル一覧にも含める。

## 3.2 `external_post_events`

状態が変わるたびに1行。`generated` / `edited` / `confirmed` / `submit_started` / `succeeded` / `failed` / `unknown`。

STEP 0 の保存は `edited`。詳細に「保存のみ。外部サービスへは投稿していません。」と残す。`succeeded` を書く処理は STEP 1 以降だけ。

記事を削除しても、このテーブルへの FK は張っていない。削除ルートは STEP 0 では変更しない。投稿行が残った場合の整理は、削除仕様を変えるときに扱う。

## 3.3 スケジュール投稿の結果

記事用テーブルには入れない。半月投稿を実際に送るときに `gbp_schedule_posts`（`period_key` + `gbp_profile`）を別途検討する。STEP 0 では作らない。

---

# 4. 画面

## 4.1 記事カード

`.admin-blog-actions`（公開状態・表示）と `.admin-blog-buttons`（編集・削除）の間。

```text
[📝 下書き | 📢 公開]  [🔗 表示]
[GBP東京] [GBP福岡] [Instagram] [Facebook]
[✏ 編集] [🗑 削除]
```

下書きは `span` で、リンクにしない。公開記事は確認画面へ進む。

```text
/admin/blogs/<id>/posts/gbp_tokyo
/admin/blogs/<id>/posts/gbp_fukuoka
/admin/blogs/<id>/posts/instagram
/admin/blogs/<id>/posts/facebook
```

## 4.2 投稿確認

投稿先ごとに1画面。記事タイトル、公開ページへのリンク、その投稿先向けの説明、投稿文、リンク先、画像、保存、直近の履歴。

保存すると `status = draft`。投稿済・送信中の行は、この画面から上書きしない。

送信ボタンは置かない。`publish_external_post` はルートから呼ばない。

## 4.3 サービス投稿管理

`/admin/gbp/services?area=tokyo|fukuoka`。ダッシュボードからは NOTES と同じ権限（`dash_perm.blogs`）でカードを出す。

```text
[ 東京 ] [ 福岡 ]
鍼灸                         東京：未投稿
整体・コンディショニング       東京：未投稿
トレーニング・リコンディショニング
美容鍼
トレーナー帯同
```

---

# 5. 既存のGBPスケジュールとの接続

二つは別コンテンツ。材料も状態も共有しない。

| | スケジュール | 記事・サービス |
|---|---|---|
| 材料 | `staff_work_shifts` | 公開記事、またはサービスカタログ |
| 既存関数 | `build_gbp_schedule_entries` | `external_posts.py` |
| 時期 | 半月（H1 / H2） | 記事は公開確認後。サービスは手動 |
| 地域 | 日ごとに東京と福岡へ振り分け | 投稿先として東京と福岡を別管理 |
| 成否 | 将来 `gbp_schedule_posts` | `external_posts` |

共有してよいのは、STEP 1 で実装する GBP 送信処理だけである。`publish_external_post` を、記事・サービス・半月スケジュールの送信側が使う。予定行を組み立てる関数は、そのために変更しない。

認証情報と location ID は環境変数で持つ。コードとログに書かない。変数名は、承認後の認証方式が分かってから決める。

## 5.1 将来拡張：特別営業時間

シフトから、東京GBPの特別営業時間と福岡GBPの特別営業時間を、それぞれ自動生成・更新することを検討する。

STEP 0 では実装しない。STEP 1 の投稿接続が動いたあとに、同じ送信基盤の隣へ足す拡張項目とする。`build_gbp_schedule_entries` の意味は、その作業を始めるときも先に維持する。

---

# 6. ロードマップ

## STEP 0：API承認前（実装済みの範囲）

- 4投稿先の状態管理（`external_posts` / `external_post_events`）
- NOTES 記事カードの4ボタンと、文字での状態表示
- 投稿確認画面と、投稿文・リンク・画像の保存
- 履歴の記録（保存イベント）
- 未接続の送信関数。成功を返さない
- ダッシュボードの「GBPサービス投稿管理」
- サービス画面の東京 / 福岡切り替えと一覧

この段階で行わないもの：

- Google / Instagram / Facebook への送信
- ダミー成功による `posted`
- `build_gbp_schedule_entries` と半月スケジュールの変更
- 記事の公開・下書き・表示・編集・削除の仕様変更
- AI による本生成
- 特別営業時間の更新

## STEP 1：GBP API 承認後

- GBP東京への投稿
- GBP福岡への投稿
- 成功時だけ状態・外部ID・投稿日時・成功履歴を書く
- 失敗と成否不明を分ける
- スケジュール投稿と、記事・サービス投稿で送信処理を共有する
- 拡張項目：東京GBP・福岡GBPの特別営業時間の自動更新

## STEP 2

- Instagram API
- Facebook API
- 各媒体への投稿と、成功状態の管理

## STEP 3

- サービス投稿の本実装
- 東京 / 福岡
- サービス選択
- AI による切り口候補
- 投稿文生成、確認・修正、投稿

## STEP 4

- 投稿履歴の見やすさと分析
- 投稿頻度
- サービス投稿のローテーション補助
- 運用を見ての改善

---

# 7. ファイル

| ファイル | STEP 0 での役割 |
|---|---|
| `docs/GBP_SNS_POSTING_PLAN.md` | 本書 |
| `add_external_posts.sql` | テーブル定義 |
| `scripts/apply_external_posts.py` | DDL の適用 |
| `supabase_security_rls.sql` | 機密テーブル一覧へ追加 |
| `external_posts.py` | 投稿先、表示、保存、未接続の送信口 |
| `app.py` | 確認画面とサービス画面のルート。既存の予定組み立ては未変更 |
| `templates/admin_blogs.html` | 4ボタン |
| `templates/admin_blog_external_post.html` | 確認と保存 |
| `templates/admin_gbp_services.html` | 東京 / 福岡のサービス一覧 |
| `templates/admin_dashboard.html` | カード1枚 |
| `static/css/admin_dashboard.css` | 4ボタンの折返しと状態の色 |
| `scripts/test_external_posts.py` | 表示・保存・未接続の検証 |

STEP 1 以降で足すもの：GBP の実装クラス、Instagram / Facebook の実装クラス、サービス投稿の切り口画面、必要なら `gbp_schedule_posts`。予定組み立て関数の置換は含まない。
