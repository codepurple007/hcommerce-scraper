# HCommerce Web Scraper

A standalone FastAPI service that scrapes any e-commerce site and returns structured data (products, categories, site info) ready to feed back into HCommerce.

## Stack

| Part | Tech |
|------|------|
| API | **FastAPI** + Uvicorn |
| Browser | **Playwright** (Chromium, headless) |
| Parsing | **BeautifulSoup4** + lxml |
| Models | **Pydantic v2** |

---

## Setup

```bash
cd scraper

# Create and activate a virtual environment
python3 -m venv .venv
source .venv/bin/activate

# Install Python deps
pip install -r requirements.txt

# Install Playwright's Chromium browser
playwright install chromium
playwright install-deps chromium   # installs OS-level deps (run as root if needed)

# Start the server
uvicorn main:app --host 0.0.0.0 --port 8000 --reload
```

Swagger UI: http://localhost:8000/docs

---

## Endpoints

| Method | Path | What it does |
|--------|------|--------------|
| `POST` | `/scrape/site` | **Best starting point** — products + categories from any URL |
| `POST` | `/scrape/listing` | Scrape a product listing / category page |
| `POST` | `/scrape/product` | Scrape a single product detail page |
| `POST` | `/scrape/categories` | Extract nav / category tree from any URL |
| `GET`  | `/health` | Health check |
| `GET`  | `/docs` | Swagger UI |

---

## Quick start — scrape any site

```bash
# Full site scan (products + categories in one call)
curl -X POST http://localhost:8000/scrape/site \
  -H "Content-Type: application/json" \
  -d '{
    "url": "https://www.somestore.com/collections/all",
    "max_products": 100,
    "scroll": true,
    "wait_for": "networkidle",
    "timeout_ms": 45000
  }'

# Single product
curl -X POST http://localhost:8000/scrape/product \
  -H "Content-Type: application/json" \
  -d '{"url": "https://www.somestore.com/products/some-product"}'

# Category / nav tree only
curl -X POST http://localhost:8000/scrape/categories \
  -H "Content-Type: application/json" \
  -d '{"url": "https://www.somestore.com"}'
```

---

## Response shape

```jsonc
{
  "status": "ok",
  "url": "https://...",
  "products": [
    {
      "title": "Blue Widget",
      "price": "$29.99",
      "original_price": "$49.99",
      "currency": "USD",
      "sku": "BW-001",
      "brand": "WidgetCo",
      "rating": 4.5,
      "review_count": 312,
      "in_stock": true,
      "description": "...",
      "images": [{ "src": "https://...", "alt": "..." }],
      "variants": [{ "name": "Color", "options": ["Blue", "Red"] }],
      "categories": ["Widgets", "Home"],
      "url": "https://..."
    }
  ],
  "site_info": {
    "url": "https://...",
    "title": "Some Store",
    "description": "...",
    "logo_url": "https://...",
    "currency": "USD",
    "categories": [
      {
        "title": "Women",
        "url": "/collections/women",
        "children": [
          { "title": "Dresses", "url": "/collections/dresses" }
        ]
      }
    ],
    "nav_links": [
      { "title": "Women", "url": "/collections/women" }
    ]
  }
}
```

---

## Notes

- Uses a **mobile Chrome user-agent** (less likely to be blocked than desktop)
- Automatically scrolls to trigger lazy-loaded products
- Respects `robots.txt` is **not** enforced — only scrape sites you have permission to
- For sites with heavy JS/SPAs (Shopify, etc.) use `"wait_for": "networkidle"` (default)
- For static HTML sites use `"wait_for": "domcontentloaded"` for speed
