from fastapi import APIRouter, Query, HTTPException
from typing import Optional
import pandas as pd
import os

router = APIRouter()
DATA_DIR = os.path.join(os.path.dirname(__file__), "..", "data")
PRODUCTS_CSV  = os.path.join(DATA_DIR, "products.csv")
SALES_CSV     = os.path.join(DATA_DIR, "sales.csv")
BATCHES_CSV   = os.path.join(DATA_DIR, "inventory_batches.csv")

CATEGORY_EMOJIS = {
    "Beauty & Hygiene": "💄",
    "Foodgrains, Oil & Masala": "🌾",
    "Snacks & Branded Foods": "🍪",
    "Beverages": "☕",
    "Bakery, Cakes & Dairy": "🥛",
    "Fruits & Vegetables": "🥦",
    "Cleaning & Household": "🧹",
    "Baby Care": "👶",
    "Eggs, Meat & Fish": "🥚",
    "Pet Care": "🐾",
    "Gourmet & World Food": "🌍",
    "Kitchen, Garden & Pets": "🍳",
}

CATEGORY_COLORS = {
    "Beauty & Hygiene": "#f43f5e",
    "Foodgrains, Oil & Masala": "#f59e0b",
    "Snacks & Branded Foods": "#8b5cf6",
    "Beverages": "#06b6d4",
    "Bakery, Cakes & Dairy": "#f97316",
    "Fruits & Vegetables": "#22c55e",
    "Cleaning & Household": "#3b82f6",
    "Baby Care": "#ec4899",
    "Eggs, Meat & Fish": "#ef4444",
    "Pet Care": "#84cc16",
    "Gourmet & World Food": "#a78bfa",
    "Kitchen, Garden & Pets": "#14b8a6",
}

# Unsplash category keywords for product images
# sig= parameter makes the image deterministic per SKU while staying category-relevant
import re as _re

# Category fallback keywords (used when product name yields nothing useful)
CATEGORY_IMG_KEYWORDS = {
    "Beauty & Hygiene":        "beauty,cosmetics",
    "Foodgrains, Oil & Masala":"grains,spices",
    "Snacks & Branded Foods":  "snacks,chips",
    "Beverages":               "drinks,juice",
    "Bakery, Cakes & Dairy":   "bakery,bread",
    "Fruits & Vegetables":     "vegetables,fruits",
    "Cleaning & Household":    "cleaning,household",
    "Baby Care":               "baby,infant",
    "Eggs, Meat & Fish":       "meat,fish",
    "Pet Care":                "pet,dog",
    "Gourmet & World Food":    "gourmet,food",
    "Kitchen, Garden & Pets":  "kitchen,cooking",
}

# Words that don't add useful search signal
_STOP = {
    "and","with","for","the","a","an","of","in","ml","gm","kg","g","l","ltr",
    "pack","no","from","by","to","on","at","is","as","be","or","it","its",
    "all","new","free","best","top","pure","plus","pro","max","mini","size",
    "super","ultra","extra","value","set","combo","kit","box","bottle","can",
    "jar","pouch","sachet","bag","piece","pcs","pc","units","unit","nos",
}


def get_image_url(sku: str, category: str, name: str = "") -> str:
    """Return a loremflickr URL unique per product, using its name as keyword."""
    # Extract up to 2 meaningful words from the product name
    tokens = _re.sub(r"[^\w\s]", " ", name).split()
    words = [
        w.lower() for w in tokens
        if w.lower() not in _STOP and len(w) > 2 and not w.isdigit()
    ][:2]

    if words:
        keyword = ",".join(words)
    else:
        keyword = CATEGORY_IMG_KEYWORDS.get(category, "grocery,food")

    # Numeric part of SKU as lock → same keyword+lock always returns the same photo
    lock = "".join(filter(str.isdigit, sku)) or "1000"
    return f"https://loremflickr.com/400/400/{keyword}?lock={lock}"


def get_fefo_expiry_map() -> dict:
    """Return {sku: earliest_active_expiry_date_str} using FEFO logic.

    Only considers batches that are active, have quantity > 0, and have not
    yet expired.  The *earliest* expiry date across those batches is what the
    customer will receive first (First Expiry, First Out).
    """
    if not os.path.exists(BATCHES_CSV):
        return {}
    try:
        bdf = pd.read_csv(BATCHES_CSV, dtype=str).fillna("")
        bdf = bdf[bdf["status"].str.lower() == "active"].copy()
        bdf["quantity"] = pd.to_numeric(bdf["quantity"], errors="coerce").fillna(0)
        bdf = bdf[bdf["quantity"] > 0]
        bdf["expiry_date"] = pd.to_datetime(bdf["expiry_date"], errors="coerce")
        today = pd.Timestamp.now().normalize()
        bdf = bdf[bdf["expiry_date"] >= today]
        if bdf.empty:
            return {}
        earliest = bdf.groupby("sku")["expiry_date"].min()
        return {sku: dt.strftime("%Y-%m-%d") for sku, dt in earliest.items()}
    except Exception:
        return {}


def load_products_df():
    if not os.path.exists(PRODUCTS_CSV):
        return pd.DataFrame()
    return pd.read_csv(PRODUCTS_CSV, dtype=str).fillna("")


def get_sales_counts(days: int = None) -> dict:
    """Sum quantity sold per SKU. If days is set, restrict to that recent window."""
    if not os.path.exists(SALES_CSV):
        return {}
    try:
        sdf = pd.read_csv(SALES_CSV)
        sdf["Quantity"] = pd.to_numeric(sdf["Quantity"], errors="coerce").fillna(0)
        if days:
            sdf["InvoiceDate"] = pd.to_datetime(sdf["InvoiceDate"], errors="coerce")
            cutoff = pd.Timestamp.now() - pd.Timedelta(days=days)
            recent = sdf[sdf["InvoiceDate"] >= cutoff]
            if not recent.empty:
                return recent.groupby("StockCode")["Quantity"].sum().to_dict()
            # No recent data — fall back to all-time so the section isn't empty
        return sdf.groupby("StockCode")["Quantity"].sum().to_dict()
    except Exception:
        return {}


def get_active_discount_map() -> dict:
    """Load manager-approved active discounts, running auto-deactivation first.
    Returns {sku: {discount_percent, original_price, discounted_price}}."""
    try:
        import json as _json
        dfile = os.path.join(DATA_DIR, "discounts.json")
        if not os.path.exists(dfile):
            return {}
        with open(dfile, "r") as f:
            store = _json.load(f)

        # Run lightweight auto-deactivation so expired/sold-out discounts never
        # reach customers even if no manager has visited the manager dashboard.
        from routes.discounts import check_auto_deactivate, save_store as _save
        if check_auto_deactivate(store):
            _save(store)

        from datetime import datetime as _dt
        today_str = _dt.now().date().isoformat()
        result = {}
        for ad in store.get("active_discounts", []):
            if ad.get("status") != "active":
                continue
            end = ad.get("scheduled_end") or ""
            if end and end < today_str:
                continue
            sku = str(ad.get("sku", "")).strip().upper()
            if sku not in result or ad["discount_percent"] > result[sku]["discount_percent"]:
                result[sku] = {
                    "discount_percent": ad["discount_percent"],
                    "original_price":   ad["original_price"],
                    "discounted_price": ad["discounted_price"],
                }
        return result
    except Exception:
        return {}


def enrich(row: dict, sales_counts: dict, discount_overrides: dict = {}) -> dict:
    sku = str(row.get("sku", ""))
    name = str(row.get("name", ""))
    category = str(row.get("category", ""))
    supplier = str(row.get("supplier_name", ""))
    notes = str(row.get("notes", ""))

    try:
        price = float(row.get("unit_price", 0) or 0)
    except Exception:
        price = 0.0
    try:
        stock = int(float(row.get("current_stock", 0) or 0))
    except Exception:
        stock = 0

    brand = supplier.replace(" Distributors", "").replace(" Suppliers", "").replace(" Wholesale", "").strip() or "SIRA Brand"

    # Deterministic rating from SKU hash (3.5–4.9)
    h = sum(ord(c) for c in sku)
    rating = round(3.5 + (h % 15) / 10, 1)
    rating_count = 50 + (h % 300)

    # Only manager-approved real discounts are shown to customers now.
    if sku.upper() in discount_overrides:
        override = discount_overrides[sku.upper()]
        discount_pct   = override["discount_percent"]
        original_price = price                                        # CSV unit_price = real original
        price          = round(price * (1 - discount_pct / 100), 2)  # customer pays less
    else:
        discount_pct = 0
        original_price = price

    sales_qty = float(sales_counts.get(sku, 0))

    return {
        "sku": sku,
        "name": name,
        "brand": brand,
        "category": category,
        "category_color": CATEGORY_COLORS.get(category, "#6366f1"),
        "category_emoji": CATEGORY_EMOJIS.get(category, "📦"),
        "description": notes[:600] if notes else f"Premium quality {name} from {brand}.",
        "price": round(price, 2),
        "original_price": round(original_price, 2),
        "discount_percent": discount_pct,
        "current_stock": stock,
        "in_stock": stock > 0,
        "rating": rating,
        "rating_count": rating_count,
        "sales_count": int(sales_qty),
        "image_url": "",
        "badge": "",
    }


@router.get("/")
async def list_products(
    search: Optional[str] = None,
    category: Optional[str] = None,
    brand: Optional[str] = None,
    min_price: Optional[float] = None,
    max_price: Optional[float] = None,
    sort: str = "name",
    page: int = 1,
    per_page: int = 20,
    in_stock_only: bool = False,
    discounted_only: bool = False,
):
    df = load_products_df()
    if df.empty:
        return {"products": [], "total": 0, "page": page, "per_page": per_page, "total_pages": 0}

    sales_counts      = get_sales_counts()
    discount_overrides = get_active_discount_map()
    products = [enrich(row, sales_counts, discount_overrides) for _, row in df.iterrows()]

    # Filters
    if search:
        ql = search.lower().strip()
        qwords = ql.split()

        def _score(p: dict) -> int:
            name_l = p["name"].lower()
            cat_l  = p["category"].lower()
            desc_l = p["description"].lower()
            brand_l = p["brand"].lower()
            # Exact substring (highest priority)
            if ql in name_l:  return 100
            if ql in brand_l: return 80
            if ql in cat_l:   return 60
            # All words in name
            if all(w in name_l for w in qwords): return 70
            # Word-level prefix / presence scoring
            name_tokens = name_l.split()
            s = 0
            for w in qwords:
                if any(t.startswith(w) for t in name_tokens): s += 30
                elif w in name_l:  s += 20
                elif w in cat_l:   s += 10
                elif w in desc_l:  s +=  5
                elif w in brand_l: s +=  8
            return s

        products = [(p, _score(p)) for p in products]
        products = [(p, s) for p, s in products if s > 0]
        products.sort(key=lambda x: -x[1])
        products = [p for p, _ in products]
    if category:
        products = [p for p in products if p["category"].lower() == category.lower()]
    if brand:
        products = [p for p in products if p["brand"].lower() == brand.lower()]
    if min_price is not None:
        products = [p for p in products if p["price"] >= min_price]
    if max_price is not None:
        products = [p for p in products if p["price"] <= max_price]
    if in_stock_only:
        products = [p for p in products if p["in_stock"]]
    if discounted_only:
        products = [p for p in products if p["discount_percent"] > 0]

    # Sort — when a search is active, relevance has already ordered products;
    # only re-sort for explicit non-default user choices so results stay relevant.
    if not search or sort not in ("name", ""):
        sort_map = {
            "price_asc":  lambda x: x["price"],
            "price_desc": lambda x: -x["price"],
            "rating":     lambda x: -x["rating"],
            "trending":   lambda x: -x["sales_count"],
            "discount":   lambda x: -x["discount_percent"],
            "name":       lambda x: x["name"].lower(),
        }
        products.sort(key=sort_map.get(sort, sort_map["name"]))

    total = len(products)
    total_pages = max(1, -(-total // per_page))
    start = (page - 1) * per_page

    return {
        "products": products[start: start + per_page],
        "total": total,
        "page": page,
        "per_page": per_page,
        "total_pages": total_pages,
    }


@router.get("/categories")
async def get_categories():
    df = load_products_df()
    if df.empty:
        return []
    cats = df["category"].dropna().unique().tolist()
    result = []
    for cat in sorted(cats):
        if cat.strip():
            result.append({
                "name": cat,
                "emoji": CATEGORY_EMOJIS.get(cat, "📦"),
                "color": CATEGORY_COLORS.get(cat, "#6366f1"),
            })
    return result


@router.get("/brands")
async def get_brands():
    df = load_products_df()
    if df.empty:
        return []
    brands = set()
    for sup in df["supplier_name"].dropna().unique():
        b = sup.replace(" Distributors", "").replace(" Suppliers", "").replace(" Wholesale", "").strip()
        if b:
            brands.add(b)
    return sorted(brands)


@router.get("/trending")
async def get_trending(limit: int = 12):
    df = load_products_df()
    if df.empty:
        return []
    # Use last 60 days of sales to surface recently popular items
    sc = get_sales_counts(days=60)
    dm = get_active_discount_map()
    products = [enrich(row, sc, dm) for _, row in df.iterrows()]
    products = [p for p in products if p["in_stock"]]
    products.sort(key=lambda x: -x["sales_count"])
    for p in products[:limit]:
        p["badge"] = "🔥 Trending"
    return products[:limit]


@router.get("/best-selling")
async def get_best_selling(limit: int = 12):
    df = load_products_df()
    if df.empty:
        return []
    sc = get_sales_counts()
    dm = get_active_discount_map()
    products = [enrich(row, sc, dm) for _, row in df.iterrows()]
    products = [p for p in products if p["in_stock"]]
    products.sort(key=lambda x: -x["sales_count"])
    result = products[3: 3 + limit] if len(products) > 3 else products[:limit]
    for p in result:
        p["badge"] = "⭐ Best Seller"
    return result


@router.get("/latest")
async def get_latest(limit: int = 12):
    df = load_products_df()
    if df.empty:
        return []
    sc = get_sales_counts()
    dm = get_active_discount_map()
    products = [enrich(row, sc, dm) for _, row in df.iterrows()]
    products = [p for p in products if p["in_stock"]]
    products.sort(key=lambda x: -x["rating"])
    for p in products[:limit]:
        p["badge"] = "🆕 New Arrival"
    return products[:limit]


@router.get("/discounted")
async def get_discounted(limit: int = 12):
    df = load_products_df()
    if df.empty:
        return []
    sc = get_sales_counts()
    dm = get_active_discount_map()
    products = [enrich(row, sc, dm) for _, row in df.iterrows()]
    products = [p for p in products if p["discount_percent"] > 0 and p["in_stock"]]
    products.sort(key=lambda x: -x["discount_percent"])
    for p in products[:limit]:
        p["badge"] = f"🏷️ {p['discount_percent']}% OFF"
    return products[:limit]




@router.get("/search-suggestions")
async def search_suggestions(q: str = "", limit: int = 8):
    q = q.strip()          # normalise before length check
    if len(q) < 2:
        return []
    df = load_products_df()
    if df.empty:
        return []

    ql = q.lower().strip()
    qwords = ql.split()
    scored: list[dict] = []
    seen: set = set()

    for _, row in df.iterrows():
        name     = str(row.get("name", "")).strip()
        category = str(row.get("category", "")).strip()
        name_l   = name.lower()
        cat_l    = category.lower()

        if not name or name in seen:
            continue

        score = 0
        # Exact prefix match
        if name_l.startswith(ql):
            score += 120
        # All query words present in name
        elif all(w in name_l for w in qwords):
            score += 80
        else:
            # Per-word prefix match inside name tokens
            name_tokens = name_l.split()
            for qw in qwords:
                if any(nt.startswith(qw) for nt in name_tokens):
                    score += 40
                elif qw in name_l:
                    score += 25
            # Category / description fallback
            if ql in cat_l:
                score += 15
            elif any(w in cat_l for w in qwords):
                score += 8

        if score > 0:
            seen.add(name)
            scored.append({"text": name, "category": category, "score": score})

    scored.sort(key=lambda x: (-x["score"], x["text"]))
    return [{"text": s["text"], "category": s["category"]} for s in scored[:limit]]


@router.get("/{sku}")
async def get_product(sku: str):
    df = load_products_df()
    if df.empty:
        raise HTTPException(404, "Product not found")

    rows = df[df["sku"].astype(str).str.strip() == sku.strip()]
    if rows.empty:
        raise HTTPException(404, "Product not found")

    sc = get_sales_counts()
    dm = get_active_discount_map()
    expiry_map = get_fefo_expiry_map()
    product = enrich(rows.iloc[0].to_dict(), sc, dm)
    product["expiry_date"] = expiry_map.get(sku.strip(), "")

    # Similar products (same category, different SKU)
    all_products = [enrich(r, sc, dm) for _, r in df.iterrows()]
    similar = [p for p in all_products if p["category"] == product["category"] and p["sku"] != sku and p["in_stock"]]
    similar.sort(key=lambda x: -x["rating"])
    product["similar"] = similar[:8]

    # Frequently bought together
    other_cat = [p for p in all_products if p["category"] != product["category"] and p["in_stock"]]
    other_cat.sort(key=lambda x: -x["sales_count"])
    product["frequently_bought_together"] = other_cat[:4]

    # 90-day sales for a realistic "sold recently" figure
    sc_90d = get_sales_counts(days=90)
    sold_90d = int(sc_90d.get(sku.strip(), product["sales_count"]))
    product["sales_count_90d"] = sold_90d

    # AI explanation — uses only real data: category and actual 90-day sales
    product["ai_explanation"] = (
        f"A popular pick in the {product['category']} category, "
        f"consistently chosen by SIRA customers. "
        f"{sold_90d} units sold in the past 90 days."
    )

    # Healthy alternatives (if food/beverage category)
    food_cats = {"Foodgrains, Oil & Masala", "Snacks & Branded Foods", "Beverages", "Bakery, Cakes & Dairy", "Fruits & Vegetables"}
    if product["category"] in food_cats:
        alts = [p for p in all_products if p["category"] in food_cats and p["sku"] != sku and p["in_stock"]]
        alts.sort(key=lambda x: -x["rating"])
        product["healthy_alternatives"] = alts[:4]
    else:
        product["healthy_alternatives"] = []

    return product
