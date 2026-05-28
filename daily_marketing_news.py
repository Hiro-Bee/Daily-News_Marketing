#!/usr/bin/env python3
import json
import re
import sys
import urllib.request
import xml.etree.ElementTree as ET
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from email.utils import parsedate_to_datetime
from html import escape, unescape
from pathlib import Path
from zoneinfo import ZoneInfo


ROOT = Path(__file__).resolve().parent
CONFIG_PATH = ROOT / "sources.json"
USER_AGENT = "CodexDailyMarketingNews/1.0 (+local daily digest)"

KEYWORDS = {
    "AI": ["ai", "生成ai", "人工知能", "chatgpt", "llm", "agent"],
    "SEO": ["seo", "search", "google", "検索", "aiao", "llmo"],
    "SNS": ["social", "sns", "instagram", "tiktok", "x ", "youtube", "linkedin"],
    "広告": ["ad ", "ads", "advertising", "広告", "キャンペーン", "cmo"],
    "データ": ["data", "analytics", "measurement", "privacy", "cookie", "計測", "データ"],
    "EC": ["commerce", "retail", "shop", "ecommerce", "ec", "購買"],
}


@dataclass
class Item:
    title: str
    link: str
    source: str
    category: str
    published: datetime
    summary: str
    tags: list[str]
    score: int


def strip_html(value: str) -> str:
    value = re.sub(r"<br\s*/?>", " ", value or "", flags=re.I)
    value = re.sub(r"<[^>]+>", " ", value)
    value = unescape(value)
    value = re.sub(r"\s+", " ", value).strip()
    return value


def first_text(element: ET.Element, names: list[str]) -> str:
    for name in names:
        found = element.find(name)
        if found is not None and found.text:
            return found.text.strip()
    return ""


def parse_date(value: str, fallback: datetime) -> datetime:
    if not value:
        return fallback
    try:
        parsed = parsedate_to_datetime(value)
        if parsed.tzinfo is None:
            parsed = parsed.replace(tzinfo=timezone.utc)
        return parsed
    except (TypeError, ValueError):
        pass
    for fmt in ("%Y-%m-%dT%H:%M:%S%z", "%Y-%m-%dT%H:%M:%SZ", "%Y-%m-%d"):
        try:
            parsed = datetime.strptime(value, fmt)
            if parsed.tzinfo is None:
                parsed = parsed.replace(tzinfo=timezone.utc)
            return parsed
        except ValueError:
            continue
    return fallback


def fetch_xml(url: str) -> ET.Element:
    request = urllib.request.Request(url, headers={"User-Agent": USER_AGENT})
    with urllib.request.urlopen(request, timeout=20) as response:
        data = response.read()
    return ET.fromstring(data)


def local_name(tag: str) -> str:
    return tag.rsplit("}", 1)[-1].lower()


def child_text(element: ET.Element, child_name: str) -> str:
    for child in list(element):
        if local_name(child.tag) == child_name.lower() and child.text:
            return child.text.strip()
    return ""


def child_attr(element: ET.Element, child_name: str, attr: str) -> str:
    for child in list(element):
        if local_name(child.tag) == child_name.lower():
            return child.attrib.get(attr, "").strip()
    return ""


def classify(title: str, summary: str) -> list[str]:
    text = f"{title} {summary}".lower()
    tags = []
    for tag, needles in KEYWORDS.items():
        if any(needle.lower() in text for needle in needles):
            tags.append(tag)
    return tags[:3] or ["Marketing"]


def score_item(item: Item, now: datetime) -> int:
    text = f"{item.title} {item.summary}".lower()
    score = 0
    score += max(0, 36 - int((now - item.published).total_seconds() // 3600))
    score += 8 * len(item.tags)
    for hot in ["ai", "生成ai", "privacy", "cookie", "google", "tiktok", "instagram", "retail media", "cmo"]:
        if hot in text:
            score += 5
    if item.category.startswith("JP"):
        score += 8
    return score


def parse_feed(source: dict, now: datetime) -> list[Item]:
    root = fetch_xml(source["url"])
    entries = [node for node in root.iter() if local_name(node.tag) in {"item", "entry"}]
    items = []
    for entry in entries:
        title = child_text(entry, "title")
        link = child_text(entry, "link") or child_attr(entry, "link", "href")
        summary = strip_html(
            child_text(entry, "description")
            or child_text(entry, "summary")
            or child_text(entry, "content")
        )
        published_raw = (
            child_text(entry, "pubDate")
            or child_text(entry, "published")
            or child_text(entry, "updated")
        )
        published = parse_date(published_raw, now)
        tags = classify(title, summary)
        item = Item(
            title=strip_html(title),
            link=link,
            source=source["name"],
            category=source["category"],
            published=published,
            summary=summary,
            tags=tags,
            score=0,
        )
        item.score = score_item(item, now)
        if item.title and item.link:
            items.append(item)
    return items


def dedupe(items: list[Item]) -> list[Item]:
    seen = set()
    unique = []
    for item in items:
        key = re.sub(r"\W+", "", item.title.lower())[:80] or item.link
        if key in seen:
            continue
        seen.add(key)
        unique.append(item)
    return unique


def short_summary(item: Item) -> str:
    if item.summary:
        return item.summary[:220] + ("..." if len(item.summary) > 220 else "")
    tag_text = "、".join(item.tags)
    return f"{tag_text}領域の新着記事です。本文で詳細を確認してください。"


def render_html(items: list[Item], failures: list[str], config: dict, now: datetime) -> str:
    generated = now.strftime("%Y-%m-%d %H:%M %Z")
    top_tags = {}
    for item in items:
        for tag in item.tags:
            top_tags[tag] = top_tags.get(tag, 0) + 1
    tag_line = " / ".join(f"{tag}: {count}" for tag, count in sorted(top_tags.items(), key=lambda x: (-x[1], x[0]))[:6])
    genres = sorted(top_tags.keys(), key=lambda tag: (-top_tags[tag], tag))
    genre_options = "\n".join(
        f'<option value="{escape(genre)}">{escape(genre)} ({top_tags[genre]})</option>'
        for genre in genres
    )
    cards = "\n".join(
        f"""
        <article class="news-card" data-primary="{escape(item.tags[0])}" data-tags="{escape("|".join(item.tags))}" data-score="{item.score}" data-published="{escape(item.published.isoformat())}" data-source="{escape(item.source.lower())}">
          <div class="meta"><span>{escape(item.source)}</span><span>{escape(item.published.astimezone(ZoneInfo(config["timezone"])).strftime("%m/%d %H:%M"))}</span></div>
          <h2><a href="{escape(item.link)}" target="_blank" rel="noopener noreferrer">{escape(item.title)}</a></h2>
          <p>{escape(short_summary(item))}</p>
          <div class="tags">{"".join(f"<span>{escape(tag)}</span>" for tag in item.tags)}</div>
        </article>
        """
        for item in items
    )
    failure_html = ""
    if failures:
        failure_html = "<section class=\"failures\"><h2>取得できなかった情報源</h2><ul>" + "".join(
            f"<li>{escape(failure)}</li>" for failure in failures
        ) + "</ul></section>"
    return f"""<!doctype html>
<html lang="ja">
<head>
  <meta charset="utf-8">
  <meta name="viewport" content="width=device-width, initial-scale=1">
  <title>Daily Marketing News - {escape(now.strftime("%Y-%m-%d"))}</title>
  <style>
    :root {{
      color-scheme: light;
      --ink: #16202a;
      --muted: #5b6673;
      --line: #d8dee6;
      --bg: #f7f8fa;
      --panel: #ffffff;
      --accent: #0f766e;
      --accent-2: #b45309;
    }}
    * {{ box-sizing: border-box; }}
    body {{
      margin: 0;
      font-family: -apple-system, BlinkMacSystemFont, "Segoe UI", sans-serif;
      line-height: 1.65;
      color: var(--ink);
      background: var(--bg);
    }}
    header {{
      padding: 36px min(6vw, 56px) 24px;
      background: #ffffff;
      border-bottom: 1px solid var(--line);
    }}
    h1 {{ margin: 0 0 8px; font-size: clamp(28px, 4vw, 44px); letter-spacing: 0; }}
    .lead {{ max-width: 920px; margin: 0; color: var(--muted); }}
    .stats {{
      display: flex;
      flex-wrap: wrap;
      gap: 10px;
      margin-top: 18px;
      color: var(--muted);
      font-size: 14px;
    }}
    .stats span {{
      border: 1px solid var(--line);
      border-radius: 999px;
      padding: 5px 10px;
      background: #fff;
    }}
    main {{ padding: 24px min(6vw, 56px) 48px; }}
    .toolbar {{
      display: flex;
      flex-wrap: wrap;
      align-items: end;
      justify-content: space-between;
      gap: 14px;
      margin-bottom: 22px;
      padding-bottom: 18px;
      border-bottom: 1px solid var(--line);
    }}
    .field-row {{
      display: flex;
      flex-wrap: wrap;
      gap: 12px;
      align-items: center;
    }}
    label {{
      display: grid;
      gap: 5px;
      color: var(--muted);
      font-size: 12px;
      font-weight: 700;
    }}
    select {{
      min-width: 180px;
      border: 1px solid var(--line);
      border-radius: 8px;
      background: #fff;
      color: var(--ink);
      font: inherit;
      padding: 8px 34px 8px 10px;
    }}
    .result-count {{
      color: var(--muted);
      font-size: 14px;
    }}
    .genre-section {{ margin-bottom: 28px; }}
    .genre-heading {{
      display: flex;
      align-items: baseline;
      gap: 10px;
      margin: 0 0 12px;
      font-size: 21px;
      line-height: 1.35;
      letter-spacing: 0;
    }}
    .genre-heading span {{
      color: var(--muted);
      font-size: 13px;
      font-weight: 500;
    }}
    .grid {{
      display: grid;
      grid-template-columns: repeat(auto-fit, minmax(min(100%, 320px), 1fr));
      gap: 16px;
    }}
    .news-card {{
      min-height: 260px;
      border: 1px solid var(--line);
      border-radius: 8px;
      padding: 18px;
      background: var(--panel);
      display: flex;
      flex-direction: column;
      gap: 12px;
    }}
    .meta {{
      display: flex;
      justify-content: space-between;
      gap: 12px;
      color: var(--muted);
      font-size: 13px;
    }}
    h2 {{ margin: 0; font-size: 18px; line-height: 1.45; letter-spacing: 0; }}
    a {{ color: var(--ink); text-decoration-color: var(--accent); text-underline-offset: 3px; }}
    p {{ margin: 0; color: #34404d; }}
    .tags {{ display: flex; flex-wrap: wrap; gap: 6px; margin-top: auto; }}
    .tags span {{
      color: #0f3f3a;
      background: #e7f4f1;
      border: 1px solid #b7ddd6;
      border-radius: 999px;
      padding: 3px 8px;
      font-size: 12px;
      font-weight: 600;
    }}
    .failures {{
      margin-top: 24px;
      padding: 16px 18px;
      border: 1px solid #f1c27d;
      border-radius: 8px;
      background: #fff8ed;
      color: #5a3908;
    }}
    .failures h2 {{ font-size: 16px; margin-bottom: 8px; }}
    .empty {{
      padding: 24px;
      border: 1px dashed var(--line);
      border-radius: 8px;
      background: #fff;
      color: var(--muted);
    }}
    @media (max-width: 640px) {{
      header {{ padding-top: 24px; }}
      .toolbar {{ align-items: stretch; }}
      .field-row, label, select {{ width: 100%; }}
      .meta {{ flex-direction: column; gap: 2px; }}
      .news-card {{ min-height: auto; }}
    }}
  </style>
</head>
<body>
  <header>
    <h1>Daily Marketing News</h1>
    <p class="lead">マーケティング、広告、SEO、SNS、MarTech、AI活用に関する直近ニュースを、公式RSSとニュース検索から収集した日次ダイジェストです。</p>
    <div class="stats">
      <span>Generated: {escape(generated)}</span>
      <span>Items: {len(items)}</span>
      <span>Signals: {escape(tag_line or "No tags")}</span>
    </div>
  </header>
  <main>
    <section class="toolbar" aria-label="表示設定">
      <div class="field-row">
        <label>
          ジャンル
          <select id="genre-filter">
            <option value="all">すべて</option>
            {genre_options}
          </select>
        </label>
        <label>
          並び順
          <select id="sort-order">
            <option value="score">おすすめ順</option>
            <option value="newest">新着順</option>
            <option value="source">媒体順</option>
          </select>
        </label>
      </div>
      <div class="result-count" id="result-count">{len(items)}件表示</div>
    </section>
    <template id="cards-template">{cards}</template>
    <section id="genre-root">
      <p class="empty">対象期間内のニュースが見つかりませんでした。</p>
    </section>
    {failure_html}
  </main>
  <script>
    (() => {{
      const template = document.getElementById("cards-template");
      const root = document.getElementById("genre-root");
      const genreFilter = document.getElementById("genre-filter");
      const sortOrder = document.getElementById("sort-order");
      const resultCount = document.getElementById("result-count");
      const cards = Array.from(template.content.querySelectorAll(".news-card"));

      function compareCards(a, b) {{
        const order = sortOrder.value;
        if (order === "newest") {{
          return Date.parse(b.dataset.published) - Date.parse(a.dataset.published);
        }}
        if (order === "source") {{
          return a.dataset.source.localeCompare(b.dataset.source, "ja") ||
            Date.parse(b.dataset.published) - Date.parse(a.dataset.published);
        }}
        return Number(b.dataset.score) - Number(a.dataset.score) ||
          Date.parse(b.dataset.published) - Date.parse(a.dataset.published);
      }}

      function render() {{
        const selected = genreFilter.value;
        const visible = cards
          .filter((card) => selected === "all" || card.dataset.tags.split("|").includes(selected))
          .sort(compareCards);
        root.replaceChildren();
        resultCount.textContent = `${{visible.length}}件表示`;

        if (!visible.length) {{
          const empty = document.createElement("p");
          empty.className = "empty";
          empty.textContent = "このジャンルの記事はありません。";
          root.append(empty);
          return;
        }}

        const groups = new Map();
        for (const card of visible) {{
          const key = selected === "all" ? card.dataset.primary : selected;
          if (!groups.has(key)) groups.set(key, []);
          groups.get(key).push(card);
        }}

        for (const [genre, groupCards] of groups) {{
          const section = document.createElement("section");
          section.className = "genre-section";

          const heading = document.createElement("h2");
          heading.className = "genre-heading";
          heading.textContent = genre;
          const count = document.createElement("span");
          count.textContent = `${{groupCards.length}}件`;
          heading.append(count);

          const grid = document.createElement("div");
          grid.className = "grid";
          for (const card of groupCards) grid.append(card);

          section.append(heading, grid);
          root.append(section);
        }}
      }}

      genreFilter.addEventListener("change", render);
      sortOrder.addEventListener("change", render);
      render();
    }})();
  </script>
</body>
</html>
"""


def render_index(config: dict, now: datetime, archive_names: list[str]) -> str:
    generated = now.strftime("%Y-%m-%d %H:%M %Z")
    archive_links = "\n".join(
        f'<li><a href="reports/{escape(name)}">{escape(name)}</a></li>'
        for name in archive_names
    )
    return f"""<!doctype html>
<html lang="ja">
<head>
  <meta charset="utf-8">
  <meta name="viewport" content="width=device-width, initial-scale=1">
  <title>Daily Marketing News</title>
  <style>
    :root {{
      color-scheme: light;
      --ink: #16202a;
      --muted: #5b6673;
      --line: #d8dee6;
      --bg: linear-gradient(180deg, #f5f8fb 0%, #eef3f1 100%);
      --panel: rgba(255, 255, 255, 0.92);
      --accent: #0f766e;
      --accent-strong: #115e59;
    }}
    * {{ box-sizing: border-box; }}
    body {{
      margin: 0;
      font-family: -apple-system, BlinkMacSystemFont, "Segoe UI", sans-serif;
      color: var(--ink);
      background: var(--bg);
    }}
    main {{
      width: min(960px, calc(100vw - 32px));
      margin: 0 auto;
      padding: 48px 0 72px;
    }}
    .hero {{
      padding: 32px;
      border: 1px solid var(--line);
      border-radius: 20px;
      background: var(--panel);
      box-shadow: 0 20px 60px rgba(22, 32, 42, 0.08);
      backdrop-filter: blur(10px);
    }}
    h1 {{
      margin: 0 0 12px;
      font-size: clamp(34px, 6vw, 56px);
      line-height: 1.05;
    }}
    p {{
      margin: 0;
      line-height: 1.7;
      color: #34404d;
    }}
    .meta {{
      margin-top: 16px;
      color: var(--muted);
      font-size: 14px;
    }}
    .actions {{
      display: flex;
      flex-wrap: wrap;
      gap: 12px;
      margin-top: 24px;
    }}
    .button {{
      display: inline-flex;
      align-items: center;
      justify-content: center;
      min-height: 48px;
      padding: 0 18px;
      border-radius: 999px;
      text-decoration: none;
      font-weight: 700;
    }}
    .button-primary {{
      background: var(--accent);
      color: #fff;
    }}
    .button-primary:hover {{
      background: var(--accent-strong);
    }}
    .button-secondary {{
      border: 1px solid var(--line);
      color: var(--ink);
      background: #fff;
    }}
    section {{
      margin-top: 24px;
      padding: 28px 32px;
      border: 1px solid var(--line);
      border-radius: 20px;
      background: rgba(255, 255, 255, 0.88);
    }}
    h2 {{
      margin: 0 0 12px;
      font-size: 20px;
    }}
    ul {{
      margin: 0;
      padding-left: 20px;
    }}
    li + li {{
      margin-top: 8px;
    }}
    a {{
      color: var(--accent-strong);
      text-underline-offset: 3px;
    }}
    @media (max-width: 640px) {{
      main {{
        width: min(960px, calc(100vw - 24px));
        padding-top: 24px;
      }}
      .hero, section {{
        padding: 22px;
        border-radius: 16px;
      }}
      .actions {{
        flex-direction: column;
      }}
    }}
  </style>
</head>
<body>
  <main>
    <section class="hero">
      <h1>Daily Marketing News</h1>
      <p>マーケティング、広告、SEO、SNS、MarTech、AI活用の直近ニュースを日次でまとめています。GitHub Pages ではこのページを入口にして、最新レポートと過去アーカイブにアクセスできます。</p>
      <div class="meta">Generated: {escape(generated)}</div>
      <div class="actions">
        <a class="button button-primary" href="reports/latest.html">最新レポートを見る</a>
        <a class="button button-secondary" href="reports/{escape(archive_names[0])}">本日分アーカイブ</a>
      </div>
    </section>
    <section>
      <h2>アーカイブ</h2>
      <ul>
        {archive_links}
      </ul>
    </section>
  </main>
</body>
</html>
"""


def main() -> int:
    config = json.loads(CONFIG_PATH.read_text(encoding="utf-8"))
    tz = ZoneInfo(config.get("timezone", "Asia/Tokyo"))
    now = datetime.now(tz)
    cutoff = now - timedelta(hours=int(config.get("lookback_hours", 48)))
    failures = []
    items = []

    for source in config["sources"]:
        try:
            items.extend(parse_feed(source, now))
        except Exception as exc:
            failures.append(f"{source['name']}: {exc}")

    items = [item for item in dedupe(items) if item.published.astimezone(tz) >= cutoff]
    items.sort(key=lambda item: (item.score, item.published), reverse=True)
    items = items[: int(config.get("max_items", 24))]

    output_dir = ROOT / config.get("output_dir", "reports")
    output_dir.mkdir(parents=True, exist_ok=True)
    dated = output_dir / f"marketing-news-{now.strftime('%Y-%m-%d')}.html"
    latest = output_dir / "latest.html"
    html = render_html(items, failures, config, now)
    dated.write_text(html, encoding="utf-8")
    latest.write_text(html, encoding="utf-8")
    archive_names = sorted(
        (
            path.name for path in output_dir.glob("marketing-news-*.html")
            if path.is_file()
        ),
        reverse=True,
    )
    index = ROOT / "index.html"
    index.write_text(render_index(config, now, archive_names), encoding="utf-8")
    print(f"Wrote {dated}")
    print(f"Wrote {latest}")
    print(f"Wrote {index}")
    print(f"Items: {len(items)}; failures: {len(failures)}")
    return 0 if items else 1


if __name__ == "__main__":
    sys.exit(main())
