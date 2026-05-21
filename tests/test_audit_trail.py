import json

from core.audit_trail import AuditLogger, AuditMemoryStore, AuditSQLiteStore, AuditStage, AuditVerdict


def test_create_log_finalize_and_json():
    store = AuditMemoryStore()
    logger = AuditLogger(store)
    trail = logger.create_trail("BTC/USDT", "1h", "unit")
    logger.log_step(trail, AuditStage.MACRO_GATE, AuditVerdict.PASS, inputs={"score": 0.1}, outputs={"state": "ALLOW_FULL"})
    logger.finalize(trail, "EXECUTED", "ok")

    assert trail.trail_id
    assert store.get_recent(1)[0].final_decision == "EXECUTED"
    assert json.loads(trail.to_json())["steps"][0]["stage"] == "macro_gate"


def test_all_stages_can_be_recorded():
    logger = AuditLogger(AuditMemoryStore())
    trail = logger.create_trail("BTC/USDT", "1h", "unit")
    for stage in AuditStage:
        logger.log_step(trail, stage, AuditVerdict.PASS)
    logger.finalize(trail, "EXECUTED", "all stages")

    assert len(trail.steps) == len(AuditStage)


def test_memory_store_limits():
    store = AuditMemoryStore(max_trails=2)
    logger = AuditLogger(store)
    for index in range(3):
        trail = logger.create_trail(f"{index}/USDT", "1h", "unit")
        logger.finalize(trail, "SKIPPED", "")

    assert len(store.get_recent(10)) == 2


def test_sqlite_store_persists(tmp_path):
    store = AuditSQLiteStore(str(tmp_path / "audit.db"))
    logger = AuditLogger(store)
    trail = logger.create_trail("BTC/USDT", "1h", "unit")
    logger.log_step(trail, AuditStage.SIGNAL_GENERATION, AuditVerdict.PASS)
    logger.finalize(trail, "EXECUTED", "ok")

    restored = AuditSQLiteStore(str(tmp_path / "audit.db")).get_recent(5)
    assert restored[0].trail_id == trail.trail_id
    assert restored[0].steps[0].stage == AuditStage.SIGNAL_GENERATION


def test_sqlite_store_filters_by_symbol(tmp_path):
    store = AuditSQLiteStore(str(tmp_path / "audit.db"))
    logger = AuditLogger(store)
    btc = logger.create_trail("BTC/USDT", "1h", "unit")
    eth = logger.create_trail("ETH/USDT", "1h", "unit")
    logger.finalize(btc, "EXECUTED", "ok")
    logger.finalize(eth, "SKIPPED", "no signal")

    restored = AuditSQLiteStore(str(tmp_path / "audit.db")).get_by_symbol("BTC/USDT", 5)

    assert len(restored) == 1
    assert restored[0].symbol == "BTC/USDT"
