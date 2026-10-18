// Same as portfolioSummary in tradiumUtils.jsx — keep both in sync.

// Turn a day % change into rupees.
function dayChangeRupees(h) {
  const denom = 100 + h.dayChangePct;
  if (!denom) return 0; // a -100% change would divide by zero
  return h.qty * h.ltp * (h.dayChangePct / denom);
}

function calculatePortfolioSummary(holdings) {
  const invested = holdings.reduce((s, h) => s + h.qty * h.avgPrice, 0);
  const value = holdings.reduce((s, h) => s + h.qty * h.ltp, 0);
  const dayPnl = holdings.reduce((s, h) => s + dayChangeRupees(h), 0);

  // what these same holdings were worth at yesterday's close
  const prevValue = value - dayPnl;

  return {
    invested,
    value,
    pnl: value - invested,
    pnlPct: invested ? ((value - invested) / invested) * 100 : 0,
    dayPnl,
    dayPnlPct: prevValue !== 0 ? (dayPnl / prevValue) * 100 : 0,
  };
}

// Value of open MIS legs; ltp of 0 falls back to the entry price.
function misComponents(positions) {
  let misValue = 0;
  let misInvested = 0;
  for (const p of positions) {
    if (p.product !== "MIS") continue;
    const dir = p.side === "SHORT" ? -1 : 1;
    const price = p.ltp || p.entry;
    const pnl = (price - p.entry) * p.qty * dir;
    misInvested += p.qty * p.entry;
    misValue += p.qty * p.entry + pnl;
  }
  return { misValue, misInvested };
}

module.exports = { calculatePortfolioSummary, misComponents };
