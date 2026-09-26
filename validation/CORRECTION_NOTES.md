# SPARK validation correction 1

This correction addresses issues discovered by the synthetic validation challenge.

Changes:
- normal generated rows use `quality_status=PASS`, matching the Data Trust contract;
- hard observed engineering failures override a non-critical Data Trust HOLD, while RETEST still has precedence for unusable required evidence;
- late-acceleration challenge is strengthened at 96h so a DETERIORATING expectation is meaningful;
- lot-wide shift is strengthened to exercise historical lot-shift evidence;
- instrument commonality is strengthened;
- commonality output preserves the strongest result from each categorical dimension before filling the remaining global top-N slots;
- regression tests cover hard-fail vs Data Trust HOLD and cross-dimension commonality visibility.

This does not retrain Module A or Module B and does not change their artifacts.
