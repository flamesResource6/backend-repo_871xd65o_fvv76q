"""
Database Schemas for SaaS Notepad

Each Pydantic model represents a MongoDB collection. The collection name is the
lowercased class name. Example: class Note -> collection "note".

These schemas are used for validation in API endpoints.
"""
from typing import Optional, List
from pydantic import BaseModel, Field


class Category(BaseModel):
    """Categories collection schema (collection: "category")"""
    name: str = Field(..., min_length=1, max_length=64, description="Display name of the category")
    color: Optional[str] = Field(None, description="Hex/RGB color used to tag notes in this category")
    icon: Optional[str] = Field(None, description="Emoji or icon key for the category")


class Note(BaseModel):
    """Notes collection schema (collection: "note")"""
    title: str = Field(..., min_length=1, max_length=200, description="Note title")
    content: str = Field("", description="Note body content (Markdown/plain text)")
    category_id: Optional[str] = Field(None, description="ID of the related category")
    pinned: bool = Field(False, description="Whether the note is pinned")
    archived: bool = Field(False, description="Whether the note is archived")


# Example additional schemas (kept for reference but not used directly)
class User(BaseModel):
    name: str
    email: str
    address: str
    age: Optional[int] = Field(None, ge=0, le=120)
    is_active: bool = True


class Product(BaseModel):
    title: str
    description: Optional[str] = None
    price: float = Field(..., ge=0)
    category: str
    in_stock: bool = True
