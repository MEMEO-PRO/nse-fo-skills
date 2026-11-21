import json
import subprocess
import sys
import zipfile
from pathlib import Path

import yaml

from nsefno import DISCLAIMER
from nsefno.cli import main, parse_legs

ROOT = Path(__file__).resolve().parent.parent
OFFLINE = ["--master", "file", "--master-file", str(ROOT / "tests/fixtures/kite_NFO_sample.csv"),
           "--master-file", str(ROOT / "tests/fixtures/kite_BFO_sample.csv")]


def run(capsys, *argv):
    code = main(list(argv))
    out = capsys.readouterr()
    return code, out.out, out.err


def test_parse_legs():
    legs = parse_legs(None, ["SELL 2 CE 24500 @ 120.5", "b 1 fut @ 24550", "BUY 1x PE 24000 @ 30"])
    assert legs[0] == {"side": "SELL", "lots": 2, "instrument": "CE", "strike": 24500.0, "price": 120.5}
    assert legs[1]["instrument"] == "FUT" and legs[1]["side"] == "BUY" and legs[1]["strike"] is None
    assert legs[2]["lots"] == 1


def test_cli_gex_json_envelope(capsys):
    code, out, _ = run(capsys, "gex", "NIFTY", "--file", str(ROOT / "tests/fixtures/nifty_2026-11-23.json"),
                       "--lot-size", "65", "--allow-stale")
    env = json.loads(out)
    assert code == 0 and env["kind"] == "gex" and env["source"] == "nse_public"
    assert env["disclaimer"] == DISCLAIMER and env["assumptions"]
    assert env["stale_after"] and env["data"]["lot_size"] == 65


def test_cli_refuses_stale_chain(capsys):
    code, _, err = run(capsys, "gex", "NIFTY", "--file", str(ROOT / "tests/fixtures/nifty_2026-11-23.json"),
                       "--lot-size", "65")
    assert code == 2 and "StaleDataError" in err


def test_cli_cost_md_uses_master_lot(capsys):
    code, out, _ = run(capsys, "cost", *OFFLINE, "--index", "NIFTY", "--leg", "BUY 1 CE 26200 @ 82",
                       "--today", "2026-11-21", "--md")
    assert code == 0 and "lot 65 (file)" in out and "Breakeven" in out


def test_cli_resolve_offline(capsys):
    code, out, _ = run(capsys, "master", "resolve", "SENSEX 28 Jan 85000 CE", *OFFLINE, "--today", "2026-11-21")
    assert code == 0 and json.loads(out)["data"]["lot_size"] == 25


def test_cli_expiry_offline(capsys):
    code, out, _ = run(capsys, "expiry", "NIFTY", "--no-master", "--today", "2026-11-21", "-n", "2")
    data = json.loads(out)["data"]
    assert data["next_expiry"]["expiry"] == "2026-11-23" and data["next_expiry"]["shifted_from"] == "2026-11-24"


def test_cli_skew_multiple_files(capsys):
    fx = ROOT / "tests/fixtures"
    code, out, _ = run(capsys, "skew", "NIFTY", "--file", str(fx / "nifty_2026-11-23.json"), "--file",
                       str(fx / "nifty_2026-12-01.json"), "--lot-size", "65", "--allow-stale")
    d = json.loads(out)["data"]
    assert code == 0 and [m["expiry"] for m in d["per_expiry"]] == ["2026-11-23", "2026-12-01"]


def test_skill_wrapper_runs_as_script():
    r = subprocess.run([sys.executable, str(ROOT / "skills/fno-expiry-calendar/scripts/expiry.py"), "SENSEX",
                        "--no-master", "--today", "2026-11-21", "-n", "1"], capture_output=True, text=True)
    assert r.returncode == 0, r.stderr
    assert json.loads(r.stdout)["data"]["next_expiry"]["expiry"] == "2026-11-26"


def test_index_validates():
    r = subprocess.run([sys.executable, str(ROOT / "scripts/validate_index.py")], capture_output=True, text=True)
    assert r.returncode == 0, r.stdout


def test_packages_are_self_contained(tmp_path):
    r = subprocess.run([sys.executable, str(ROOT / "scripts/build_packages.py")], capture_output=True, text=True)
    assert r.returncode == 0, r.stderr
    idx = yaml.safe_load((ROOT / "skills-index.yaml").read_text())
    pkg = ROOT / "skill-packages" / "fno-cost-calculator.skill"
    assert len(list((ROOT / "skill-packages").glob("*.skill"))) == len(idx["skills"])
    with zipfile.ZipFile(pkg) as z:
        names = z.namelist()
        assert "fno-cost-calculator/SKILL.md" in names
        assert "fno-cost-calculator/scripts/nsefno/data/charges.yaml" in names
        z.extractall(tmp_path)
    # Run the packaged script with the repo NOT on sys.path.
    r = subprocess.run([sys.executable, "-I", str(tmp_path / "fno-cost-calculator/scripts/cost.py"),
                        "--lot-size", "65", "--leg", "SELL 1 CE 26400 @ 31", "--today", "2026-11-21"],
                       capture_output=True, text=True, cwd=tmp_path)
    assert r.returncode == 0, r.stderr
    assert json.loads(r.stdout)["data"]["totals"]["stt"] > 0
