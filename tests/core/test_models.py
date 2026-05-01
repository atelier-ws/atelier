from __future__ import annotations

import pytest
from pydantic import ValidationError

from atelier.core.foundation.models import ReasonBlock, Rubric, Trace


def _block(**kw: object) -> ReasonBlock:
    base: dict[str, object] = dict(
        id="b1",
        title="t",
        domain="coding",
        situation="s",
        procedure=["do thing"],
    )
    base.update(kw)
    return ReasonBlock(**base)  # type: ignore[arg-type]


def test_procedure_must_be_non_empty() -> None:
    with pytest.raises(ValidationError):
        _block(procedure=[])


def test_extra_fields_forbidden() -> None:
    with pytest.raises(ValidationError):
        ReasonBlock(
            id="b1",
            title="t",
            domain="coding",
            situation="s",
            procedure=["x"],
            extra_field="nope",  # type: ignore[call-arg]
        )


def test_make_id_is_stable() -> None:
    a = ReasonBlock.make_id("Hello World", "coding")
    b = ReasonBlock.make_id("Hello World", "coding")
    assert a == b
    assert a.startswith("coding-hello-world")


def test_success_rate() -> None:
    b = _block(success_count=3, failure_count=1)
    assert b.success_rate() == 0.75
    b2 = _block()
    assert b2.success_rate() == 0.0


def test_trace_extra_forbidden() -> None:
    with pytest.raises(ValidationError):
        Trace(
            id="t1",
            agent="a",
            domain="coding",
            task="x",
            status="success",
            mystery=1,  # type: ignore[call-arg]
        )


def test_rubric_extra_forbidden() -> None:
    with pytest.raises(ValidationError):
        Rubric(
            id="r1",
            domain="coding",
            required_checks=["c"],
            something_else=True,  # type: ignore[call-arg]
        )
