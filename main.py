import os
import hashlib
import random
import string
from datetime import datetime, timedelta, timezone
from typing import List, Optional, Dict, Any

from fastapi import FastAPI, HTTPException, Header, Query
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel
from bson import ObjectId

from database import db, create_document, get_documents

app = FastAPI(title="E-commerce API", version="1.0.0")

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# ---------------------- Utilities ----------------------

def oid(id_str: str) -> ObjectId:
    try:
        return ObjectId(id_str)
    except Exception:
        raise HTTPException(status_code=400, detail="Invalid ID")

def now_utc():
    return datetime.now(timezone.utc)

def hash_password(pw: str) -> str:
    return hashlib.sha256(pw.encode()).hexdigest()

ADMIN_KEY = os.getenv("ADMIN_KEY", "demo-admin-key")

# ---------------------- Models ----------------------

class RegisterBody(BaseModel):
    name: str
    email: str
    password: str
    phone: Optional[str] = None

class LoginBody(BaseModel):
    email: str
    password: str

class OTPRequest(BaseModel):
    phone: str

class OTPVerify(BaseModel):
    phone: str
    code: str
    name: Optional[str] = None
    email: Optional[str] = None

class CartItem(BaseModel):
    product_id: str
    quantity: int = 1

class Address(BaseModel):
    label: str
    line1: str
    line2: Optional[str] = None
    city: str
    state: str
    country: str
    postal_code: str
    phone: Optional[str] = None

class CheckoutBody(BaseModel):
    user_id: Optional[str] = None
    items: List[CartItem]
    address: Address
    coupon: Optional[str] = None

# ---------------------- Root & Health ----------------------

@app.get("/")
def read_root():
    return {"message": "E-commerce API running"}

@app.get("/test")
def test_database():
    response = {
        "backend": "✅ Running",
        "database": "❌ Not Available",
        "database_url": None,
        "database_name": None,
        "connection_status": "Not Connected",
        "collections": []
    }
    try:
        if db is not None:
            response["database"] = "✅ Available"
            response["database_name"] = db.name
            response["connection_status"] = "Connected"
            try:
                response["collections"] = db.list_collection_names()
                response["database"] = "✅ Connected & Working"
            except Exception as e:
                response["database"] = f"⚠️ Connected but Error: {str(e)[:80]}"
    except Exception as e:
        response["database"] = f"❌ Error: {str(e)[:80]}"
    return response

# ---------------------- Schemas Endpoint ----------------------

@app.get("/schema")
def get_schema():
    try:
        import schemas as s
        def model_fields(m):
            return {k: str(v.annotation) for k, v in getattr(m, "model_fields", {}).items()}
        return {
            "models": {
                "user": model_fields(s.User),
                "category": model_fields(s.Category),
                "product": model_fields(s.Product),
                "coupon": model_fields(s.Coupon),
                "banner": model_fields(s.Banner),
                "order": model_fields(s.Order),
            }
        }
    except Exception as e:
        return {"error": str(e)}

# ---------------------- Auth ----------------------

@app.post("/auth/register")
def register(body: RegisterBody):
    existing = db["user"].find_one({"email": body.email})
    if existing:
        raise HTTPException(400, "Email already registered")
    user = {
        "name": body.name,
        "email": body.email,
        "password_hash": hash_password(body.password),
        "phone": body.phone,
        "is_admin": False,
        "is_active": True,
        "created_at": now_utc(),
        "updated_at": now_utc(),
    }
    res = db["user"].insert_one(user)
    token = str(res.inserted_id)
    return {"token": token, "user_id": token, "name": body.name}

@app.post("/auth/login")
def login(body: LoginBody):
    user = db["user"].find_one({"email": body.email})
    if not user or user.get("password_hash") != hash_password(body.password):
        raise HTTPException(401, "Invalid credentials")
    return {"token": str(user["_id"]), "user_id": str(user["_id"]), "name": user.get("name")}

@app.post("/auth/request-otp")
def request_otp(body: OTPRequest):
    code = "".join(random.choices(string.digits, k=6))
    db["otp"].update_one(
        {"phone": body.phone},
        {"$set": {"code": code, "expires_at": now_utc() + timedelta(minutes=5)}},
        upsert=True,
    )
    # Demo note: In a real app, send via SMS provider. For demo, return code.
    return {"message": "OTP sent (demo)", "code": code}

@app.post("/auth/verify-otp")
def verify_otp(body: OTPVerify):
    doc = db["otp"].find_one({"phone": body.phone})
    if not doc or doc.get("code") != body.code or doc.get("expires_at") < now_utc():
        raise HTTPException(400, "Invalid or expired OTP")
    user = db["user"].find_one({"phone": body.phone})
    if not user:
        user = {
            "name": body.name or "User",
            "email": body.email or f"{body.phone}@example.com",
            "phone": body.phone,
            "is_active": True,
            "created_at": now_utc(),
            "updated_at": now_utc(),
        }
        res = db["user"].insert_one(user)
        user_id = res.inserted_id
    else:
        user_id = user["_id"]
    db["otp"].delete_one({"phone": body.phone})
    return {"token": str(user_id), "user_id": str(user_id)}

# ---------------------- Products & Categories ----------------------

@app.get("/categories")
def list_categories():
    cats = get_documents("category")
    for c in cats:
        c["_id"] = str(c["_id"])
    return cats

@app.get("/products")
def list_products(q: Optional[str] = None, category: Optional[str] = None, brand: Optional[str] = None,
                  min_price: Optional[float] = None, max_price: Optional[float] = None, featured: Optional[bool] = None,
                  limit: int = 50):
    filt: Dict[str, Any] = {}
    if q:
        filt["title"] = {"$regex": q, "$options": "i"}
    if category:
        filt["category"] = category
    if brand:
        filt["brand"] = brand
    price_cond = {}
    if min_price is not None:
        price_cond["$gte"] = min_price
    if max_price is not None:
        price_cond["$lte"] = max_price
    if price_cond:
        filt["price"] = price_cond
    if featured is not None:
        filt["featured"] = featured
    items = db["product"].find(filt).limit(limit)
    out = []
    for p in items:
        p["_id"] = str(p["_id"])
        out.append(p)
    return out

@app.get("/products/{pid}")
def get_product(pid: str):
    # allow lookup by slug or _id
    prod = db["product"].find_one({"$or": [{"_id": oid(pid)}, {"slug": pid}]}) if len(pid) == 24 else db["product"].find_one({"slug": pid})
    if not prod:
        raise HTTPException(404, "Product not found")
    prod["_id"] = str(prod["_id"])
    return prod

# ---------------------- Admin: Products, Categories, Banners, Coupons ----------------------

class ProductBody(BaseModel):
    title: str
    slug: str
    description: Optional[str] = None
    price: float
    sale_price: Optional[float] = None
    currency: str = "INR"
    category: str
    brand: Optional[str] = None
    stock: int = 0
    images: List[Dict[str, str]] = []
    specs: Dict[str, str] = {}
    featured: bool = False
    tags: List[str] = []

@app.post("/admin/products")
def admin_create_product(body: ProductBody, x_admin_key: str = Header(None)):
    if x_admin_key != ADMIN_KEY:
        raise HTTPException(401, "Unauthorized")
    doc = body.model_dump()
    doc.update({"rating": 0.0, "rating_count": 0, "created_at": now_utc(), "updated_at": now_utc()})
    res = db["product"].insert_one(doc)
    return {"_id": str(res.inserted_id)}

@app.put("/admin/products/{pid}")
def admin_update_product(pid: str, body: Dict[str, Any], x_admin_key: str = Header(None)):
    if x_admin_key != ADMIN_KEY:
        raise HTTPException(401, "Unauthorized")
    db["product"].update_one({"_id": oid(pid)}, {"$set": {**body, "updated_at": now_utc()}})
    return {"ok": True}

@app.delete("/admin/products/{pid}")
def admin_delete_product(pid: str, x_admin_key: str = Header(None)):
    if x_admin_key != ADMIN_KEY:
        raise HTTPException(401, "Unauthorized")
    db["product"].delete_one({"_id": oid(pid)})
    return {"ok": True}

class CategoryBody(BaseModel):
    name: str
    slug: str
    icon: Optional[str] = None

@app.post("/admin/categories")
def admin_add_category(body: CategoryBody, x_admin_key: str = Header(None)):
    if x_admin_key != ADMIN_KEY:
        raise HTTPException(401, "Unauthorized")
    res = db["category"].insert_one({**body.model_dump(), "created_at": now_utc()})
    return {"_id": str(res.inserted_id)}

@app.get("/banners")
def list_banners():
    banners = db["banner"].find({"active": True})
    out = []
    for b in banners:
        b["_id"] = str(b["_id"])
        out.append(b)
    return out

class BannerBody(BaseModel):
    title: str
    subtitle: Optional[str] = None
    image_url: str
    link: Optional[str] = None
    active: bool = True

@app.post("/admin/banners")
def admin_add_banner(body: BannerBody, x_admin_key: str = Header(None)):
    if x_admin_key != ADMIN_KEY:
        raise HTTPException(401, "Unauthorized")
    res = db["banner"].insert_one({**body.model_dump(), "created_at": now_utc()})
    return {"_id": str(res.inserted_id)}

class CouponBody(BaseModel):
    code: str
    type: str  # percent or flat
    value: float
    min_order: float = 0
    active: bool = True

@app.post("/admin/coupons")
def admin_add_coupon(body: CouponBody, x_admin_key: str = Header(None)):
    if x_admin_key != ADMIN_KEY:
        raise HTTPException(401, "Unauthorized")
    res = db["coupon"].insert_one({**body.model_dump(), "created_at": now_utc()})
    return {"_id": str(res.inserted_id)}

@app.get("/coupons/{code}")
def get_coupon(code: str):
    c = db["coupon"].find_one({"code": code.upper(), "active": True})
    if not c:
        raise HTTPException(404, "Invalid coupon")
    c["_id"] = str(c["_id"])
    return c

# ---------------------- Cart & Wishlist ----------------------

@app.get("/cart")
def get_cart(user_id: str = Query(...)):
    cart = db["cart"].find_one({"user_id": user_id}) or {"user_id": user_id, "items": []}
    if "_id" in cart:
        cart["_id"] = str(cart["_id"])
    return cart

@app.post("/cart/add")
def add_to_cart(item: CartItem, user_id: str = Query(...)):
    cart = db["cart"].find_one({"user_id": user_id}) or {"user_id": user_id, "items": []}
    items = cart.get("items", [])
    found = False
    for it in items:
        if it["product_id"] == item.product_id:
            it["quantity"] += item.quantity
            found = True
            break
    if not found:
        items.append(item.model_dump())
    db["cart"].update_one({"user_id": user_id}, {"$set": {"items": items, "updated_at": now_utc()}}, upsert=True)
    return {"ok": True}

@app.post("/cart/remove")
def remove_from_cart(item: CartItem, user_id: str = Query(...)):
    cart = db["cart"].find_one({"user_id": user_id}) or {"user_id": user_id, "items": []}
    items = [it for it in cart.get("items", []) if it["product_id"] != item.product_id]
    db["cart"].update_one({"user_id": user_id}, {"$set": {"items": items, "updated_at": now_utc()}}, upsert=True)
    return {"ok": True}

@app.get("/wishlist")
def get_wishlist(user_id: str = Query(...)):
    w = db["wishlist"].find_one({"user_id": user_id}) or {"user_id": user_id, "items": []}
    if "_id" in w:
        w["_id"] = str(w["_id"])
    return w

@app.post("/wishlist/toggle")
def toggle_wishlist(item: CartItem, user_id: str = Query(...)):
    w = db["wishlist"].find_one({"user_id": user_id}) or {"user_id": user_id, "items": []}
    items = w.get("items", [])
    if any(it["product_id"] == item.product_id for it in items):
        items = [it for it in items if it["product_id"] != item.product_id]
    else:
        items.append({"product_id": item.product_id, "quantity": 1})
    db["wishlist"].update_one({"user_id": user_id}, {"$set": {"items": items}}, upsert=True)
    return {"ok": True}

# ---------------------- Checkout & Payments (Razorpay Mock) ----------------------

@app.post("/checkout/create-order")
def create_order(body: CheckoutBody):
    # compute amount from items
    total = 0.0
    order_items = []
    for it in body.items:
        prod = db["product"].find_one({"_id": oid(it.product_id)})
        if not prod:
            raise HTTPException(400, "Product not found")
        price = float(prod.get("sale_price") or prod.get("price"))
        total += price * it.quantity
        order_items.append({
            "product_id": it.product_id,
            "title": prod.get("title"),
            "price": price,
            "quantity": it.quantity,
            "image": (prod.get("images") or [{}])[0].get("url") if prod.get("images") else None,
        })
    applied_coupon = None
    if body.coupon:
        c = db["coupon"].find_one({"code": body.coupon.upper(), "active": True})
        if c and total >= float(c.get("min_order", 0)):
            if c.get("type") == "percent":
                total = max(0.0, total * (1 - float(c.get("value"))/100.0))
            else:
                total = max(0.0, total - float(c.get("value")))
            applied_coupon = c.get("code")
    order = {
        "user_id": body.user_id or "guest",
        "items": order_items,
        "amount": round(total, 2),
        "currency": "INR",
        "address": body.address.model_dump(),
        "status": "pending",
        "payment_provider": "razorpay",
        "payment_order_id": "order_" + ''.join(random.choices(string.ascii_letters + string.digits, k=12)),
        "created_at": now_utc(),
        "updated_at": now_utc(),
        "coupon": applied_coupon,
    }
    res = db["order"].insert_one(order)
    return {"order_id": str(res.inserted_id), "razorpay_order_id": order["payment_order_id"], "amount": order["amount"], "currency": order["currency"]}

class PaymentVerifyBody(BaseModel):
    order_id: str
    payment_id: str
    signature: Optional[str] = None

@app.post("/payment/verify")
def payment_verify(body: PaymentVerifyBody):
    # In real Razorpay, verify signature using secret
    db["order"].update_one({"_id": oid(body.order_id)}, {"$set": {"status": "paid", "payment_id": body.payment_id, "updated_at": now_utc()}})
    return {"ok": True}

# ---------------------- Orders ----------------------

@app.get("/orders")
def list_orders(user_id: Optional[str] = None):
    filt: Dict[str, Any] = {}
    if user_id:
        filt["user_id"] = user_id
    cur = db["order"].find(filt).sort("created_at", -1)
    out = []
    for o in cur:
        o["_id"] = str(o["_id"])
        out.append(o)
    return out

@app.get("/orders/{oid_str}")
def get_order(oid_str: str):
    o = db["order"].find_one({"_id": oid(oid_str)})
    if not o:
        raise HTTPException(404, "Order not found")
    o["_id"] = str(o["_id"])
    return o

@app.get("/orders/track/{oid_str}")
def track_order(oid_str: str):
    o = db["order"].find_one({"_id": oid(oid_str)})
    if not o:
        raise HTTPException(404, "Order not found")
    return {"status": o.get("status"), "estimated_delivery": (now_utc() + timedelta(days=5)).date().isoformat()}

# ---------------------- Home Aggregate ----------------------

@app.get("/home")
def home():
    featured = db["product"].find({"featured": True}).limit(8)
    out_feat = []
    for p in featured:
        p["_id"] = str(p["_id"])
        out_feat.append(p)
    cats = list_categories()
    banners = list_banners()
    return {"featured": out_feat, "categories": cats, "banners": banners}

# ---------------------- Seed Demo Data ----------------------

@app.post("/admin/seed")
def seed(x_admin_key: str = Header(None)):
    if x_admin_key != ADMIN_KEY:
        raise HTTPException(401, "Unauthorized")
    if db["category"].count_documents({}) == 0:
        db["category"].insert_many([
            {"name": "Electronics", "slug": "electronics"},
            {"name": "Fashion", "slug": "fashion"},
            {"name": "Home", "slug": "home"},
        ])
    if db["product"].count_documents({}) == 0:
        demo = []
        for i in range(1, 13):
            demo.append({
                "title": f"Premium Gadget {i}",
                "slug": f"premium-gadget-{i}",
                "description": "A modern, minimalist gadget with premium build.",
                "price": 4999 + i * 100,
                "sale_price": 4499 + i * 80,
                "currency": "INR",
                "category": "electronics",
                "brand": "Flames",
                "rating": 4.5,
                "rating_count": 120 + i,
                "stock": 50,
                "images": [
                    {"url": f"https://picsum.photos/seed/gadget{i}/600/400", "alt": "Product image"}
                ],
                "specs": {"Color": "Black", "Material": "Aluminum"},
                "featured": i <= 8,
                "tags": ["new", "trending"],
                "created_at": now_utc(),
                "updated_at": now_utc(),
            })
        db["product"].insert_many(demo)
    if db["banner"].count_documents({}) == 0:
        db["banner"].insert_many([
            {"title": "Festive Sale", "subtitle": "Up to 50% off", "image_url": "https://picsum.photos/seed/banner1/1200/400", "link": "/", "active": True},
            {"title": "New Arrivals", "subtitle": "Latest tech", "image_url": "https://picsum.photos/seed/banner2/1200/400", "link": "/", "active": True},
        ])
    return {"ok": True}

if __name__ == "__main__":
    import uvicorn
    port = int(os.getenv("PORT", 8000))
    uvicorn.run(app, host="0.0.0.0", port=port)
