"""Broker adapters: masters parsed from real-format slices of each broker's public file
(captured 21 Nov 2026), cross-broker consistency, order payloads and mocked API calls."""

import datetime as dt
import hashlib
import json
from pathlib import Path

import pytest

from nsefno import orders
from nsefno.brokers import REGISTRY, OrderIntent, get_broker
from nsefno.brokers.base import detect_oi_unit
from nsefno.errors import ComplianceBlock, ConfigError
from nsefno.instruments import InstrumentMaster
from nsefno.session import IST

FX = Path(__file__).parent / "fixtures" / "brokers"
TODAY = dt.date(2026, 11, 21)
FILES = {
    "upstox": [("NFO", "upstox_NSE.json"), ("BFO", "upstox_BSE.json")],
    "dhan": [("ALL", "dhan.csv")],
    "fyers": [("NFO", "fyers_NSE_FO.csv"), ("BFO", "fyers_BSE_FO.csv")],
    "angel": [("ALL", "angel.json")],
    "groww": [("ALL", "groww.csv")],
    "shoonya": [("NFO", "shoonya_NFO.zip"), ("BFO", "shoonya_BFO.zip")],
    "breeze": [("ALL", "breeze_SecurityMaster.zip")],
    "fivepaisa": [("NFO", "fivepaisa_NSE_FO.csv"), ("BFO", "fivepaisa_BSE_FO.csv")],
    "aliceblue": [("NFO", "aliceblue_NFO.json"), ("BFO", "aliceblue_BFO.json")],
}


def load(name):
    b = get_broker(name)
    items = []
    for ex, fn in FILES[name]:
        items += b.parse_master((FX / fn).read_bytes(), ex)
    return b, InstrumentMaster(items, name, TODAY)


@pytest.fixture(params=sorted(FILES))
def bm(request):
    return (request.param, *load(request.param))


# ------------------------------------------------------------------ masters

def test_master_contract_facts(bm):
    name, _, m = bm
    nov23, nov26, jan28 = dt.date(2026, 11, 23), dt.date(2026, 11, 26), dt.date(2027, 1, 28)
    assert nov23 in m.expiries("NIFTY"), name                     # 24 Nov holiday -> Mon 23 Nov
    assert m.lot_size("NIFTY", nov23) == 65, name
    assert m.lot_size("BANKNIFTY", nov23) == 30, name
    assert m.lot_size("SENSEX", nov26) == 20, name                # live lot transition 20 -> 25
    assert m.lot_size("SENSEX", jan28) == 25, name
    ce = m.option("NIFTY", nov23, 26000, "CE")
    assert ce.tick_size == pytest.approx(0.05) and ce.exchange == "NFO"
    assert m.option("SENSEX", nov26, 85000, "CE").exchange == "BFO"
    fut = [x for x in m.for_underlying("NIFTY") if x.instrument_type == "FUT"]
    assert fut and fut[0].strike == 0.0


def test_exchange_tokens_agree_across_brokers():
    """NSE/BSE contract tokens are universal - every broker's master must agree."""
    want = {("NIFTY", dt.date(2026, 11, 23), 26000.0, "CE"): "64497"}
    seen = {}
    for name in FILES:
        _, m = load(name)
        for (u, e, k, t), tok in want.items():
            assert str(m.option(u, e, k, t).get("exchange_token")) == tok, name
        sx = m.option("SENSEX", dt.date(2026, 11, 26), 85000, "CE")
        seen[name] = str(sx.get("exchange_token"))
    assert len(set(seen.values())) == 1, seen


def test_order_caps_from_each_convention():
    """Upstox/5paisa publish max order qty (1755); Angel/Groww publish exchange freeze (1801)."""
    caps = {}
    for name in ("upstox", "fivepaisa", "angel", "groww"):
        _, m = load(name)
        inst = m.option("NIFTY", dt.date(2026, 11, 23), 26000, "CE")
        caps[name] = inst.order_qty_cap
        slices = orders.slice_quantity(65 * 60, 65, inst.freeze_qty, inst.max_order_qty)
        assert max(slices) == 27 * 65, name                     # 27 lots per order either way
    assert caps == {"upstox": 1755, "fivepaisa": 1755, "angel": 1800, "groww": 1800}


def test_registry_and_aliases():
    assert len(REGISTRY) == 12
    assert get_broker("zerodha").name == "kite" and get_broker("5paisa").name == "fivepaisa"
    assert get_broker("icici").name == "breeze" and get_broker("iifl").name == "xts"
    with pytest.raises(ConfigError):
        get_broker("nope")


def test_missing_credentials_are_explicit(monkeypatch):
    for k in ("UPSTOX_ACCESS_TOKEN",):
        monkeypatch.delenv(k, raising=False)
    with pytest.raises(ConfigError, match="UPSTOX_ACCESS_TOKEN"):
        get_broker("upstox").creds()


# ------------------------------------------------------------------ payloads

def _intent(name, otype="LIMIT", product="NRML", side="BUY"):
    _, m = load(name)
    inst = m.option("NIFTY", dt.date(2026, 11, 23), 26000, "CE")
    return OrderIntent(inst, side, 130, otype, 82.05 if otype == "LIMIT" else None, product, "ALGO1")


@pytest.mark.parametrize("name,checks", [
    ("upstox", {"instrument_token": "NSE_FO|64497", "product": "D", "order_type": "LIMIT", "quantity": 130}),
    ("dhan", {"exchangeSegment": "NSE_FNO", "productType": "MARGIN", "securityId": "64497", "quantity": 130}),
    ("fyers", {"symbol": "NSE:NIFTY26NOV26000CE", "type": 1, "side": 1, "productType": "MARGIN", "qty": 130}),
    ("angel", {"producttype": "CARRYFORWARD", "symboltoken": "64497", "quantity": "130", "variety": "NORMAL"}),
    ("groww", {"segment": "FNO", "exchange": "NSE", "product": "NRML", "trading_symbol": "NIFTY26NOV26000CE"}),
    ("shoonya", {"tsym": "NIFTY23NOV26C26000", "prctyp": "LMT", "prd": "M", "trantype": "B", "ordersource": "API"}),
    ("breeze", {"stock_code": "NIFTY", "right": "call", "product": "options", "expiry_date": "2026-11-23T06:00:00.000Z"}),
    ("fivepaisa", {"Exchange": "N", "ExchangeType": "D", "ScripCode": "64497", "OrderType": "B", "IsIntraday": False}),
    ("aliceblue", {"instrumentId": "64497", "exchange": "NFO", "product": "LONGTERM", "orderType": "LIMIT"}),
])
def test_order_payloads(name, checks):
    p = get_broker(name).order_payload(_intent(name))
    for k, v in checks.items():
        assert p[k] == v, (name, k, p.get(k))


def test_intraday_product_mapping():
    assert get_broker("upstox").order_payload(_intent("upstox", product="MIS"))["product"] == "I"
    assert get_broker("dhan").order_payload(_intent("dhan", product="MIS"))["productType"] == "INTRADAY"
    assert get_broker("angel").order_payload(_intent("angel", product="MIS"))["producttype"] == "INTRADAY"


@pytest.mark.parametrize("name", ["shoonya", "breeze"])
def test_market_orders_rejected_where_api_forbids(name):
    with pytest.raises(ComplianceBlock):
        get_broker(name).order_payload(_intent(name, otype="MARKET"))


def test_xts_uses_exchange_token(master):
    inst = master.option("NIFTY", dt.date(2026, 11, 23), 26000, "CE")
    p = get_broker("xts").order_payload(OrderIntent(inst, "SELL", 65, "LIMIT", 80.0))
    assert p["exchangeSegment"] == "NSEFO" and p["exchangeInstrumentID"] == 64497 and p["orderSide"] == "SELL"
    assert p["apiOrderSource"] and p["productType"] == "NRML"


def test_prepare_with_upstox_slices_on_broker_cap():
    _, m = load("upstox")
    cfg = {"broker": "upstox", "max_lots_per_leg": 60, "algo_id": None, "static_ip": "1.2.3.4", "product": "NRML",
           "orders_per_second": 8}
    res = orders.prepare([{"instrument": "NIFTY 23 Nov 26000 CE", "side": "BUY", "lots": 30, "price": 82.05}], m, cfg,
                         now=dt.datetime(2026, 11, 20, 11, 0, tzinfo=IST), broker="upstox")
    assert res["broker"] == "upstox" and [o["quantity"] for o in res["orders"]] == [1755, 195]
    assert all(o["instrument_token"] == "NSE_FO|64497" for o in res["orders"])


# ------------------------------------------------------------------ mocked API calls

class Recorder:
    def __init__(self, responses):
        self.responses = list(responses)
        self.calls = []

    def __call__(self, method, url, **kw):
        self.calls.append({"method": method, "url": url, **kw})
        return self.responses.pop(0)


@pytest.fixture
def creds(monkeypatch):
    for b in REGISTRY.values():
        for k in b.env:
            monkeypatch.setenv(k, f"test-{k.lower()}")


def _strikes(m, exp):
    return sorted({o.strike for o in m.for_underlying("NIFTY") if o.expiry == exp and o.instrument_type != "FUT"})


def test_upstox_option_chain(creds, monkeypatch):
    b, m = load("upstox")
    exp = dt.date(2026, 11, 23)
    data = [{"strike_price": k, "underlying_spot_price": 25990.5,
             "call_options": {"market_data": {"ltp": 50.0, "bid_price": 49.9, "ask_price": 50.1, "oi": 650 * 100,
                                              "prev_oi": 650 * 90, "volume": 1000}, "option_greeks": {"iv": 11.2}},
             "put_options": {"market_data": {"ltp": 40.0, "bid_price": 39.9, "ask_price": 40.1, "oi": 650 * 80,
                                             "prev_oi": 650 * 80, "volume": 900}, "option_greeks": {"iv": 11.9}}}
            for k in _strikes(m, exp)]
    rec = Recorder([{"status": "success", "data": data}])
    monkeypatch.setattr(type(b), "_request", lambda self, *a, **k: rec(*a, **k))
    ch = b.option_chain("NIFTY", exp, m)
    call = rec.calls[0]
    assert call["url"] == "https://api.upstox.com/v2/option/chain"
    assert call["params"] == {"instrument_key": "NSE_INDEX|Nifty 50", "expiry_date": "2026-11-23"}
    assert call["headers"]["Authorization"] == "Bearer test-upstox_access_token"
    assert ch.spot == 25990.5 and ch.lot_size == 65
    assert ch.meta["oi_unit_reported"] == "units" and ch.rows[0]["ce_oi"] == 1000  # 65000 units / 65
    assert ch.rows[0]["ce_doi"] == 100


def test_dhan_option_chain_and_order(creds, monkeypatch):
    b, m = load("dhan")
    exp = dt.date(2026, 11, 23)
    oc = {f"{k:.6f}": {"ce": {"last_price": 50, "oi": 1300, "previous_oi": 1170, "volume": 10, "top_bid_price": 49.9,
                              "top_ask_price": 50.1, "implied_volatility": 11.0},
                       "pe": {"last_price": 40, "oi": 2600, "previous_oi": 2600, "volume": 5, "top_bid_price": 39.9,
                              "top_ask_price": 40.1, "implied_volatility": 12.0}} for k in _strikes(m, exp)}
    rec = Recorder([{"data": {"last_price": 25990.5, "oc": oc}, "status": "success"},
                    {"orderId": "112111182198", "orderStatus": "PENDING"}])
    monkeypatch.setattr(type(b), "_request", lambda self, *a, **k: rec(*a, **k))
    ch = b.option_chain("NIFTY", exp, m)
    assert rec.calls[0]["json_body"] == {"UnderlyingScrip": 13, "UnderlyingSeg": "IDX_I", "Expiry": "2026-11-23"}
    assert rec.calls[0]["headers"]["access-token"] == "test-dhan_access_token"
    assert ch.rows[0]["pe_oi"] == 40 and ch.rows[0]["ce_iv_src"] == 11.0
    payload = b.order_payload(_intent("dhan"))
    res = b.place_order(payload)
    assert rec.calls[1]["json_body"]["dhanClientId"] == "test-dhan_client_id" and res["orderId"]


def test_fyers_two_step_option_chain(creds, monkeypatch):
    b, m = load("fyers")
    exp = dt.date(2026, 11, 23)
    chain_rows = [{"strike_price": -1, "option_type": "", "ltp": 25990.5}]
    for k in _strikes(m, exp):
        chain_rows += [{"strike_price": k, "option_type": "CE", "ltp": 50, "bid": 49.9, "ask": 50.1, "oi": 1000,
                        "oich": 10, "volume": 1},
                       {"strike_price": k, "option_type": "PE", "ltp": 40, "bid": 39.9, "ask": 40.1, "oi": 2001,
                        "oich": -5, "volume": 1}]
    rec = Recorder([{"s": "ok", "data": {"expiryData": [{"date": "23-11-2026", "expiry": "1795428600"}]}},
                    {"s": "ok", "data": {"optionsChain": chain_rows}}])
    monkeypatch.setattr(type(b), "_request", lambda self, *a, **k: rec(*a, **k))
    ch = b.option_chain("NIFTY", exp, m)
    assert rec.calls[1]["params"]["timestamp"] == "1795428600"
    assert rec.calls[0]["headers"]["Authorization"] == "test-fyers_app_id:test-fyers_access_token"
    assert ch.spot == 25990.5 and ch.meta["oi_unit_reported"] == "contracts" and ch.rows[0]["pe_oi"] == 2001


def test_groww_chain_margin(creds, monkeypatch):
    b, m = load("groww")
    exp = dt.date(2026, 11, 23)
    strikes = {f"{k:g}": {"CE": {"ltp": 50, "open_interest": 650, "volume": 1, "greeks": {"iv": 11}},
                          "PE": {"ltp": 40, "open_interest": 1300, "volume": 1, "greeks": {"iv": 12}}}
               for k in _strikes(m, exp)}
    rec = Recorder([{"status": "SUCCESS", "payload": {"underlying_ltp": 25990.5, "strikes": strikes}},
                    {"status": "SUCCESS", "payload": {"total_requirement": 51234.5, "span_required": 40000,
                                                      "exposure_required": 11234.5, "option_buy_premium": 0}}])
    monkeypatch.setattr(type(b), "_request", lambda self, *a, **k: rec(*a, **k))
    ch = b.option_chain("NIFTY", exp, m)
    assert rec.calls[0]["url"].endswith("/option-chain/exchange/NSE/underlying/NIFTY")
    assert ch.rows[0]["ce_oi"] == 10   # units -> contracts
    from nsefno import margin

    res = margin.basket_margin("groww", [{"instrument": "NIFTY 23 Nov 26000 CE", "side": "SELL", "lots": 1,
                                          "price": 50}], m)
    assert rec.calls[1]["params"] == {"segment": "FNO"} and rec.calls[1]["json_body"][0]["quantity"] == 65
    assert res["final_total"] == 51234.5 and res["span"] == 40000


def test_shoonya_jdata_encoding(creds, monkeypatch):
    b, m = load("shoonya")
    exp = dt.date(2026, 11, 23)
    vals = [{"tsym": "x", "strprc": f"{k:.2f}", "optt": t, "token": "1", "lp": "50.00", "oi": "650"}
            for k in _strikes(m, exp) for t in ("CE", "PE")]
    rec = Recorder([{"stat": "Ok", "lp": "25990.50"}, {"stat": "Ok", "values": vals},
                    {"stat": "Ok", "span": "19416.00", "expo": "4338.34"}])
    monkeypatch.setattr(type(b), "_request", lambda self, *a, **k: rec(*a, **k))
    ch = b.option_chain("NIFTY", exp, m)
    assert rec.calls[0]["url"].endswith("/GetQuotes")
    assert rec.calls[0]["data"].startswith('jData={"uid": "test-shoonya_user_id", "exch": "NSE", "token": "26000"}')
    assert rec.calls[0]["data"].endswith("&jKey=test-shoonya_session_token")
    assert ch.spot == 25990.5
    from nsefno import margin

    res = margin.basket_margin("shoonya", [{"instrument": "NIFTY 23 Nov 26000 CE", "side": "SELL", "lots": 1}], m)
    pos = json.loads(rec.calls[2]["data"].split("&jKey=")[0][len("jData="):])["pos"][0]
    assert pos == {"prd": "M", "exch": "NFO", "instname": "OPTIDX", "symname": "NIFTY", "exd": "23-NOV-2026",
                   "optt": "CE", "strprc": "26000.00", "buyqty": "0", "sellqty": "65", "netqty": "-65"}
    assert res["final_total"] == pytest.approx(23754.34)


def test_breeze_checksum_headers(creds, monkeypatch):
    b, m = load("breeze")
    rec = Recorder([{"Status": 200, "Success": {"order_id": "20261120N1"}, "Error": None}])
    monkeypatch.setattr(type(b), "_request", lambda self, *a, **k: rec(*a, **k))
    b.place_order(b.order_payload(_intent("breeze")))
    call = rec.calls[0]
    h = call["headers"]
    expected = hashlib.sha256((h["X-Timestamp"] + call["data"] + "test-breeze_secret_key").encode()).hexdigest()
    assert h["X-Checksum"] == "token " + expected and h["X-Timestamp"].endswith(".000Z")
    assert json.loads(call["data"])["order_type"] == "limit" and call["url"].endswith("/v1/order")


def test_angel_quotes_and_headers(creds, monkeypatch):
    b, m = load("angel")
    b.parse_master((FX / "angel.json").read_bytes(), "ALL")   # registers index tokens
    exp = dt.date(2026, 11, 23)
    opts = [o for o in m.for_underlying("NIFTY") if o.expiry == exp and o.instrument_type != "FUT"]
    fetched = [{"symbolToken": o.token, "ltp": 50.0, "opnInterest": 6500, "tradeVolume": 1,
                "depth": {"buy": [{"price": 49.9}], "sell": [{"price": 50.1}]}} for o in opts]
    rec = Recorder([{"status": True, "data": {"fetched": fetched}},
                    {"status": True, "data": {"fetched": [{"symbolToken": "99926000", "ltp": 25990.5}]}}])
    monkeypatch.setattr(type(b), "_request", lambda self, *a, **k: rec(*a, **k))
    ch = b.option_chain("NIFTY", exp, m)
    h = rec.calls[0]["headers"]
    assert h["X-PrivateKey"] == "test-angel_api_key" and h["X-UserType"] == "USER" and h["X-SourceID"] == "WEB"
    assert rec.calls[0]["json_body"]["mode"] == "FULL" and ch.spot == 25990.5 and ch.rows[0]["ce_oi"] == 100


def test_kite_chain_and_margin(creds, monkeypatch, master):
    b = get_broker("kite")
    exp = dt.date(2026, 11, 23)
    opts = [o for o in master.for_underlying("NIFTY") if o.expiry == exp and o.instrument_type != "FUT"]
    q = {f"NFO:{o.tradingsymbol}": {"last_price": 50, "oi": 6500, "volume": 1,
                                     "depth": {"buy": [{"price": 49.9}], "sell": [{"price": 50.1}]}} for o in opts}
    q["NSE:NIFTY 50"] = {"last_price": 25990.5}
    rec = Recorder([{"status": "success", "data": q},
                    {"status": "success", "data": {"initial": {"total": 150000}, "final": {"total": 40000,
                                                                                            "span": 30000,
                                                                                            "exposure": 10000}}}])
    monkeypatch.setattr(type(b), "_request", lambda self, *a, **k: rec(*a, **k))
    ch = b.option_chain("NIFTY", exp, master)
    assert ch.rows[0]["ce_oi"] == 100 and rec.calls[0]["headers"]["X-Kite-Version"] == "3"
    from nsefno import margin

    res = margin.basket_margin("kite", [{"instrument": "NIFTY 23 Nov 26000 CE", "side": "BUY", "lots": 1, "price": 50},
                                        {"instrument": "NIFTY 23 Nov 26100 CE", "side": "SELL", "lots": 1,
                                         "price": 30}], master)
    assert res["hedge_benefit"] == 110000 and rec.calls[1]["url"].endswith("/margins/basket")


def test_gdfl_chain(monkeypatch):
    from nsefno.vendors import gdfl

    monkeypatch.setenv("GDFL_ENDPOINT", "http://endpoint:4000")
    monkeypatch.setenv("GDFL_ACCESS_KEY", "k")
    rows = []
    for k in (25900, 26000, 26100):
        rows += [{"INSTRUMENTIDENTIFIER": f"OPTIDX_NIFTY_23NOV2026_CE_{k}", "LASTTRADEPRICE": 50, "BUYPRICE": 49.9,
                  "SELLPRICE": 50.1, "OPENINTEREST": 6500, "TOTALQTYTRADED": 10},
                 {"INSTRUMENTIDENTIFIER": f"OPTIDX_NIFTY_23NOV2026_PE_{k}", "LASTTRADEPRICE": 40, "BUYPRICE": 39.9,
                  "SELLPRICE": 40.1, "OPENINTEREST": 13000, "TOTALQTYTRADED": 10}]

    class R:
        status_code = 200

        def json(self):
            return rows

    captured = {}

    def fake_get(url, params=None, timeout=None):
        captured.update(url=url, params=params)
        return R()

    from nsefno import http

    monkeypatch.setattr(http.session(), "get", fake_get)
    ch = gdfl.option_chain("NIFTY", dt.date(2026, 11, 23), 65, spot=25990.5)
    assert captured["params"]["expiry"] == "23NOV2026" and captured["params"]["exchange"] == "NFO"
    assert captured["url"] == "http://endpoint:4000/GetLastQuoteOptionChain/"
    assert len(ch.rows) == 3 and ch.rows[0]["pe_oi"] == 200


def test_detect_oi_unit():
    units = [{"ce_oi": 65 * n, "pe_oi": 65 * (n + 3)} for n in range(1, 10)]
    contracts = [{"ce_oi": 1000 + 7 * n, "pe_oi": 2003 + n} for n in range(1, 10)]
    assert detect_oi_unit(units, 65) == "units"
    assert detect_oi_unit(contracts, 65) == "contracts"
    assert detect_oi_unit(units[:2], 65) == "unknown"
