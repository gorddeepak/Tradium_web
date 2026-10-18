const { streamText } = require('ai');
const { aiModel } = require('../config/ai');

const pageContext = {
  dashboard: "This is the user's first view after login — make it feel like a sharp, confident briefing, not a dry stat. Lead with the most notable thing (biggest gain/loss driver), not just the total.",
  holdings: "Focus on which specific holding is driving today's performance — name the symbol if one stands out.",
  positions: "Focus on risk/exposure and the single biggest mover (winner or loser), mentioning product type (CNC/MIS) if relevant.",
  orders: "Focus on execution health. Order statuses are EXECUTED, OPEN, CANCELLED and REJECTED — only OPEN orders are pending or working. Never describe a cancelled or rejected order as pending, and never lump the three non-executed statuses into one count.",
  watchlist: "Focus on the biggest mover in the tracked list and overall sentiment (more advancing or declining), not a full rundown of every symbol.",
  markets: "Focus on breadth (advancing vs declining) and the single biggest NIFTY 50 mover, naming the symbol. Mention the index level only if it moved notably."
};

// Number formatting rules given to the AI.
const FORMAT_RULES = `Number formatting:
- Currency uses ₹ and Indian digit grouping: ₹4,30,016 not ₹430,016 and never ₹4,30016.5.
- Round currency to whole rupees unless the value is under ₹100.
- Percentages get at most two decimals: 1.78%, not 1.7800000000000002%.
- Write counts as plain integers: "5 legs", not "5.0 legs".`;

const generatePageInsight = async (req, res) => {
  const { page, data } = req.body;
  // page: which dashboard page; data: that page's summary numbers

  const result = streamText({
    model: aiModel,
    system: `You write a single short insight sentence (max 25 words) for a trading dashboard.
Be specific with numbers and symbol names when available in the data. No greetings, no fluff, just the insight.
If a value is 0 or there's no notable signal, say something neutral rather than inventing detail.
End with a full stop.
${FORMAT_RULES}
${pageContext[page] || ''}`,
    prompt: `Page: ${page}\nData: ${JSON.stringify(data)}\n\nWrite one insight sentence.`,
  });

  await result.pipeTextStreamToResponse(res);
};

const generateDashboardBriefing = async (req, res) => {
  const { data } = req.body;

  const result = streamText({
    model: aiModel,
    system: `You are Tradium's portfolio assistant, writing a short daily briefing for the user's dashboard — the first thing they see after logging in.

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

${FORMAT_RULES}`,
    prompt: `Data: ${JSON.stringify(data)}\n\nWrite the briefing.`,
  });

  await result.pipeTextStreamToResponse(res);
};
module.exports = {
  generatePageInsight, generateDashboardBriefing 
};