from llmlens_server.alerting import breached, validate_rule_type


def test_breached():
    assert breached({"threshold": 0.1}, 0.2) is True
    assert breached({"threshold": 0.1}, 0.05) is False
    assert breached({"threshold": 0.1}, 0.1) is False  # strictly greater


def test_validate_rule_type():
    assert validate_rule_type("error_rate") == "error_rate"
    for bad in ("nope", "", "COST"):
        try:
            validate_rule_type(bad)
            raise AssertionError("should have raised")
        except ValueError:
            pass
