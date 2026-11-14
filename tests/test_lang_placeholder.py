CONFIG = """
    sheet_generation:
      sheets:
        alice:
          full_sheet: ["intro_{lang}.rst", common.rst]
    inventory_generation:
      main:
        inventory_data: inv_{lang}.yaml
        inventory_per_section_template: sec_{lang}.rst
        inventory_per_section_destination: inventories/sec_{lang}
    summary_generation:
      game_items_template: items_{lang}.rst
      game_items_destination: summaries/items_{lang}
    """


def _write_project(storygen):
    storygen.write("configuration.yaml", CONFIG)
    for lang in ("fr", "en"):
        storygen.write("intro_%s.rst" % lang, "Intro %s" % lang)
        storygen.write("inv_%s.yaml" % lang, "Section:\n  - Item %s\n" % lang)
        storygen.write("sec_%s.rst" % lang, "Sec {{ items_per_section }}")
        storygen.write("items_%s.rst" % lang, "Items %s" % lang)
    storygen.write("common.rst", "Common")


def test_lang_placeholder_expanded_everywhere(storygen):
    _write_project(storygen)
    storygen.run("--lang", "en")
    assert "Intro en" in storygen.build_text("alice_full_sheet.txt", lang="en")
    assert "Item en" in storygen.build_text("inventories/sec_en.txt", lang="en")
    assert "Items en" in storygen.build_text("summaries/items_en.txt", lang="en")
    storygen.run("--lang", "fr")
    assert "Intro fr" in storygen.build_text("alice_full_sheet.txt", lang="fr")


def test_lang_placeholder_without_language_is_an_error(storygen):
    _write_project(storygen)
    result = storygen.run(expect_ok=False)
    assert result.exit_code != 0
    assert "{lang}" in result.output and "--lang" in result.output
