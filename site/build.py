"""MemoFast yama sitesi üreticisi.

games.json'dan statik site üretir: ana sayfa (tüm yamalar), her yama için ayrı sayfa,
"oyun nasıl Türkçe yapılır" rehberi, sitemap.xml ve 404 sayfası.
Yama indirme linki hiçbir yerde yoktur; her şey MemoFast Launcher'a yönlendirir.

Kullanım:
    python site/build.py --games games.json --out _site
    SITE_URL=https://zibildak.github.io/memofast-yamalar/  (sonunda / olmalı)
    GOOGLE_VERIFY=<search console kodu>  (isteğe bağlı)
Sadece standart kütüphane kullanır.
"""

from __future__ import annotations

import argparse
import datetime as dt
import html
import json
import os
import re
import shutil
import sys
import urllib.parse
import urllib.request
from pathlib import Path

HERE = Path(__file__).resolve().parent
CATALOG_REPO = "zibildak/memofast-yamalar"
RAW_BASE = f"https://raw.githubusercontent.com/{CATALOG_REPO}/main/"
LAUNCHER_URL = f"https://github.com/{CATALOG_REPO}/releases/download/launcher/MemoFast.exe"
YOUTUBE_JOIN = "https://www.youtube.com/@MehmetariTv/join"
DISCORD_URL = "https://discord.com/invite/9ZWkEtsduC"
MEMOFAST_APP_URL = "https://zibildak.github.io/MemoFastv/"
STEAM_ASSETS = "https://shared.cloudflare.steamstatic.com/store_item_assets/"

AYLAR = ["Ocak", "Şubat", "Mart", "Nisan", "Mayıs", "Haziran", "Temmuz",
         "Ağustos", "Eylül", "Ekim", "Kasım", "Aralık"]

e = html.escape


# ---------------------------------------------------------------- veri

def load_catalog(path: str | None) -> dict:
    if path and Path(path).exists():
        text = Path(path).read_text(encoding="utf-8-sig")
    else:
        url = RAW_BASE + "games.json"
        text = urllib.request.urlopen(url, timeout=30).read().decode("utf-8-sig")
    data = json.loads(text)
    if "data" in data and "sig" in data:  # imzalı zarf
        data = json.loads(data["data"])
    return data


def steam_info(app_ids: list[int]) -> dict[int, dict]:
    """Steam'den kapak/banner resmi ve geliştirici adını alır. Hata olursa boş döner."""
    if not app_ids:
        return {}
    payload = json.dumps({
        "ids": [{"appid": i} for i in app_ids],
        "context": {"language": "turkish", "country_code": "TR"},
        "data_request": {"include_assets": True, "include_basic_info": True},
    })
    url = "https://api.steampowered.com/IStoreBrowseService/GetItems/v1/?input_json=" + urllib.parse.quote(payload)
    try:
        doc = json.load(urllib.request.urlopen(url, timeout=30))
    except Exception as ex:  # çevrimdışı derleme: düz CDN yollarına düşülür
        print("Steam bilgisi alınamadı:", ex, file=sys.stderr)
        return {}
    out: dict[int, dict] = {}
    for item in doc.get("response", {}).get("store_items", []):
        a = item.get("assets") or {}
        fmt = a.get("asset_url_format")
        if not fmt or "appid" not in item:
            continue

        def u(*names):
            for n in names:
                if a.get(n):
                    return STEAM_ASSETS + fmt.replace("${FILENAME}", a[n])
            return None

        basic = item.get("basic_info") or {}
        out[item["appid"]] = {
            "capsule": u("library_capsule_2x", "library_capsule", "main_capsule"),
            "hero": u("library_hero", "page_background", "main_capsule_2x"),
            "header": u("header", "main_capsule"),
            "developers": [d.get("name") for d in basic.get("developers", []) if d.get("name")],
            "publishers": [d.get("name") for d in basic.get("publishers", []) if d.get("name")],
        }
    return out


def asset_url(value: str | None) -> str | None:
    if not value:
        return None
    return value if value.startswith("http") else RAW_BASE + value.lstrip("/")


def tr_date(s: str | None) -> str:
    try:
        d = dt.date.fromisoformat((s or "")[:10])
    except ValueError:
        return ""
    return f"{d.day} {AYLAR[d.month - 1]} {d.year}"


def tr_short_date(s: str | None) -> str:
    """Kart altı için kısa tarih: bu yılsa '3 Ekim', değilse '3 Ekim 2025'."""
    try:
        d = dt.date.fromisoformat((s or "")[:10])
    except ValueError:
        return ""
    return f"{d.day} {AYLAR[d.month - 1]}" + ("" if d.year == dt.date.today().year else f" {d.year}")


def tr_size(n: int | None) -> str:
    if not n:
        return ""
    mb = n / 1024 / 1024
    return f"{mb / 1024:.1f} GB".replace(".", ",") if mb >= 1024 else f"{mb:.0f} MB"


def clip(s: str, n: int) -> str:
    s = re.sub(r"\s+", " ", s).strip()
    return s if len(s) <= n else s[: n - 1].rsplit(" ", 1)[0] + "…"


def sentence(s: str) -> str:
    s = re.sub(r"\s+", " ", (s or "")).strip()
    if not s:
        return ""
    s = s[0].upper() + s[1:]
    return s if s[-1] in ".!?…" else s + "."


def nice_name(name: str) -> str:
    """'ELDEN RING' gibi tamamı büyük adları başlıkta olduğu gibi bırakır."""
    return name.strip()


class Patch:
    def __init__(self, raw: dict, steam: dict[int, dict]):
        self.raw = raw
        self.id: str = raw["id"]
        self.name: str = nice_name(raw.get("gameName") or raw["id"])
        self.title: str = raw.get("title") or "Türkçe Yama"
        self.version: str = raw.get("version") or ""
        self.pro: bool = raw.get("tier") == "pro"
        self.soon: bool = bool(raw.get("comingSoon"))
        self.description: str = raw.get("description") or ""
        self.warning: str = (raw.get("warning") or "").strip()
        self.updated: str = (raw.get("updatedAt") or "")[:10]
        self.changelog: list = raw.get("changelog") or []
        self.info: dict = raw.get("info") or {}
        self.size: int | None = (raw.get("package") or {}).get("size")
        self.scripted: bool = bool(raw.get("installer"))
        self.app_id: int | None = (raw.get("detect") or {}).get("steamAppId")
        s = steam.get(self.app_id or -1, {})
        plain = f"{STEAM_ASSETS}steam/apps/{self.app_id}/" if self.app_id else None
        self.capsule = asset_url(raw.get("cover")) or s.get("capsule") or (plain + "library_600x900_2x.jpg" if plain else None)
        self.hero = asset_url(raw.get("hero")) or s.get("hero") or (plain + "library_hero.jpg" if plain else None)
        self.header = s.get("header") or (plain + "header.jpg" if plain else None)
        self.developers: list[str] = s.get("developers", [])
        self.publishers: list[str] = s.get("publishers", [])

    @property
    def tier_label(self) -> str:
        if self.soon:
            return "Yakında"
        return "Pro" if self.pro else "Ücretsiz"

    @property
    def tier_class(self) -> str:
        return "soon" if self.soon else ("pro" if self.pro else "free")

    @property
    def page_title(self) -> str:
        return f"{self.name} {self.title}"

    def install_method(self) -> str:
        if self.scripted:
            return "Yama, launcher'ın çalıştırdığı kurulum betiğiyle oyun dosyalarına işlenir."
        return "Yama dosyaları oyun klasörüne eklenir; üzerine yazılan orijinal dosyalar önce yedeklenir."


# ---------------------------------------------------------------- şablon

class Site:
    def __init__(self, url: str, verify: str | None):
        self.url = url if url.endswith("/") else url + "/"
        self.base = urllib.parse.urlparse(self.url).path or "/"
        self.verify = verify
        self.today = dt.date.today()

    def abs(self, path: str = "") -> str:
        return self.url + path

    def rel(self, path: str = "") -> str:
        return self.base + path

    def head(self, *, title: str, desc: str, path: str, image: str | None = None,
             jsonld: list | None = None, noindex: bool = False) -> str:
        canonical = self.abs(path)
        parts = [
            "<!doctype html>",
            '<html lang="tr">',
            "<head>",
            '<meta charset="utf-8">',
            '<meta name="viewport" content="width=device-width, initial-scale=1">',
            f"<title>{e(title)}</title>",
            f'<meta name="description" content="{e(desc)}">',
            '<meta name="robots" content="noindex">' if noindex else f'<link rel="canonical" href="{e(canonical)}">',
            '<meta name="theme-color" content="#070C0A">',
            f'<meta property="og:type" content="website">',
            f'<meta property="og:site_name" content="MemoFast">',
            f'<meta property="og:locale" content="tr_TR">',
            f'<meta property="og:title" content="{e(title)}">',
            f'<meta property="og:description" content="{e(desc)}">',
            f'<meta property="og:url" content="{e(canonical)}">',
            f'<meta property="og:image" content="{e(image or self.abs("static/og.png"))}">',
            '<meta name="twitter:card" content="summary_large_image">',
        ]
        if self.verify:
            parts.append(f'<meta name="google-site-verification" content="{e(self.verify)}">')
        parts += [
            f'<link rel="icon" type="image/png" href="{self.rel("static/icon-64.png")}">',
            '<link rel="preconnect" href="https://fonts.googleapis.com">',
            '<link rel="preconnect" href="https://fonts.gstatic.com" crossorigin>',
            '<link href="https://fonts.googleapis.com/css2?family=Archivo:wght@500;700;800;900&family=IBM+Plex+Sans:wght@400;500;600&family=IBM+Plex+Mono:wght@500&display=swap" rel="stylesheet">',
            f'<link rel="stylesheet" href="{self.rel("static/style.css")}?v={self.today:%Y%m%d}">',
        ]
        for block in jsonld or []:
            parts.append('<script type="application/ld+json">' +
                         json.dumps(block, ensure_ascii=False).replace("</", "<\\/") + "</script>")
        parts.append("</head>")
        return "\n".join(parts)

    def topbar(self, active: str = "") -> str:
        def nav(href, label, key):
            cur = ' aria-current="page"' if key == active else ""
            return f'<a href="{self.rel(href)}"{cur}>{label}</a>'
        return f"""<body>
<a class="skip" href="#icerik">İçeriğe geç</a>
<header class="top">
  <div class="wrap top-in">
    <a class="brand" href="{self.rel()}" aria-label="MemoFast ana sayfa">
      <img src="{self.rel('static/icon-64.png')}" width="28" height="28" alt="">
      <span class="brand-name">MemoFast</span><span class="brand-sub">Türkçe yamalar</span>
    </a>
    <nav class="nav" aria-label="Site">
      {nav('', 'Yamalar', 'home')}
      {nav('oyun-turkce-yapma/', 'Oyun nasıl Türkçe yapılır?', 'guide')}
      {nav('#sss', 'SSS', 'faq')}
    </nav>
    <a class="btn btn-dl" href="{LAUNCHER_URL}" data-dl>{ICON_DL}<span>Launcher'ı indir</span></a>
  </div>
</header>
<main id="icerik">"""

    def footer(self) -> str:
        return f"""</main>
<footer class="foot">
  <div class="wrap foot-in">
    <div>
      <p class="foot-brand"><img src="{self.rel('static/icon-64.png')}" width="20" height="20" alt=""> MemoFast</p>
      <p class="muted">Türkçe yamalar MemoFast ekibi tarafından hazırlanır ve sadece MemoFast Launcher ile kurulur.
      Oyun adları ve görselleri sahiplerine aittir; bu site oyun yapımcılarıyla bağlantılı değildir.</p>
    </div>
    <ul class="foot-links">
      <li><a href="{self.rel()}">Tüm yamalar</a></li>
      <li><a href="{self.rel('oyun-turkce-yapma/')}">Oyun nasıl Türkçe yapılır?</a></li>
      <li><a href="{MEMOFAST_APP_URL}">MemoFast çeviri uygulaması</a></li>
      <li><a href="{DISCORD_URL}" rel="noopener">Discord</a></li>
      <li><a href="{YOUTUBE_JOIN}" rel="noopener">YouTube</a></li>
    </ul>
  </div>
</footer>
<script src="{self.rel('static/app.js')}?v={self.today:%Y%m%d}" defer></script>
</body>
</html>
"""


ICON_DL = '<svg viewBox="0 0 24 24" width="18" height="18" aria-hidden="true"><path d="M12 3v12m0 0-5-5m5 5 5-5M4 19h16" fill="none" stroke="currentColor" stroke-width="2.2" stroke-linecap="round" stroke-linejoin="round"/></svg>'
ICON_OPEN = '<svg viewBox="0 0 24 24" width="18" height="18" aria-hidden="true"><path d="M14 4h6v6M20 4l-9 9M18 14v5a1 1 0 0 1-1 1H5a1 1 0 0 1-1-1V7a1 1 0 0 1 1-1h5" fill="none" stroke="currentColor" stroke-width="2.2" stroke-linecap="round" stroke-linejoin="round"/></svg>'
ICON_SEARCH = '<svg viewBox="0 0 24 24" width="18" height="18" aria-hidden="true"><circle cx="11" cy="11" r="7" fill="none" stroke="currentColor" stroke-width="2"/><path d="m20 20-4-4" stroke="currentColor" stroke-width="2" stroke-linecap="round"/></svg>'


def card(site: Site, p: Patch, lazy: bool = True) -> str:
    lazy_attr = ' loading="lazy"' if lazy else ""
    fallback = e(p.header or "")
    img = (f'<img src="{e(p.capsule)}" alt="{e(p.name)} kapak resmi" width="300" height="450"'
           f'{lazy_attr} decoding="async" data-fallback="{fallback}">') if p.capsule else ""
    meta = " · ".join(x for x in [f"v{p.version}" if p.version and not p.soon else "", tr_short_date(p.updated)] if x)
    search = f"{p.name} {p.id.replace('-', ' ')}"
    return f"""<li class="card" data-tier="{p.tier_class}" data-name="{e(p.name.lower())}" data-search="{e(search)}" data-updated="{e(p.updated)}">
  <a href="{site.rel(f'yama/{p.id}/')}">
    <span class="cover" style="--c:{e(p.raw.get('color') or '#26352C')}">{img}<span class="ph">{e(p.name)}</span>
      <span class="tag tag-{p.tier_class}">{p.tier_label}</span></span>
    <span class="card-name">{e(p.name)}</span>
    <span class="card-meta">{e(p.title)}{' · ' + e(meta) if meta else ''}</span>
  </a>
</li>"""


def faq_html(items: list[tuple[str, str]], open_first: bool = False) -> str:
    out = []
    for i, (q, a) in enumerate(items):
        out.append(f'<details{" open" if open_first and i == 0 else ""}><summary>{e(q)}</summary><div class="ans">{a}</div></details>')
    return "\n".join(out)


def faq_ld(items: list[tuple[str, str]]) -> dict:
    return {
        "@context": "https://schema.org",
        "@type": "FAQPage",
        "mainEntity": [{
            "@type": "Question", "name": q,
            "acceptedAnswer": {"@type": "Answer", "text": re.sub(r"<[^>]+>", "", a)},
        } for q, a in items],
    }


def steps_html(site: Site, game: str | None = None) -> str:
    g = e(game) if game else "oyunun"
    target = f"{g} yamasını" if game else "istediğin yamayı"
    return f"""<ol class="steps">
  <li><span class="n">1</span><div><b>MemoFast Launcher'ı indir</b><p>Tek dosya, kurulum gerektirmez. Açılışta Windows yönetici izni ister; oyun klasörüne yazabilmek için gerekli.</p></div></li>
  <li><span class="n">2</span><div><b>Launcher'da {target} seç</b><p>Liste kendiliğinden güncellenir; yeni çıkan yamalar ve güncellemeler açılışta görünür.</p></div></li>
  <li><span class="n">3</span><div><b>Oyun klasörünü göster, Kur'a bas</b><p>Launcher orijinal dosyaları yedekler, yamayı kurar. İstediğin zaman Kaldır ile oyun eski hâline döner.</p></div></li>
</ol>"""


def cta(site: Site, p: Patch | None = None) -> str:
    open_btn = ""
    if p and not p.soon:
        open_btn = (f'<a class="btn btn-ghost" href="memofast://yama/{e(p.id)}" data-open>{ICON_OPEN}<span>Launcher\'da aç</span></a>')
    return f"""<div class="cta">
  <a class="btn btn-dl btn-lg" href="{LAUNCHER_URL}" data-dl>{ICON_DL}<span>MemoFast Launcher'ı indir</span></a>
  {open_btn}
</div>
<p class="cta-note" data-open-note hidden>Launcher açılmadıysa henüz kurulu değil demektir. Önce indir, açtıktan sonra bu düğme yamayı doğrudan gösterir.</p>"""


# ---------------------------------------------------------------- sayfalar

def home_faq() -> list[tuple[str, str]]:
    return [
        ("Türkçe yamalar nereden indirilir?",
         "Yamalar sadece MemoFast Launcher üzerinden kurulur. Launcher'ı indirip açtığında bu listedeki tüm yamalar orada görünür; "
         "oyunu seçip Kur'a basman yeterli. Ayrı dosya indirip elle kopyalaman gerekmez."),
        ("MemoFast Launcher ücretsiz mi?",
         "Evet. Launcher ve ücretsiz yamalar herkese açık, giriş bile istemez. <b>Pro</b> işaretli yamalar YouTube kanalımızın Katıl "
         f"üyelerine açıktır: üyelere özel gönderideki aylık kodu launcher'a yazınca açılır. <a href=\"{YOUTUBE_JOIN}\" rel=\"noopener\">Katıl üyeliği</a>"),
        ("Yama oyunumu bozar mı? Nasıl kaldırırım?",
         "Launcher kurmadan önce üzerine yazacağı orijinal dosyaları yedekler. Launcher'da Kaldır'a basınca yedekler geri konur ve oyun ilk hâline döner. "
         "Olmazsa Steam'de oyuna sağ tıklayıp Özellikler → Yüklü dosyalar → Dosya bütünlüğünü doğrula ile onarabilirsin."),
        ("Windows \"bilgisayarınız korundu\" uyarısı veriyor, ne yapmalıyım?",
         "Launcher yeni ve imza sertifikası olmadığı için Windows SmartScreen bu uyarıyı gösterebilir. "
         "\"Ek bilgi\" yazısına, ardından \"Yine de çalıştır\" düğmesine bas."),
        ("Çevrim içi oyunlarda yama kullanmak ban sebebi olur mu?",
         "Hile koruması olan oyunlarda oyun dosyasını değiştirmek risklidir. Böyle yamaların sayfasında ve launcher'da kurulumdan önce "
         "uyarı gösterilir; uyarıyı okumadan kurma."),
        ("Oyunum listede yok, nasıl isterim?",
         "Launcher'daki <b>İstekler</b> sayfasından oyunu arayıp oy verebilirsin. En çok istenen oyunlar önce çevrilir; "
         "yama çıkınca oy verenlere launcher bildirim gönderir."),
    ]


def build_home(site: Site, patches: list[Patch]) -> str:
    live = [p for p in patches if not p.soon]
    free = sum(1 for p in live if not p.pro)
    pro = sum(1 for p in live if p.pro)
    soon = sum(1 for p in patches if p.soon)
    latest = max((p.updated for p in patches if p.updated), default="")
    faq = home_faq()
    title = "Türkçe Yama Listesi: Oyunları Türkçe Oyna | MemoFast"
    desc = (f"{len(live)} oyun için Türkçe yama tek yerde: {', '.join(p.name for p in live[:4])} ve diğerleri. "
            "MemoFast Launcher ile oyunu Türkçeye çevir, tek tıkla kur, istediğin zaman kaldır.")
    ld = [
        {"@context": "https://schema.org", "@type": "WebSite", "name": "MemoFast", "url": site.abs(), "inLanguage": "tr"},
        {"@context": "https://schema.org", "@type": "SoftwareApplication", "name": "MemoFast Launcher",
         "operatingSystem": "Windows 10, Windows 11", "applicationCategory": "UtilitiesApplication",
         "description": "Türkçe oyun yamalarını tek tıkla kurup kaldıran ücretsiz Windows uygulaması.",
         "offers": {"@type": "Offer", "price": "0", "priceCurrency": "TRY"}, "downloadUrl": LAUNCHER_URL},
        {"@context": "https://schema.org", "@type": "ItemList", "name": "Türkçe yamalar",
         "itemListElement": [{"@type": "ListItem", "position": i + 1, "name": f"{p.name} {p.title}",
                              "url": site.abs(f"yama/{p.id}/")} for i, p in enumerate(patches)]},
        faq_ld(faq),
    ]
    cards = "\n".join(card(site, p, lazy=i >= 12) for i, p in enumerate(patches))
    chips = [("all", "Tümü", len(patches)), ("free", "Ücretsiz", free), ("pro", "Pro", pro), ("soon", "Yakında", soon)]
    chip_html = "".join(
        f'<button type="button" class="chip" data-filter="{k}" aria-pressed="{"true" if k == "all" else "false"}"{" hidden" if n == 0 else ""}>'
        f'{lbl}<span>{n}</span></button>' for k, lbl, n in chips)
    return site.head(title=title, desc=desc, path="", jsonld=ld) + site.topbar("home") + f"""
<section class="intro wrap">
  <div class="intro-text">
    <h1>Türkçe yama listesi</h1>
    <p class="lead">Oyunlarını Türkçe oyna. MemoFast Launcher'daki tüm Türkçe yamalar burada; birini seç, launcher'la tek tıkla kur.
    Yama dosyası indirip klasör klasör kopyalamak yok.</p>
  </div>
  <dl class="stats" aria-label="Özet">
    <div><dt>Yama</dt><dd>{len(live)}</dd></div>
    <div><dt>Ücretsiz</dt><dd>{free}</dd></div>
    <div><dt>Yakında</dt><dd>{soon}</dd></div>
    <div><dt>Son güncelleme</dt><dd class="sm">{e(tr_date(latest))}</dd></div>
  </dl>
</section>

<section class="list wrap" aria-labelledby="yamalar-baslik">
  <h2 id="yamalar-baslik" class="sr">Yamalar</h2>
  <div class="tools">
    <label class="search">{ICON_SEARCH}<span class="sr">Oyun ara</span>
      <input type="search" id="q" placeholder="Oyun ara…" autocomplete="off" spellcheck="false"></label>
    <div class="chips" role="group" aria-label="Filtre">{chip_html}</div>
    <label class="sort"><span class="sr">Sırala</span>
      <select id="sort"><option value="new">Son güncellenen</option><option value="az">A → Z</option></select></label>
  </div>
  <ul class="grid" id="grid">
{cards}
  </ul>
  <div class="empty" id="empty" hidden>
    <p><b>Bu oyunun yaması henüz yok.</b> Launcher'daki İstekler sayfasından oyunu arayıp oy ver; en çok istenenler önce çevrilir.</p>
  </div>
</section>

<section class="how wrap" aria-labelledby="nasil">
  <div class="how-head">
    <h2 id="nasil">Nasıl kurulur?</h2>
    <p class="muted">Üç adım, birkaç dakika. Kurduğun her yama launcher'da durur; tek tıkla kaldırılır.</p>
  </div>
  {steps_html(site)}
  {cta(site)}
</section>

<section class="faq wrap" id="sss" aria-labelledby="sss-baslik">
  <h2 id="sss-baslik">Sık sorulan sorular</h2>
  {faq_html(faq)}
  <p class="more">Oyunun listede yoksa ve kendin çevirmek istiyorsan: <a href="{site.rel('oyun-turkce-yapma/')}">Oyun nasıl Türkçe yapılır?</a></p>
</section>
""" + site.footer()


def patch_faq(p: Patch) -> list[tuple[str, str]]:
    n = e(p.name)
    items = [
        (f"{p.name} Türkçe yama nasıl kurulur?",
         f"MemoFast Launcher'ı indirip aç, listeden <b>{n}</b> yamasını seç ve oyunun kurulu olduğu klasörü göster. "
         "Kur'a basınca launcher orijinal dosyaları yedekler ve yamayı kurar."),
    ]
    if p.soon:
        items.append((f"{p.name} Türkçe yaması ne zaman çıkacak?",
                      "Yama hazırlanıyor. Çıktığı an launcher'da görünür ve bildirim gelir; ayrıca bir şey yapman gerekmez."))
    elif p.pro:
        items.append((f"{p.name} Türkçe yaması ücretsiz mi?",
                      "Bu yama <b>Pro</b>: YouTube kanalımızın Katıl üyelerine açık. Üyelere özel gönderideki aylık kodu launcher'daki "
                      f"Pro ekranına yazınca kurulum açılır. <a href=\"{YOUTUBE_JOIN}\" rel=\"noopener\">Katıl üyeliği</a>"))
    else:
        items.append((f"{p.name} Türkçe yaması ücretsiz mi?",
                      "Evet, bu yama ücretsiz. Giriş ya da üyelik istemez; launcher'dan doğrudan kurulur."))
    items.append(("Yamayı nasıl kaldırırım?",
                  "Launcher'da yamanın sayfasında Kaldır'a bas. Yedeklenen orijinal dosyalar geri konur, oyun ilk hâline döner."))
    if p.warning:
        items.append(("Kurmadan önce bilmem gereken bir şey var mı?", e(sentence(p.warning))))
    items.append(("Oyun güncellenince yama ne olur?",
                  "Büyük oyun güncellemeleri yama dosyalarının üzerine yazabilir. Böyle olursa launcher'dan yamayı yeniden kurman yeterli. "
                  "Yamanın yeni sürümü çıkınca launcher güncelleme olarak gösterir."))
    return items


def build_patch(site: Site, p: Patch, others: list[Patch]) -> str:
    path = f"yama/{p.id}/"
    status = ("hazırlanıyor, çıkınca launcher'da görünecek." if p.soon
              else "MemoFast Launcher ile tek tıkla kur, istediğin zaman kaldır.")
    desc = clip(f"{p.name} Türkçe yama: {sentence(p.description) or 'Oyundaki metinler Türkçeye çevrildi.'} {status}", 158)
    title = f"{p.name} Türkçe Yama" + (" (Yakında)" if p.soon else "") + " | MemoFast"
    faq = patch_faq(p)
    ld = [
        {"@context": "https://schema.org", "@type": "BreadcrumbList", "itemListElement": [
            {"@type": "ListItem", "position": 1, "name": "Türkçe yamalar", "item": site.abs()},
            {"@type": "ListItem", "position": 2, "name": f"{p.name} Türkçe Yama", "item": site.abs(path)}]},
        faq_ld(faq),
    ]

    facts = []
    if p.version and not p.soon:
        facts.append(("Sürüm", p.version))
    if p.updated:
        facts.append(("Güncellendi", tr_date(p.updated)))
    if p.size and not p.soon:
        facts.append(("Boyut", tr_size(p.size)))
    facts.append(("Erişim", "Pro (Katıl üyeleri)" if p.pro else "Ücretsiz"))
    for k, v in p.info.items():
        if v:
            facts.append((k, str(v)))
    if p.developers:
        facts.append(("Geliştirici", ", ".join(p.developers[:2])))
    facts_html = "".join(f"<div><dt>{e(k)}</dt><dd>{e(v)}</dd></div>" for k, v in facts)

    about = [e(sentence(p.description))] if p.description else []
    about.append(f"{e(p.name)} için hazırlanan bu Türkçe yama MemoFast Launcher ile kurulur. {p.install_method()} "
                 "Kaldırdığında oyun orijinal hâline döner.")
    if p.developers:
        dev = ", ".join(p.developers[:2])
        pub = ", ".join(x for x in p.publishers[:2] if x not in p.developers)
        about.append(f"{e(p.name)}, {e(dev)} tarafından geliştirildi" + (f" ve {e(pub)} tarafından yayımlandı." if pub else "."))
    about_html = "".join(f"<p>{x}</p>" for x in about)

    warn = (f'<aside class="warn" role="note"><b>Kurmadan önce oku</b><p>{e(sentence(p.warning))}</p></aside>'
            if p.warning else "")
    pro_box = ""
    if p.pro and not p.soon:
        pro_box = f"""<aside class="probox"><b>Pro yama</b>
<p>YouTube kanalımızın Katıl üyelerine açık. Üyelere özel gönderideki aylık kodu launcher'daki Pro ekranına yaz, kurulum açılır.</p>
<a href="{YOUTUBE_JOIN}" rel="noopener">Katıl üyeliğine bak →</a></aside>"""
    soon_box = ('<aside class="soonbox"><b>Bu yama hazırlanıyor</b><p>Çıktığında launcher\'da görünür ve bildirim gelir. '
                'Launcher\'ı şimdiden kurarsan ilk sen haberdar olursun.</p></aside>') if p.soon else ""

    changes = ""
    if p.changelog:
        rows = []
        for c in p.changelog[:8]:
            if isinstance(c, dict):
                head = " · ".join(x for x in [c.get("version") and f"v{c['version']}", tr_date(c.get("date"))] if x)
                notes = c.get("notes") or c.get("changes") or c.get("text") or ""
                notes = notes if isinstance(notes, str) else " ".join(map(str, notes))
                rows.append(f"<li><b>{e(head)}</b> {e(notes)}</li>")
            else:
                rows.append(f"<li>{e(str(c))}</li>")
        changes = f'<section class="block"><h2>Değişiklikler</h2><ul class="changes">{"".join(rows)}</ul></section>'

    steam = (f'<a class="steam" href="https://store.steampowered.com/app/{p.app_id}/" rel="noopener">Oyunun Steam sayfası →</a>'
             if p.app_id else "")
    hero_style = f' style="--hero:url(\'{e(p.hero)}\')"' if p.hero else ""
    cover = (f'<img class="pcover" src="{e(p.capsule)}" alt="{e(p.name)} kapak resmi" width="240" height="360" '
             f'data-fallback="{e(p.header or "")}">') if p.capsule else ""

    rel = [o for o in others if o.id != p.id][:6]
    more = "\n".join(card(site, o) for o in rel)

    return site.head(title=title, desc=desc, path=path, image=p.hero or p.capsule, jsonld=ld) + site.topbar() + f"""
<section class="phero"{hero_style}>
  <div class="wrap phero-in">
    {cover}
    <div class="phead">
      <nav class="crumbs" aria-label="Konum"><a href="{site.rel()}">Türkçe yamalar</a><span>/</span>{e(p.name)}</nav>
      <h1>{e(p.name)} <span>{e(p.title)}</span></h1>
      <p class="pbadges"><span class="tag tag-{p.tier_class}">{p.tier_label}</span>
        {f'<span class="pill">v{e(p.version)}</span>' if p.version and not p.soon else ''}
        {f'<span class="pill">{e(tr_date(p.updated))}</span>' if p.updated else ''}
        {f'<span class="pill">{e(tr_size(p.size))}</span>' if p.size and not p.soon else ''}</p>
      {cta(site, p)}
    </div>
  </div>
</section>

<div class="wrap pbody">
  <div class="pmain">
    {soon_box}{warn}
    <section class="block"><h2>{e(p.name)} Türkçe yama hakkında</h2>{about_html}</section>
    <section class="block"><h2>{e(p.name)} Türkçe yama nasıl kurulur?</h2>{steps_html(site, p.name)}</section>
    {changes}
    <section class="block faq"><h2>Sorular</h2>{faq_html(faq)}</section>
  </div>
  <aside class="pside">
    <dl class="facts">{facts_html}</dl>
    {pro_box}
    {steam}
  </aside>
</div>

<section class="wrap others" aria-labelledby="diger">
  <h2 id="diger">Diğer Türkçe yamalar</h2>
  <ul class="grid grid-sm">
{more}
  </ul>
  <p class="more"><a href="{site.rel()}">Tüm yamaları gör →</a></p>
</section>
""" + site.footer()


def build_guide(site: Site, patches: list[Patch]) -> str:
    path = "oyun-turkce-yapma/"
    live = [p for p in patches if not p.soon]
    faq = [
        ("Oyun çevirme programı var mı?",
         f"Evet. Hazır yaması olmayan oyunlar için <a href=\"{MEMOFAST_APP_URL}\">MemoFast</a> uygulaması Unity, Unreal Engine, Ren'Py ve "
         "RPG Maker ile yapılmış birçok oyunun metinlerini otomatik olarak Türkçeye çevirebilir. Hazır yaması olan oyunlarda "
         "MemoFast Launcher'daki yamayı kurmak daha hızlı ve daha temiz sonuç verir."),
        ("Steam oyunlarını Türkçe yapabilir miyim?",
         "Oyunun resmi Türkçesi varsa Steam'de oyuna sağ tıklayıp Özellikler → Dil bölümünden Türkçe'yi seçmen yeterli. "
         "Resmi Türkçesi yoksa Türkçe yama gerekir; listede olan oyunlar MemoFast Launcher'la tek tıkla kurulur."),
        ("Türkçe yama güvenli mi?",
         "MemoFast Launcher yamayı kurmadan önce değiştireceği orijinal dosyaları yedekler; Kaldır'a basınca her şey geri konur. "
         "Yamalar imzalı bir listeden gelir, launcher imzası tutmayan listeyi kabul etmez."),
        ("Çevrim içi oyunlarda Türkçe yama kullanılır mı?",
         "Hile koruması (EAC, BattlEye vb.) olan oyunlarda dosya değiştirmek ban riski taşır. Bu tür yamalarda launcher kurulumdan "
         "önce açıkça uyarır; bazı yamalar sadece çevrimdışı oynanacak şekilde hazırlanır."),
        ("Yama kurdum ama oyun hâlâ İngilizce, neden?",
         "Çoğu yama oyunun İngilizce dil dosyalarının yerine geçer. Oyunun içindeki dil ayarının English olduğundan emin ol; "
         "yamanın sayfasında farklı bir dil gerekiyorsa yazar."),
    ]
    ld = [
        {"@context": "https://schema.org", "@type": "Article", "headline": "Oyun nasıl Türkçe yapılır?",
         "inLanguage": "tr", "author": {"@type": "Organization", "name": "MemoFast"},
         "dateModified": site.today.isoformat(), "mainEntityOfPage": site.abs(path)},
        faq_ld(faq),
    ]
    sample = ", ".join(f'<a href="{site.rel(f"yama/{p.id}/")}">{e(p.name)}</a>' for p in live[:6])
    return site.head(
        title="Oyun Nasıl Türkçe Yapılır? Oyun Çevirme Rehberi | MemoFast",
        desc="Oyunu Türkçe yapmanın üç yolu: resmi dil ayarı, hazır Türkçe yama ve oyun çevirme programı. "
             "Adım adım anlatım, dikkat edilecekler ve sık sorulan sorular.",
        path=path, jsonld=ld) + site.topbar("guide") + f"""
<article class="wrap guide">
  <header class="guide-head">
    <nav class="crumbs" aria-label="Konum"><a href="{site.rel()}">Türkçe yamalar</a><span>/</span>Rehber</nav>
    <h1>Oyun nasıl Türkçe yapılır?</h1>
    <p class="lead">Bir oyunu Türkçe oynamanın üç yolu var. Hangisinin işine yarayacağı oyunun resmi Türkçesi olup olmadığına
    ve hazır bir Türkçe yaması bulunup bulunmadığına bağlı.</p>
  </header>

  <ol class="ways">
    <li><h2><span>1</span> Oyunun kendi dil ayarı</h2>
      <p>Önce oyunun resmi Türkçesi var mı bak. Steam'de oyuna sağ tıkla, <b>Özellikler → Dil</b> bölümünden Türkçe'yi seç.
      Oyun içi ayarlarda da dil seçeneği olabilir. Resmi çeviri varsa başka bir şeye gerek yok.</p></li>
    <li><h2><span>2</span> Hazır Türkçe yama</h2>
      <p>Resmi Türkçesi olmayan oyunlar için Türkçe yama kurulur. MemoFast Launcher'da şu an {len(live)} oyunun yaması var:
      {sample}{' ve diğerleri' if len(live) > 6 else ''}. Launcher oyun klasörünü bulmana yardım eder, orijinal dosyaları yedekler
      ve yamayı tek tıkla kurar.</p>
      <p><a href="{site.rel()}">Tüm Türkçe yama listesini gör →</a></p></li>
    <li><h2><span>3</span> Oyunu kendin çevir</h2>
      <p>Oyunun hazır yaması yoksa <a href="{MEMOFAST_APP_URL}">MemoFast</a> uygulamasıyla oyunu kendin çevirebilirsin.
      Unity, Unreal Engine, Ren'Py ve RPG Maker oyunlarında metinleri bulup otomatik olarak Türkçeye çevirir.
      Makine çevirisi olduğu için bazı cümleler hazır yama kadar düzgün olmayabilir.</p></li>
  </ol>

  <section class="block">
    <h2>MemoFast Launcher ile Türkçe yama kurma</h2>
    {steps_html(site)}
    {cta(site)}
  </section>

  <section class="block">
    <h2>Kurmadan önce dikkat et</h2>
    <ul class="checks">
      <li><b>Oyun kapalı olsun.</b> Açık oyunun dosyaları değiştirilemez; launcher oyun açıksa kurulumu durdurur.</li>
      <li><b>Oyun dilini kontrol et.</b> Yamaların çoğu İngilizce dosyaların yerine geçer, oyun dili English olmalı.</li>
      <li><b>Hile korumalı oyunlarda dikkat.</b> Çevrim içi oyunlarda dosya değiştirmek ban sebebi olabilir; yama sayfasındaki uyarıyı oku.</li>
      <li><b>Güncellemeden sonra yeniden kur.</b> Büyük oyun güncellemeleri yamanın üzerine yazabilir.</li>
    </ul>
  </section>

  <section class="block faq">
    <h2>Sık sorulan sorular</h2>
    {faq_html(faq)}
  </section>
</article>
""" + site.footer()


def build_404(site: Site) -> str:
    return site.head(title="Sayfa bulunamadı | MemoFast", desc="Aradığın sayfa bulunamadı.", path="404.html",
                     noindex=True) + site.topbar() + f"""
<section class="wrap notfound">
  <h1>Bu sayfa yok</h1>
  <p class="lead">Yama kaldırılmış ya da adres değişmiş olabilir.</p>
  <p><a class="btn btn-dl" href="{site.rel()}">Tüm yamalara dön</a></p>
</section>
""" + site.footer()


def sitemap(site: Site, patches: list[Patch]) -> str:
    urls = [("", site.today.isoformat()), ("oyun-turkce-yapma/", site.today.isoformat())]
    urls += [(f"yama/{p.id}/", p.updated or site.today.isoformat()) for p in patches]
    body = "".join(f"<url><loc>{e(site.abs(u))}</loc><lastmod>{d}</lastmod></url>" for u, d in urls)
    return f'<?xml version="1.0" encoding="UTF-8"?>\n<urlset xmlns="http://www.sitemaps.org/schemas/sitemap/0.9">{body}</urlset>\n'


# ---------------------------------------------------------------- ana

def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--games", default=None, help="games.json yolu (yoksa GitHub'dan çekilir)")
    ap.add_argument("--out", default="_site")
    args = ap.parse_args()

    site = Site(os.environ.get("SITE_URL", "https://zibildak.github.io/memofast-yamalar/"),
                os.environ.get("GOOGLE_VERIFY") or None)
    catalog = load_catalog(args.games)
    raws = [p for p in catalog.get("patches", []) if p.get("id") and not p.get("hidden")]
    steam = steam_info([p["detect"]["steamAppId"] for p in raws if (p.get("detect") or {}).get("steamAppId")])
    patches = [Patch(r, steam) for r in raws]
    # Çıkmış yamalar önce (son güncellenen en üstte), "yakında" olanlar sonda.
    patches.sort(key=lambda p: p.name.lower())
    patches.sort(key=lambda p: p.updated, reverse=True)
    patches.sort(key=lambda p: p.soon)

    out = Path(args.out)
    if out.exists():
        shutil.rmtree(out)
    (out / "static").mkdir(parents=True)
    for f in (HERE / "static").iterdir():
        shutil.copy2(f, out / "static" / f.name)
    # site/root içindekiler (ör. Google doğrulama dosyası) sitenin köküne olduğu gibi kopyalanır.
    if (HERE / "root").is_dir():
        for f in (HERE / "root").iterdir():
            shutil.copy2(f, out / f.name)

    def write(rel: str, text: str) -> None:
        dest = out / rel
        dest.parent.mkdir(parents=True, exist_ok=True)
        dest.write_text(text, encoding="utf-8")

    write("index.html", build_home(site, patches))
    write("oyun-turkce-yapma/index.html", build_guide(site, patches))
    for p in patches:
        write(f"yama/{p.id}/index.html", build_patch(site, p, patches))
    write("404.html", build_404(site))
    write("sitemap.xml", sitemap(site, patches))
    write("robots.txt", f"User-agent: *\nAllow: /\nSitemap: {site.abs('sitemap.xml')}\n")
    write(".nojekyll", "")
    print(f"{len(patches)} yama, {len(patches) + 3} sayfa -> {out}")


if __name__ == "__main__":
    main()
