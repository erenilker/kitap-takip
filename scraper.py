import os
import re

import requests
import truststore
from bs4 import BeautifulSoup


truststore.inject_into_ssl()

BASE_URL = "https://www.kitapyurdu.com"
SEARCH_URL = f"{BASE_URL}/index.php"
USER_AGENT = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
    "AppleWebKit/537.36 (KHTML, like Gecko) "
    "Chrome/131.0.0.0 Safari/537.36"
)
TIMEOUT = 5


def _session():
    session = requests.Session()
    session.headers.update({"User-Agent": USER_AGENT})
    return session


def _text(element):
    return element.get_text(" ", strip=True) if element else ""


def _clean_int(value):
    if not value:
        return None
    match = re.search(r"\d+", str(value).replace(".", "").replace(",", ""))
    return int(match.group()) if match else None


def _set_response_encoding(response):
    charset = response.headers.get("Content-Type", "").lower()
    if "charset=" in charset:
        response.encoding = charset.split("charset=", 1)[1].split(";")[0].strip()
        return
    for encoding in ("utf-8", "windows-1254", "iso-8859-9"):
        try:
            decoded = response.content.decode(encoding)
            if "\ufffd" not in decoded:
                response.encoding = encoding
                return
        except UnicodeDecodeError:
            continue
    response.encoding = "utf-8"


def search_books(query):
    if not query or not query.strip():
        return []
    session = _session()
    response = session.get(
        SEARCH_URL,
        params={"route": "product/search", "filter_name": query.strip()},
        timeout=TIMEOUT,
    )
    response.raise_for_status()
    _set_response_encoding(response)
    soup = BeautifulSoup(response.text, "html.parser")
    results = []

    for card in soup.select(".ky-product"):
        title_link = card.select_one("a.ky-product-title")
        if not title_link:
            continue
        href = title_link.get("href", "")
        cover = card.select_one("a.ky-product-cover img")
        cover_url = ""
        if cover:
            cover_url = cover.get("data-src") or cover.get("src") or ""
        if cover_url and cover_url.startswith("//"):
            cover_url = "https:" + cover_url
        elif cover_url and cover_url.startswith("/"):
            cover_url = BASE_URL + cover_url
        if href and href.startswith("/"):
            href = BASE_URL + href
        results.append(
            {
                "title": _text(title_link),
                "author": _text(card.select_one(".ky-product-author a")),
                "publisher": _text(card.select_one(".ky-product-publisher a")),
                "cover_url": cover_url,
                "product_url": href,
            }
        )
    return results


def get_book_detail(product_url):
    session = _session()
    response = session.get(product_url, timeout=TIMEOUT)
    response.raise_for_status()
    _set_response_encoding(response)
    soup = BeautifulSoup(response.text, "html.parser")
    pages = None
    isbn = ""
    publication_year = ""

    for item in soup.select(".ky-pd-attributes__item"):
        text = _text(item)
        label = item.select_one("span")
        label_text = _text(label)
        value_text = text
        if label_text:
            value_text = text[len(label_text):].strip(" :-")
        if "Sayfa" in text:
            pages = _clean_int(value_text)
        elif "ISBN" in text:
            isbn = value_text
        elif "Yayın" in text or "Basım" in text:
            year_match = re.search(r"(19|20)\d{2}", text)
            if year_match:
                publication_year = year_match.group()

    title = _text(soup.select_one("h1"))
    return {
        "title": title,
        "pages": pages,
        "isbn": isbn,
        "publication_year": publication_year,
    }


def download_cover(cover_url, isbn=None, title=None):
    if not cover_url:
        return None
    folder = os.path.join("static", "kapaklar")
    os.makedirs(folder, exist_ok=True)
    safe_name = re.sub(r"[^a-zA-Z0-9_-]+", "-", isbn or title or "kitap").strip("-")
    if not safe_name:
        safe_name = "kitap"
    extension = os.path.splitext(cover_url.split("?")[0])[1].lower()
    if extension not in (".jpg", ".jpeg", ".png", ".webp"):
        extension = ".jpg"
    path = os.path.join(folder, f"{safe_name}{extension}")
    session = _session()
    response = session.get(cover_url, timeout=TIMEOUT)
    response.raise_for_status()
    if not response.content:
        return None
    with open(path, "wb") as cover_file:
        cover_file.write(response.content)
    return path.replace("\\", "/")
