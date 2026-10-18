const { streamText, tool, convertToModelMessages, stepCountIs } = require('ai');
const { aiModel } = require('../config/ai');
const { z } = require('zod');
const { HoldingsModel: Holding } = require('../models/HoldingsModel');
const { PositionsModel: Position } = require('../models/PositionsModel');
const { OrdersModel: Order } = require('../models/OrdersModel');
const { calculatePortfolioSummary } = require('../utils/portfolioMath');
const { WatchlistModel: Watchlist } = require('../models/WatchlistModel');
const { FundsModel: Funds } = require('../models/FundsModel');

const chatWithAssistant = async (req, res) => {
  try {
    const { messages } = req.body;
    const userId = req.userId;

    if (!Array.isArray(messages)) {
      console.error('chatWithAssistant error: expected messages array', messages);
      return res.status(400).json({ error: 'Invalid messages payload' });
    }

    const modelMessages = await convertToModelMessages(messages);

    const result = streamText({
      model: aiModel,
      system: `You are Nova, the portfolio assistant built into Tradium — a sharp, sharp-eyed trading-desk analyst the user can talk to about their account.

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
- If asked about something outside portfolio/positions/orders/watchlist/funds/market news, say plainly that's outside what you can help with here`,
      messages: modelMessages,
      stopWhen: stepCountIs(5),
      tools: {
        getPortfolioSummary: tool({
          description: "Get the user's current portfolio summary: total value, day's P&L, overall P&L, and top movers.",
          parameters: z.object({}),
          execute: async () => {
            const holdings = await Holding.find({ user: userId });
            const summaryNumbers = calculatePortfolioSummary(holdings);
            const invested = Math.round(summaryNumbers.invested || 0);
            const value = Math.round(summaryNumbers.value || 0);
            const pnl = Math.round(summaryNumbers.pnl || 0);
            const pnlPct = (summaryNumbers.pnlPct || 0).toFixed(2);

            // top mover by absolute day change percent
            let topMover = null;
            if (Array.isArray(holdings) && holdings.length) {
              const sorted = [...holdings].sort((a, b) => Math.abs(b.dayChangePct || 0) - Math.abs(a.dayChangePct || 0));
              const h = sorted[0];
              topMover = h ? `${h.symbol} (${(h.dayChangePct || 0).toFixed(2)}%)` : null;
            }

            const summary = `Portfolio ₹${value} (invested ₹${invested}), P&L ₹${pnl} (${pnlPct}%). Top mover: ${topMover || 'none'}.`;

            return { data: summaryNumbers, summary, holdingsCount: holdings.length };
          },
        }),

        getHoldings: tool({
          description: "Get the user's current holdings with symbol, name, exchange, quantity, average price, last traded price, and today's change.",
          parameters: z.object({}),
          execute: async () => {
            const holdings = await Holding.find({ user: userId });
            const items = holdings.map((h) => ({
              symbol: h.symbol,
              name: h.name,
              exchange: h.exchange,
              quantity: h.qty,
              avgPrice: h.avgPrice,
              ltp: h.ltp,
              dayChangePct: h.dayChangePct,
            }));

            // compute total value and top holding
            const totalValue = items.reduce((s, it) => s + (it.quantity || 0) * (it.ltp || 0), 0);
            const top = items.length ? items.slice().sort((a, b) => (b.quantity * b.ltp) - (a.quantity * a.ltp))[0] : null;
            const summary = `Holdings ${items.length} items, total value ₹${Math.round(totalValue)}${top ? `; top: ${top.symbol} ${top.quantity}@${top.ltp}` : ''}`;

            return { data: items, summary };
          },
        }),

        getPositions: tool({
          description: "Get the user's open positions (intraday/derivatives), with product type (CNC/MIS), quantity, entry price, current price, and current P&L.",
          parameters: z.object({}),
          execute: async () => {
            const positions = await Position.find({ user: userId });
            const items = positions.map((p) => ({
              symbol: p.symbol,
              product: p.product,
              quantity: p.qty,
              entryPrice: p.entry,
              currentPrice: p.ltp,
              pnl: (p.ltp || 0) * (p.qty || 0) - (p.entry || 0) * (p.qty || 0),
            }));

            const totalExposure = items.reduce((s, it) => s + (it.quantity || 0) * (it.currentPrice || 0), 0);
            const biggest = items.length ? items.slice().sort((a, b) => Math.abs(b.pnl) - Math.abs(a.pnl))[0] : null;
            const summary = `Positions ${items.length} open, exposure ₹${Math.round(totalExposure)}${biggest ? `; biggest: ${biggest.symbol} P&L ₹${Math.round(biggest.pnl)}` : ''}`;

            return { data: items, summary };
          },
        }),


        getWatchlist: tool({
          description: "Get the user's tracked watchlist symbols with current price and today's change.",
          parameters: z.object({}),
          execute: async () => {
            const watchlist = await Watchlist.find({ user: userId });
            const items = watchlist.map((w) => ({
              symbol: w.symbol,
              ltp: w.ltp,
              dayChangePct: w.dayChangePct,
            }));
            const topMover = items.length
              ? items.slice().sort((a, b) => Math.abs(b.dayChangePct || 0) - Math.abs(a.dayChangePct || 0))[0]
              : null;
            const summary = `Watchlist ${items.length} symbols${topMover ? `; biggest mover: ${topMover.symbol} (${topMover.dayChangePct?.toFixed(2)}%)` : ''}`;
            return { data: items, summary };
          },
        }),

        getFunds: tool({
          description: "Get the user's available margin, used margin, and total balance.",
          parameters: z.object({}),
          execute: async () => {
            const funds = await Funds.findOne({ user: userId });
            const summary = funds
              ? `Available margin ₹${Math.round(funds.available)}, used ₹${Math.round(funds.used || 0)}`
              : 'No funds data available.';
            return { data: funds, summary };
          },
        }),
        getOrders: tool({
          description: "Get the user's recent orders. Can filter by status (pending, executed, cancelled) or by date range if the user mentions 'today', 'this week', etc.",
          parameters: z.object({
            status: z.enum(['pending', 'executed', 'cancelled', 'all']).default('all')
              .describe("Filter orders by status; use 'all' if the user didn't specify"),
            limit: z.number().default(10).describe("How many recent orders to return"),
          }),
          execute: async ({ status, limit }) => {
            const filter = { user: userId };
            if (status !== 'all') filter.status = status;
            const orders = await Order.find(filter).sort({ createdAt: -1 }).limit(limit);
            const items = orders.map((o) => ({
              symbol: o.symbol,
              type: o.type,
              quantity: o.quantity,
              price: o.price,
              status: o.status,
              createdAt: o.createdAt,
            }));
            const latest = items[0];
            const summary = `Orders ${items.length} ${status === 'all' ? 'recent' : status}${latest ? `; latest: ${latest.symbol} ${latest.type} ${latest.quantity}@₹${latest.price}` : ''}`;
            return { data: items, summary };
          },
        }),
      },
    });

    await result.pipeUIMessageStreamToResponse(res);
  } catch (err) {
    console.error('chatWithAssistant error:', err);
    res.status(500).json({ error: err.message });
  }
};


module.exports = {
  chatWithAssistant,
};