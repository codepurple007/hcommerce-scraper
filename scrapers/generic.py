"""
Generic e-commerce scraper that works on any site without site-specific rules.
It uses a set of common CSS/JSON-LD heuristics to extract:
  - Products from listing pages
  - Product detail from single-product pages
  - Site-wide navigation / category tree
"""
from __future__ import annotations

import re
import json
import urllib.parse
from typing import Optional

from bs4 import BeautifulSoup, Tag

from models import (
    Product, ProductImage, ProductVariant, CategoryNode, SiteInfo, ScrapeResult
)
from scrapers.base import new_page, auto_scroll


# ── Helpers ───────────────────────────────────────────────────────────────────

def _abs(base: str, href: Optional[str]) -> Optional[str]:
    if not href:
        return None
    if href.startswith("//"):
        return "https:" + href
    if href.startswith("http"):
        return href
    return urllib.parse.urljoin(base, href)


def _clean(text: Optional[str]) -> Optional[str]:
    if not text:
        return None
    return re.sub(r"\s+", " ", text).strip() or None


def _find_price(text: Optional[str]) -> Optional[str]:
    if not text:
        return None
    m = re.search(r"[\$€£¥₹]?\s*[\d,]+\.?\d*", text)
    return m.group(0).strip() if m else _clean(text)


# ── JSON-LD extraction ────────────────────────────────────────────────────────

def _parse_jsonld(soup: BeautifulSoup) -> list[dict]:
    results = []
    for tag in soup.find_all("script", type="application/ld+json"):
        try:
            data = json.loads(tag.string or "")
            if isinstance(data, list):
                results.extend(data)
            else:
                results.append(data)
        except Exception:
            pass
    return results


def _product_from_jsonld(node: dict, base_url: str) -> Optional[Product]:
    t = node.get("@type", "")
    if not isinstance(t, str):
        t = " ".join(t)
    if "Product" not in t:
        return None

    images: list[ProductImage] = []
    img_raw = node.get("image", [])
    if isinstance(img_raw, str):
        img_raw = [img_raw]
    elif isinstance(img_raw, dict):
        img_raw = [img_raw.get("url", "")]
    for img in img_raw:
        if isinstance(img, dict):
            src = img.get("url") or img.get("contentUrl") or ""
        else:
            src = str(img)
        if src:
            images.append(ProductImage(src=_abs(base_url, src) or src))

    offers = node.get("offers", {})
    if isinstance(offers, list):
        offers = offers[0] if offers else {}
    price = str(offers.get("price", "")) or None
    currency = offers.get("priceCurrency")
    in_stock = None
    avail = offers.get("availability", "")
    if avail:
        in_stock = "InStock" in avail or "instock" in avail.lower()

    rating_node = node.get("aggregateRating", {})
    rating = None
    review_count = None
    if rating_node:
        try:
            rating = float(rating_node.get("ratingValue", 0)) or None
            review_count = int(rating_node.get("reviewCount", 0)) or None
        except (TypeError, ValueError):
            pass

    return Product(
        title=_clean(node.get("name")),
        price=_find_price(price),
        currency=currency,
        sku=_clean(str(node.get("sku", ""))) or None,
        brand=_clean(node.get("brand", {}).get("name") if isinstance(node.get("brand"), dict) else node.get("brand")),
        rating=rating,
        review_count=review_count,
        in_stock=in_stock,
        description=_clean(node.get("description")),
        images=images,
        url=_abs(base_url, node.get("url")),
    )


# ── HTML heuristic extraction ─────────────────────────────────────────────────

# Common CSS selectors used by Shopify, WooCommerce, BigCommerce, custom stores
PRODUCT_CARD_SELECTORS = [
    "[data-product-id]", "[data-product]", "[data-item-id]",
    ".product-card", ".product-item", ".product-tile", ".product-grid-item",
    ".product_card", ".ProductCard", ".product__card",
    "li.product", "article.product", ".woocommerce-product",
    ".s-product-image-container",   # Amazon-like
    "[class*='product-card']", "[class*='ProductCard']", "[class*='product-tile']",
]

TITLE_SELECTORS = [
    "h1.product-title", "h1.product__title", "h1[itemprop='name']",
    ".product-title", ".product__title", ".product-name",
    ".ProductCard__title", "[data-product-title]",
    "h2.woocommerce-loop-product__title",
]

PRICE_SELECTORS = [
    "[itemprop='price']", ".price", ".product-price", ".product__price",
    ".offer-price", ".sale-price", ".regular-price",
    ".ProductCard__price", "[data-price]", "[class*='price']",
]

IMAGE_SELECTORS = [
    "img[data-src]", "img[data-lazy-src]", "img.product-image",
    "img.product__image", "[class*='product'] img",
]


def _extract_card(card: Tag, base_url: str) -> Optional[Product]:
    """Extract one product from a product card element."""
    # Title
    title = None
    for sel in TITLE_SELECTORS:
        el = card.select_one(sel)
        if el:
            title = _clean(el.get_text())
            break
    if not title:
        for tag in ["h1", "h2", "h3", "h4"]:
            el = card.find(tag)
            if el:
                title = _clean(el.get_text())
                break
    if not title:
        return None

    # Price
    price = None
    for sel in PRICE_SELECTORS:
        el = card.select_one(sel)
        if el:
            price = _find_price(el.get_text())
            if price:
                break

    # Image
    images: list[ProductImage] = []
    for sel in IMAGE_SELECTORS:
        el = card.select_one(sel)
        if el:
            src = (el.get("data-src") or el.get("data-lazy-src") or
                   el.get("data-original") or el.get("src") or "")
            alt = el.get("alt", "")
            if src and not src.startswith("data:"):
                images.append(ProductImage(src=_abs(base_url, str(src)), alt=str(alt) or None))
            break

    # Link → URL
    link = card.find("a", href=True)
    url = _abs(base_url, str(link["href"])) if link else None  # type: ignore

    return Product(title=title, price=price, images=images, url=url)


def _extract_product_cards(soup: BeautifulSoup, base_url: str, max_products: int) -> list[Product]:
    cards: list[Tag] = []
    for sel in PRODUCT_CARD_SELECTORS:
        found = soup.select(sel)
        if found:
            cards = found
            break

    products: list[Product] = []
    seen_titles: set[str] = set()
    for card in cards[:max_products * 2]:
        p = _extract_card(card, base_url)
        if p and p.title and p.title not in seen_titles:
            seen_titles.add(p.title)
            products.append(p)
        if len(products) >= max_products:
            break
    return products


# ── Navigation / categories ───────────────────────────────────────────────────

def _extract_nav(soup: BeautifulSoup, base_url: str) -> tuple[list[CategoryNode], list[dict]]:
    """Return (category_tree, flat_nav_links)."""
    nav_links: list[dict] = []
    categories: list[CategoryNode] = []
    seen: set[str] = set()

    # Try to find nav / header / menu elements
    nav_el = (
        soup.find("nav", attrs={"aria-label": re.compile("main|primary|category", re.I)})
        or soup.find("nav")
        or soup.find(id=re.compile("nav|menu|header", re.I))
        or soup.header
    )
    if not nav_el:
        return categories, nav_links

    for a in nav_el.find_all("a", href=True):
        text = _clean(a.get_text())
        href = _abs(base_url, str(a["href"]))
        if not text or not href or text in seen:
            continue
        seen.add(text)
        nav_links.append({"title": text, "url": href})

        # Check for a dropdown / sub-menu sibling
        parent = a.find_parent(["li", "div"])
        children: list[CategoryNode] = []
        if parent:
            sub = parent.find(["ul", "div"], class_=re.compile("sub|drop|child|mega", re.I))
            if sub:
                for sub_a in sub.find_all("a", href=True):
                    sub_text = _clean(sub_a.get_text())
                    sub_href = _abs(base_url, str(sub_a["href"]))
                    if sub_text and sub_href:
                        children.append(CategoryNode(title=sub_text, url=sub_href))
        categories.append(CategoryNode(title=text, url=href, children=children))

    return categories, nav_links


def _extract_site_info(soup: BeautifulSoup, base_url: str) -> SiteInfo:
    title = _clean(soup.title.string if soup.title else None)
    description = None
    meta_desc = soup.find("meta", attrs={"name": "description"})
    if meta_desc:
        description = _clean(str(meta_desc.get("content", "")))

    logo_url = None
    for sel in ["header img", "a[href='/'] img", ".logo img", "#logo img"]:
        el = soup.select_one(sel)
        if el:
            src = el.get("src") or el.get("data-src") or ""
            if src:
                logo_url = _abs(base_url, str(src))
                break

    categories, nav_links = _extract_nav(soup, base_url)
    return SiteInfo(
        url=base_url,
        title=title,
        description=description,
        logo_url=logo_url,
        categories=categories,
        nav_links=nav_links,
    )


# ── Main scrape functions ─────────────────────────────────────────────────────

async def _goto_resilient(page, url: str, wait_for: str, timeout_ms: int):
    """Try networkidle first; fall back to load, then domcontentloaded."""
    strategies = [wait_for] if wait_for != "networkidle" else ["networkidle", "load", "domcontentloaded"]
    last_exc = None
    for strategy in strategies:
        try:
            await page.goto(url, wait_until=strategy, timeout=timeout_ms)
            return
        except Exception as e:
            last_exc = e
            continue
    raise last_exc  # type: ignore


async def scrape_listing(
    url: str,
    max_products: int = 100,
    scroll: bool = True,
    wait_for: str = "networkidle",
    timeout_ms: int = 60_000,
) -> ScrapeResult:
    ctx, page = await new_page(timeout_ms)
    try:
        await _goto_resilient(page, url, wait_for, timeout_ms)
        if scroll:
            await auto_scroll(page)
        html = await page.content()
    except Exception as e:
        return ScrapeResult(status="error", url=url, message=str(e))
    finally:
        await ctx.close()

    soup = BeautifulSoup(html, "lxml")
    products: list[Product] = []

    # 1. Try JSON-LD first (most reliable)
    for node in _parse_jsonld(soup):
        if isinstance(node, dict) and node.get("@type") == "ItemList":
            for item in node.get("itemListElement", []):
                p = _product_from_jsonld(item.get("item", item), url)
                if p:
                    products.append(p)

    # 2. Fall back to HTML heuristics
    if not products:
        products = _extract_product_cards(soup, url, max_products)

    # Also extract site info
    site_info = _extract_site_info(soup, url)

    return ScrapeResult(
        status="ok",
        url=url,
        products=products[:max_products],
        site_info=site_info,
        raw_html_preview=html[:2000],
    )


async def scrape_product_detail(
    url: str,
    scroll: bool = True,
    wait_for: str = "networkidle",
    timeout_ms: int = 60_000,
) -> ScrapeResult:
    ctx, page = await new_page(timeout_ms)
    try:
        await _goto_resilient(page, url, wait_for, timeout_ms)
        if scroll:
            await auto_scroll(page)
        html = await page.content()
    except Exception as e:
        return ScrapeResult(status="error", url=url, message=str(e))
    finally:
        await ctx.close()

    soup = BeautifulSoup(html, "lxml")
    product: Optional[Product] = None

    # 1. JSON-LD
    for node in _parse_jsonld(soup):
        if isinstance(node, dict):
            p = _product_from_jsonld(node, url)
            if p:
                product = p
                break

    # 2. OpenGraph fallback
    if not product:
        og = {}
        for tag in soup.find_all("meta", property=re.compile("^og:")):
            key = str(tag.get("property", ""))[3:]
            og[key] = str(tag.get("content", ""))
        if og.get("title"):
            images = []
            if og.get("image"):
                images.append(ProductImage(src=og["image"]))
            product = Product(
                title=_clean(og.get("title")),
                description=_clean(og.get("description")),
                images=images,
                url=url,
            )

    # 3. Bare HTML heuristic
    if not product:
        title_el = soup.find("h1")
        if title_el:
            title = _clean(title_el.get_text())
            price = None
            for sel in PRICE_SELECTORS:
                el = soup.select_one(sel)
                if el:
                    price = _find_price(el.get_text())
                    break
            images: list[ProductImage] = []
            for sel in IMAGE_SELECTORS:
                el = soup.select_one(sel)
                if el:
                    src = str(el.get("data-src") or el.get("src") or "")
                    if src and not src.startswith("data:"):
                        images.append(ProductImage(src=_abs(url, src) or src))
                    break
            product = Product(title=title, price=price, images=images, url=url)

    return ScrapeResult(
        status="ok",
        url=url,
        products=[product] if product else [],
        raw_html_preview=html[:2000],
    )


async def scrape_categories(
    url: str,
    wait_for: str = "networkidle",
    timeout_ms: int = 60_000,
) -> ScrapeResult:
    ctx, page = await new_page(timeout_ms)
    try:
        await _goto_resilient(page, url, wait_for, timeout_ms)
        html = await page.content()
    except Exception as e:
        return ScrapeResult(status="error", url=url, message=str(e))
    finally:
        await ctx.close()

    soup = BeautifulSoup(html, "lxml")
    site_info = _extract_site_info(soup, url)
    return ScrapeResult(status="ok", url=url, site_info=site_info)
