from pathlib import Path

import pytest

from job_finder.keyword_filter import KeywordFilter

def test_should_reject_title():
    # Use default config path (should load the default config which has our new rejection rules)
    kf = KeywordFilter()
    
    # 1. Absolute rejection: formativ[oa]s?
    assert kf.should_reject_title("110 CONTRATOS FORMATIVOS PCA. PROFESIONAL") is True
    assert kf.should_reject_title("CONTRATOS FORMATIVAS DE EMPLEO") is True
    assert kf.should_reject_title("Curso formativo de Sistemas") is True # formativo is absolute, it doesn't matter if it has "Sistemas" (an IT override is only for relative)
    
    # 2. Relative rejection: bomber[oa]s? or mantenimiento
    assert kf.should_reject_title("ACTUALIZACIÓN BOLSAS BOMBERO/A") is True
    assert kf.should_reject_title("Bolsa de Trabajo de Bomberos") is True
    assert kf.should_reject_title("Técnico de Mantenimiento de Edificios") is True
    
    # 3. Relative override: contains relative keyword but also positive IT keyword
    assert kf.should_reject_title("TÉCNICO MANTENIMIENTO SISTEMAS INFORMÁTICOS") is False
    assert kf.should_reject_title("Ingeniero de Sistemas y Mantenimiento") is False
    
    # 4. Standard irrelevant and relevant titles
    assert kf.should_reject_title("Administrativo de Contratación") is False # No reject keyword present
    assert kf.should_reject_title("Técnico Auxiliar de Informática") is False # No reject keyword, has IT keyword


def test_portal_search_keywords_are_normalized_without_affecting_regex_lists(tmp_path):
    config_path = tmp_path / "keywords.yaml"
    config_path.write_text(
        """
it_keywords: ['Python']
contest_anchors: ['selección']
boilerplate_exclusions: []
title_reject_absolute: []
title_reject_relative: []
portal_search_keywords: ['  Python  ', '', 'Python', 'Artificial Intelligence']
""",
        encoding="utf-8",
    )

    kf = KeywordFilter(config_path)

    assert kf.portal_search_keywords == ["Python", "Artificial Intelligence"]
    assert kf.raw_it_keywords == ["Python"]


@pytest.mark.parametrize(
    "value",
    ["Python", {"term": "Python"}, ["Python", 3], None],
)
def test_invalid_portal_search_keywords_raise_contextual_error(tmp_path, value):
    config_path = tmp_path / "keywords.yaml"
    config_path.write_text(
        f"portal_search_keywords: {value!r}\n",
        encoding="utf-8",
    )

    with pytest.raises(ValueError, match="portal_search_keywords"):
        KeywordFilter(config_path)


def test_missing_portal_search_keywords_defaults_to_blank_discovery(tmp_path):
    config_path = tmp_path / "keywords.yaml"
    config_path.write_text("it_keywords: ['Python']\n", encoding="utf-8")

    assert KeywordFilter(config_path).portal_search_keywords == []
