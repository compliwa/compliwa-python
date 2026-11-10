from __future__ import annotations

import re

from compliwa import API_VERSION, OPERATIONS


def test_the_generated_table_is_sound() -> None:
    assert re.fullmatch(r"\d+\.\d+\.\d+", API_VERSION)
    names = set()
    for op in OPERATIONS:
        assert op["python"] not in names, op["python"]
        names.add(op["python"])
        assert re.fullmatch(r"[a-z_.]+", op["python"]), op["python"]
        assert op["path"].startswith("/v1/")
        assert op["method"] in {"GET", "POST", "PATCH", "PUT", "DELETE"}
        assert op["path_params"] == re.findall(r"\{([^}]+)\}", op["path"])
        if op.get("paginated"):
            assert op.get("query") and op["method"] == "GET"
        if op.get("idempotent"):
            assert op["method"] != "GET"
