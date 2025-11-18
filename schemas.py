"""
Database Schemas for E-commerce

Each Pydantic model represents a collection in MongoDB.
Class name lowercased = collection name (e.g., Product -> "product").
"""
from pydantic import BaseModel, Field, EmailStr
from typing import Optional, List, Literal, Dict
from datetime import datetime

class Address(BaseModel):
    label: str = Field(..., description="Home, Work, etc.")
    line1: str
    line2: Optional[str] = None
    city: str
    state: str
    country: str
    postal_code: str
    phone: Optional[str] = None
    is_default: bool = False

class User(BaseModel):
    name: str
    email: EmailStr
    password_hash: Optional[str] = None
    phone: Optional[str] = None
    avatar_url: Optional[str] = None
    is_active: bool = True
    is_admin: bool = False
    token: Optional[str] = None
    addresses: List[Address] = []

class Category(BaseModel):
    name: str
    slug: str
    icon: Optional[str] = None

class ProductImage(BaseModel):
    url: str
    alt: Optional[str] = None

class Product(BaseModel):
    title: str
    slug: str
    description: Optional[str] = None
    price: float = Field(..., ge=0)
    sale_price: Optional[float] = Field(None, ge=0)
    currency: str = "INR"
    category: str
    brand: Optional[str] = None
    rating: float = 0.0
    rating_count: int = 0
    stock: int = 0
    images: List[ProductImage] = []
    specs: Dict[str, str] = {}
    featured: bool = False
    tags: List[str] = []

class Review(BaseModel):
    product_id: str
    user_id: str
    rating: int = Field(..., ge=1, le=5)
    comment: Optional[str] = None

class Coupon(BaseModel):
    code: str
    type: Literal["percent", "flat"]
    value: float
    min_order: float = 0
    active: bool = True
    expires_at: Optional[datetime] = None

class Banner(BaseModel):
    title: str
    subtitle: Optional[str] = None
    image_url: str
    link: Optional[str] = None
    active: bool = True

class CartItem(BaseModel):
    product_id: str
    quantity: int = Field(1, ge=1)

class Cart(BaseModel):
    user_id: str
    items: List[CartItem] = []

class OrderItem(BaseModel):
    product_id: str
    title: str
    price: float
    quantity: int
    image: Optional[str] = None

class Order(BaseModel):
    user_id: str
    items: List[OrderItem]
    amount: float
    currency: str = "INR"
    address: Address
    status: Literal["pending", "paid", "shipped", "delivered", "cancelled"] = "pending"
    payment_provider: Optional[str] = None
    payment_order_id: Optional[str] = None
    payment_id: Optional[str] = None
    coupon: Optional[str] = None

# The Flames database viewer will automatically read these from /schema
