"""
Ashewa scraper — talks directly to https://api.ashewa.com/graphql/

No browser needed for product listings. Parse category/subcategory/parentCategory
slugs from the shop URL query string and call filterProducts.
"""
from __future__ import annotations

from typing import Any, Optional
from urllib.parse import urlparse, parse_qs

import httpx

from models import Product, ProductImage, CategoryNode, SiteInfo, ScrapeResult
from scrapers.generic import _clean, _find_price


GRAPHQL_URL = "https://api.ashewa.com/graphql/"
SITE_BASE = "https://www.ashewa.com"

PRODUCT_FIELDS = """
  id
  name
  nameSlug
  sellingPrice
  discount
  stockAmount
  thumbnail
  image
  smallDescription
  description
  category { name slugName }
  subcategory { name slugName }
  parentCategory { name slugName }
"""

FILTER_PRODUCTS_QUERY = f"""
query($filter: ProductSearchInput, $page: Int, $perPage: Int) {{
  filterProducts(filter: $filter, page: $page, perPage: $perPage) {{
    page
    pages
    hasNext
    totalObjects
    objects {{
      {PRODUCT_FIELDS}
    }}
  }}
}}
"""

CATEGORIES_QUERY = """
query {
  parentCategories {
    name
    slugName
    categorySet {
      name
      slugName
      subcategorySet {
        name
        slugName
      }
    }
  }
}
"""


async def _gql(query: str, variables: Optional[dict] = None, timeout: float = 30.0) -> dict:
    payload: dict[str, Any] = {"query": query}
    if variables is not None:
        payload["variables"] = variables
    headers = {
        "Content-Type": "application/json",
        "Accept": "application/json",
        "Origin": SITE_BASE,
        "Referer": f"{SITE_BASE}/",
        "User-Agent": (
            "Mozilla/5.0 (Linux; Android 12; Pixel 6) "
            "AppleWebKit/537.36 (KHTML, like Gecko) "
            "Chrome/120.0.0.0 Mobile Safari/537.36"
        ),
    }
    async with httpx.AsyncClient(timeout=timeout, follow_redirects=True) as client:
        r = await client.post(GRAPHQL_URL, json=payload, headers=headers)
        r.raise_for_status()
        data = r.json()
    if data.get("errors"):
        raise RuntimeError(f"GraphQL errors: {data['errors']}")
    return data.get("data") or {}


def _media(url: Optional[str]) -> Optional[str]:
    if not url:
        return None
    if url.startswith("http"):
        return url
    if url.startswith("/"):
        return f"https://api.ashewa.com{url}"
    return f"https://api.ashewa.com/media/{url}"


def _product_from_gql(item: dict) -> Optional[Product]:
    title = _clean(str(item.get("name") or ""))
    if not title:
        return None

    selling = item.get("sellingPrice")
    discount = item.get("discount") or 0
    price = _find_price(str(selling)) if selling is not None else None
    original_price = None
    if selling is not None and discount and float(discount) > 0:
        try:
            original_price = _find_price(str(float(selling) + float(discount)))
        except (TypeError, ValueError):
            pass

    images: list[ProductImage] = []
    for key in ("thumbnail", "image"):
        src = _media(item.get(key))
        if src:
            images.append(ProductImage(src=src, alt=title))

    slug = item.get("nameSlug") or ""
    prod_url = f"{SITE_BASE}/product/default/{slug}" if slug else None

    categories: list[str] = []
    for key in ("parentCategory", "category", "subcategory"):
        node = item.get(key)
        if isinstance(node, dict) and node.get("name"):
            categories.append(str(node["name"]))

    stock = item.get("stockAmount")
    in_stock = bool(stock and int(stock) > 0) if stock is not None else None

    return Product(
        title=title,
        price=price,
        original_price=original_price,
        discount=str(discount) if discount else None,
        currency="ETB",
        description=_clean(str(item.get("description") or item.get("smallDescription") or "")) or None,
        images=images,
        categories=categories,
        url=prod_url,
        slug=slug or None,
        in_stock=in_stock,
        sku=str(item.get("id") or "") or None,
    )


def _filter_from_url(url: str) -> dict:
    """Map shop URL query params → ProductSearchInput."""
    qs = parse_qs(urlparse(url).query)
    filt: dict[str, Any] = {}

    if qs.get("parentCategory"):
        filt["parentCategorySlug"] = qs["parentCategory"][0]
    if qs.get("category"):
        filt["categorySlug"] = qs["category"][0]
    if qs.get("subcategory"):
        filt["subCategorySlug"] = qs["subcategory"][0]
    if qs.get("name"):
        filt["name"] = qs["name"][0]

    # Bare homepage / shop with no filters → return empty filter (all products)
    return filt


def _build_category_tree(parents: list[dict]) -> list[CategoryNode]:
    tree: list[CategoryNode] = []
    for p in parents or []:
        p_slug = p.get("slugName") or ""
        cats: list[CategoryNode] = []
        for c in p.get("categorySet") or []:
            c_slug = c.get("slugName") or ""
            subs = [
                CategoryNode(
                    title=str(s.get("name") or ""),
                    url=f"{SITE_BASE}/shop/sidebar/3cols?category={c_slug}&subcategory={s.get('slugName')}",
                )
                for s in (c.get("subcategorySet") or [])
                if s.get("name")
            ]
            cats.append(
                CategoryNode(
                    title=str(c.get("name") or ""),
                    url=f"{SITE_BASE}/shop/sidebar/3cols?category={c_slug}",
                    children=subs,
                )
            )
        tree.append(
            CategoryNode(
                title=str(p.get("name") or ""),
                url=f"{SITE_BASE}/shop/sidebar/3cols?parentCategory={p_slug}",
                children=cats,
            )
        )
    return tree


async def scrape_ashewa_listing(
    url: str,
    max_products: int = 100,
    timeout_ms: int = 60_000,
) -> ScrapeResult:
    timeout = max(10.0, timeout_ms / 1000)
    filt = _filter_from_url(url)
    per_page = min(max_products, 50)
    products: list[Product] = []
    total = 0
    page = 1

    try:
        while len(products) < max_products:
            data = await _gql(
                FILTER_PRODUCTS_QUERY,
                {"filter": filt, "page": page, "perPage": per_page},
                timeout=timeout,
            )
            block = data.get("filterProducts") or {}
            total = block.get("totalObjects") or total
            for item in block.get("objects") or []:
                p = _product_from_gql(item)
                if p:
                    products.append(p)
                if len(products) >= max_products:
                    break
            if not block.get("hasNext"):
                break
            page += 1
            if page > 20:  # safety cap
                break
    except Exception as e:
        return ScrapeResult(status="error", url=url, message=str(e))

    # Category tree (best-effort; don't fail the whole scrape)
    site_info = SiteInfo(url=url, title="Ashewa.com", currency="ETB")
    try:
        cat_data = await _gql(CATEGORIES_QUERY, timeout=timeout)
        parents = cat_data.get("parentCategories") or []
        # parentCategories shape may vary — try fallback field names
        if not parents and "categories" in cat_data:
            parents = cat_data["categories"]
        tree = _build_category_tree(parents)
        site_info.categories = tree
        site_info.nav_links = [{"title": n.title, "url": n.url} for n in tree]
    except Exception:
        pass

    return ScrapeResult(
        status="ok",
        url=url,
        products=products[:max_products],
        site_info=site_info,
        message=f"GraphQL filterProducts: filter={filt}, total={total}, returned={len(products[:max_products])}",
    )


def is_ashewa_url(url: str) -> bool:
    host = urlparse(url).netloc.lower()
    return "ashewa.com" in host
