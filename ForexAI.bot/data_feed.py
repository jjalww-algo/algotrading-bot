import pandas as pd
from oandapyV20 import API
from oandapyV20.endpoints.instruments import InstrumentsCandles
from logger import log_info, log_error


def get_candles(account_cfg, symbol, timeframe="M5", count=200):
    """
    Fetch OHLCV candles directly from Oanda's API.
    Returns a clean pandas DataFrame.
    """
    try:
        client = API(
            access_token=account_cfg["API_KEY"],
            environment=account_cfg["ENVIRONMENT"]
        )

        params = {
            "count": count,
            "granularity": timeframe,
            "price": "M"  # midpoint prices
        }

        r = InstrumentsCandles(instrument=symbol, params=params)
        client.request(r)

        candles = r.response["candles"]

        rows = []
        for c in candles:
            if c["complete"]:
                rows.append({
                    "time": c["time"],
                    "Open": float(c["mid"]["o"]),
                    "High": float(c["mid"]["h"]),
                    "Low": float(c["mid"]["l"]),
                    "Close": float(c["mid"]["c"]),
                    "Volume": int(c["volume"])
                })

        df = pd.DataFrame(rows)
        df["time"] = pd.to_datetime(df["time"])
        df.set_index("time", inplace=True)

        log_info(f"Fetched {len(df)} candles for {symbol}")
        return df

    except Exception as e:
        log_error(f"Error fetching candles for {symbol}: {e}")
        return None
