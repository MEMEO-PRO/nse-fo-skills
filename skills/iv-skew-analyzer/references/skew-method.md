# Skew method

- IVs are Black-76 implied vols on the put-call-parity forward (see option-chain-snapshot).
- Smile uses OTM options only: puts for K < F, calls for K ≥ F.
- Delta-space interpolation: IV at Black-76 delta +0.25 (calls) and -0.25 (puts) is
  linearly interpolated from OTM strikes; returned as `null` if the chain does not span
  that delta.
- **Risk reversal** RR25 = IV(25Δ call) - IV(25Δ put). Index skew is normally negative.
  `skew_read` buckets: < -0.25 vol "put skew", > +0.25 "call skew", otherwise flat.
- **Butterfly** BF25 = ½(IV25C + IV25P) - ATM IV. Measures wing (tail) premium.
- **Term structure** = ATM IV by days to expiry; shape is contango if the last point is
  > 0.25 vol above the first, backwardation if > 0.25 vol below.
- **IV percentile** = % of history days with ATM IV below today's. **IV rank** =
  (today - min) / (max - min). History = daily ATM IV of the nearest expiry with ≥ 2 days to
  go, from NSE UDiFF F&O bhavcopy closing prices (`nsefno ivhistory`).
- Weekly ATM IV near expiry is noisy (theta + event premium); compare like-for-like DTE.
