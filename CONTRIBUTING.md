# Contributing

Thanks for helping make Indian F&O tooling more correct.

## Ground rules
1. **No hardcoded market quantities.** Lot size, tick size, freeze quantity and expiry
   always come from an instrument master. Rules go in `nsefno/data/indices.yaml`.
2. **Every rate has a date and a source.** Edit `nsefno/data/charges.yaml`, add a new
   entry with `effective_from` + `source` (do not overwrite history), bump `reviewed_on`.
3. **No advice.** Skills describe; they never say buy/sell, target or stop. Every
   `SKILL.md` keeps its `## Never` section.
4. **No secrets in files.** Credentials only via environment variables / OS keychain.
5. **No exchange data in the repo.** Fixtures are synthetic (see `tests/fixtures/README.md`).

## Dev setup
```bash
pip install -e ".[dev]"
pytest
ruff check .
python scripts/validate_index.py
python scripts/build_packages.py
```

## Adding a broker adapter (Upstox, Dhan, Fyers, ...)
- Add `nsefno/adapters/<broker>.py` exposing what applies: `load_instruments() -> InstrumentMaster`,
  a chain builder returning `OptionChain` (OI in **contracts**), `basket_margin(legs)`, `place_order(payload)`.
- Wire it into `nsefno/sources.py` / `nsefno/margin.py`, list it in `skills-index.yaml`.
- Add parser tests with a small synthetic fixture in the broker's real column layout.

## Adding a skill
1. `skills/<name>/SKILL.md` following the [Agent Skills spec](https://agentskills.io/specification)
   (`name` = folder, description says what it does *and when to use it*, < 500 lines).
2. A thin script in `skills/<name>/scripts/` calling `nsefno.cli`.
3. An entry in `skills-index.yaml`; `python scripts/validate_index.py` must pass.

## Each December
Add next year's NSE/BSE trading holidays to `nsefno/data/holidays.yaml` from the exchange
circular and add the resulting expiry shifts to `tests/test_calendar.py`.
