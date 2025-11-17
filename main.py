import os
from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel, Field
from typing import Literal, Dict, Any
from bson import ObjectId

from database import db, create_document, get_documents
from schemas import Player, GameResult

app = FastAPI(title="Fun Casino API", description="Play-for-fun casino games. No real money.")

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# Utility functions

def collection(name: str):
    if db is None:
        raise HTTPException(status_code=500, detail="Database not available")
    return db[name]

# Request models

class BetRequest(BaseModel):
    username: str = Field(..., min_length=3, max_length=24)
    bet: int = Field(..., ge=1, le=1000)

# Public endpoints

@app.get("/")
def read_root():
    return {"message": "Fun Casino API running"}

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
            response["database_url"] = "✅ Configured"
            response["database_name"] = db.name if hasattr(db, 'name') else "✅ Connected"
            response["connection_status"] = "Connected"
            try:
                collections = db.list_collection_names()
                response["collections"] = collections[:10]
                response["database"] = "✅ Connected & Working"
            except Exception as e:
                response["database"] = f"⚠️  Connected but Error: {str(e)[:50]}"
        else:
            response["database"] = "⚠️  Available but not initialized"
    except Exception as e:
        response["database"] = f"❌ Error: {str(e)[:50]}"

    response["database_url"] = "✅ Set" if os.getenv("DATABASE_URL") else "❌ Not Set"
    response["database_name"] = "✅ Set" if os.getenv("DATABASE_NAME") else "❌ Not Set"
    return response

# Player endpoints

@app.post("/api/player/register")
def register_player(player: Player):
    col = collection("player")
    existing = col.find_one({"username": player.username})
    if existing:
        raise HTTPException(status_code=400, detail="Username already taken")
    player_id = create_document("player", player)
    return {"ok": True, "id": player_id, "username": player.username, "balance": player.balance}

@app.get("/api/player/{username}")
def get_player(username: str):
    col = collection("player")
    doc = col.find_one({"username": username})
    if not doc:
        raise HTTPException(status_code=404, detail="Player not found")
    return {"username": doc["username"], "balance": int(doc.get("balance", 0))}

# Helpers

def adjust_balance(username: str, delta: int) -> int:
    col = collection("player")
    doc = col.find_one({"username": username})
    if not doc:
        raise HTTPException(status_code=404, detail="Player not found")
    new_balance = max(0, int(doc.get("balance", 0)) + delta)
    col.update_one({"_id": doc["_id"]}, {"$set": {"balance": new_balance}})
    return new_balance

# Game logic (simple, provably-fair-like seeds could be added later)
import random

# Blackjack

def blackjack_hand_value(cards):
    value = 0
    aces = 0
    for c in cards:
        r = c[:-1]
        if r in ["J","Q","K"]:
            value += 10
        elif r == "A":
            aces += 1
            value += 11
        else:
            value += int(r)
    while value > 21 and aces:
        value -= 10
        aces -= 1
    return value


def draw_card():
    ranks = ["A","2","3","4","5","6","7","8","9","10","J","Q","K"]
    suits = ["♠","♥","♦","♣"]
    return f"{random.choice(ranks)}{random.choice(suits)}"

@app.post("/api/blackjack/play")
def play_blackjack(req: BetRequest):
    # deal
    player = [draw_card(), draw_card()]
    dealer = [draw_card(), draw_card()]
    player_val = blackjack_hand_value(player)
    dealer_val = blackjack_hand_value(dealer)

    outcome = "push"
    payout = 0
    if player_val == 21 and dealer_val != 21:
        outcome = "blackjack"
        payout = int(req.bet * 1.5)
    elif player_val > 21:
        outcome = "bust"
        payout = -req.bet
    else:
        # simple dealer play to 17+
        while dealer_val < 17:
            dealer.append(draw_card())
            dealer_val = blackjack_hand_value(dealer)
        if dealer_val > 21 or player_val > dealer_val:
            outcome = "win"
            payout = req.bet
        elif player_val < dealer_val:
            outcome = "lose"
            payout = -req.bet
        else:
            outcome = "push"
            payout = 0

    new_balance = adjust_balance(req.username, payout)
    create_document("gameresult", GameResult(
        username=req.username,
        game="blackjack",
        bet=req.bet,
        payout=payout,
        balance_after=new_balance,
        details={"player": player, "dealer": dealer, "outcome": outcome}
    ))
    return {"outcome": outcome, "payout": payout, "player": player, "dealer": dealer, "balance": new_balance}

# Slots

symbols = ["🍒","🍋","🔔","⭐","7️⃣","🍀"]
weights = [30, 25, 20, 15, 7, 3]  # simple rarity

@app.post("/api/slots/spin")
def spin_slots(req: BetRequest):
    reels = []
    for _ in range(3):
        reels.append(random.choices(symbols, weights=weights, k=1)[0])
    payout = 0
    outcome = "lose"
    if len(set(reels)) == 1:
        outcome = "jackpot"
        payout = req.bet * 10
    elif reels[0] == reels[1] or reels[1] == reels[2] or reels[0] == reels[2]:
        outcome = "win"
        payout = req.bet * 2
    else:
        payout = -req.bet
    new_balance = adjust_balance(req.username, payout)
    create_document("gameresult", GameResult(
        username=req.username,
        game="slots",
        bet=req.bet,
        payout=payout,
        balance_after=new_balance,
        details={"reels": reels, "outcome": outcome}
    ))
    return {"reels": reels, "outcome": outcome, "payout": payout, "balance": new_balance}

# Baccarat (simplified punto banco)

card_values = {
    "A": 1, "2": 2, "3": 3, "4": 4, "5": 5, "6": 6, "7": 7, "8": 8, "9": 9, "10": 0, "J": 0, "Q": 0, "K": 0
}

def draw_rank():
    ranks = ["A","2","3","4","5","6","7","8","9","10","J","Q","K"]
    return random.choice(ranks)

class BaccaratBet(BaseModel):
    username: str
    bet: int = Field(..., ge=1, le=1000)
    side: Literal["player","banker","tie"]


def hand_total(cards):
    return sum(card_values[r] for r in cards) % 10

@app.post("/api/baccarat/play")
def play_baccarat(req: BaccaratBet):
    player = [draw_rank(), draw_rank()]
    banker = [draw_rank(), draw_rank()]
    player_total = hand_total(player)
    banker_total = hand_total(banker)

    # Natural
    if player_total in [8,9] or banker_total in [8,9]:
        pass
    else:
        # draw rules simplified: if player <=5 draw one, banker mirrors
        if player_total <= 5:
            player.append(draw_rank())
            player_total = hand_total(player)
        if banker_total <= 5:
            banker.append(draw_rank())
            banker_total = hand_total(banker)

    outcome = "tie"
    if player_total > banker_total:
        outcome = "player"
    elif banker_total > player_total:
        outcome = "banker"

    payout = -req.bet
    if req.side == outcome:
        if outcome == "tie":
            payout = req.bet * 8
        elif outcome == "player":
            payout = req.bet
        elif outcome == "banker":
            payout = int(req.bet * 0.95)  # house commission
    elif req.side == "tie" and outcome != "tie":
        payout = -req.bet
    else:
        payout = -req.bet

    new_balance = adjust_balance(req.username, payout)
    create_document("gameresult", GameResult(
        username=req.username,
        game="baccarat",
        bet=req.bet,
        payout=payout,
        balance_after=new_balance,
        details={"player": player, "banker": banker, "result": outcome}
    ))
    return {"player": player, "banker": banker, "result": outcome, "payout": payout, "balance": new_balance}

# History endpoint

@app.get("/api/history/{username}")
def history(username: str):
    col = collection("gameresult")
    docs = list(col.find({"username": username}).sort("created_at", -1).limit(20))
    for d in docs:
        d["_id"] = str(d["_id"])  # serialize
    return docs

if __name__ == "__main__":
    import uvicorn
    port = int(os.getenv("PORT", 8000))
    uvicorn.run(app, host="0.0.0.0", port=port)
