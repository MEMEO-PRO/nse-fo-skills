"""Optional matplotlib charts (pip install 'nsefno[charts]'). Returns the PNG path or None."""

from __future__ import annotations

from pathlib import Path


def _plt():
    try:
        import matplotlib

        matplotlib.use("Agg")
        import matplotlib.pyplot as plt

        return plt
    except ImportError:
        return None


def gex_chart(gex: dict, path: str | Path, window_pct: float = 0.05) -> str | None:
    plt = _plt()
    if plt is None:
        return None
    spot = gex["spot"]
    rows = [r for r in gex["by_strike"] if abs(r["strike"] / spot - 1) <= window_pct]
    k = [r["strike"] for r in rows]
    fig, ax = plt.subplots(figsize=(11, 5.5), dpi=120)
    width = (k[1] - k[0]) * 0.8 if len(k) > 1 else 10
    ax.bar(k, [r["call_gex_cr"] for r in rows], width=width, color="#2a9d8f", label="Call GEX")
    ax.bar(k, [r["put_gex_cr"] for r in rows], width=width, color="#e76f51", label="Put GEX")
    ax.plot(k, [r["net_gex_cr"] for r in rows], color="#264653", lw=1.6, label="Net GEX")
    ax.axvline(spot, color="black", ls="--", lw=1, label=f"Spot {spot:,.0f}")
    if gex.get("flip_level"):
        ax.axvline(gex["flip_level"], color="#9b5de5", ls=":", lw=1.5, label=f"Flip {gex['flip_level']:,.0f}")
    ax.axhline(0, color="grey", lw=0.6)
    ax.set_title(f"{gex['underlying']} {gex['expiry']} GEX (INR cr / 1% move) - {gex['convention']} convention")
    ax.set_xlabel("Strike")
    ax.legend(loc="upper left", fontsize=8)
    fig.text(0.01, 0.01, "Assumption: " + gex["assumption"] + "  Not investment advice.", fontsize=7, color="grey")
    fig.tight_layout()
    fig.savefig(path)
    plt.close(fig)
    return str(path)


def smile_chart(smiles: dict[str, list[dict]], path: str | Path) -> str | None:
    plt = _plt()
    if plt is None:
        return None
    fig, ax = plt.subplots(figsize=(10, 5), dpi=120)
    for exp, pts in smiles.items():
        ax.plot([p["moneyness"] * 100 for p in pts], [p["iv"] for p in pts], marker=".", lw=1.2, label=exp)
    ax.axvline(0, color="grey", lw=0.6)
    ax.set_xlabel("log-moneyness ln(K/F), %")
    ax.set_ylabel("IV, %")
    ax.set_title("OTM IV smile (Black-76 on forward)")
    ax.legend(fontsize=8)
    fig.tight_layout()
    fig.savefig(path)
    plt.close(fig)
    return str(path)
