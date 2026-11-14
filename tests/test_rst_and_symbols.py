from pychronia_storygen.document_formats import write_rst_file
from pychronia_storygen.story_tags import detect_game_symbol_errors

BOM = chr(0xFEFF)
NBSP = chr(0xA0)


def _written(tmp_path, data, language=None):
    rst_file = tmp_path / "sub" / "out.txt"
    write_rst_file(rst_file, data, language=language)
    return rst_file.read_text(encoding="utf8")


def test_boms_are_stripped_everywhere_in_all_languages(tmp_path):
    parts = [BOM + "Title\n=====", BOM + "Second part", "Third " + BOM + "part"]
    for language in (None, "fr", "en"):
        text = _written(tmp_path, parts, language=language)
        assert BOM not in text
        assert text == "Title\n=====\n\nSecond part\n\nThird part"


def test_french_space_before_colon_becomes_non_breaking(tmp_path):
    assert _written(tmp_path, "Un mot : une chose :\nsuite ! Quoi ? a ; b", language="fr") == (
        "Un mot" + NBSP + ": une chose" + NBSP + ":\nsuite" + NBSP + "! Quoi" + NBSP + "? a" + NBSP + "; b")
    assert _written(tmp_path, "Un mot : suite", language=None) == "Un mot" + NBSP + ": suite"


def test_english_punctuation_is_left_alone(tmp_path):
    assert _written(tmp_path, "A word : thing !", language="en") == "A word : thing !"


def test_symbol_values_differing_by_whitespace_or_case_are_not_errors():
    registry = {"s1": ["Gold", " gold\n", "GOLD\r\n"], "s2": ["a\nb", "ab"]}
    assert detect_game_symbol_errors(registry) == (False, [])


def test_really_different_symbol_values_are_errors():
    has_errors, messages = detect_game_symbol_errors({"s1": ["gold", "silver "], "s2": ["x", " x"]})
    assert has_errors
    assert len(messages) == 1 and "'s1'" in messages[0][1]
