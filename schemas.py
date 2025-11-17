"""
Database Schemas

Define your MongoDB collection schemas here using Pydantic models.
These schemas are used for data validation in your application.

Each Pydantic model represents a collection in your database.
Model name is converted to lowercase for the collection name:
- User -> "user" collection
- Product -> "product" collection
- BlogPost -> "blogs" collection
"""

from pydantic import BaseModel, Field
from typing import Optional, Literal, Dict, Any, List

# Example schemas (kept for reference)

class User(BaseModel):
    """
    Users collection schema
    Collection name: "user" (lowercase of class name)
    """
    name: str = Field(..., description="Full name")
    email: str = Field(..., description="Email address")
    address: str = Field(..., description="Address")
    age: Optional[int] = Field(None, ge=0, le=120, description="Age in years")
    is_active: bool = Field(True, description="Whether user is active")

class Product(BaseModel):
    """
    Products collection schema
    Collection name: "product" (lowercase of class name)
    """
    title: str = Field(..., description="Product title")
    description: Optional[str] = Field(None, description="Product description")
    price: float = Field(..., ge=0, description="Price in dollars")
    category: str = Field(..., description="Product category")
    in_stock: bool = Field(True, description="Whether product is in stock")

# Casino app schemas

class Player(BaseModel):
    """
    Players collection schema
    Collection name: "player"
    """
    username: str = Field(..., min_length=3, max_length=24, description="Unique username")
    balance: int = Field(1000, ge=0, description="Play credits (no real money)")

class GameResult(BaseModel):
    """
    Game results history schema
    Collection name: "gameresult"
    """
    username: str
    game: Literal["blackjack", "slots", "baccarat"]
    bet: int = Field(..., ge=1)
    payout: int = Field(..., description="Credits won (can be negative for loss)")
    balance_after: int = Field(..., ge=0)
    details: Dict[str, Any] = Field(default_factory=dict)

class BlackjackHand(BaseModel):
    """
    Blackjack hands (active sessions)
    Collection name: "blackjackhand"
    """
    username: str
    bet: int = Field(..., ge=1, le=1000)
    player_cards: List[str]
    dealer_cards: List[str]
    shoe: List[str] = Field(default_factory=list)
    status: Literal["player_turn", "dealer_turn", "resolved"] = "player_turn"
    outcome: Optional[Literal["win", "lose", "push", "blackjack", "bust"]] = None
    payout: Optional[int] = None
    can_double: bool = True
    can_split: bool = False  # reserved for future
