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

## Adding a broker adapter
- Subclass `nsefno.brokers.base.Broker` in `nsefno/brokers/<broker>.py`: `master_sources()` +
  `parse_master()`, `option_chain()` (use `finalise_chain`, which normalises OI to contracts),
  `basket_margin()`, `order_payload()` (pure function) and `place_order()`. Fill `VERIFICATION` honestly.
- Register it in `nsefno/brokers/__init__.py`, add it to `docs/brokers.md` and `skills-index.yaml`.
- Add a small real-format master slice to `tests/fixtures/brokers/` (contract metadata only) and
  extend `tests/test_brokers.py`; mock HTTP by patching `Broker._request` (the network is blocked in tests).
- **Live confirmation wanted:** if you have an account with a broker whose authenticated calls are
  only `sdk`/`docs` verified, run the read-only calls and open an issue with the (redacted) result.

## Adding a skill
1. `skills/<name>/SKILL.md` following the [Agent Skills spec](https://agentskills.io/specification)
   (`name` = folder, description says what it does *and when to use it*, < 500 lines).
2. A thin script in `skills/<name>/scripts/` calling `nsefno.cli`.
3. An entry in `skills-index.yaml`; `python scripts/validate_index.py` must pass.

## Each December
Add next year's NSE/BSE trading holidays to `nsefno/data/holidays.yaml` from the exchange
circular and add the resulting expiry shifts to `tests/test_calendar.py`.
