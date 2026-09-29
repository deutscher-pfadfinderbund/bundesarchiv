import pytest
from django.template import engines


def test_a_missing_template_variable_fails_naming_it() -> None:
    with pytest.raises(NameError, match="nicht_im_kontext"):
        engines["django"].from_string("{{ nicht_im_kontext }}").render({})
