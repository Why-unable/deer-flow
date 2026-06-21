import json

from deerflow.tools.builtins.report_active_skill_tool import _report_active_skill, report_active_skill_tool
from deerflow.tools.tools import get_available_tools


def test_report_active_skill_accepts_current_agent_skill():
    result = _report_active_skill(
        "local-deep-research",
        config={"metadata": {"available_skills": ["local-deep-research", "local-systematic-literature-review"]}},
    )

    assert json.loads(result) == {"skill_name": "local-deep-research"}


def test_report_active_skill_rejects_skill_outside_current_agent_config():
    result = _report_active_skill(
        "deep-research",
        config={"metadata": {"available_skills": ["local-deep-research", "local-systematic-literature-review"]}},
    )

    assert result.startswith("Error:")
    assert "local-deep-research" in result
    assert "local-systematic-literature-review" in result


def test_report_active_skill_uses_langchain_injected_config():
    result = report_active_skill_tool.invoke(
        {"skill_name": "local-systematic-literature-review"},
        config={"metadata": {"available_skills": ["local-systematic-literature-review"]}},
    )

    assert json.loads(result) == {"skill_name": "local-systematic-literature-review"}


def test_report_active_skill_is_builtin_tool():
    names = {tool.name for tool in get_available_tools(include_mcp=False)}

    assert "report_active_skill" in names
