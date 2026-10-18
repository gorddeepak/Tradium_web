// Single source of truth for the API origin. Local dev talks to the separate
// backend on port 3002; a production build is served by the backend itself,
// so it just uses its own origin with the /api prefix.
export const BASE_URL =
  import.meta.env.VITE_API_URL ||
  (import.meta.env.DEV ? "http://localhost:3002/api" : "/api");

async function request(path, options = {}) {
  const res = await fetch(`${BASE_URL}${path}`, {
    credentials: "include",
    headers: { "Content-Type": "application/json" },
    ...options,
  });
  if (!res.ok) {
    const body = await res.json().catch(() => ({}));
    throw new Error(body.message || `Request failed: ${res.status}`);
  }
  if (res.status === 204) return null;
  return res.json();
}

export const getHoldings = () => request("/holdings");
export const getPositions = () => request("/positions");
export const squareOffPosition = (id) => request(`/positions/${id}/square-off`, { method: "POST" });
export const getOrders = () => request("/orders");
export const placeOrder = (order) =>
  request("/orders", { method: "POST", body: JSON.stringify(order) });
export const placeExitRules = (payload) =>
  request("/orders/exits", { method: "POST", body: JSON.stringify(payload) });
export const cancelOrder = (id) =>
  request(`/orders/${id}`, { method: "DELETE" });
export const getWatchlist = () => request("/watchlist");
export const addToWatchlist = (item) =>
  request("/watchlist", { method: "POST", body: JSON.stringify(item) });
export const removeFromWatchlist = (id) =>
  request(`/watchlist/${id}`, { method: "DELETE" });
export const getFunds = () => request("/funds");
export const getPortfolioHistory = (range) => request(`/portfolio/history?range=${range}`);
export const lookupInstrument = (symbol, exchange = "NSE") =>
  request(`/instruments/lookup/${symbol}?exchange=${exchange}`);
export const searchInstruments = (q) =>
  request(`/instruments/search?q=${encodeURIComponent(q)}`);
export const getTransactions = () => request("/funds/transactions");
export const createTransaction = (payload) =>
  request("/funds/transactions", { method: "POST", body: JSON.stringify(payload) });
export const getInstrument = (symbol, exchange = "NSE") =>
  request(`/instruments/${symbol}?exchange=${exchange}`);
export const getCandles = (symbol, range, exchange = "NSE") =>
  request(`/instruments/${symbol}/candles?exchange=${exchange}&range=${range}`);
// Reads the server's NIFTY 50 cache. One call returns all 53 rows; breadth,
// gainers, losers and most-active are derived from them on the client.
export const getMarketOverview = () => request("/market/overview");

