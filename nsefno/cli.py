"""`nsefno` command line - the single entry point every skill script calls.

All commands print a JSON envelope (source, fetched_at, stale_after, data, warnings,
assumptions, disclaimer). Add `--md` for a short markdown summary instead.
"""

from __future__ import annotations

import argparse
import datetime as dt
import json
import re
import sys
from pathlib import Path

from . import DISCLAIMER, calendar, chain, costs, gex, orders, session, sizer, skew, sources
from .envelope import dumps, ensure_fresh, envelope
from .errors import NseFnoError

# --------------------------------------------------------------------------- helpers

_LEG_RE = re.compile(
    r"^\s*(BUY|SELL|B|S)\s+(\d+)\s*(?:X|LOTS?)?\s*(CE|PE|FUT)\s*(\d+(?:\.\d+)?)?\s*@\s*(\d+(?:\.\d+)?)\s*$", re.I)


def parse_legs(spec: str | None, leg_strings: list[str] | None) -> list[dict]:
    """Legs from JSON (inline or file) or compact strings like 'SELL 2 CE 24500 @ 120.5', 'BUY 1 FUT @ 24550'."""
    legs: list[dict] = []
    if spec:
        p = Path(spec)
        legs += json.loads(p.read_text() if p.exists() else spec)
    for s in leg_strings or []:
        m = _LEG_RE.match(s)
        if not m:
            raise NseFnoError(f"Bad --leg {s!r}. Use e.g. 'SELL 2 CE 24500 @ 120.5' or 'BUY 1 FUT @ 24550'.")
        side = {"B": "BUY", "S": "SELL"}.get(m.group(1).upper(), m.group(1).upper())
        legs.append({"side": side, "lots": int(m.group(2)), "instrument": m.group(3).upper(),
                     "strike": float(m.group(4)) if m.group(4) else None, "price": float(m.group(5))})
    if not legs:
        raise NseFnoError("No legs given (use --leg or --legs).")
    return legs


def _today(args) -> dt.date:
    return dt.date.fromisoformat(args.today) if getattr(args, "today", None) else session.now_ist().date()


def _lot(args, index: str, expiry: dt.date | None = None) -> tuple[int, str]:
    if getattr(args, "lot_size", None):
        return int(args.lot_size), "user"
    m = sources.get_master(args.master, args.master_file)
    return m.lot_size(index, expiry), m.source


def _emit(args, env: dict, md: str) -> None:
    if getattr(args, "md", False):
        print(md.rstrip() + "\n\n_" + DISCLAIMER + "_")
    else:
        print(dumps(env))


def _fmt(x, nd=2):
    if x is None:
        return "n/a"
    if isinstance(x, (int, float)):
        return f"{x:,.{nd}f}"
    return str(x)


def _load_chain(args, index: str, expiry_s: str, file: str | None):
    """Load a chain from --file (NSE JSON or saved snapshot) or a live source; enforce freshness."""
    today = _today(args)
    snapshot = None
    if file:
        payload = json.loads(Path(file).read_text(encoding="utf-8"))
        if "rows" in payload:
            snapshot = chain.OptionChain.from_dict(payload)
        elif expiry_s in ("next", "far", "monthly"):
            from .adapters import nse_public

            expiry_s = nse_public.infer_expiry(payload).isoformat()
    master = None
    need_master = not (args.lot_size and (snapshot or (file and expiry_s not in ("next", "far", "monthly"))))
    if need_master and not (snapshot and snapshot.lot_size):
        try:
            master = sources.get_master(args.master, args.master_file)
        except NseFnoError:
            if not file:
                raise
    if snapshot:
        ch = snapshot
    else:
        expiry = sources.resolve_expiry(master, index, expiry_s, today)
        lot = args.lot_size or (master.lot_size(index, expiry) if master else None)
        ch = sources.get_chain(index, expiry, args.source, file, lot)
    if args.lot_size:
        ch.lot_size = int(args.lot_size)
    elif not ch.lot_size and master is not None:
        ch.lot_size = master.lot_size(index, ch.expiry)
    if not args.allow_stale:
        ensure_fresh({"stale_after": (ch.fetched_at + dt.timedelta(seconds=ch.stale_after_s)).isoformat()},
                     what=f"{ch.underlying} {ch.expiry} chain ({ch.source})")
    return ch


def _chain_env(kind, ch, data, warnings=None, assumptions=None):
    return envelope(kind, data, source=ch.source, fetched_at=ch.fetched_at, stale_after_s=ch.stale_after_s,
                    warnings=warnings, assumptions=assumptions)


# --------------------------------------------------------------------------- commands

def cmd_session(args):
    st = session.market_state(dt.datetime.fromisoformat(args.at) if args.at else None, args.exchange)
    _emit(args, envelope("market_state", st, source="nsefno.session"),
          f"**{args.exchange}** at {st['ts_ist']}: **{st['state']}**" + (f" ({st.get('holiday')})"
                                                                        if st.get("holiday") else ""))


def cmd_expiry(args):
    today = _today(args)
    master_dates, src, warn = None, "rules", []
    if not args.no_master:
        try:
            m = sources.get_master(args.master, args.master_file)
            master_dates, src = m.expiries(args.index), m.source
        except NseFnoError as e:
            warn.append(f"Instrument master unavailable ({e}); falling back to rules.")
    cal = calendar.expiry_calendar(args.index, args.n, today, master_dates)
    cal["warnings"] = warn + cal["warnings"]
    lines = [f"**{cal['index']}** ({cal['exchange']}) expiries from {cal['today']} - source: {src}", "",
             "| Expiry | Day | Kind | Days | Sessions | Note |", "|---|---|---|---|---|---|"]
    for e in cal["expiries"]:
        note = f"moved from {e['shifted_from']} ({e['shift_reason']})" if e.get("shifted_from") else ""
        lines.append(f"| {e['expiry']} | {e['weekday']} | {e['kind']} | {e['days_to_expiry']} | "
                     f"{e['sessions_to_expiry']} | {note} |")
    if cal["is_expiry_today"]:
        lines.insert(1, "\n**Expiry is TODAY.**")
    lines += [f"\n> {w}" for w in cal["warnings"]]
    _emit(args, envelope("expiry_calendar", cal, source=src, warnings=cal["warnings"]), "\n".join(lines))


def cmd_master(args):
    m = sources.get_master(args.master, args.master_file)
    if args.action == "resolve":
        inst = m.resolve(args.query, _today(args))
        d = inst.to_dict()
        md = (f"`{inst.tradingsymbol}` - {inst.underlying} {inst.expiry} {inst.strike:g} {inst.instrument_type} | "
              f"lot {inst.lot_size} | tick {inst.tick_size} | token {inst.token} | source {m.source}")
    elif args.action == "lots":
        exps = [e for e in m.expiries(args.query) if e >= _today(args)]
        d = [{"expiry": e.isoformat(), "lot_size": m.lot_size(args.query, e)} for e in exps]
        md = "\n".join([f"**{args.query.upper()}** lot sizes (source {m.source}):"] +
                       [f"- {x['expiry']}: {x['lot_size']}" for x in d])
    else:  # expiries
        d = [e.isoformat() for e in m.expiries(args.query) if e >= _today(args)]
        md = f"**{args.query.upper()}** listed option expiries: " + ", ".join(d)
    _emit(args, envelope("instrument", d, source=m.source, stale_after_s=24 * 3600), md)


def cmd_chain(args):
    ch = _load_chain(args, args.index, args.expiry, args.file)
    a = chain.analyse(ch, r=args.rate)
    if args.save:
        from .adapters import local_store

        a["saved_to"] = str(local_store.save_chain(ch))
    if args.parquet:
        from .adapters import local_store

        a["parquet"] = str(local_store.export_parquet(ch, args.parquet))
    s = a["summary"]
    near = sorted(a["rows"], key=lambda r: abs(r["strike"] - s["forward"]))[: args.rows]
    if not args.full:
        a["rows"] = sorted(near, key=lambda r: r["strike"])
    md = [f"**{s['underlying']} {s['expiry']}** | spot {_fmt(s['spot'])} | fwd {_fmt(s['forward'])} "
          f"({s['forward_source']}) | DTE {s['days_to_expiry']:.2f}d | lot {s['lot_size']}",
          f"ATM {s['atm_strike']:g} | ATM IV {_fmt(s['atm_iv'])}% | straddle {_fmt(s['atm_straddle'])} | "
          f"1-sd move +/-{_fmt(s['expected_move_1sd'], 0)} | PCR(OI) {_fmt(s['pcr_oi'], 3)} | "
          f"max pain {s['max_pain']:g}",
          f"Highest CE OI {s['max_ce_oi_strike']:g} | highest PE OI {s['max_pe_oi_strike']:g}", "",
          "| Strike | CE mid | CE IV | CE OI | CE dOI | PE mid | PE IV | PE OI | PE dOI |",
          "|---|---|---|---|---|---|---|---|---|"]
    for r in sorted(near, key=lambda r: r["strike"]):
        md.append(f"| {r['strike']:g} | {_fmt(r['ce_mid'])} | {_fmt(r['ce_iv'])} | {_fmt(r['ce_oi'], 0)} | "
                  f"{_fmt(r['ce_doi'], 0)} | {_fmt(r['pe_mid'])} | {_fmt(r['pe_iv'])} | {_fmt(r['pe_oi'], 0)} | "
                  f"{_fmt(r['pe_doi'], 0)} |")
    _emit(args, _chain_env("option_chain", ch, a, assumptions=[
        "IV is our own Black-76 solve on bid/ask mids against the put-call-parity forward "
        "(exchange IV used only as fallback).", "OI in contracts (lots)."]), "\n".join(md))


def cmd_gex(args):
    ch = _load_chain(args, args.index, args.expiry, args.file)
    if not ch.lot_size:
        raise NseFnoError("lot size unknown - pass --lot-size or allow the instrument master to load.")
    a = chain.analyse(ch, r=args.rate)
    res = gex.compute_gex(a, ch.lot_size, args.convention)
    prev_note = None
    if args.compare_previous:
        from .adapters import local_store

        prev = local_store.previous_chain(ch)
        if prev:
            pg = gex.compute_gex(chain.analyse(prev, r=args.rate), prev.lot_size or ch.lot_size, args.convention)
            res["vs_previous"] = gex.diff_vs_previous(res, pg) | {"previous_fetched_at": prev.fetched_at.isoformat()}
        else:
            prev_note = "No previous snapshot in local store (run `nsefno chain ... --save` to build history)."
    if args.chart:
        from . import charts

        res["chart"] = charts.gex_chart(res, args.chart)
    if not args.full:
        res.pop("by_strike")
    md = [f"**{res['underlying']} {res['expiry']} GEX** ({res['convention']} convention)",
          f"- Spot {_fmt(res['spot'])} vs flip {_fmt(res['flip_level'], 0)}: **{res['spot_vs_flip'] or 'no flip in +/-6%'}**"
          f" -> net GEX {_fmt(res['net_gex_cr'])} cr/1% => {res['regime']}",
          f"- Call wall {_fmt(res['call_wall'], 0)} | Put wall {_fmt(res['put_wall'], 0)}",
          f"- Assumption: {res['assumption']}"]
    if res.get("vs_previous"):
        md.append(f"- Change vs previous snapshot: {res['vs_previous']}")
    md += ["", "| Strike | Call GEX cr | Put GEX cr | Net cr |", "|---|---|---|---|"]
    md += [f"| {r['strike']:g} | {r['call_gex_cr']:.2f} | {r['put_gex_cr']:.2f} | {r['net_gex_cr']:.2f} |"
           for r in res["top_strikes"]]
    if res.get("chart"):
        md.append(f"\nChart: `{res['chart']}`")
    _emit(args, _chain_env("gex", ch, res, warnings=[prev_note] if prev_note else [],
                           assumptions=[res["assumption"], "IV held constant when re-pricing gamma across spot."]),
          "\n".join(md))


def cmd_skew(args):
    files = args.file or [None] * len(args.expiries.split(","))
    exps = args.expiries.split(",") if not args.file else ["next"] * len(args.file)
    per, smiles, first = [], {}, None
    for e, f in zip(exps, files, strict=True):
        ch = _load_chain(args, args.index, e, f)
        if ch.expiry.isoformat() in smiles:  # e.g. 'next' and 'monthly' resolve to the same date
            continue
        first = first or ch
        a = chain.analyse(ch, r=args.rate)
        m = skew.skew_metrics(a)
        per.append(m)
        smiles[m["expiry"]] = skew.otm_smile(a)
    ts = skew.term_structure(per)
    res = {"per_expiry": per, "term_structure": ts}
    from .adapters import local_store

    hist = [r["atm_iv"] for r in local_store.read_iv_history(args.index)]
    if per and per[0]["atm_iv"] is not None:
        res["iv_percentile"] = skew.iv_percentile(per[0]["atm_iv"], hist)
    if args.chart:
        from . import charts

        res["chart"] = charts.smile_chart(smiles, args.chart)
    if args.smile:
        res["smiles"] = smiles
    md = [f"**{args.index.upper()} skew**", "", "| Expiry | DTE | ATM IV | 25d RR | 25d BF | 10d RR | read |",
          "|---|---|---|---|---|---|---|"]
    md += [f"| {m['expiry']} | {m['days_to_expiry']:.1f} | {_fmt(m['atm_iv'])} | {_fmt(m['rr_25d'])} | "
           f"{_fmt(m['bf_25d'])} | {_fmt(m['rr_10d'])} | {m['skew_read']} |" for m in per]
    md.append(f"\nTerm structure: {ts['shape'] or 'single expiry'}")
    if "iv_percentile" in res:
        ip = res["iv_percentile"]
        md.append(f"IV percentile: {_fmt(ip['iv_percentile'], 1)} (rank {_fmt(ip['iv_rank'], 1)}, n={ip['n_obs']})"
                  + (f" - {ip['note']}" if ip.get("note") else ""))
    _emit(args, _chain_env("iv_skew", first, res, assumptions=[
        "RR = IV(25d call) - IV(25d put); BF = avg(25d wings) - ATM IV; Black-76 deltas, OTM options only."]),
        "\n".join(md))


def cmd_ivhistory(args):
    from .adapters import local_store, nse_archives

    day, done, errs = _today(args), [], 0
    target = args.days
    while len(done) < target and errs < target * 2:
        day -= dt.timedelta(days=1)
        if not session.is_trading_day(day):
            continue
        try:
            rows = nse_archives.parse_bhavcopy(nse_archives.fetch_bhavcopy(day), args.index.upper())
            rec = nse_archives.atm_iv_from_bhavcopy(rows)
            if rec:
                local_store.append_iv_history(args.index, rec)
                done.append(rec)
        except NseFnoError:
            errs += 1
    _emit(args, envelope("iv_history", {"added": len(done), "file": str(local_store.iv_history_path(args.index)),
                                        "latest": done[:3]}, source="nse_archives"),
          f"Backfilled {len(done)} days of ATM IV for {args.index.upper()} -> "
          f"`{local_store.iv_history_path(args.index)}`")


def _legs_with_qty(legs, lot, exchange):
    return [{"instrument": x["instrument"], "side": x["side"], "price": x["price"],
             "qty": x.get("qty") or x.get("lots", 1) * lot, "exchange": x.get("exchange", exchange),
             "orders": x.get("orders", 1)} for x in legs]


def cmd_cost(args):
    from . import resources

    legs = parse_legs(args.legs, args.leg)
    lot, lot_src = _lot(args, args.index) if args.index else (int(args.lot_size or 1), "user")
    exchange = resources.index_rule(args.index)["exchange"] if args.index else "NSE"
    on = dt.date.fromisoformat(args.trade_date) if args.trade_date else _today(args)
    exits = [float(x) for x in args.exit_prices.split(",")] if args.exit_prices else None
    res = costs.trade_cost(_legs_with_qty(legs, lot, exchange), args.broker, on, not args.one_way, exits)
    res["lot_size"], res["lot_size_source"] = lot, lot_src
    t = res["totals"]
    md = [f"**Cost ({'round trip' if res['round_trip'] else 'one way'}, {args.broker}, {on})** - lot {lot} ({lot_src})",
          "", "| Phase | Leg | Turnover | Brokerage | STT | Txn | SEBI | Stamp | GST | Total |",
          "|---|---|---|---|---|---|---|---|---|---|"]
    for line in res["lines"]:
        md.append(f"| {line['phase']} | {line['side']} {line['qty']} {line['instrument']} @ {line['price']} | "
                  f"{_fmt(line['turnover'])} | {line['brokerage']} | {line['stt']} | {line['exchange_txn']} | "
                  f"{line['sebi_fee']} | {line['stamp_duty']} | {line['gst']} | {line['total']} |")
    md.append(f"| **Total** | | | {t['brokerage']} | {t['stt']} | {t['exchange_txn']} | {t['sebi_fee']} | "
              f"{t['stamp_duty']} | {t['gst']} | **{t['total']}** |")
    md.append(f"\nBreakeven: **{res['breakeven_points']} points** of premium on {res['units']} units just to cover costs.")
    _emit(args, envelope("cost", res, source="nsefno.charges.yaml"), "\n".join(md))


def cmd_size(args):
    legs = parse_legs(args.legs, args.leg)
    lot, lot_src = _lot(args, args.index)
    res = sizer.size_position(args.capital, args.risk_pct, legs, lot, args.spot, args.margin_per_unit,
                              args.max_margin_pct, args.cost_per_unit, args.max_lots)
    res["lot_size_source"] = lot_src
    r = res["risk"]
    md = [f"**Sizing** capital {_fmt(args.capital, 0)} @ {args.risk_pct}% risk = budget {_fmt(res['risk_budget'], 0)}"
          f" | lot {lot} ({lot_src})",
          f"- Per unit: max loss {_fmt(r['max_loss_per_unit'])} | max profit {_fmt(r['max_profit_per_unit'])} | "
          f"{r['credit_or_debit']} {_fmt(abs(r['net_premium_per_unit']))} | breakevens {r['breakevens']}",
          f"- Units by risk {res['units_by_risk']} | by margin {res['units_by_margin']} | cap {res['max_lots_cap']}"
          f" -> **{res['units_allowed']} unit(s)**, lots per leg {res['lots_per_leg']}",
          f"- Max loss at that size: {_fmt(res['max_loss_at_size'])}"]
    md += [f"> {w}" for w in res["warnings"]]
    _emit(args, envelope("position_size", res, source="nsefno.sizer", warnings=res["warnings"]), "\n".join(md))


def cmd_margin(args):
    from . import margin

    legs = json.loads(Path(args.legs).read_text() if Path(args.legs).exists() else args.legs)
    m = sources.get_master(args.master, args.master_file) if args.master else None
    res = margin.basket_margin(args.broker, legs, m)
    md = (f"**Margin ({args.broker})**: required {_fmt(res.get('final_total'))} "
          f"(SPAN {_fmt(res.get('span'))}, exposure {_fmt(res.get('exposure'))}), "
          f"hedge benefit {_fmt(res.get('hedge_benefit'))}")
    _emit(args, envelope("margin", res, source=args.broker, stale_after_s=60), md)


def cmd_order(args):
    if args.action == "prep":
        plan = json.loads(Path(args.plan).read_text() if Path(args.plan).exists() else args.plan)
        cfg = orders.load_config()
        broker = args.broker or cfg.get("broker", "kite")
        m = (sources.get_master(args.master, args.master_file) if args.master
             else sources.broker_master(broker))
        freeze = {args.index.upper(): args.freeze_qty} if args.freeze_qty and args.index else {}
        res = orders.prepare(plan, m, cfg, freeze=freeze, broker=broker)
        md = [f"**DRY RUN - nothing sent.** Broker: {res['broker']} | Market: {res['market_state']['state']} | "
              f"{res['n_orders']} order(s) | "
              f"sha256 `{res['payload_sha256'][:12]}`", "", "| Leg | Symbol | Expiry | Lot | Lots | Qty | Slices |",
              "|---|---|---|---|---|---|---|"]
        md += [f"| {c['leg']} | {c['resolved']} | {c['expiry']} | {c['lot_size']} | {c['lots']} | {c['qty']} | "
               f"{c['slices']} |" for c in res["checklist"]]
        md += ["", "```json", json.dumps(res["orders"], indent=1), "```"] + [f"> {w}" for w in res["warnings"]]
        md.append(f"\n{res['how_to_send']}" + (f"\nToken: `{res['confirm_token']}`" if res["confirm_token"] else ""))
        _emit(args, envelope("order_prep", res, source=m.source, stale_after_s=orders.TOKEN_TTL_S,
                             warnings=res["warnings"]), "\n".join(md))
    else:
        pend = orders.pending_path(args.sha)
        if not pend.exists():
            raise NseFnoError(f"No prepared payload {args.sha}; run `nsefno order prep` first.")
        pending = json.loads(pend.read_text())
        res = orders.send(pending["orders"], args.confirm, pending["broker"])
        _emit(args, envelope("order_send", res, source=args.broker),
              "\n".join(f"- {r['order']['tradingsymbol']} {r['order']['quantity']}: {r['status']} "
                        f"{r.get('response') or r.get('error')}" for r in res))


def cmd_journal(args):
    from . import journal

    con = journal.connect(args.db)
    if args.action == "plan":
        legs = json.loads(Path(args.legs).read_text() if Path(args.legs).exists() else args.legs)
        pid = journal.add_plan(con, args.tag, args.index, legs, args.thesis or "")
        _emit(args, envelope("journal", {"plan_id": pid}, source="journal"), f"Logged plan #{pid} ({args.tag}).")
    elif args.action == "fill":
        fid = journal.add_fill(con, args.plan_id, args.ts or session.now_ist().isoformat(timespec="seconds"),
                               args.symbol, args.side, args.qty, args.price, args.planned_price,
                               broker=args.broker)
        _emit(args, envelope("journal", {"fill_id": fid}, source="journal"), f"Logged fill #{fid}.")
    elif args.action == "import":
        n = journal.import_kite_tradebook(con, args.csv, args.plan_id)
        _emit(args, envelope("journal", {"imported": n}, source="journal"), f"Imported {n} fills.")
    else:
        end = _today(args)
        start = end - dt.timedelta(days=args.days - 1)
        res = journal.weekly_review(con, start, end)
        md = [f"**Review {res['period']}**: {res['trades_closed']} closed, {res['trades_open']} open | win rate "
              f"{_fmt(res['win_rate_pct'], 1)}%", f"- Gross {_fmt(res['gross_pnl'])} | costs {_fmt(res['costs'])} | "
              f"net {_fmt(res['net_pnl'])} | cost drag {_fmt(res['cost_drag_pct_of_gross'], 1)}% of gross",
              f"- Avg win {_fmt(res['avg_win'])} | avg loss {_fmt(res['avg_loss'])} | slippage vs plan "
              f"{_fmt(res['total_slippage_inr'])}", "- By setup: " + ", ".join(
                  f"{k}: {v['n']} trades, {_fmt(v['net_pnl'])}" for k, v in res["by_tag"].items())]
        _emit(args, envelope("journal_review", res, source="journal"), "\n".join(md))


def cmd_brokers(args):
    from .brokers import REGISTRY, get_broker

    caps = [get_broker(n).capabilities() for n in REGISTRY]
    yn = {True: "yes", False: "-"}
    md = ["| Broker | Public master | Option chain | Margin | Orders | Credentials (env) |",
          "|---|---|---|---|---|---|"]
    md += [f"| {c['display']} (`{c['broker']}`) | {yn[c['public_master']]} | {yn[c['option_chain']]} | "
           f"{yn[c['margin']]} | {yn[c['orders']]} | {', '.join(c['credentials'])} |" for c in caps]
    if args.check_master:
        m = sources.get_master(args.check_master)
        exps = [e for e in m.expiries("NIFTY") if e >= _today(args)][:1]
        md.append(f"\n`{args.check_master}` master: {len(m)} contracts; NIFTY next expiry {exps[0] if exps else 'n/a'}, "
                  f"lot {m.lot_size('NIFTY', exps[0]) if exps else 'n/a'}")
    _emit(args, envelope("brokers", caps, source="nsefno.brokers"), "\n".join(md))


# --------------------------------------------------------------------------- parser

def build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(prog="nsefno", description="NSE/BSE index F&O toolkit behind nse-fo-skills.")
    common = argparse.ArgumentParser(add_help=False)
    common.add_argument("--md", action="store_true", help="print a markdown summary instead of JSON")
    common.add_argument("--today", help="override 'today' (YYYY-MM-DD), for tests/backfills")
    common.add_argument("--master", default=None,
                        help="instrument master: kite_public (default) | upstox | dhan | fyers | angel | groww | "
                             "shoonya | breeze | fivepaisa | aliceblue | kotak_neo | file")
    common.add_argument("--master-file", action="append", help="CSV(s) for --master kotak_neo/file")
    common.add_argument("--lot-size", type=int, help="override lot size (otherwise from the instrument master)")
    sub = p.add_subparsers(dest="cmd", required=True)

    s = sub.add_parser("brokers", parents=[common], help="supported brokers and what each can do")
    s.add_argument("--check-master", help="download one broker's public master and print a sanity line")
    s.set_defaults(fn=cmd_brokers)

    s = sub.add_parser("session", parents=[common], help="market state now (IST)")
    s.add_argument("--exchange", default="NSE")
    s.add_argument("--at", help="ISO timestamp to evaluate")
    s.set_defaults(fn=cmd_session)

    s = sub.add_parser("expiry", parents=[common], help="expiry calendar")
    s.add_argument("index")
    s.add_argument("-n", type=int, default=6)
    s.add_argument("--no-master", action="store_true", help="rules only (offline)")
    s.set_defaults(fn=cmd_expiry)

    s = sub.add_parser("master", parents=[common], help="instrument master lookups")
    s.add_argument("action", choices=["resolve", "lots", "expiries"])
    s.add_argument("query")
    s.set_defaults(fn=cmd_master)

    chain_common = argparse.ArgumentParser(add_help=False)
    chain_common.add_argument("index")
    chain_common.add_argument("--expiry", default="next", help="YYYY-MM-DD | next | far | monthly")
    chain_common.add_argument("--source", default="nse_public",
                              help="nse_public | gdfl | kite | upstox | dhan | fyers | angel | groww | shoonya | "
                                   "breeze | fivepaisa | aliceblue")
    chain_common.add_argument("--allow-stale", action="store_true", help="analyse a chain past its stale_after")
    chain_common.add_argument("--rate", type=float, default=chain.DEFAULT_RATE)
    chain_common.add_argument("--full", action="store_true", help="include every strike in JSON")

    s = sub.add_parser("chain", parents=[common, chain_common], help="option chain snapshot")
    s.add_argument("--file", help="saved NSE JSON / normalised snapshot instead of fetching")
    s.add_argument("--rows", type=int, default=15)
    s.add_argument("--save", action="store_true", help="store snapshot in ~/.nsefno for later comparison")
    s.add_argument("--parquet", help="also export rows to this parquet path")
    s.set_defaults(fn=cmd_chain)

    s = sub.add_parser("gex", parents=[common, chain_common], help="gamma exposure, flip, walls")
    s.add_argument("--file")
    s.add_argument("--convention", default="classic", choices=list(gex.CONVENTIONS))
    s.add_argument("--chart", help="PNG output path")
    s.add_argument("--compare-previous", action="store_true")
    s.set_defaults(fn=cmd_gex)

    s = sub.add_parser("skew", parents=[common, chain_common], help="IV smile, RR/BF, term structure")
    s.add_argument("--expiries", default="next,far", help="comma list, e.g. next,far,monthly")
    s.add_argument("--file", action="append", help="one per expiry (repeat)")
    s.add_argument("--chart")
    s.add_argument("--smile", action="store_true", help="include smile points")
    s.set_defaults(fn=cmd_skew)

    s = sub.add_parser("ivhistory", parents=[common], help="backfill ATM IV history from NSE bhavcopy")
    s.add_argument("index")
    s.add_argument("--days", type=int, default=260)
    s.set_defaults(fn=cmd_ivhistory)

    legs_common = argparse.ArgumentParser(add_help=False)
    legs_common.add_argument("--leg", action="append", help="'SELL 2 CE 24500 @ 120.5' (repeat)")
    legs_common.add_argument("--legs", help="JSON list or path")

    s = sub.add_parser("cost", parents=[common, legs_common], help="round-trip F&O cost")
    s.add_argument("--index", help="NIFTY/BANKNIFTY/SENSEX... (for lot size and exchange)")
    s.add_argument("--broker", default="zerodha")
    s.add_argument("--trade-date")
    s.add_argument("--one-way", action="store_true")
    s.add_argument("--exit-prices", help="comma list, one per leg")
    s.set_defaults(fn=cmd_cost)

    s = sub.add_parser("size", parents=[common, legs_common], help="position sizing")
    s.add_argument("--index", required=True)
    s.add_argument("--capital", type=float, required=True)
    s.add_argument("--risk-pct", type=float, required=True)
    s.add_argument("--spot", type=float, required=True)
    s.add_argument("--margin-per-unit", type=float)
    s.add_argument("--max-margin-pct", type=float, default=50.0)
    s.add_argument("--cost-per-unit", type=float, default=0.0)
    s.add_argument("--max-lots", type=int)
    s.set_defaults(fn=cmd_size)

    s = sub.add_parser("margin", parents=[common], help="broker basket margin (login required)")
    s.add_argument("--broker", default="kite")
    s.add_argument("--legs", required=True, help='JSON: [{"instrument":"NIFTY 23 Nov 26200 CE","side":"BUY",'
                                                  '"lots":1,"price":82}]')
    s.set_defaults(fn=cmd_margin)

    s = sub.add_parser("order", parents=[common], help="SEBI-aware order prep (dry run) / confirmed send")
    s.add_argument("action", choices=["prep", "send"])
    s.add_argument("--plan")
    s.add_argument("--index")
    s.add_argument("--freeze-qty", type=int)
    s.add_argument("--sha")
    s.add_argument("--confirm")
    s.add_argument("--broker", help="kite | upstox | dhan | fyers | angel | groww | shoonya | breeze | fivepaisa | "
                                    "aliceblue | kotak_neo | xts (default: config.yaml broker)")
    s.set_defaults(fn=cmd_order)

    s = sub.add_parser("journal", parents=[common], help="trade journal + weekly review")
    s.add_argument("action", choices=["plan", "fill", "import", "review"])
    s.add_argument("--db")
    s.add_argument("--tag", default="untagged")
    s.add_argument("--index", default="NIFTY")
    s.add_argument("--legs")
    s.add_argument("--thesis")
    s.add_argument("--plan-id", type=int)
    s.add_argument("--ts")
    s.add_argument("--symbol")
    s.add_argument("--side")
    s.add_argument("--qty", type=int)
    s.add_argument("--price", type=float)
    s.add_argument("--planned-price", type=float)
    s.add_argument("--broker", default="zerodha")
    s.add_argument("--csv")
    s.add_argument("--days", type=int, default=7)
    s.set_defaults(fn=cmd_journal)
    return p


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    try:
        args.fn(args)
        return 0
    except (NseFnoError, KeyError, ValueError) as e:
        msg = e.args[0] if isinstance(e, KeyError) and e.args else str(e)
        print(dumps({"error": type(e).__name__, "message": msg, "disclaimer": DISCLAIMER}), file=sys.stderr)
        return 2


if __name__ == "__main__":
    sys.exit(main())
