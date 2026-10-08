"""
HCommerce Web Scraper — FastAPI service
========================================
Endpoints
---------
POST /scrape/listing        Scrape a product listing / category page
POST /scrape/product        Scrape a single product detail page
POST /scrape/categories     Extract navigation & category tree from any URL
POST /scrape/site           Full site scan (listing + categories in one call)
GET  /health                Health check
GET  /docs                  Auto-generated Swagger UI (built-in)
"""

import contextlib
from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse

from models import (
    ScrapeResult,
    ProductListRequest,
    ProductDetailRequest,
    CategoryRequest,
    ScrapeRequest,
)
from scrapers.base import get_browser, close_browser
from scrapers.generic import scrape_listing, scrape_product_detail, scrape_categories
from scrapers.ashewa import scrape_ashewa_listing, is_ashewa_url


# ── Lifespan ──────────────────────────────────────────────────────────────────

@contextlib.asynccontextmanager
async def lifespan(app: FastAPI):
    """Browser is started lazily on first scrape request."""
    yield
    await close_browser()


# ── App ───────────────────────────────────────────────────────────────────────

app = FastAPI(
    title="HCommerce Web Scraper",
    description=(
        "Scrapes e-commerce sites and returns structured product, "
        "category, and site data ready to feed back into HCommerce."
    ),
    version="1.0.0",
    lifespan=lifespan,
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["*"],
    allow_headers=["*"],
)


# ── Routes ────────────────────────────────────────────────────────────────────

@app.get("/health")
async def health():
    return {"status": "ok"}


@app.post("/scrape/listing", response_model=ScrapeResult, summary="Scrape product listing page")
async def api_scrape_listing(req: ProductListRequest):
    """
    Scrape a product listing / category page.

    Returns all products found (up to `max_products`) with titles, prices,
    images, and URLs — plus the site navigation tree.

    **Example body:**
    ```json
    {
      "url": "https://www.example-shop.com/products",
      "max_products": 50,
      "scroll": true
    }
    ```
    """
    if is_ashewa_url(req.url):
        result = await scrape_ashewa_listing(
            url=req.url,
            max_products=req.max_products,
            timeout_ms=req.timeout_ms,
        )
    else:
        result = await scrape_listing(
            url=req.url,
            max_products=req.max_products,
            scroll=req.scroll,
            wait_for=req.wait_for,
            timeout_ms=req.timeout_ms,
        )
    if result.status == "error":
        raise HTTPException(status_code=502, detail=result.message)
    return result


@app.post("/scrape/product", response_model=ScrapeResult, summary="Scrape single product page")
async def api_scrape_product(req: ProductDetailRequest):
    """
    Scrape a single product detail page.

    Extracts full product details: title, price, description, images,
    variants, rating, stock status, brand, SKU.

    **Example body:**
    ```json
    {
      "url": "https://www.example-shop.com/products/awesome-widget"
    }
    ```
    """
    result = await scrape_product_detail(
        url=req.url,
        scroll=req.scroll,
        wait_for=req.wait_for,
        timeout_ms=req.timeout_ms,
    )
    if result.status == "error":
        raise HTTPException(status_code=502, detail=result.message)
    return result


@app.post("/scrape/categories", response_model=ScrapeResult, summary="Extract site category tree")
async def api_scrape_categories(req: CategoryRequest):
    """
    Extract the navigation / category tree from a site's homepage or any URL.

    Returns a nested category tree and flat nav links — useful for building
    your sidebar and main navigation.

    **Example body:**
    ```json
    {
      "url": "https://www.example-shop.com"
    }
    ```
    """
    result = await scrape_categories(
        url=req.url,
        wait_for=req.wait_for,
        timeout_ms=req.timeout_ms,
    )
    if result.status == "error":
        raise HTTPException(status_code=502, detail=result.message)
    return result


@app.post("/scrape/ashewa", response_model=ScrapeResult, summary="Scrape Ashewa.com product listing (JS-rendered)")
async def api_scrape_ashewa(req: ProductListRequest):
    """
    Ashewa-specific scraper. Waits for JS to inject product cards before parsing.

    **Example body:**
    ```json
    {
      "url": "https://www.ashewa.com/shop/sidebar/3cols?category=consumer-electronics",
      "max_products": 100
    }
    ```
    """
    result = await scrape_ashewa_listing(
        url=req.url,
        max_products=req.max_products,
        timeout_ms=req.timeout_ms,
    )
    if result.status == "error":
        raise HTTPException(status_code=502, detail=result.message)
    return result


@app.post("/scrape/site", response_model=ScrapeResult, summary="Full site scan (listing + categories)")
async def api_scrape_site(req: ProductListRequest):
    """
    Full site scan in one call:
    - Loads the URL
    - Extracts products (same as /scrape/listing)
    - Extracts the navigation / category tree (same as /scrape/categories)

    **Ashewa.com is auto-detected** and uses the JS/API interceptor scraper.

    **Example body:**
    ```json
    {
      "url": "https://www.ashewa.com/shop/sidebar/3cols?category=consumer-electronics",
      "max_products": 100,
      "scroll": true,
      "wait_for": "domcontentloaded",
      "timeout_ms": 60000
    }
    ```
    """
    if is_ashewa_url(req.url):
        result = await scrape_ashewa_listing(
            url=req.url,
            max_products=req.max_products,
            timeout_ms=req.timeout_ms,
        )
    else:
        result = await scrape_listing(
            url=req.url,
            max_products=req.max_products,
            scroll=req.scroll,
            wait_for=req.wait_for,
            timeout_ms=req.timeout_ms,
        )
    if result.status == "error":
        raise HTTPException(status_code=502, detail=result.message)
    return result
