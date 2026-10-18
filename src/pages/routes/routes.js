export const ROUTES = {
  home: "/",
  login: "/login",
  signup: "/signup",
  dashboard: "/dashboard",
  watchlist: "/dashboard/watchlist",
  funds: "/dashboard/funds",
  holdings: "/dashboard/holdings",
  positions: "/dashboard/positions",
  orders: "/dashboard/orders",
  markets: "/dashboard/markets",
  // The instrument view is a nested route inside the watchlist, not a page of
  // its own — selecting a symbol keeps the watchlist rail on screen.
  instrument: (symbol) => `/dashboard/watchlist/${symbol}`,
};

