from pydantic import BaseModel, HttpUrl
from typing import Optional


# ── Request models ────────────────────────────────────────────────────────────

class ScrapeRequest(BaseModel):
    url: str
    wait_for: str = "networkidle"       # "load" | "domcontentloaded" | "networkidle"
    scroll: bool = True                 # auto-scroll to trigger lazy-loads
    timeout_ms: int = 60_000


class ProductListRequest(ScrapeRequest):
    """Scrape a product listing / category page."""
    max_products: int = 100
    next_page_selector: Optional[str] = None    # CSS selector for "next page" button


class ProductDetailRequest(ScrapeRequest):
    """Scrape a single product detail page."""
    pass


class CategoryRequest(ScrapeRequest):
    """Extract site-wide category / navigation tree."""
    pass


# ── Response models ───────────────────────────────────────────────────────────

class ProductImage(BaseModel):
    src: str
    alt: Optional[str] = None


class ProductVariant(BaseModel):
    name: str
    options: list[str]


class Product(BaseModel):
    title: Optional[str] = None
    price: Optional[str] = None
    original_price: Optional[str] = None
    discount: Optional[str] = None
    currency: Optional[str] = None
    sku: Optional[str] = None
    brand: Optional[str] = None
    rating: Optional[float] = None
    review_count: Optional[int] = None
    in_stock: Optional[bool] = None
    description: Optional[str] = None
    images: list[ProductImage] = []
    variants: list[ProductVariant] = []
    categories: list[str] = []
    tags: list[str] = []
    url: Optional[str] = None
    slug: Optional[str] = None


class CategoryNode(BaseModel):
    title: str
    url: Optional[str] = None
    children: list["CategoryNode"] = []

CategoryNode.model_rebuild()


class SiteInfo(BaseModel):
    url: str
    title: Optional[str] = None
    description: Optional[str] = None
    logo_url: Optional[str] = None
    currency: Optional[str] = None
    categories: list[CategoryNode] = []
    nav_links: list[dict] = []


class ScrapeResult(BaseModel):
    status: str                         # "ok" | "error"
    url: str
    message: Optional[str] = None
    products: list[Product] = []
    site_info: Optional[SiteInfo] = None
    raw_html_preview: Optional[str] = None   # first 2000 chars for debugging
