# ND-4: Prisijungimas prie brokerio API ir prekybos operacijų vykdymas
# Autorius: Dominykas Pavlavčius
#
# Programa per Alpaca paper trading API:
#   1) prisijungia ir patikrina ryšį,
#   2) gauna realaus laiko kotiruotes, 3) gauna istorines kainas ir nubraižo grafiką,
#   4) pateikia market ir 5) limit pavedimus, 6) atšaukia pavedimą,
#   7) rodo brokerio grąžintus pavedimų ID ir būsenas.
# Instrumentas - kriptovaliuta (numatytoji BTC/USD).
# Parametrai imami iš config.json (meniu juos galima pakeisti), API raktai iš .env failo.

import json
import logging
import os
import sys
import threading
import time
from datetime import datetime, timedelta, timezone
from pathlib import Path

import matplotlib.pyplot as plt
from dotenv import load_dotenv
from alpaca.common.exceptions import APIError
from alpaca.data.enums import CryptoFeed
from alpaca.data.historical import CryptoHistoricalDataClient
from alpaca.data.live import CryptoDataStream
from alpaca.data.requests import CryptoBarsRequest, CryptoLatestTradeRequest
from alpaca.data.timeframe import TimeFrame
from alpaca.trading.client import TradingClient
from alpaca.trading.enums import OrderSide, QueryOrderStatus, TimeInForce
from alpaca.trading.requests import GetOrdersRequest, LimitOrderRequest, MarketOrderRequest

BASE_DIR = Path(__file__).parent
TIMEFRAMES = {"1Min": TimeFrame.Minute, "1Hour": TimeFrame.Hour, "1Day": TimeFrame.Day}
log = logging.info


def setup_logging(log_file):
    sys.stdout.reconfigure(encoding="utf-8")
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s  %(message)s",
        datefmt="%Y-%m-%d %H:%M:%S",
        handlers=[logging.StreamHandler(sys.stdout), logging.FileHandler(log_file, encoding="utf-8")],
    )


def value(x):
    return getattr(x, "value", x)


def ask(prompt, default, cast=str):
    while True:
        raw = input(f"{prompt} [{default}]: ").strip()
        if not raw:
            return default
        try:
            return cast(raw)
        except ValueError:
            print("  Neteisinga reikšmė, bandykite dar kartą.")


def log_order(o):
    limit = f" | limit {o.limit_price}" if o.limit_price else ""
    fill = f" | įvykdyta {o.filled_qty} @ {o.filled_avg_price}" if o.filled_avg_price else ""
    log(f"  [{o.client_order_id}] brokerio ID {o.id} | {value(o.type)} {value(o.side)} {o.qty} {o.symbol}"
        f"{limit} | būsena: {value(o.status)}{fill}")


class AlpacaBroker:
    def __init__(self, api_key, secret_key, cfg):
        self.cfg = cfg
        self.keys = (api_key, secret_key)
        self.feed = CryptoFeed(cfg["data_feed"])
        self.trading = TradingClient(api_key, secret_key, paper=cfg["paper"])
        self.data = CryptoHistoricalDataClient(api_key, secret_key)
        self.next_id = None

    # ---------- 1. Prisijungimas ----------
    def connect(self):
        acc = self.trading.get_account()
        log(f"Prisijungta prie Alpaca ({'paper' if self.cfg['paper'] else 'LIVE'}). "
            f"Paskyra {acc.account_number}, būsena: {value(acc.status)}")
        log(f"Grynieji: {acc.cash} USD | perkamoji galia: {acc.buying_power} USD")
        log(f"Kriptovaliutų prekyba: {'leidžiama' if value(acc.crypto_status) == 'ACTIVE' else value(acc.crypto_status)}")
        self.next_id = self.find_next_id()
        log(f"Kitas laisvas pavedimo ID: {self.cfg['order_prefix']}-{self.next_id}")

    def find_next_id(self):
        prefix = self.cfg["order_prefix"] + "-"
        orders = self.trading.get_orders(GetOrdersRequest(status=QueryOrderStatus.ALL, limit=500))
        used = [int(o.client_order_id[len(prefix):]) for o in orders
                if o.client_order_id.startswith(prefix) and o.client_order_id[len(prefix):].isdigit()]
        return max(used, default=0) + 1

    def new_order_id(self):
        order_id = f"{self.cfg['order_prefix']}-{self.next_id}"
        self.next_id += 1
        return order_id

    def last_trade(self, symbol):
        trades = self.data.get_crypto_latest_trade(CryptoLatestTradeRequest(symbol_or_symbols=symbol), feed=self.feed)
        return trades[symbol]

    # ---------- 2. Realaus laiko duomenys ----------
    def stream_quotes(self, symbol, seconds):
        stream = CryptoDataStream(*self.keys, feed=self.feed)
        received = 0

        async def on_quote(q):
            nonlocal received
            received += 1
            delay = max((datetime.now(timezone.utc) - q.timestamp).total_seconds(), 0)
            log(f"  {q.timestamp.astimezone():%H:%M:%S} {symbol} pirkimo (bid) {q.bid_price:.2f} USD, kiekis {q.bid_size:.5f} | "
                f"pardavimo (ask) {q.ask_price:.2f} USD, kiekis {q.ask_size:.5f} | vėlavimas {delay:.1f} s")

        stream.subscribe_quotes(on_quote, symbol)
        timer = threading.Timer(seconds, stream.stop)
        timer.daemon = True
        timer.start()
        log(f"Klausomasi {symbol} kotiruočių {seconds} s (šaltinis: {self.feed.value.upper()})...")
        stream.run()
        log(f"Gauta kotiruočių: {received}")

        if received == 0:
            t = self.last_trade(symbol)
            age_min = (datetime.now(timezone.utc) - t.timestamp).total_seconds() / 60
            log(f"Naujų kotiruočių negauta. Paskutinis sandoris: "
                f"{t.price} USD, {t.timestamp.astimezone():%Y-%m-%d %H:%M:%S} (duomenys VĖLUOJA {age_min:.0f} min)")

    # ---------- 3. Istoriniai duomenys ----------
    def history(self, symbol, days, timeframe):
        end = datetime.now(timezone.utc)
        request = CryptoBarsRequest(symbol_or_symbols=symbol, timeframe=TIMEFRAMES[timeframe],
                                    start=end - timedelta(days=days), end=end)
        bars = self.data.get_crypto_bars(request, feed=self.feed).df
        if bars.empty:
            log(f"Istorinių duomenų {symbol} nerasta.")
            return
        bars = bars.loc[symbol]
        log(f"Gauta {len(bars)} žvakių ({timeframe}) {symbol}: {bars.index[0]:%Y-%m-%d} - {bars.index[-1]:%Y-%m-%d}")
        log("Paskutinės 10 žvakių:\n" + bars[["open", "high", "low", "close", "volume"]].tail(10).to_string())

        plt.figure(figsize=(10, 5))
        plt.plot(bars.index, bars["close"])
        plt.title(f"{symbol} uždarymo kainos, paskutinės {days} d. ({timeframe}, {self.feed.value.upper()})")
        plt.xlabel("Data")
        plt.ylabel("Kaina, USD")
        plt.grid(True)
        plt.tight_layout()
        file_name = f"istoriniai_{symbol.replace('/', '-')}.png"
        plt.savefig(file_name)
        log(f"Grafikas išsaugotas: {file_name} (uždarykite langą, kad grįžtumėte į meniu)")
        plt.show()

    # ---------- 4-5. Market ir limit pavedimai ----------
    def place_order(self, order_type, symbol, qty, side, limit_price=None):
        params = dict(symbol=symbol, qty=qty, side=OrderSide(side),
                      time_in_force=TimeInForce(self.cfg["time_in_force"]),
                      client_order_id=self.new_order_id())
        if order_type == "market":
            request = MarketOrderRequest(**params)
        else:
            request = LimitOrderRequest(**params, limit_price=limit_price)

        order = self.trading.submit_order(request)
        log(f"Brokeris priėmė {order_type} pavedimą:")
        log_order(order)
        self.log_status_later(order)

    def log_status_later(self, order):
        wait = self.cfg["status_wait_seconds"]
        time.sleep(wait)
        log(f"Būsena po {wait} s:")
        log_order(self.trading.get_order_by_id(order.id))

    # ---------- 6. Atšaukimas ----------
    def cancel_order(self, client_order_id):
        order = self.trading.get_order_by_client_id(client_order_id)
        self.trading.cancel_order_by_id(order.id)
        log(f"Atšaukimo užklausa pavedimui {client_order_id} išsiųsta.")
        self.log_status_later(order)

    # ---------- 7. Pavedimų būsenos ----------
    def show_orders(self, status, limit):
        orders = self.trading.get_orders(GetOrdersRequest(status=QueryOrderStatus(status), limit=limit))
        log(f"Pavedimai ({status}), rasta {len(orders)}:")
        for o in orders:
            log_order(o)
        return orders


MENU = """
========== ND-4 · Alpaca ==========
1 - Ryšio ir paskyros patikrinimas
2 - Realaus laiko kainos
3 - Istoriniai duomenys + grafikas
4 - Market pavedimas
5 - Limit pavedimas
6 - Atšaukti pavedimą
7 - Pavedimų būsenos
0 - Išeiti"""


def limit_order_dialog(broker, cfg):
    symbol = ask("Simbolis", cfg["symbol"]).upper()
    qty = ask("Kiekis", cfg["qty"], float)
    side = ask("Kryptis (buy/sell)", cfg["side"], str.lower)
    last = broker.last_trade(symbol).price
    shift = -cfg["limit_offset_pct"] if side == "buy" else cfg["limit_offset_pct"]
    default_price = round(last * (1 + shift / 100))
    log(f"Paskutinė {symbol} kaina: {last} USD")
    price = ask("Limit kaina", default_price, float)
    broker.place_order("limit", symbol, qty, side, limit_price=price)


def cancel_dialog(broker, cfg):
    open_orders = broker.show_orders("open", cfg["orders_to_show"])
    if not open_orders:
        log("Nėra neįvykdytų pavedimų, kuriuos būtų galima atšaukti.")
        return
    broker.cancel_order(ask("Kurį pavedimą atšaukti (mūsų ID)", open_orders[0].client_order_id))


def run_menu(broker, cfg):
    while True:
        print(MENU)
        choice = input("Pasirinkite: ").strip()
        if choice == "0":
            break
        try:
            if choice == "1":
                broker.connect()
            elif choice == "2":
                broker.stream_quotes(ask("Simbolis", cfg["symbol"]).upper(),
                                     ask("Kiek sekundžių klausytis", cfg["stream_seconds"], int))
            elif choice == "3":
                broker.history(ask("Simbolis", cfg["symbol"]).upper(),
                               ask("Kiek dienų atgal", cfg["history_days"], int),
                               ask(f"Intervalas {list(TIMEFRAMES)}", cfg["history_timeframe"]))
            elif choice == "4":
                broker.place_order("market", ask("Simbolis", cfg["symbol"]).upper(),
                                   ask("Kiekis", cfg["qty"], float),
                                   ask("Kryptis (buy/sell)", cfg["side"], str.lower))
            elif choice == "5":
                limit_order_dialog(broker, cfg)
            elif choice == "6":
                cancel_dialog(broker, cfg)
            elif choice == "7":
                broker.show_orders(ask("Kokie (open/closed/all)", "all", str.lower), cfg["orders_to_show"])
            else:
                print("Nėra tokio pasirinkimo.")
        except APIError as e:
            log(f"BROKERIO KLAIDA: {e}")
        except (ValueError, KeyError) as e:
            log(f"Neteisingas parametras: {e}")
        except Exception as e:
            log(f"KLAIDA: {type(e).__name__}: {e}")


def main():
    with open(BASE_DIR / "config.json", encoding="utf-8") as f:
        cfg = json.load(f)
    setup_logging(cfg["log_file"])
    load_dotenv(BASE_DIR / ".env")

    api_key = os.getenv("ALPACA_API_KEY")
    secret_key = os.getenv("ALPACA_SECRET_KEY")
    if not api_key or not secret_key:
        sys.exit("Nerasti API raktai. Nukopijuokite .env.example į .env ir įrašykite savo raktus.")

    broker = AlpacaBroker(api_key, secret_key, cfg)
    try:
        broker.connect()
    except Exception as e:
        sys.exit(f"Nepavyko prisijungti prie Alpaca: {e}")
    run_menu(broker, cfg)


if __name__ == "__main__":
    main()
