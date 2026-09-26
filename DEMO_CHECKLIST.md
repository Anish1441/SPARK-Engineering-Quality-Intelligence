# SPARK Phase 7 — Demo Checklist

1. Start: `python app.py` and open `http://127.0.0.1:5000`.
2. Activate `original-spark-module-b`.
3. Open QA Inspector and show one component.
4. Show Data Trust = PASS and explain it is evidence completeness/quality, not ML confidence.
5. Show Engineering Safety and the documented electrical limit; explain hard failures cannot be relaxed by ML.
6. Show Unified Reliability Risk: score, band, evidence completeness and recommended action; state that the score is not failure probability.
7. Show Explainable QA Decision: primary reason code, ranked reasons and decision path.
8. Show original Module A: lot/historical/batch anomaly evidence and action.
9. Show original Module B: 168h forecast, interval and selected model.
10. Record one normal QA agreement. If needed, demonstrate an override with controlled reason and >=20-character justification.
11. Open Decision History and show the persisted evidence trail / ledger hash status.
12. Open QA feedback summary and explain that it supports future offline threshold/model review; it does not auto-retrain.
13. Optional safety proof: demonstrate the synthetic 180 uA vs 175 uA hard-failure test -> REJECT.
14. Close with: SPARK supports earlier, explainable QA intervention; final physical screening remains authoritative.
