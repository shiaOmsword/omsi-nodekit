import ast
import re
from pathlib import Path
from string import Formatter

import pytest

from framework.entities import NotFoundError, ValidationError
from framework.messages import DEFAULT_CATALOG, ErrorCode, MessageCatalog, MessageKey, text


def test_every_key_has_one_renderable_template():
    assert set(DEFAULT_CATALOG.templates) == set(MessageKey)
    for key, template in DEFAULT_CATALOG.templates.items():
        parameters = {field: "value" for _, field, _, _ in Formatter().parse(template) if field}
        assert isinstance(text(key, **parameters), str)


def test_named_parameters_are_not_interpreted_as_more_templates():
    assert text(MessageKey.PORT_OCCUPIED, port=2096).startswith("Port 2096 already occupied")
    assert "{secret}" in text(MessageKey.PREREQUISITE_MISSING, name="{secret}")


@pytest.mark.parametrize("parameters", [{}, {"port": 2096, "extra": "no"}])
def test_wrong_template_arguments_fail_early(parameters):
    with pytest.raises(ValueError):
        text(MessageKey.PORT_OCCUPIED, **parameters)


def test_catalog_is_read_only_and_can_be_used_independently():
    with pytest.raises(TypeError):
        DEFAULT_CATALOG.templates[MessageKey.NODE_NOT_FOUND] = "changed"
    alternate = MessageCatalog({MessageKey.NODE_NOT_FOUND: "No such node"})
    assert alternate.render(MessageKey.NODE_NOT_FOUND) == "No such node"
    assert text(MessageKey.NODE_NOT_FOUND) == "Node not found"


def test_error_codes_do_not_depend_on_wording():
    assert NotFoundError(text(MessageKey.NODE_NOT_FOUND)).code == ErrorCode.NOT_FOUND
    assert ValidationError("Alternative wording").code.value == "validation_error"


def test_frontend_covers_all_backend_error_codes():
    frontend = Path(__file__).parents[2] / "frontend/src/framework/api/codes.ts"
    values = set(re.findall(r"= '([^']+)'", frontend.read_text()))
    assert {code.value for code in ErrorCode} <= values


def test_errors_and_progress_messages_are_not_inline_literals():
    root = Path(__file__).parents[1] / "src"
    for path in root.rglob("*.py"):
        if "messages" in path.relative_to(root).parts:
            continue
        for node in ast.walk(ast.parse(path.read_text())):
            call = node.exc if isinstance(node, ast.Raise) else None
            if (
                isinstance(node, ast.Call)
                and isinstance(node.func, ast.Attribute)
                and node.func.attr in {"emit", "info", "warning", "error"}
            ):
                call = node
            if isinstance(call, ast.Call) and call.args:
                assert not (
                    isinstance(call.args[0], ast.JoinedStr)
                    or (
                        isinstance(call.args[0], ast.Constant)
                        and isinstance(call.args[0].value, str)
                    )
                ), (
                    path,
                    call.lineno,
                )
