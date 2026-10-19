"""Nova: the Gemini-backed assistant and its read-only portfolio tools.

This is the FastAPI port of server/controllers/assistantController.js and
server/controllers/insightController.js. The prompts and tool descriptions are
kept verbatim because they are behaviour. The tools only read data for the user
resolved from the JWT; a user id is never accepted as a tool argument.
"""

import json
import math
from dataclasses import dataclass
from typing import Literal

from bson import ObjectId
from pydantic_ai import Agent, RunContext
from pydantic_ai.models.google import GoogleModel
from pydantic_ai.providers.google import GoogleProvider
from pymongo.database import Database

from .config import get_ai_settings
from .js_compat import format_inr
from .portfolio_math import calculate_portfolio_summary
from .serialization import to_json_value

CHAT_SYSTEM_PROMPT = """You are Nova, the portfolio assistant built into Tradium — a sharp, sharp-eyed trading-desk analyst the user can talk to about their account.

PERSONALITY
- Confident, direct, a little dry — like a good analyst who respects the user's time
- Never generic or robotic. Never say "As an AI..." or "I'd be happy to help!"
- You have opinions about what's worth noticing, even if you can't give investment advice

HOW TO ANSWER
- Always ground answers in tool data — never guess numbers
- After giving the requested info, add ONE brief, genuinely useful observation or follow-up when it's relevant — not on every single reply, only when there's something worth flagging (e.g. a position close to a stop-loss zone, a stock unusually flat, exposure concentrated in one sector)
- If a question is ambiguous, ask a short clarifying question rather than assuming
- If the answer naturally invites a next step, offer it briefly — e.g. after showing holdings, "Want me to check which of these moved the most today?" — but don't force this onto every reply
- Use ₹ for currency
- Keep replies tight — a few sentences, not paragraphs, unless the user is asking for a full rundown

BOUNDARIES
- Never give investment advice ("you should buy/sell X") — you can point out facts and patterns, not recommend action
- If asked about something outside portfolio/positions/orders/watchlist/funds/market news, say plainly that's outside what you can help with here"""

PAGE_CONTEXT = {
    "dashboard": "This is the user's first view after login — make it feel like a sharp, confident briefing, not a dry stat. Lead with the most notable thing (biggest gain/loss driver), not just the total.",
    "holdings": "Focus on which specific holding is driving today's performance — name the symbol if one stands out.",
    "positions": "Focus on risk/exposure and the single biggest mover (winner or loser), mentioning product type (CNC/MIS) if relevant.",
    "orders": "Focus on execution health. Order statuses are EXECUTED, OPEN, CANCELLED and REJECTED — only OPEN orders are pending or working. Never describe a cancelled or rejected order as pending, and never lump the three non-executed statuses into one count.",
    "watchlist": "Focus on the biggest mover in the tracked list and overall sentiment (more advancing or declining), not a full rundown of every symbol.",
    "markets": "Focus on breadth (advancing vs declining) and the single biggest NIFTY 50 mover, naming the symbol. Mention the index level only if it moved notably.",
}

FORMAT_RULES = """Number formatting:
- Currency uses ₹ and Indian digit grouping: ₹4,30,016 not ₹430,016 and never ₹4,30016.5.
- Round currency to whole rupees unless the value is under ₹100.
- Percentages get at most two decimals: 1.78%, not 1.7800000000000002%.
- Write counts as plain integers: "5 legs", not "5.0 legs"."""

BRIEFING_SYSTEM_PROMPT = f"""You are Tradium's portfolio assistant, writing a short daily briefing for the user's dashboard — the first thing they see after logging in.

Write like a sharp, calm trading-desk analyst giving a 2-3 sentence morning briefing. Not a chatbot greeting, not a stat dump.

Rules:
- Address the user by name naturally if given (e.g. "Deepak, ..." or weave it in, don't force "Hi Deepak!" as a greeting)
- Lead with the single most important thing today — biggest mover, standout gain or loss — not the total first
- Mention the overall number (day P&L) but as supporting context, not the headline
- If something stands out (a big winner, a notable loss, unusual order activity), name it specifically with the symbol
- If nothing stands out (flat day, no notable movers), say so plainly and briefly rather than inventing drama
- Max 2-3 short sentences, no bullet points, no markdown
- Confident and direct tone — this is a briefing, not small talk
- Never use exclamation marks or generic enthusiasm ("Great job!", "Looking good!")

{FORMAT_RULES}"""


class AINotConfigured(RuntimeError):
    """Raised when no Gemini API key is present."""


@dataclass
class NovaDeps:
    db: Database
    user_id: str


def get_ai_model():
    """Build the shared Gemini model from environment configuration."""
    settings = get_ai_settings()
    if not settings.api_key:
        raise AINotConfigured("GOOGLE_GENERATIVE_AI_API_KEY is not set")
    return GoogleModel(settings.model, provider=GoogleProvider(api_key=settings.api_key))


def _js_round(value):
    """Reproduce Math.round, whose halves round towards positive infinity."""
    return math.floor(value + 0.5)


def _json_text(value):
    """Match JSON.stringify: no spaces, and don't escape non-ASCII text."""
    return json.dumps(value, separators=(",", ":"), ensure_ascii=False)


def _user_object_id(user_id):
    return ObjectId(user_id)


def insight_system_prompt(page):
    return f"""You write a single short insight sentence (max 25 words) for a trading dashboard.
Be specific with numbers and symbol names when available in the data. No greetings, no fluff, just the insight.
If a value is 0 or there's no notable signal, say something neutral rather than inventing detail.
End with a full stop.
{FORMAT_RULES}
{PAGE_CONTEXT.get(page, "")}"""


def insight_user_prompt(page, data):
    return f"Page: {page}\nData: {_json_text(data)}\n\nWrite one insight sentence."


def briefing_user_prompt(data):
    return f"Data: {_json_text(data)}\n\nWrite the briefing."


def portfolio_snapshot(db, user_id):
    """Data and summary for the getPortfolioSummary tool."""
    holdings = list(db["holdings"].find({"user": _user_object_id(user_id)}))
    numbers = calculate_portfolio_summary(holdings)

    invested = _js_round(numbers["invested"] or 0)
    value = _js_round(numbers["value"] or 0)
    pnl = _js_round(numbers["pnl"] or 0)
    pnl_pct = f"{numbers['pnlPct'] or 0:.2f}"

    top_mover = None
    if holdings:
        sorted_holdings = sorted(
            holdings,
            key=lambda holding: abs(holding.get("dayChangePct") or 0),
            reverse=True,
        )
        holding = sorted_holdings[0]
        top_mover = f"{holding.get('symbol')} ({(holding.get('dayChangePct') or 0):.2f}%)"

    summary = (
        f"Portfolio ₹{format_inr(value)} (invested ₹{format_inr(invested)}), "
        f"P&L ₹{format_inr(pnl)} ({pnl_pct}%). Top mover: {top_mover or 'none'}."
    )

    return {"data": numbers, "summary": summary, "holdingsCount": len(holdings)}


def holdings_snapshot(db, user_id):
    """Data and summary for the getHoldings tool."""
    holdings = list(db["holdings"].find({"user": _user_object_id(user_id)}))
    items = [
        {
            "symbol": holding.get("symbol"),
            "name": holding.get("name"),
            "exchange": holding.get("exchange"),
            "quantity": holding.get("qty"),
            "avgPrice": holding.get("avgPrice"),
            "ltp": holding.get("ltp"),
            "dayChangePct": holding.get("dayChangePct"),
        }
        for holding in holdings
    ]

    total_value = sum(
        (item.get("quantity") or 0) * (item.get("ltp") or 0) for item in items
    )
    top = (
        sorted(
            items,
            key=lambda item: (item.get("quantity") or 0) * (item.get("ltp") or 0),
            reverse=True,
        )[0]
        if items
        else None
    )
    summary = f"Holdings {len(items)} items, total value ₹{format_inr(_js_round(total_value))}"
    if top:
        summary += f"; top: {top['symbol']} {top['quantity']}@{top['ltp']}"

    return {"data": items, "summary": summary}


def positions_snapshot(db, user_id):
    """Data and summary for the getPositions tool."""
    positions = list(db["positions"].find({"user": _user_object_id(user_id)}))
    items = []
    for position in positions:
        direction = -1 if position.get("side") == "SHORT" else 1
        quantity = position.get("qty") or 0
        entry = position.get("entry") or 0
        current = position.get("ltp") or 0
        items.append(
            {
                "symbol": position.get("symbol"),
                "side": position.get("side"),
                "product": position.get("product"),
                "quantity": quantity,
                "entryPrice": entry,
                "currentPrice": current,
                "pnl": (current - entry) * quantity * direction,
            }
        )

    total_exposure = sum(
        abs((item.get("quantity") or 0) * (item.get("currentPrice") or 0))
        for item in items
    )
    biggest = (
        sorted(items, key=lambda item: abs(item.get("pnl") or 0), reverse=True)[0]
        if items
        else None
    )
    summary = f"Positions {len(items)} open, exposure ₹{format_inr(_js_round(total_exposure))}"
    if biggest:
        summary += f"; biggest: {biggest['symbol']} P&L ₹{format_inr(_js_round(biggest['pnl']))}"

    return {"data": items, "summary": summary}


def watchlist_snapshot(db, user_id):
    """Data and summary for the getWatchlist tool."""
    watchlist = list(db["watchlist"].find({"user": _user_object_id(user_id)}))
    items = [
        {
            "symbol": stock.get("symbol"),
            "ltp": stock.get("ltp"),
            "dayChangePct": stock.get("dayChangePct"),
        }
        for stock in watchlist
    ]

    top_mover = (
        sorted(
            items,
            key=lambda item: abs(item.get("dayChangePct") or 0),
            reverse=True,
        )[0]
        if items
        else None
    )
    summary = f"Watchlist {len(items)} symbols"
    if top_mover:
        summary += (
            f"; biggest mover: {top_mover['symbol']} "
            f"({(top_mover.get('dayChangePct') or 0):.2f}%)"
        )

    return {"data": items, "summary": summary}


def funds_snapshot(db, user_id):
    """Data and summary for the getFunds tool.

    ``usedMargin`` is derived exactly as server/routes/fundsRoutes.js does; it
    is not a stored field.
    """
    user = _user_object_id(user_id)
    funds = db["funds"].find_one({"user": user})
    available = (funds or {}).get("available") or 0

    open_orders = list(db["orders"].find({"user": user, "status": "OPEN"}))
    blocked_in_orders = sum(
        ((order.get("qty") or 0) - (order.get("filled") or 0)) * (order.get("price") or 0)
        for order in open_orders
        if not order.get("isExit")
        and (order.get("side") == "BUY" or order.get("product") == "MIS")
    )

    positions = list(db["positions"].find({"user": user, "product": "MIS"}))
    mis_margin = sum(
        (position.get("entry") or 0) * (position.get("qty") or 0) for position in positions
    )

    settlements = list(db["transactions"].find({"user": user, "kind": "SETTLEMENT"}))
    realized_pnl = sum((settlement.get("amount") or 0) for settlement in settlements)

    used_margin = blocked_in_orders + mis_margin
    data = {
        "available": available,
        "usedMargin": used_margin,
        "blockedInOrders": blocked_in_orders,
        "misMargin": mis_margin,
        "realizedPnl": realized_pnl,
    }
    summary = (
        f"Available margin ₹{format_inr(_js_round(available))}, "
        f"used ₹{format_inr(_js_round(used_margin))} "
        f"(orders ₹{format_inr(_js_round(blocked_in_orders))}, "
        f"MIS ₹{format_inr(_js_round(mis_margin))}), "
        f"realized P&L ₹{format_inr(_js_round(realized_pnl))}."
    )
    return {"data": data, "summary": summary}


def orders_snapshot(db, user_id, status="all", limit=10):
    """Data and summary for the getOrders tool.

    Stored statuses are uppercase, while the tool's public filter is lowercase.
    The schema field is ``qty``, not ``quantity``.
    """
    query = {"user": _user_object_id(user_id)}
    if status != "all":
        query["status"] = {
            "pending": "OPEN",
            "executed": "EXECUTED",
            "cancelled": "CANCELLED",
        }[status]

    safe_limit = max(1, min(int(limit), 50))
    orders = list(
        db["orders"].find(query).sort("createdAt", -1).limit(safe_limit)
    )
    items = []
    for order in orders:
        item = {
            "symbol": order.get("symbol"),
            "type": order.get("type"),
            "quantity": order.get("qty"),
            "price": order.get("price"),
            "status": order.get("status"),
        }
        if order.get("createdAt") is not None:
            item["createdAt"] = to_json_value(order["createdAt"])
        items.append(item)

    latest = items[0] if items else None
    summary = f"Orders {len(items)} {'recent' if status == 'all' else status}"
    if latest:
        summary += (
            f"; latest: {latest['symbol']} {latest['type']} "
            f"{latest['quantity']}@₹{latest['price']}"
        )

    return {"data": items, "summary": summary}


# The agent is module-level so the tool schemas are registered once. The model,
# deps and step limit are supplied per request by the route.
chat_agent = Agent(None, deps_type=NovaDeps, system_prompt=CHAT_SYSTEM_PROMPT)
plain_agent = Agent(None)


@chat_agent.tool(name="getPortfolioSummary")
def get_portfolio_summary(ctx: RunContext[NovaDeps]) -> dict:
    """Get the user's current portfolio summary: total value, day's P&L, overall P&L, and top movers."""
    return portfolio_snapshot(ctx.deps.db, ctx.deps.user_id)


@chat_agent.tool(name="getHoldings")
def get_holdings(ctx: RunContext[NovaDeps]) -> dict:
    """Get the user's current holdings with symbol, name, exchange, quantity, average price, last traded price, and today's change."""
    return holdings_snapshot(ctx.deps.db, ctx.deps.user_id)


@chat_agent.tool(name="getPositions")
def get_positions(ctx: RunContext[NovaDeps]) -> dict:
    """Get the user's open positions (intraday/derivatives), with product type (CNC/MIS), quantity, entry price, current price, and current P&L."""
    return positions_snapshot(ctx.deps.db, ctx.deps.user_id)


@chat_agent.tool(name="getWatchlist")
def get_watchlist(ctx: RunContext[NovaDeps]) -> dict:
    """Get the user's tracked watchlist symbols with current price and today's change."""
    return watchlist_snapshot(ctx.deps.db, ctx.deps.user_id)


@chat_agent.tool(name="getFunds")
def get_funds(ctx: RunContext[NovaDeps]) -> dict:
    """Get the user's available margin, used margin, and total balance."""
    return funds_snapshot(ctx.deps.db, ctx.deps.user_id)


@chat_agent.tool(name="getOrders")
def get_orders(
    ctx: RunContext[NovaDeps],
    status: Literal["pending", "executed", "cancelled", "all"] = "all",
    limit: int = 10,
) -> dict:
    """Get the user's recent orders. Can filter by status (pending, executed, cancelled) or by date range if the user mentions 'today', 'this week', etc.

    Args:
        status: Filter orders by status; use 'all' if the user didn't specify.
        limit: How many recent orders to return.
    """
    return orders_snapshot(ctx.deps.db, ctx.deps.user_id, status=status, limit=limit)
