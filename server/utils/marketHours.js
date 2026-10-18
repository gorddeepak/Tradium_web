// Deliberate duplicate of isMarketOpen() in src/services/marketStatus.js — keep
// the two in sync. No holiday calendar: on holidays Yahoo just serves the last close.
function isMarketOpen() {
  const now = new Date();
  const istNow = new Date(now.toLocaleString("en-US", { timeZone: "Asia/Kolkata" }));
  const day = istNow.getDay(); // 0 = Sunday, 6 = Saturday
  if (day === 0 || day === 6) return false;

  const totalMinutes = istNow.getHours() * 60 + istNow.getMinutes();
  const marketOpen = 9 * 60 + 15;  // 9:15 AM
  const marketClose = 15 * 60 + 30; // 3:30 PM
  return totalMinutes >= marketOpen && totalMinutes <= marketClose;
}

module.exports = { isMarketOpen };
