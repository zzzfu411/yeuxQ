# Prospective Trial Packet Verification: PASS

- Trial: `guard-v1-20260716`
- Packet: `evidence\trial_registry\guard-v1-20260716\prospective_trial_packet.json`
- Packet SHA-256: `b33e834ef03feeac10b4427015c48952a293adedff7fcf38abe565d73682f2a9`
- Registry: `evidence\trial_registry\research_trials.jsonl`
- Registry tail: `ee8c7566e9d8c1f9994ef04f39ea22be31bb9191b8e1ec64512c874a3797ca18`
- Execution allowed: `False`

## Checks

- `PASS` `packet_contract`: Packet artifact type and schema version match.
- `PASS` `packet_sha256`: Packet canonical SHA-256 matches.
- `PASS` `execution_config`: Frozen execution config SHA-256 matches.
- `PASS` `protocol_plan`: Retained protocol plan SHA-256 matches.
- `PASS` `code:src/quantify/research/candidates.py`: Code SHA-256 matches.
- `PASS` `code:src/quantify/research/factors.py`: Code SHA-256 matches.
- `PASS` `code:src/quantify/research/strategy.py`: Code SHA-256 matches.
- `PASS` `code:src/quantify/research/walk_forward_protocol.py`: Code SHA-256 matches.
- `PASS` `code:src/quantify/research/robustness.py`: Code SHA-256 matches.
- `PASS` `code:src/quantify/engine/backtest.py`: Code SHA-256 matches.
- `PASS` `code:src/quantify/engine/paper_broker.py`: Code SHA-256 matches.
- `PASS` `code:src/quantify/risk/manager.py`: Code SHA-256 matches.
- `PASS` `development_prefix`: Development prefix SHA-256 matches.
- `PASS` `registry_chain`: Registry chain and unique trial preregistration verify.
- `PASS` `registry_packet_binding`: Registry event matches the packet preregistration payload.

## Blockers

- None.

Integrity PASS cannot upgrade source QA, market evidence, strategy, paper, or live-trading gates.
