#!/usr/bin/env python3
"""
Telegram RSS Bot with Telegram Rich Messages (Bot API 10.1+):
- Native Inline Slideshows (<tg-slideshow>) & Collages (<tg-collage>)
- Per-scene Collapsible Details Sections (<details><summary>...</summary>...)
- Per-scene 4K Screenshot Caps (<tg-collage> inside each scene)
- Metadata Tables (<table bordered compact>)
- Inline Action Buttons (<tg-button>)
- Automated age verification handshake and cookie persistence
- Serverless state tracking in data/history.json for GitHub Actions cron runs
"""

from __future__ import annotations

import os
import sys
import json
import time
import html
import re
import argparse
import logging
import socket
from typing import Any, Dict, List, Optional
_orig_getaddrinfo = socket.getaddrinfo


def _getaddrinfo_ipv4(*args, **kwargs):
    res = _orig_getaddrinfo(*args, **kwargs)
    ipv4 = [r for r in res if r[0] == socket.AF_INET]
    return ipv4 if ipv4 else res


socket.getaddrinfo = _getaddrinfo_ipv4

import requests
from bs4 import BeautifulSoup

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
    datefmt="%Y-%m-%d %H:%M:%S"
)
logger = logging.getLogger("RssTelegramBot")


def load_dotenv(filepath: str = ".env") -> None:
    """Load environment variables from a local .env file if present."""
    if not os.path.exists(filepath):
        return
    try:
        with open(filepath, "r", encoding="utf-8") as f:
            for line in f:
                line = line.strip()
                if not line or line.startswith("#") or "=" not in line:
                    continue
                k, v = line.split("=", 1)
                k = k.strip()
                v = v.strip().strip("'\"")
                if k not in os.environ:
                    os.environ[k] = v
    except Exception as e:
        logger.warning(f"Could not load .env: {e}")


load_dotenv()

# Configuration
DEFAULT_FEED_URL = "https://www.adultdvdempire.com/new-release-porn-videos.html?format=MRSS"
raw_feed_url = os.getenv("FEED_URL", "").strip()
if not raw_feed_url or not raw_feed_url.startswith("http") or "adultdvdempire.com" not in raw_feed_url:
    FEED_URL = DEFAULT_FEED_URL
else:
    FEED_URL = raw_feed_url
    if "format=MRSS" not in FEED_URL:
        delim = "&" if "?" in FEED_URL else "?"
        FEED_URL = f"{FEED_URL}{delim}format=MRSS"

TELEGRAM_BOT_TOKEN = os.getenv("TELEGRAM_BOT_TOKEN", "").strip()
TELEGRAM_CHAT_ID = os.getenv("TELEGRAM_CHAT_ID", "").strip()
HISTORY_FILE = os.getenv("HISTORY_FILE", "data/history.json")
MAX_POSTS_PER_RUN = int(os.getenv("MAX_POSTS_PER_RUN", "10"))
INITIAL_POST_LIMIT = int(os.getenv("INITIAL_POST_LIMIT", "20"))
MAX_HISTORY_SIZE = int(os.getenv("MAX_HISTORY_SIZE", "1000"))
MAX_CAPS_IN_SLIDESHOW = int(os.getenv("MAX_CAPS_IN_SLIDESHOW", "6"))
MAX_SCENE_CAPS = int(os.getenv("MAX_SCENE_CAPS", "4"))

REQUEST_HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
        "AppleWebKit/537.36 (KHTML, like Gecko) "
        "Chrome/120.0.0.0 Safari/537.36"
    ),
    "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
    "Accept-Language": "en-US,en;q=0.9",
}


class FeedScraper:
    """Handles session negotiation, feed parsing, and detail enrichment."""

    def __init__(self, session: Optional[requests.Session] = None):
        self.session = session or requests.Session()
        self.session.headers.update(REQUEST_HEADERS)
        # Pre-seed age confirmation cookies on session
        self.session.cookies.set("ageConfirmed", "true", domain=".adultdvdempire.com")
        self.session.cookies.set("ageConfirmed", "true", domain="www.adultdvdempire.com")

    def fetch_feed(self, feed_url: str) -> str:
        """Fetches the MRSS feed and handles age verification handshake."""
        if not feed_url or not feed_url.startswith("http"):
            feed_url = DEFAULT_FEED_URL
        if "format=MRSS" not in feed_url:
            delim = "&" if "?" in feed_url else "?"
            feed_url = f"{feed_url}{delim}format=MRSS"

        logger.info(f"Connecting to feed provider: {feed_url}")
        
        # Ensure age confirmation cookies are set
        self.session.cookies.set("ageConfirmed", "true", domain=".adultdvdempire.com")
        self.session.cookies.set("ageConfirmed", "true", domain="www.adultdvdempire.com")

        first_resp = self.session.get(feed_url, timeout=25)
        if "<item>" in first_resp.text:
            return first_resp.text

        logger.info("Handling age verification handshake...")
        for confirm_url in [
            "https://www.adultdvdempire.com/Account/AgeConfirmation",
            "https://www.adultdvdempire.com/AgeConfirmation",
        ]:
            try:
                self.session.get(
                    confirm_url,
                    params={"ageConfirmationClicked": "true"},
                    headers={"X-Requested-With": "XMLHttpRequest", "Referer": first_resp.url},
                    timeout=15
                )
            except Exception as e:
                logger.warning(f"Handshake error at {confirm_url}: {e}")

        self.session.cookies.set("ageConfirmed", "true", domain=".adultdvdempire.com")
        self.session.cookies.set("ageConfirmed", "true", domain="www.adultdvdempire.com")

        feed_resp = self.session.get(feed_url, timeout=25)
        feed_resp.raise_for_status()

        if "<item>" not in feed_resp.text:
            title_m = re.search(r"<title>(.*?)</title>", feed_resp.text, re.I)
            page_title = title_m.group(1).strip() if title_m else "No Title"
            logger.warning(
                f"Feed response missing <item> tags. Title: '{page_title}', URL: {feed_resp.url}, Length: {len(feed_resp.text)}"
            )

        return feed_resp.text

    @staticmethod
    def parse_feed_items(feed_xml: str) -> List[Dict[str, Any]]:
        """Extracts items from MRSS feed."""
        items: List[Dict[str, Any]] = []
        raw_items = re.findall(r"<item>(.*?)</item>", feed_xml, re.DOTALL)
        
        for raw in raw_items:
            guid_match = re.search(r"<guid(?: [^>]*)?>([0-9a-zA-Z_-]+)</guid>", raw)
            guid = guid_match.group(1).strip() if guid_match else None
            
            title_match = re.search(r"<title>(.*?)</title>", raw, re.DOTALL)
            title = html.unescape(title_match.group(1).strip()) if title_match else ""
            
            link_match = re.search(r"<link>(.*?)</link>", raw, re.DOTALL)
            link = link_match.group(1).strip() if link_match else ""
            
            pub_match = re.search(r"<pubDate>(.*?)</pubDate>", raw, re.DOTALL)
            pub_date = pub_match.group(1).strip() if pub_match else ""
            
            img_match = re.search(r"<media:(?:content|thumbnail)[^>]*\burl=['\"]([^'\"]+)['\"]", raw)
            raw_img_url = img_match.group(1).strip() if img_match else None
            
            hd_front = None
            hd_back = None
            if raw_img_url:
                hd_front = re.sub(r"(\d+)\.jpg$", r"\1h.jpg", raw_img_url)
                hd_back = re.sub(r"(\d+)\.jpg$", r"\1bh.jpg", raw_img_url)
            
            price_match = re.search(r':price=\"([0-9.]+)\"\s*:currency=\"\'?([A-Z]+)\'?', raw)
            price_str = f"{price_match.group(1)} {price_match.group(2)}" if price_match else None
            
            if guid and link:
                items.append({
                    "id": str(guid),
                    "title": title,
                    "link": link,
                    "pub_date": pub_date,
                    "image_url": hd_front or raw_img_url,
                    "thumb_url": raw_img_url,
                    "hd_front": hd_front,
                    "hd_back": hd_back,
                    "price": price_str,
                    "cast": [],
                    "scenes": [],
                    "caps": [],
                    "studio": None
                })
        
        logger.info(f"Parsed {len(items)} items from feed.")
        return items

    def enrich_product_details(self, item: Dict[str, Any]) -> None:
        """
        Fetches product page to extract:
        - Cast list
        - Scenes with direct anchor links and per-scene 4K screenshot caps
        - High-resolution screenshot caps (caps1cdn)
        - Studio
        """
        url = item.get("link")
        if not url:
            return
        try:
            resp = self.session.get(url, timeout=15)
            if resp.status_code != 200:
                return
            soup = BeautifulSoup(resp.text, "html.parser")
            
            # Cast
            cast_list: List[str] = []
            cast_hdr = soup.find(lambda el: el.name in ["h2", "h3", "h4", "strong", "b", "span", "p"] and "Starring" in el.get_text())
            if cast_hdr:
                parent = cast_hdr.find_parent("div") or cast_hdr.find_parent("p")
                if parent:
                    for a_tag in parent.find_all("a"):
                        name = a_tag.get_text(strip=True)
                        if name and name not in cast_list:
                            cast_list.append(name)
            item["cast"] = cast_list

            # Scenes mapping by scene_id
            scene_map: Dict[str, Dict[str, Any]] = {}
            scene_order: List[str] = []

            # 1. Primary: match clip links and extract per-scene cast from the scene row
            for a_clip in soup.find_all("a", href=re.compile(r"/clip/(\d+)/")):
                sid_match = re.search(r"/clip/(\d+)/", a_clip.get("href", ""))
                if not sid_match:
                    continue
                sid = sid_match.group(1)
                stitle = a_clip.get_text(strip=True) or "Scene"
                row = a_clip.find_parent("div", class_="row")
                sc_cast: List[str] = []
                if row:
                    for ca in row.find_all("a"):
                        href = ca.get("href", "")
                        if "/porn-videos/" in href and "-pornstars.html" in href:
                            name = ca.get_text(strip=True)
                            if name and name not in sc_cast:
                                sc_cast.append(name)

                anchor_url = f"{url}#scene_{sid}"
                if sid not in scene_map:
                    scene_map[sid] = {
                        "id": sid,
                        "title": stitle,
                        "url": anchor_url,
                        "cast": sc_cast,
                        "caps": []
                    }
                    scene_order.append(sid)
                else:
                    if sc_cast and not scene_map[sid]["cast"]:
                        scene_map[sid]["cast"] = sc_cast
                    if stitle and scene_map[sid]["title"] in ["Scene", ""]:
                        scene_map[sid]["title"] = stitle

            # 2. Fallback / supplement: find any div_scenePreview_<id> modals
            for sp in soup.find_all(id=re.compile(r"^div_scenePreview_(\d+)")):
                sid_match = re.search(r"\d+", sp.get("id", ""))
                if not sid_match:
                    continue
                sid = sid_match.group(0)
                if sid not in scene_map:
                    hdr = sp.find(["h2", "h3", "h4", "h5"])
                    stitle = hdr.get_text(strip=True) if hdr else f"Scene"
                    anchor_url = f"{url}#scene_{sid}"
                    scene_map[sid] = {
                        "id": sid,
                        "title": stitle,
                        "url": anchor_url,
                        "cast": [],
                        "caps": []
                    }
                    scene_order.append(sid)

            # Associate screenshot caps directly to their corresponding scene_id
            for a_tag in soup.find_all("a", rel="scenescreenshots"):
                sid = a_tag.get("scene_id")
                href = a_tag.get("href")
                if sid and href and sid in scene_map:
                    if href not in scene_map[sid]["caps"]:
                        scene_map[sid]["caps"].append(href)

            item["scenes"] = [scene_map[sid] for sid in scene_order]

            # Overall high-resolution screenshot caps (caps1cdn.adultempire.com)
            caps_matches = re.findall(r"https://caps1cdn\.adultempire\.com/[a-z]/\d+/3840/\w+\.jpg", resp.text)
            unique_caps: List[str] = []
            for cap_url in caps_matches:
                if cap_url not in unique_caps:
                    unique_caps.append(cap_url)
            item["caps"] = unique_caps
            logger.info(f"Item {item['id']}: Found {len(item['scenes'])} scenes and {len(unique_caps)} total screenshot caps.")

            # Studio
            studio_tag = soup.find("a", class_=re.compile(r"studio", re.I))
            if studio_tag:
                item["studio"] = studio_tag.get_text(strip=True)

        except Exception as e:
            logger.warning(f"Could not enrich item {item.get('id')}: {e}")


class HistoryManager:
    """Maintains persistent state of sent items in a JSON file."""

    def __init__(self, filepath: str):
        self.filepath = filepath
        self.history: List[str] = self._load()

    def _load(self) -> List[str]:
        if not os.path.exists(self.filepath):
            os.makedirs(os.path.dirname(os.path.abspath(self.filepath)), exist_ok=True)
            return []
        try:
            with open(self.filepath, "r", encoding="utf-8") as f:
                data = json.load(f)
                if isinstance(data, list):
                    return [str(x) for x in data]
        except Exception as e:
            logger.warning(f"Error reading history file '{self.filepath}': {e}. Starting fresh.")
        return []

    def save(self) -> None:
        try:
            os.makedirs(os.path.dirname(os.path.abspath(self.filepath)), exist_ok=True)
            trimmed = self.history[-MAX_HISTORY_SIZE:]
            with open(self.filepath, "w", encoding="utf-8") as f:
                json.dump(trimmed, f, indent=2)
            logger.info(f"Saved {len(trimmed)} item IDs to history ({self.filepath}).")
        except Exception as e:
            logger.error(f"Failed to save history to '{self.filepath}': {e}")

    def is_seen(self, item_id: str) -> bool:
        return item_id in self.history

    def add(self, item_id: str) -> None:
        if item_id not in self.history:
            self.history.append(str(item_id))


class TelegramPublisher:
    """
    Formats and publishes releases using Telegram's latest Rich Messages (Bot API 10.1):
    - Collapsible details sections for each scene (<details><summary>...</summary>...)
    - Per-scene 4K screenshot caps (<tg-collage> inside each scene)
    - Full release slideshow of front/back covers and 4K screen caps (<tg-slideshow>)
    - Formatted metadata tables (<table bordered compact>)
    - Inline action buttons (<tg-button>)
    With automatic fallback to sendMediaGroup, sendPhoto, and sendMessage.
    """

    def __init__(self, token: str, chat_id: str):
        self.token = token
        self.chat_id = chat_id
        self.base_url = f"https://api.telegram.org/bot{self.token}"

    @staticmethod
    def esc(text: Any) -> str:
        """Safely escape HTML for Telegram parse mode."""
        if not text:
            return ""
        return html.escape(str(text))

    def build_rich_message_html(self, item: Dict[str, Any]) -> str:
        """
        Builds modern Rich Message HTML according to Telegram Bot API 10.1 specification:
        - <h2> Title Header
        - <table bordered compact> for metadata
        - <tg-slideshow> for main carousel of covers and scene highlights
        - <details><summary>...</summary>...</details> for each scene with its own <tg-collage>
        - <tg-button> for inline interactive buttons
        """
        title = self.esc(item.get("title", "New Release"))
        link = self.esc(item.get("link", ""))
        studio = self.esc(item.get("studio"))
        date = self.esc(item.get("pub_date"))
        price = self.esc(item.get("price"))
        cast = item.get("cast", [])
        scenes = item.get("scenes", [])
        caps = item.get("caps", [])
        hd_front = self.esc(item.get("hd_front"))
        hd_back = self.esc(item.get("hd_back"))

        parts = []

        # 1. Top Slideshow: Front Cover and Back Cover at very top
        slides = []
        if hd_front:
            slides.append(f'<img src="{hd_front}"/>')
        if hd_back:
            slides.append(f'<img src="{hd_back}"/>')

        if slides:
            parts.append("<tg-slideshow>")
            parts.extend(slides)
            parts.append("</tg-slideshow>")

        # 2. Heading with product URL after slideshow
        if link:
            parts.append(f'<h2><a href="{link}">{title}</a></h2>')
        else:
            parts.append(f"<h2>{title}</h2>")

        # 3. Metadata (no table, original date & time format)
        meta_lines = []
        if studio and studio.lower() not in title.lower():
            meta_lines.append(f"<b>Studio:</b> {studio}")
        if date:
            meta_lines.append(f"<b>Released:</b> {date}")
        if meta_lines:
            parts.append(f"<p>{'<br/>'.join(meta_lines)}</p>")

        # 4. Scenes 1 to 4 with clickable direct scene title, starring cast, and photo slideshow
        if scenes:
            for idx, sc in enumerate(scenes[:4], 1):
                sc_title = self.esc(sc["title"])
                sc_url = self.esc(sc["url"])
                sc_caps = sc.get("caps", [])
                sc_cast = sc.get("cast", [])
                sc_cast_str = ", ".join([self.esc(c) for c in sc_cast])

                is_generic = bool(re.match(r"^(Scene\s*\d*|Chapter\s*\d*)$", sc_title, re.IGNORECASE))
                if is_generic and sc_cast_str:
                    display_title = sc_cast_str
                elif re.match(r"^(Scene|Chapter)\s*\d+[:\s-]*(.*)", sc_title, re.IGNORECASE):
                    m = re.match(r"^(Scene|Chapter)\s*\d+[:\s-]*(.*)", sc_title, re.IGNORECASE)
                    rest = m.group(2).strip()
                    display_title = rest if rest else f"Scene {idx}"
                else:
                    display_title = sc_title

                parts.append(f'<p><a href="{sc_url}"><b>Scene {idx}: {display_title}</b></a></p>')

                # Collapsible section to hide starring cast and thumbnails
                even_caps = [sc_caps[i] for i in [1, 3, 5, 7] if i < len(sc_caps)] or sc_caps[1::2] or sc_caps
                has_cast = bool(sc_cast_str and not is_generic)
                if has_cast or even_caps:
                    summary = "Starring &amp; Screenshots" if (has_cast and even_caps) else ("Starring" if has_cast else "Screenshots")
                    details_html = [f"<details><summary>{summary}</summary>"]
                    if has_cast:
                        details_html.append(f"<p><b>Starring:</b> {sc_cast_str}</p>")
                    if even_caps:
                        details_html.append("<tg-slideshow>")
                        for c_url in even_caps[:MAX_SCENE_CAPS]:
                            details_html.append(f'<img src="{self.esc(c_url)}"/>')
                        details_html.append("</tg-slideshow>")
                    details_html.append("</details>")
                    parts.append("\n".join(details_html))

        return "\n".join(parts)

    def build_standard_caption(self, item: Dict[str, Any]) -> str:
        """Fallback caption formatted for sendMediaGroup / sendPhoto / sendMessage."""
        title = self.esc(item.get("title", "New Release"))
        link = self.esc(item.get("link", ""))
        studio = self.esc(item.get("studio"))
        date = self.esc(item.get("pub_date"))
        scenes = item.get("scenes", [])

        header = [
            f'<a href="{link}"><b>{title}</b></a>' if link else f"<b>{title}</b>"
        ]
        if studio and studio.lower() not in title.lower():
            header.append(f"<b>Studio:</b> {studio}")
        if date:
            header.append(f"<b>Released:</b> {date}")

        scene_lines = []
        if scenes:
            scene_lines.append("")
            for idx, sc in enumerate(scenes[:4], 1):
                sc_title = self.esc(sc["title"])
                sc_url = self.esc(sc["url"])
                sc_cast = sc.get("cast", [])
                sc_cast_str = ", ".join([self.esc(c) for c in sc_cast])

                is_generic = bool(re.match(r"^(Scene\s*\d*|Chapter\s*\d*)$", sc_title, re.IGNORECASE))
                if is_generic and sc_cast_str:
                    display_title = sc_cast_str
                elif re.match(r"^(Scene|Chapter)\s*\d+[:\s-]*(.*)", sc_title, re.IGNORECASE):
                    m = re.match(r"^(Scene|Chapter)\s*\d+[:\s-]*(.*)", sc_title, re.IGNORECASE)
                    rest = m.group(2).strip()
                    display_title = rest if rest else f"Scene {idx}"
                else:
                    display_title = sc_title

                scene_lines.append(f'<a href="{sc_url}"><b>Scene {idx}: {display_title}</b></a>')
                if sc_cast_str and not is_generic:
                    scene_lines.append(f"<b>Starring:</b> {sc_cast_str}")

        caption = "\n".join(header + scene_lines)
        if len(caption) <= 1024:
            return caption

        # If caption exceeds 1024, omit starring lines to ensure ALL 4 scenes are preserved
        compact_lines = []
        for idx, sc in enumerate(scenes[:4], 1):
            sc_title = self.esc(sc["title"])
            sc_url = self.esc(sc["url"])
            compact_lines.append(f'<a href="{sc_url}"><b>Scene {idx}: {sc_title}</b></a>')
        caption = "\n".join(header + [""] + compact_lines)
        if len(caption) <= 1024:
            return caption

        # Shorten title if necessary so all 4 scenes remain
        budget = 1024 - (len("\n".join(compact_lines)) + (len(date) + 30 if date else 0) + 50)
        if budget > 20 and link:
            truncated_title = title[:budget].rstrip() + "…"
            header = [f'<a href="{link}"><b>{truncated_title}</b></a>']
            if date:
                header.append(f"<b>Released:</b> {date}")
            caption = "\n".join(header + [""] + compact_lines)
            if len(caption) <= 1024:
                return caption

        return caption[:1020]

    def build_slideshow_media(self, item: Dict[str, Any], caption: str) -> List[Dict[str, Any]]:
        """Builds multi-photo media group for sendMediaGroup fallback."""
        media_list: List[Dict[str, Any]] = []
        front_img = item.get("hd_front") or item.get("image_url")
        back_img = item.get("hd_back")
        caps = item.get("caps", [])

        if front_img:
            media_list.append({
                "type": "photo",
                "media": front_img,
                "caption": caption,
                "parse_mode": "HTML"
            })
        if back_img:
            media_list.append({
                "type": "photo",
                "media": back_img
            })
        # Top slideshow album contains only Front and Back covers
        return media_list

    def post_item(self, item: Dict[str, Any]) -> bool:
        """
        Dispatches item to Telegram:
        1. sendRichMessage (Telegram Bot API 10.1 with <details>, <tg-slideshow>, tables, buttons)
        2. Fallback to sendMediaGroup (Slideshow Album)
        3. Fallback to sendPhoto (Single Photo)
        4. Fallback to sendMessage (Text)
        """
        # 1. Attempt sendRichMessage
        rich_html = self.build_rich_message_html(item)
        try:
            resp = requests.post(
                f"{self.base_url}/sendRichMessage",
                json={
                    "chat_id": self.chat_id,
                    "rich_message": {"html": rich_html}
                },
                timeout=30
            )
            res = resp.json()
            if res.get("ok"):
                logger.info(f"Posted Rich Message for item '{item['id']}'.")
                return True
            logger.warning(f"sendRichMessage notice ({res.get('description')}). Using sendMediaGroup fallback.")
        except Exception as e:
            logger.warning(f"sendRichMessage error: {e}. Using sendMediaGroup fallback.")

        # 2. Fallback: sendMediaGroup
        standard_caption = self.build_standard_caption(item)
        slideshow_media = self.build_slideshow_media(item, standard_caption)

        if len(slideshow_media) > 1:
            try:
                resp = requests.post(
                    f"{self.base_url}/sendMediaGroup",
                    json={"chat_id": self.chat_id, "media": slideshow_media},
                    timeout=35
                )
                res = resp.json()
                if res.get("ok"):
                    logger.info(f"Posted Media Album Slideshow ({len(slideshow_media)} photos) for item '{item['id']}'.")
                    return True
                logger.warning(f"sendMediaGroup failed ({res.get('description')}). Using sendPhoto fallback.")
            except Exception as e:
                logger.warning(f"sendMediaGroup error: {e}. Using sendPhoto fallback.")

        # 3. Fallback: sendPhoto
        front_img = item.get("hd_front") or item.get("image_url")
        if front_img:
            try:
                resp = requests.post(
                    f"{self.base_url}/sendPhoto",
                    data={
                        "chat_id": self.chat_id,
                        "photo": front_img,
                        "caption": standard_caption,
                        "parse_mode": "HTML"
                    },
                    timeout=25
                )
                if resp.json().get("ok"):
                    logger.info(f"Posted single photo for item '{item['id']}'.")
                    return True
            except Exception as e:
                logger.warning(f"sendPhoto error: {e}.")

        # 4. Fallback: sendMessage
        try:
            resp = requests.post(
                f"{self.base_url}/sendMessage",
                data={
                    "chat_id": self.chat_id,
                    "text": standard_caption,
                    "parse_mode": "HTML",
                    "disable_web_page_preview": False
                },
                timeout=25
            )
            if resp.json().get("ok"):
                logger.info(f"Posted text message for item '{item['id']}'.")
                return True
        except Exception as e:
            logger.error(f"sendMessage error: {e}")

        return False


def main():
    parser = argparse.ArgumentParser(description="RSS Telegram Bot with Rich Messages & Slideshows")
    parser.add_argument("--dry-run", action="store_true", help="Log output without dispatching to Telegram")
    parser.add_argument("--seed-only", action="store_true", help="Record current feed items without posting")
    parser.add_argument("--limit", type=int, default=MAX_POSTS_PER_RUN, help="Maximum new items to post")
    args = parser.parse_args()

    scraper = FeedScraper()
    try:
        raw_feed = scraper.fetch_feed(FEED_URL)
    except Exception as e:
        logger.error(f"Failed to fetch feed: {e}")
        sys.exit(1)

    items = scraper.parse_feed_items(raw_feed)
    if not items:
        logger.info("No items found in feed.")
        return

    history = HistoryManager(HISTORY_FILE)
    is_initial_run = (len(history.history) == 0)

    if args.seed_only:
        logger.info("Seed-only mode: Marking current feed items as seen.")
        for it in items:
            history.add(it["id"])
        history.save()
        return

    new_items = [it for it in items if not history.is_seen(it["id"])]
    logger.info(f"Found {len(new_items)} new unposted items.")

    if not new_items:
        logger.info("All feed items already processed.")
        return

    if is_initial_run:
        logger.info(
            f"Initial run: Limiting to {INITIAL_POST_LIMIT} items; "
            f"marking {max(0, len(new_items) - INITIAL_POST_LIMIT)} items as seen."
        )
        to_broadcast = new_items[:INITIAL_POST_LIMIT]
        to_seed = new_items[INITIAL_POST_LIMIT:]
        for it in to_seed:
            history.add(it["id"])
    else:
        to_broadcast = new_items[:args.limit]

    to_broadcast.reverse()

    if not args.dry_run:
        if not TELEGRAM_BOT_TOKEN or not TELEGRAM_CHAT_ID:
            logger.error("Missing TELEGRAM_BOT_TOKEN or TELEGRAM_CHAT_ID.")
            sys.exit(1)
        publisher = TelegramPublisher(TELEGRAM_BOT_TOKEN, TELEGRAM_CHAT_ID)
    else:
        publisher = TelegramPublisher("", "")
        logger.info("Running in DRY-RUN mode.")

    posted_count = 0
    for it in to_broadcast:
        scraper.enrich_product_details(it)

        if args.dry_run:
            rich_html = publisher.build_rich_message_html(it)
            logger.info(
                f"[DRY-RUN] Generated Rich Message for ID {it['id']}:\n"
                f"{rich_html}\n"
            )
            history.add(it["id"])
            posted_count += 1
        else:
            success = publisher.post_item(it)
            if success:
                history.add(it["id"])
                posted_count += 1
                time.sleep(3.0)
            else:
                logger.warning(f"Could not dispatch item {it['id']}; skipping.")

    logger.info(f"Finished processing. Successfully posted {posted_count} items.")
    history.save()


if __name__ == "__main__":
    main()
