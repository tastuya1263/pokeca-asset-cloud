# Poké Asset Cloud — クラウド日次更新型

## 現在できること

- BOXごとの在庫数・平均仕入価格をブラウザに保存
- X買取提示額、メルカリ成約額、スニダン成約額を別々に表示
- 各出典の価格中央値を使い、取得できた出典のみの**単純平均**を参考資産価格として計算
- 推定含み損益、現金化シミュレーション、日次価格履歴、JSONバックアップ
- GitHub Actionsで毎朝9:17頃（日本時間）に更新試行。GitHub側の都合で遅延・実行漏れの場合あり
- 外部サイトの画面スクレイピング、ログイン回避、非公開API解析なし

## 重要な制限

**3サイトすべての自動取得が保証されたアプリではありません。**

- X: 公式X APIと対象買取店のアカウント一覧を設定すれば、公開投稿に含まれる明示的な買取金額を抽出できます。ただし本文形式によっては抽出不可、商品名の重複や価格記載形式により誤抽出の可能性があります。実運用前にサンプルを精査してください。Xは買取提示価格であり成約価格ではありません。
- メルカリ: 一般の成約価格を自動取得できる公開APIを確認できていません。権利・利用規約上適切なCSVデータがある場合だけ自動連携します。
- スニダン: 参考になる外部APIは存在するものの、出品価格と成約価格の区別が必要です。本アプリは**成約価格**として提供された許可済みCSVのみを採用します。
- CSVやXのデータが0件だった日は平均は空欄です。過去価格を当日相場として再利用しません。
- 端末ごとにブラウザ保存されます。同じURLを別PCで開いても保有BOXは同期されません。同期させるには別途認証付きDBが必要です。
- GitHub Pagesの公開リポジトリには価格履歴・商品名が公開されます。**在庫数や仕入金額は公開リポジトリへアップロードしないでください。**

## 初回設定（GitHub Pages / GitHub Actions）

1. GitHubで新しいリポジトリを作成し、解凍後の `pokeca_cloud` フォルダの**中身**をリポジトリ直下へアップロード。
2. GitHub → Settings → Pages → Deploy from a branch → `main` / `/ (root)` を設定。
3. `https://ユーザー名.github.io/リポジトリ名/` でアプリを表示。
4. リポジトリ → Settings → Secrets and variables → Actions → Secrets に `X_BEARER_TOKEN` を登録（利用契約・費用が必要な場合があります）。
5. 同画面の Variables に `X_SELLER_ACCOUNTS` を登録。例: `shopaccount1,shopaccount2`（**実在する投稿元のアカウントを自分で確認して入力**）。
6. 許可済みの成約データCSVがある場合は、HTTPSでアクセスできる**非個人情報の**CSVファイルURLを Secrets `AUTHORIZED_PRICE_CSV_URL` に設定。共有URLは第三者が参照可能な場合があるので、秘密情報・保有数・仕入額は含めないこと。
7. Actions → `Update BOX reference prices` → Run workflow で初回実行を試す。`data/prices.json` の `updated_at`, `warnings` を確認。
8. 毎朝の更新は Actions の `schedule` で実行される。GitHub Pagesの配信反映には少し時間差がある。

GitHub Actionsの設定によってはBotの `git push` が権限不足になります。その場合はリポジトリの Settings → Actions → General → Workflow permissions を確認し、読み書き権限を許可してください。ブランチ保護がある場合は別の更新経路が必要です。

## BOXの追加

`data/catalog.json` に商品の `id`（英数字とアンダースコア推奨）・`name`・`aliases` を追加する。X検索は商品名を使用します。

## 許可済みCSVの形式

UTF-8、ヘッダー：

```csv
id,source,price,price_type,url,observed_at
pokemon151,x,30000,buy_offer,https://example.org/quote,2026-10-31T08:00:00+09:00
pokemon151,mercari,35000,sold,https://example.org/sale,2026-10-31T08:00:00+09:00
pokemon151,snkrdunk,33000,sold,https://example.org/trade,2026-10-31T08:00:00+09:00
```

※上記は**架空の入力形式サンプル**です。実際の相場ではありません。`source` は `x` / `mercari` / `snkrdunk`、`price_type` は X のみ `buy_offer`、それ以外は `sold`。同一商品・サイトの複数レコードは中央値を採用。更新日に古いCSVを再利用すると日次価格が最新に見えてしまうため、CSVの入手元・日時を必ず確認してください。

## ローカル起動

Python 3を使い、このフォルダで `python -m http.server 8000` を実行し `http://localhost:8000` を開く。クラウド価格更新のテストは `python scripts/update.py`。

## 次に必要な改善

- X投稿の抽出精度テスト・アカウント別誤認防止・箱状態（シュリンクなど）の正規化
- データの鮮度判定（CSVの observed_at を検証）とサンプル数の最低基準
- 認証つきクラウドDBで保有データを複数端末同期
- 送料・手数料・振込日まで含めた売却経路ごとの手取り計算


## BOX名の入力（修正版）
「BOXを登録」の「BOX名（自由入力）」に商品名を入力して、数量・仕入単価を設定し「登録・追加」を押します。HTMLをローカルで開いた場合も登録は可能ですが、相場の取得にはクラウド公開が必要です。自由入力した商品はクラウドの `data/catalog.json` に追加するまで自動価格更新の対象にはなりません。
