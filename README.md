# Daily Marketing News

マーケティング関連ニュースとデジタルマーケティングの最新情報を、毎朝HTMLでまとめるための小さな収集プログラムです。

## 使い方

```bash
python3 daily_marketing_news.py
```

生成結果:

- `reports/latest.html`: 常に最新のHTML
- `reports/marketing-news-YYYY-MM-DD.html`: 日別アーカイブ

## 情報源

初期設定では、公式RSS/Atomを優先しつつ、国内外のニュースを補完するためにGoogle News RSS検索も入れています。

- MarkeZine
- Web担当者Forum
- Marketing Dive
- Social Media Today
- Search Engine Land
- HubSpot Marketing Blog
- Google News JP: Marketing
- Google News EN: Digital Marketing

情報源を増減したい場合は `sources.json` の `sources` を編集してください。

## 運用メモ

- 直近48時間の記事を対象にします。
- 国内情報を少し優先してスコアリングします。
- AI、SEO、SNS、広告、データ、ECなどのタグを自動付与します。
- 取得に失敗したフィードがあっても、HTML内に失敗情報を表示して処理を継続します。
