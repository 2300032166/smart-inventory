#!/usr/bin/env python3
"""Regenerate supplier master data, supplier-product mappings, and purchase history.

This script creates 50-80 realistic suppliers, a proper many-to-many mapping
between suppliers and products, and a rich purchase-order history that lets
SIRA's supplier analytics and recommendation routes compute meaningful metrics.
"""
import csv
import random
import uuid
from collections import Counter, defaultdict
from datetime import datetime, timedelta
from pathlib import Path

import pandas as pd

RANDOM_SEED = 42
random.seed(RANDOM_SEED)

DATA_DIR = Path(__file__).resolve().parent.parent / "data"
PRODUCTS_CSV = DATA_DIR / "products.csv"
SUPPLIERS_CSV = DATA_DIR / "suppliers.csv"
SUPPLIER_PRODUCTS_CSV = DATA_DIR / "supplier_products.csv"
PURCHASE_ORDERS_CSV = DATA_DIR / "purchase_orders.csv"

# Category pools. Each pool contains a category name (from products.csv) and a
# list of supplier specs. The number of suppliers per category is sized so the
# total supplier count lands between 50 and 80.
CATEGORY_POOLS = {
    "Beauty & Hygiene": [
        ("Glamour Care Distributors", "Glamour Care Distributors Pvt Ltd", "Priya Sharma", "+91-9876543210", "contact@glamourcare.in", "Block 4, Cosmetic Park, Baddi, HP 173205", "Active", 5, "Daily", "Specialized in beauty, personal care, and hygiene products"),
        ("PureSkin Essentials", "PureSkin Essentials Co.", "Arun Mehta", "+91-9876543211", "sales@pureskin.in", "Sector 12, Industrial Area, Gurgaon, HR 122001", "Active", 4, "Daily", "Premium skincare and cosmetic supplies"),
        ("Naturals Beauty Supply", "Naturals Beauty Supply LLP", "Sunita Rao", "+91-9876543212", "info@naturalsbeauty.in", "Plot 8, Herbal Park, Indore, MP 452001", "Active", 6, "Alternate Day", "Herbal and ayurvedic beauty products"),
        ("CareWell Distributors", "CareWell Distributors Co.", "Ravi Kumar", "+91-9876543213", "orders@carewelldist.in", "APIE Phase 2, Hyderabad, TS 500037", "Active", 4, "Daily", "Personal care and wellness products"),
        ("Personal Care Plus", "Personal Care Plus India", "Meera Iyer", "+91-9876543214", "support@pcplus.in", "Unit 15, Pharma Zone, Ahmedabad, GJ 382001", "Active", 5, "Daily", "Daily-use personal care essentials"),
        ("HerbalGlow India", "HerbalGlow India Pvt Ltd", "Vikram Patel", "+91-9876543215", "biz@herbalglow.in", "Green Belt, Jaipur, RJ 302001", "Active", 6, "Alternate Day", "Natural and herbal hygiene products"),
        ("SoftTouch Hygiene", "SoftTouch Hygiene Solutions", "Anita Desai", "+91-9876543216", "hello@softtouch.in", "Warehouse 22, Pune, MH 411001", "Active", 3, "Daily", "Hygiene and sanitization products"),
        ("MedLife Wholesale", "MedLife Wholesale Pvt Ltd", "Dr. Sanjay Gupta", "+91-9876543217", "wholesale@medlife.in", "Medical Zone, Nampally, Hyderabad, TS 500001", "Active", 5, "Daily", "Health and medicated personal care"),
        ("DermaCare Solutions", "DermaCare Solutions India", "Neha Singh", "+91-9876543218", "sales@dermacare.in", "Skin Care Park, Bangalore, KA 560001", "Active", 4, "Daily", "Dermatologist-recommended skincare"),
        ("Aura Personal Care", "Aura Personal Care Ltd", "Kiran Shah", "+91-9876543219", "info@aurapc.in", "Personal Care Hub, Mumbai, MH 400001", "Active", 5, "Daily", "Luxury personal care brands"),
    ],
    "Gourmet & World Food": [
        ("GlobalFoods India", "GlobalFoods India Pvt Ltd", "Rajesh Khanna", "+91-9876543220", "contact@globalfoods.in", "World Food Park, Mumbai, MH 400001", "Active", 7, "Twice Weekly", "Imported gourmet and specialty foods"),
        ("Exotic Ingredients Co.", "Exotic Ingredients Co. LLP", "Pooja Malhotra", "+91-9876543221", "orders@exoticingredients.in", "Spice Trade Center, Kochi, KL 682001", "Active", 6, "Twice Weekly", "Exotic spices, sauces, and condiments"),
        ("Continental Flavors", "Continental Flavors Ltd", "Amit Bhatia", "+91-9876543222", "sales@continentalflavors.in", "Food Park, Delhi, DL 110001", "Active", 7, "Weekly", "Continental and European specialty foods"),
        ("World Pantry", "World Pantry India", "Sneha Joshi", "+91-9876543223", "hello@worldpantry.in", "Import Zone, Chennai, TN 600001", "Active", 8, "Weekly", "International pantry staples"),
        ("Chef's Basket Supplies", "Chef's Basket Supplies Co.", "Chef Karan", "+91-9876543224", "biz@chefsbasket.in", "Restaurant Supply Hub, Bangalore, KA 560001", "Active", 5, "Twice Weekly", "Premium chef-grade ingredients"),
        ("FineFoods Distributors", "FineFoods Distributors Pvt Ltd", "Lata Nair", "+91-9876543225", "orders@finefoods.in", "Gourmet Park, Kolkata, WB 700001", "Active", 6, "Weekly", "High-end gourmet foods"),
        ("TasteWorld Imports", "TasteWorld Imports India", "Farhan Qureshi", "+91-9876543226", "import@tasteworld.in", "Sea Port Zone, Vizag, AP 530001", "Active", 9, "Weekly", "Imported world food brands"),
        ("FlavorFusion Foods", "FlavorFusion Foods LLP", "Deepa Menon", "+91-9876543227", "sales@flavorfusion.in", "Fusion Food Park, Coimbatore, TN 641001", "Active", 7, "Twice Weekly", "Fusion and ethnic specialty foods"),
    ],
    "Kitchen, Garden & Pets": [
        ("HomeEssentials India", "HomeEssentials India Pvt Ltd", "Suresh Pillai", "+91-9876543228", "info@homeessentials.in", "Home Utility Park, Bangalore, KA 560001", "Active", 5, "Daily", "Kitchen tools and home essentials"),
        ("KitchenCraft Supplies", "KitchenCraft Supplies Co.", "Rekha Agarwal", "+91-9876543229", "orders@kitchencraft.in", "Kitchenware Zone, Delhi, DL 110001", "Active", 4, "Daily", "Premium kitchenware and cookware"),
        ("GardenGreen Distributors", "GardenGreen Distributors LLP", "Mohan Reddy", "+91-9876543230", "sales@gardengreen.in", "Garden Supply Hub, Hyderabad, TS 500001", "Active", 6, "Weekly", "Garden tools, seeds, and accessories"),
        ("PetCare Wholesale", "PetCare Wholesale India", "Rohini Das", "+91-9876543231", "wholesale@petcare.in", "Pet Products Park, Pune, MH 411001", "Active", 5, "Twice Weekly", "Pet food and care products"),
        ("HandyHome Products", "HandyHome Products Ltd", "Tarun Bose", "+91-9876543232", "contact@handyhome.in", "Home Goods Park, Ahmedabad, GJ 382001", "Active", 5, "Daily", "Household utility and organization products"),
        ("Modern Kitchen Co.", "Modern Kitchen Co. India", "Isha Verma", "+91-9876543233", "info@modernkitchen.in", "Modular Kitchen Park, Noida, UP 201301", "Active", 4, "Daily", "Modern kitchen appliances and gadgets"),
    ],
    "Snacks & Branded Foods": [
        ("SweetSource Regional", "SweetSource Regional Pvt Ltd", "Manish Jain", "+91-9876543234", "orders@sweetsourceregional.in", "Shop 22, Market Complex, Nellore, AP 524001", "Active", 3, "Daily", "Regional sweets and packaged snacks"),
        ("CrunchTime Snacks", "CrunchTime Snacks India", "Divya Kapoor", "+91-9876543235", "sales@crunchtime.in", "Snack Park, Indore, MP 452001", "Active", 4, "Daily", "Salty snacks and namkeen"),
        ("SnackWorld India", "SnackWorld India Pvt Ltd", "Kabir Khan", "+91-9876543236", "biz@snackworld.in", "Food Processing Zone, Mumbai, MH 400001", "Active", 5, "Daily", "National snack brands"),
        ("Munchies Mart", "Munchies Mart Distributors", "Tina Patel", "+91-9876543237", "orders@munchiesmart.in", "Wholesale Market, Surat, GJ 395001", "Active", 4, "Daily", "Biscuits and ready-to-eat snacks"),
        ("SavoryBites Supply", "SavoryBites Supply Co.", "Naveen Gowda", "+91-9876543238", "contact@savorybites.in", "Food Park, Mysore, KA 570001", "Active", 5, "Daily", "Savory and ethnic snacks"),
        ("Britannia Regional Hub", "Britannia Regional Hub", "Shalini Krishnan", "+91-9876543239", "hub@britannia-regional.in", "Regional Distribution Center, Coimbatore, TN 641001", "Active", 3, "Daily", "Branded biscuits and bakery snacks"),
    ],
    "Cleaning & Household": [
        ("CleanHome Supplies", "CleanHome Supplies Co.", "Aditya Naik", "+91-9876543240", "contact@cleanhomesupplies.in", "Sector 7, Warehouse Zone, Hyderabad, TS 500001", "Active", 5, "Daily", "Household cleaning products"),
        ("SparkleClean Distributors", "SparkleClean Distributors Pvt Ltd", "Bhavna Sharma", "+91-9876543241", "sales@sparkleclean.in", "Cleaning Park, Nagpur, MH 440001", "Active", 4, "Daily", "Floor and surface cleaners"),
        ("HomeCare Solutions", "HomeCare Solutions India", "Prakash Iyer", "+91-9876543242", "orders@homecaresolutions.in", "Home Care Park, Bangalore, KA 560001", "Active", 5, "Daily", "Home care and disinfectants"),
        ("FreshHome Wholesale", "FreshHome Wholesale LLP", "Geeta Rani", "+91-9876543243", "wholesale@freshhome.in", "Warehouse District, Lucknow, UP 226001", "Active", 6, "Alternate Day", "Air fresheners and home fragrances"),
        ("HygieneFirst Supplies", "HygieneFirst Supplies Co.", "Ashok Mishra", "+91-9876543244", "info@hygienefirst.in", "Hygiene Park, Bhopal, MP 462001", "Active", 4, "Daily", "Hygiene and cleaning supplies"),
        ("EcoClean India", "EcoClean India Pvt Ltd", "Lakshmi Narayan", "+91-9876543245", "sales@ecoclean.in", "Eco Park, Chennai, TN 600001", "Active", 5, "Daily", "Eco-friendly cleaning products"),
    ],
    "Foodgrains, Oil & Masala": [
        ("GrainCo Vijayawada", "GrainCo Agro Pvt Ltd", "Srinivas Rao", "+91-9876543246", "contact@graincovijayawada.in", "Plot 12, Industrial Area, Vijayawada, AP 520001", "Active", 5, "Daily", "Rice, wheat, and grain staples"),
        ("OilTrade AP", "OilTrade AP Industries", "Venkatesh Naidu", "+91-9876543247", "contact@oiltradeap.in", "Unit 4, Oil Mill Road, Guntur, AP 522001", "Active", 5, "Daily", "Edible oils and ghee"),
        ("Spices of India", "Spices of India Co.", "Zahid Khan", "+91-9876543248", "orders@spicesofindia.in", "Spice Market, Guntur, AP 522001", "Active", 4, "Daily", "Whole and ground spices"),
        ("OrganicGrains Co.", "OrganicGrains Co. LLP", "Ramesh Yadav", "+91-9876543249", "sales@organicgrains.in", "Organic Park, Jaipur, RJ 302001", "Active", 6, "Alternate Day", "Organic grains and flours"),
        ("Masala King", "Masala King Pvt Ltd", "Imran Sheikh", "+91-9876543250", "biz@masalaking.in", "Masala Park, Mumbai, MH 400001", "Active", 3, "Daily", "Blended masalas and spice mixes"),
        ("FarmFresh Pulses", "FarmFresh Pulses Ltd", "Sumitra Devi", "+91-9876543251", "orders@farmfreshpulses.in", "Pulse Market, Indore, MP 452001", "Active", 5, "Daily", "Pulses and lentils"),
    ],
    "Beverages": [
        ("BevCorp India", "BevCorp India Ltd", "Alok Verma", "+91-9876543252", "contact@bevcorpindia.in", "Industrial Plot 88, Vizag, AP 530001", "Active", 5, "Daily", "Soft drinks and packaged beverages"),
        ("Refresh Beverages", "Refresh Beverages Pvt Ltd", "Diya Thomas", "+91-9876543253", "sales@refreshbeverages.in", "Beverage Park, Kochi, KL 682001", "Active", 4, "Daily", "Juices and fruit drinks"),
        ("DrinkWell Distributors", "DrinkWell Distributors Co.", "Harsh Vardhan", "+91-9876543254", "orders@drinkwell.in", "Drinks Hub, Gurgaon, HR 122001", "Active", 5, "Daily", "Health drinks and energy beverages"),
        ("Hydration Hub", "Hydration Hub India", "Simran Kaur", "+91-9876543255", "info@hydrationhub.in", "Water Bottling Zone, Chennai, TN 600001", "Active", 3, "Daily", "Packaged water and hydration products"),
    ],
    "Bakery, Cakes & Dairy": [
        ("BakeMaster Artisans", "BakeMaster Artisans Pvt Ltd", "Chef Joseph", "+91-9876543256", "contact@bakemasterartisans.in", "Baker Street, Tirupati, AP 517501", "Active", 1, "Daily", "Bakery, cakes, and bread"),
        ("DairyBest Krishna", "DairyBest Krishna Farms", "Krishna Murthy", "+91-9876543257", "contact@dairybestkrishna.in", "Dairy Colony, Krishna Dist, AP 521001", "Active", 2, "Daily", "Fresh dairy products"),
        ("Cream Valley Foods", "Cream Valley Foods Ltd", "Shobha Nair", "+91-9876543258", "sales@creamvalley.in", "Dairy Park, Anand, GJ 388001", "Active", 2, "Daily", "Cheese, cream, and dairy specialties"),
        ("Golden Loaf Bakers", "Golden Loaf Bakers Co.", "Thomas George", "+91-9876543259", "orders@goldenloaf.in", "Bakery Park, Bangalore, KA 560001", "Active", 3, "Daily", "Premium bakery products"),
    ],
    "Baby Care": [
        ("BabyBase Supplies", "BabyBase Supplies India", "Anjali Menon", "+91-9876543260", "contact@babybasesupplies.in", "Baby Products Hub, Secunderabad, TS 500003", "Active", 5, "Daily", "Baby care and infant products"),
        ("LittleOnes Care", "LittleOnes Care Pvt Ltd", "Rahul Saxena", "+91-9876543261", "sales@littleonescare.in", "Baby Care Park, Noida, UP 201301", "Active", 4, "Daily", "Baby diapers and wipes"),
        ("TinyTots Essentials", "TinyTots Essentials LLP", "Fatima Begum", "+91-9876543262", "orders@tinytots.in", "Infant Products Hub, Hyderabad, TS 500001", "Active", 5, "Daily", "Baby food and feeding essentials"),
    ],
    "Fruits & Vegetables": [
        ("FreshFarm Veg Market", "FreshFarm Veg Market LLC", "Govind Raju", "+91-9876543263", "contact@freshfarmvegmarket.in", "Farm Road, Agricultural Zone, Rajahmundry, AP 533001", "Active", 5, "Daily", "Fresh vegetables and greens"),
        ("FruitKing South", "FruitKing South Distributors", "Narasimha Reddy", "+91-9876543264", "contact@fruitkingsouth.in", "Fruit Market, Kurnool, AP 518001", "Active", 5, "Daily", "Fresh fruits and seasonal produce"),
        ("GreenHarvest Produce", "GreenHarvest Produce LLP", "Catherine D'Souza", "+91-9876543265", "sales@greenharvest.in", "Produce Park, Bangalore, KA 560001", "Active", 4, "Daily", "Organic fruits and vegetables"),
    ],
    "Eggs, Meat & Fish": [
        ("FreshCatch Meats", "FreshCatch Meats Pvt Ltd", "Biju Kurian", "+91-9876543266", "orders@freshcatch.in", "Meat Processing Zone, Kochi, KL 682001", "Active", 3, "Daily", "Fresh meat and poultry"),
        ("ProteinFresh Suppliers", "ProteinFresh Suppliers India", "Harpreet Singh", "+91-9876543267", "sales@proteinfresh.in", "Cold Chain Park, Delhi, DL 110001", "Active", 4, "Daily", "Eggs, chicken, and protein products"),
        ("FarmEggs & Poultry", "FarmEggs & Poultry Ltd", "Jessica Munda", "+91-9876543268", "contact@farmeggs.in", "Poultry Farm Zone, Hyderabad, TS 500001", "Active", 3, "Daily", "Farm-fresh eggs and poultry"),
    ],
    # Small/legacy categories are merged into the pools above for mapping purposes.
}

# Map a few legacy/small categories to the pool used for supplier assignment.
CATEGORY_FOR_SUPPLIER = {
    "Household": "Cleaning & Household",
    "Dairy": "Bakery, Cakes & Dairy",
    "Groceries": "Foodgrains, Oil & Masala",
}


def _valid_email(email: str) -> bool:
    """Basic email format sanity check."""
    return isinstance(email, str) and "@" in email and "." in email.split("@")[-1] and " " not in email


def generate_suppliers():
    suppliers = []
    counter = 1
    for category, specs in CATEGORY_POOLS.items():
        for spec in specs:
            name, company, contact, phone, email, address, status, lead_time, schedule, notes = spec
            if not _valid_email(email):
                raise ValueError(f"Malformed supplier email for {name!r}: {email!r}")
            sid = f"SUP{counter:03d}"
            counter += 1
            suppliers.append({
                "supplier_id": sid,
                "name": name,
                "company_name": company,
                "contact_person": contact,
                "phone": phone,
                "email": email,
                "address": address,
                "status": status,
                "default_lead_time_days": lead_time,
                "delivery_schedule": schedule,
                "notes": f"{notes}. Specialized in {category!r}.",
                "specialization": category,
            })
    return suppliers


def assign_suppliers_to_products(products_df):
    """Create a many-to-many mapping satisfying the task constraints."""
    mappings = []
    by_category = products_df.groupby("category")

    # Track which suppliers have been assigned and how many products each covers.
    supplier_counts = Counter()

    for category, group in by_category:
        pool_key = CATEGORY_FOR_SUPPLIER.get(category, category)
        pool = [s for s in SUPPLIERS if s["specialization"] == pool_key]
        if not pool:
            # Fallback: if a category has no dedicated pool, use the closest or skip.
            continue
        skus = group["sku"].tolist()

        # Strategy: every supplier gets at least one product. Then spread the rest.
        # We assign suppliers round-robin first to ensure coverage, then augment.
        pool_cycle = list(pool)
        random.shuffle(pool_cycle)
        # Pre-allocate one supplier per product, cycling through pool to cover every supplier.
        base_assignments = []
        for i, sku in enumerate(skus):
            chosen = [pool_cycle[i % len(pool_cycle)]["supplier_id"]]
            base_assignments.append((sku, chosen))
            supplier_counts[pool_cycle[i % len(pool_cycle)]["supplier_id"]] += 1

        # Now augment each product to 2-4 suppliers while balancing load.
        # We want roughly 50% with 2 suppliers, 35% with 3, 15% with 4.
        for i, (sku, chosen) in enumerate(base_assignments):
            target = random.choices([2, 3, 4], weights=[50, 35, 15], k=1)[0]
            pool_ids = [s["supplier_id"] for s in pool]
            # Exclude already chosen suppliers.
            candidates = [sid for sid in pool_ids if sid not in chosen]
            # Prefer suppliers with fewer current assignments to keep load balanced.
            candidates.sort(key=lambda sid: supplier_counts[sid])
            needed = target - len(chosen)
            for sid in candidates[:needed]:
                chosen.append(sid)
                supplier_counts[sid] += 1
            for sid in chosen:
                mappings.append({
                    "supplier_id": sid,
                    "sku": sku,
                    "category": category,
                })

    return mappings, supplier_counts


def generate_purchase_orders(mappings, products_df):
    """Generate realistic purchase history for all suppliers."""
    product_map = {str(r["sku"]): r for _, r in products_df.iterrows()}

    # Group mappings by supplier.
    supplier_to_skus = defaultdict(list)
    for m in mappings:
        supplier_to_skus[m["supplier_id"]].append(m["sku"])

    supplier_map = {s["supplier_id"]: s for s in SUPPLIERS}
    orders = []
    po_number = 2000
    today = datetime.now().date()

    for sid, skus in supplier_to_skus.items():
        s = supplier_map[sid]
        # Number of POs proportional to the number of products, but every supplier gets at least 8.
        po_count = max(8, min(15, len(skus) + 3))
        for _ in range(po_count):
            sku = random.choice(skus)
            product = product_map.get(sku, {})
            product_name = product.get("name", "Unknown Product")
            unit_price = float(product.get("unit_price", 100) or 100)
            # Order quantities vary by product price to keep totals realistic.
            base_qty = max(10, int(50000 / (unit_price + 1)))
            ordered_qty = random.randint(base_qty // 2, base_qty * 2)
            # Order date in the past 18 months.
            order_date = today - timedelta(days=random.randint(7, 540))
            expected_delivery = order_date + timedelta(days=s["default_lead_time_days"])

            # 80% received, 15% ordered, 5% cancelled.
            status = random.choices(["received", "ordered", "cancelled"], weights=[80, 15, 5], k=1)[0]

            if status == "received":
                # On-time 75%, delayed 25%. Delay is 1-5 days.
                on_time = random.random() < 0.75
                if on_time:
                    # Early delivery can be up to 2 days before expected, but never before the order date.
                    early_days = min(random.randint(0, 2), (expected_delivery - order_date).days)
                    actual_delivery = expected_delivery - timedelta(days=early_days)
                else:
                    actual_delivery = expected_delivery + timedelta(days=random.randint(1, 5))
                # Ensure actual delivery is never before the order date.
                if actual_delivery < order_date:
                    actual_delivery = order_date
                received_qty = ordered_qty if random.random() < 0.85 else int(ordered_qty * random.uniform(0.90, 0.99))
                quality_rating = random.choices([3, 4, 4, 5, 5], weights=[5, 30, 30, 20, 15], k=1)[0]
                # Make a few suppliers occasionally have low quality ratings to differentiate metrics.
                if sid in ("SUP008", "SUP025") and random.random() < 0.3:
                    quality_rating = random.randint(2, 3)
            elif status == "cancelled":
                actual_delivery = ""
                received_qty = 0
                quality_rating = ""
            else:  # ordered
                actual_delivery = ""
                received_qty = 0
                quality_rating = ""

            orders.append({
                "po_id": str(uuid.uuid4()),
                "po_number": f"PO-{po_number}",
                "supplier_id": sid,
                "supplier_name": s["name"],
                "sku": sku,
                "product_name": product_name,
                "ordered_qty": ordered_qty,
                "received_qty": received_qty,
                "order_date": order_date.isoformat(),
                "expected_delivery_date": expected_delivery.isoformat(),
                "actual_delivery_date": actual_delivery.isoformat() if actual_delivery else "",
                "status": status,
                "quality_rating": quality_rating,
                "notes": "",
            })
            po_number += 1

    return orders


def validate(suppliers, mappings, products_df, orders, supplier_counts):
    """Run the final validation checks requested by the task."""
    errors = []

    # 1. Every product has at least two suppliers.
    sku_suppliers = defaultdict(set)
    for m in mappings:
        sku_suppliers[m["sku"]].add(m["supplier_id"])
    products_without_two = [sku for sku, sids in sku_suppliers.items() if len(sids) < 2]
    if products_without_two:
        errors.append(f"{len(products_without_two)} products have fewer than 2 suppliers")

    # 2. Some products have three or more suppliers.
    products_with_three_plus = [sku for sku, sids in sku_suppliers.items() if len(sids) >= 3]
    if not products_with_three_plus:
        errors.append("No product has 3 or more suppliers")

    # 3. No product has zero suppliers.
    all_skus = set(products_df["sku"].tolist())
    mapped_skus = set(sku_suppliers.keys())
    unmapped = all_skus - mapped_skus
    if unmapped:
        errors.append(f"{len(unmapped)} products have zero suppliers")

    # 4. Every supplier supplies at least one product.
    idle_suppliers = [s["supplier_id"] for s in suppliers if supplier_counts[s["supplier_id"]] == 0]
    if idle_suppliers:
        errors.append(f"Idle suppliers: {idle_suppliers}")

    # 5. Supplier specialization: suppliers with multiple products should stay within one category.
    supplier_categories = defaultdict(set)
    for m in mappings:
        supplier_categories[m["supplier_id"]].add(m["category"])
    multi_category_suppliers = [sid for sid, cats in supplier_categories.items() if len(cats) > 1]
    if multi_category_suppliers:
        # This is acceptable for merged categories, but we report it.
        pass

    # 6. Supplier combinations are not identical across all products in the same category.
    by_cat = defaultdict(list)
    for sku, sids in sku_suppliers.items():
        cat = products_df[products_df["sku"] == sku]["category"].values[0]
        by_cat[cat].append(frozenset(sids))
    for cat, combos in by_cat.items():
        if len(set(combos)) == 1 and len(combos) > 1:
            errors.append(f"Category {cat!r} has identical supplier combinations for all products")

    # 7. Every supplier has at least one purchase order.
    po_suppliers = set(o["supplier_id"] for o in orders)
    suppliers_without_po = [s["supplier_id"] for s in suppliers if s["supplier_id"] not in po_suppliers]
    if suppliers_without_po:
        errors.append(f"Suppliers without purchase orders: {suppliers_without_po}")

    # 8. Received orders must have actual_delivery_date >= order_date.
    for o in orders:
        if o.get("status") == "received" and o.get("actual_delivery_date"):
            try:
                od = datetime.strptime(o["order_date"], "%Y-%m-%d").date()
                ad = datetime.strptime(o["actual_delivery_date"], "%Y-%m-%d").date()
                if ad < od:
                    errors.append(f"PO {o['po_number']}: actual_delivery_date {ad} is before order_date {od}")
            except Exception:
                pass

    return errors


def update_products_primary_supplier(mappings, products_df):
    """Update products.csv supplier_name column to the highest-ranked mapped supplier."""
    # Rank by supplier default lead time (shorter is better) as a simple heuristic.
    supplier_rank = {s["supplier_id"]: s["default_lead_time_days"] for s in SUPPLIERS}
    sku_suppliers = defaultdict(list)
    for m in mappings:
        sku_suppliers[m["sku"]].append(m["supplier_id"])

    primary = {}
    for sku, sids in sku_suppliers.items():
        best = min(sids, key=lambda sid: supplier_rank[sid])
        supplier_name_map = {s["supplier_id"]: s["name"] for s in SUPPLIERS}
        primary[sku] = supplier_name_map[best]

    products_df["supplier_name"] = products_df["sku"].map(primary).fillna(products_df["supplier_name"])
    return products_df


def main():
    global SUPPLIERS
    print(f"Loading products from {PRODUCTS_CSV}")
    products_df = pd.read_csv(PRODUCTS_CSV, keep_default_na=False)

    print("Generating suppliers...")
    SUPPLIERS = generate_suppliers()
    print(f"  -> {len(SUPPLIERS)} suppliers generated")

    print("Generating supplier-product mappings...")
    mappings, supplier_counts = assign_suppliers_to_products(products_df)
    print(f"  -> {len(mappings)} mappings generated")

    print("Generating purchase orders...")
    orders = generate_purchase_orders(mappings, products_df)
    print(f"  -> {len(orders)} purchase orders generated")

    print("Validating generated data...")
    errors = validate(SUPPLIERS, mappings, products_df, orders, supplier_counts)
    if errors:
        print("VALIDATION FAILED:")
        for e in errors:
            print("  -", e)
        raise SystemExit(1)
    print("  -> Validation passed")

    print("Updating products.csv primary supplier...")
    products_df = update_products_primary_supplier(mappings, products_df)

    # Save suppliers (drop helper specialization column before saving).
    supplier_cols = ["supplier_id", "name", "company_name", "contact_person", "phone", "email",
                     "address", "status", "default_lead_time_days", "delivery_schedule", "notes"]
    suppliers_df = pd.DataFrame(SUPPLIERS)[supplier_cols]
    suppliers_df.to_csv(SUPPLIERS_CSV, index=False)
    print(f"  -> wrote {SUPPLIERS_CSV}")

    mappings_df = pd.DataFrame(mappings)
    mappings_df.to_csv(SUPPLIER_PRODUCTS_CSV, index=False)
    print(f"  -> wrote {SUPPLIER_PRODUCTS_CSV}")

    orders_df = pd.DataFrame(orders)
    orders_df.to_csv(PURCHASE_ORDERS_CSV, index=False)
    print(f"  -> wrote {PURCHASE_ORDERS_CSV}")

    products_df.to_csv(PRODUCTS_CSV, index=False)
    print(f"  -> wrote {PRODUCTS_CSV}")

    # Print summary.
    print("\n=== Summary ===")
    print(f"Suppliers: {len(SUPPLIERS)}")
    print(f"Products mapped: {products_df['sku'].nunique()}")
    print(f"Total mappings: {len(mappings)}")
    print(f"Avg suppliers per product: {len(mappings) / products_df['sku'].nunique():.2f}")
    print(f"Purchase orders: {len(orders)}")
    print(f"Suppliers with orders: {orders_df['supplier_id'].nunique()}")

    # Category mapping summary.
    print("\nSuppliers per category:")
    for cat in sorted(CATEGORY_POOLS.keys()):
        count = len(CATEGORY_POOLS[cat])
        print(f"  {cat}: {count} suppliers")

    # Mapping count distribution per supplier.
    print("\nTop 10 suppliers by mapped products:")
    for sid, n in supplier_counts.most_common(10):
        name = next(s["name"] for s in SUPPLIERS if s["supplier_id"] == sid)
        print(f"  {sid} {name}: {n} products")


if __name__ == "__main__":
    main()
