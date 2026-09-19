"""O loop nao pode girar para sempre quando a tela nao muda."""

from __future__ import annotations

from jevcu.config import Config
from jevcu.contracts import Candidate, Choice
from jevcu.driver import Element, MockDriver, Observation
from jevcu.loop import Agent


def _observation() -> Observation:
    return Observation("s1", "App", "janela", [Element("e1", "Button", "Salvar")])


def _always_unsure(*, goal, observation, history, candidates):
    return Choice(
        selected_id=candidates[0].id,
        confidence=0.01,
        probabilities={c.id: 1.0 / len(candidates) for c in candidates},
        model="stub",
    )


def _always_reobserve(*, goal, observation, history, candidates):
    return Choice("reobserve", 1.0, {c.id: 0.0 for c in candidates}, model="stub")


def test_confianca_no_chao_desiste_em_vez_de_girar():
    driver = MockDriver([_observation()])
    run = Agent(driver, _always_unsure, Config(max_steps=50)).run("qualquer coisa")
    assert run.outcome == "escalate"
    assert len(run.steps) <= 3          # nao consumiu os 50 passos
    assert driver.executed == []


def test_reobserve_repetido_desiste():
    driver = MockDriver([_observation()])
    run = Agent(driver, _always_reobserve, Config(max_steps=50)).run("qualquer coisa")
    assert run.outcome == "escalate"
    assert len(run.steps) <= 3
    assert driver.executed == []
