import os
from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel, Field
from typing import Literal, Dict, Any, List, Optional

from database import db, create_document
from schemas import Player, GameResult, BlackjackHand

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

def get_balance(username: str) -> int:
    col = collection("player")
    doc = col.find_one({"username": username})
    if not doc:
        raise HTTPException(status_code=404, detail="Player not found")
    return int(doc.get("balance", 0))

def adjust_balance(username: str, delta: int) -> int:
    col = collection("player")
    doc = col.find_one({"username": username})
    if not doc:
        raise HTTPException(status_code=404, detail="Player not found")
    new_balance = max(0, int(doc.get("balance", 0)) + delta)
    col.update_one({"_id": doc["_id"]}, {"$set": {"balance": new_balance}})
    return new_balance

# Game logic
import random

# ----- Blackjack with player actions -----

RANKS = ["A","2","3","4","5","6","7","8","9","10","J","Q","K"]
SUITS = ["♠","♥","♦","♣"]

CARD_VALUES = {"A": 11, "2": 2, "3": 3, "4": 4, "5": 5, "6": 6, "7": 7, "8": 8, "9": 9, "10": 10, "J": 10, "Q": 10, "K": 10}


def hand_value(cards: List[str]) -> int:
    total = 0
    aces = 0
    for c in cards:
        r = c[:-1]
        total += CARD_VALUES[r]
        if r == "A":
            aces += 1
    while total > 21 and aces:
        total -= 10
        aces -= 1
    return total


def make_shoe(decks: int = 6) -> List[str]:
    shoe = [f"{r}{s}" for r in RANKS for s in SUITS] * decks
    random.shuffle(shoe)
    # burn 1 card
    if shoe:
        shoe.pop()
    return shoe


def draw(shoe: List[str]) -> str:
    if not shoe:
        # reshuffle new shoe if exhausted
        shoe.extend(make_shoe())
    return shoe.pop()


class BlackjackStart(BaseModel):
    username: str
    bet: int = Field(..., ge=1, le=1000)


@app.post("/api/blackjack/start")
def blackjack_start(req: BlackjackStart):
    # ensure no other active hand
    hand_col = collection("blackjackhand")
    existing = hand_col.find_one({"username": req.username, "status": "player_turn"})
    if existing:
        raise HTTPException(status_code=400, detail="Finish your current hand first")
    # balance check
    if get_balance(req.username) < req.bet:
        raise HTTPException(status_code=400, detail="Insufficient balance")

    shoe = make_shoe()
    player_cards = [draw(shoe), draw(shoe)]
    dealer_cards = [draw(shoe), draw(shoe)]

    p_val = hand_value(player_cards)
    d_val = hand_value(dealer_cards)

    # Natural checks
    if p_val == 21 or d_val == 21:
        # resolve immediately
        outcome = "push"
        payout = 0
        if p_val == 21 and d_val != 21:
            outcome = "blackjack"
            payout = int(req.bet * 1.5)
        elif d_val == 21 and p_val != 21:
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
            details={"player": player_cards, "dealer": dealer_cards, "outcome": outcome, "natural": True}
        ))
        return {
            "status": "resolved",
            "player": player_cards,
            "dealer": dealer_cards,
            "outcome": outcome,
            "payout": payout,
            "balance": new_balance
        }

    # otherwise create active hand
    hand = BlackjackHand(
        username=req.username,
        bet=req.bet,
        player_cards=player_cards,
        dealer_cards=dealer_cards,
        shoe=shoe,
        status="player_turn",
        can_double=True
    )
    hand_id = create_document("blackjackhand", hand)
    return {
        "status": "player_turn",
        "player": player_cards,
        "dealer": dealer_cards,
        "bet": req.bet,
        "can_double": True,
        "hand_id": hand_id
    }


class BlackjackAction(BaseModel):
    username: str


def get_active_hand(username: str):
    col = collection("blackjackhand")
    hand = col.find_one({"username": username, "status": "player_turn"})
    if not hand:
        raise HTTPException(status_code=404, detail="No active hand")
    return hand


def resolve_and_record(username: str, bet: int, player_cards: List[str], dealer_cards: List[str]) -> Dict[str, Any]:
    p_val = hand_value(player_cards)
    d_val = hand_value(dealer_cards)
    # Dealer plays to 17, stands on soft 17
    while d_val < 17:
        dealer_cards.append(draw([]))  # draw from a fresh card if needed (should not happen). We'll handle properly below.
        d_val = hand_value(dealer_cards)
    # Compare
    if p_val > 21:
        outcome = "bust"
        payout = -bet
    elif d_val > 21 or p_val > d_val:
        outcome = "win"
        payout = bet
    elif p_val < d_val:
        outcome = "lose"
        payout = -bet
    else:
        outcome = "push"
        payout = 0
    new_balance = adjust_balance(username, payout)
    create_document("gameresult", GameResult(
        username=username,
        game="blackjack",
        bet=bet,
        payout=payout,
        balance_after=new_balance,
        details={"player": player_cards, "dealer": dealer_cards, "outcome": outcome}
    ))
    # mark hand resolved
    collection("blackjackhand").update_many({"username": username}, {"$set": {"status": "resolved"}})
    return {"outcome": outcome, "payout": payout, "balance": new_balance}


@app.post("/api/blackjack/hit")
def blackjack_hit(req: BlackjackAction):
    col = collection("blackjackhand")
    hand = get_active_hand(req.username)
    shoe = hand.get("shoe", [])
    # draw card
    if not shoe:
        shoe = make_shoe()
    card = shoe.pop()
    player_cards = hand["player_cards"] + [card]
    dealer_cards = hand["dealer_cards"]
    p_val = hand_value(player_cards)

    if p_val > 21:
        # bust resolves immediately
        col.update_one({"_id": hand["_id"]}, {"$set": {"player_cards": player_cards, "shoe": shoe, "status": "resolved"}})
        result = resolve_and_record(req.username, int(hand["bet"]), player_cards, dealer_cards)
        return {"status": "resolved", "player": player_cards, "dealer": dealer_cards, **result}
    else:
        col.update_one({"_id": hand["_id"]}, {"$set": {"player_cards": player_cards, "shoe": shoe, "can_double": False}})
        return {"status": "player_turn", "player": player_cards, "dealer": dealer_cards, "bet": hand["bet"], "can_double": False}


@app.post("/api/blackjack/stand")
def blackjack_stand(req: BlackjackAction):
    col = collection("blackjackhand")
    hand = get_active_hand(req.username)
    shoe = hand.get("shoe", [])
    dealer_cards = hand["dealer_cards"]
    if not shoe:
        shoe = make_shoe()
    # dealer plays to 17 stand on all 17
    while hand_value(dealer_cards) < 17:
        dealer_cards.append(shoe.pop())
        if not shoe:
            shoe = make_shoe()
    col.update_one({"_id": hand["_id"]}, {"$set": {"dealer_cards": dealer_cards, "shoe": shoe, "status": "resolved"}})
    result = resolve_and_record(req.username, int(hand["bet"]), hand["player_cards"], dealer_cards)
    return {"status": "resolved", "player": hand["player_cards"], "dealer": dealer_cards, **result}


@app.post("/api/blackjack/double")
def blackjack_double(req: BlackjackAction):
    col = collection("blackjackhand")
    hand = get_active_hand(req.username)
    if not hand.get("can_double", False) or len(hand.get("player_cards", [])) != 2:
        raise HTTPException(status_code=400, detail="Double not allowed now")
    # check balance can cover doubling
    current_bet = int(hand["bet"])
    if get_balance(req.username) < current_bet:
        raise HTTPException(status_code=400, detail="Insufficient balance to double")

    shoe = hand.get("shoe", [])
    if not shoe:
        shoe = make_shoe()
    # double bet, draw one, then stand and resolve
    current_bet *= 2
    player_cards = hand["player_cards"] + [shoe.pop()]
    dealer_cards = hand["dealer_cards"]

    # Dealer plays
    while hand_value(dealer_cards) < 17:
        if not shoe:
            shoe = make_shoe()
        dealer_cards.append(shoe.pop())

    # save resolution
    col.update_one({"_id": hand["_id"]}, {"$set": {"player_cards": player_cards, "dealer_cards": dealer_cards, "shoe": shoe, "status": "resolved"}})
    result = resolve_and_record(req.username, current_bet, player_cards, dealer_cards)
    return {"status": "resolved", "player": player_cards, "dealer": dealer_cards, **result}


# ----- Slots (simple for now) -----

symbols = ["🍒","🍋","🔔","⭐","7️⃣","🍀"]
weights = [30, 25, 20, 15, 7, 3]

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

# ----- Baccarat (same as before simplified rules) -----

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
