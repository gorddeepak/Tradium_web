"""Port of server/data/nifty50.js.

The NIFTY 50 universe as a static list -- small enough to quote in one request.
Reviewed by the NSE twice a year; check symbols against nseindia.com if one
stops resolving.

Indices keep Yahoo's own tickers (no ``.NS`` suffix) and have no sector.
"""

# (symbol, name) in the order the Express file declares them.
NIFTY50 = [
    ("ADANIENT", "Adani Enterprises"),
    ("ADANIPORTS", "Adani Ports & SEZ"),
    ("APOLLOHOSP", "Apollo Hospitals"),
    ("ASIANPAINT", "Asian Paints"),
    ("AXISBANK", "Axis Bank"),
    ("BAJAJ-AUTO", "Bajaj Auto"),
    ("BAJFINANCE", "Bajaj Finance"),
    ("BAJAJFINSV", "Bajaj Finserv"),
    ("BEL", "Bharat Electronics"),
    ("BHARTIARTL", "Bharti Airtel"),
    ("CIPLA", "Cipla"),
    ("COALINDIA", "Coal India"),
    ("DRREDDY", "Dr. Reddy's Laboratories"),
    ("EICHERMOT", "Eicher Motors"),
    ("ETERNAL", "Eternal"),
    ("GRASIM", "Grasim Industries"),
    ("HCLTECH", "HCL Technologies"),
    ("HDFCBANK", "HDFC Bank"),
    ("HDFCLIFE", "HDFC Life Insurance"),
    ("HINDALCO", "Hindalco Industries"),
    ("HINDUNILVR", "Hindustan Unilever"),
    ("ICICIBANK", "ICICI Bank"),
    ("INDIGO", "InterGlobe Aviation"),
    ("INFY", "Infosys"),
    ("ITC", "ITC"),
    ("JIOFIN", "Jio Financial Services"),
    ("JSWSTEEL", "JSW Steel"),
    ("KOTAKBANK", "Kotak Mahindra Bank"),
    ("LT", "Larsen & Toubro"),
    ("M&M", "Mahindra & Mahindra"),
    ("MARUTI", "Maruti Suzuki India"),
    ("MAXHEALTH", "Max Healthcare Institute"),
    ("NESTLEIND", "Nestle India"),
    ("NTPC", "NTPC"),
    ("ONGC", "Oil & Natural Gas Corporation"),
    ("POWERGRID", "Power Grid Corporation"),
    ("RELIANCE", "Reliance Industries"),
    ("SBILIFE", "SBI Life Insurance"),
    ("SHRIRAMFIN", "Shriram Finance"),
    ("SBIN", "State Bank of India"),
    ("SUNPHARMA", "Sun Pharmaceutical"),
    ("TCS", "Tata Consultancy Services"),
    ("TATACONSUM", "Tata Consumer Products"),
    ("TMPV", "Tata Motors Passenger Vehicles"),
    ("TATASTEEL", "Tata Steel"),
    ("TECHM", "Tech Mahindra"),
    ("TITAN", "Titan Company"),
    ("TRENT", "Trent"),
    ("ULTRACEMCO", "UltraTech Cement"),
    ("WIPRO", "Wipro"),
]

# The indices, quoted in the same request. Yahoo's own tickers -- no .NS suffix.
INDICES = [
    ("^NSEI", "NIFTY 50"),
    ("^NSEBANK", "BANK NIFTY"),
    ("^BSESN", "SENSEX"),
]
