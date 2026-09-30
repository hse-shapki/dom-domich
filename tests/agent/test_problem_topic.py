"""Распознавание предмета заявки не должно путать похожие слова."""

from dom_domych.infrastructure.postgres.message_agent import problem_topic


def test_common_problem_topics_have_distinct_routes() -> None:
    assert problem_topic("Нет света во всём втором подъезде") == "lighting"
    assert problem_topic("Искрит электропроводка в подъезде") == "lighting"
    assert problem_topic("Нет воды на пятом этаже") == "water_supply"
    assert problem_topic("Лифт не работает") == "elevator"
    assert problem_topic("Батареи холодные") == "heating"
    assert problem_topic("Проблема во втором подъезде") is None
    assert problem_topic("Нет воды и света во втором подъезде") is None
