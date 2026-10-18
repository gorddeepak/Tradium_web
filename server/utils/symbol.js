// NSE-only app: indices use Yahoo's own ticker (starting with ^), stocks get .NS
function tickerFor(symbol) {
  // Indices start with ^, so we don't append .NS
  if (symbol.startsWith('^')) {
    return symbol;
  }
  return `${symbol}.NS`;
}

module.exports = { tickerFor };
