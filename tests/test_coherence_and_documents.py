from pychronia_storygen import cli as cli_module


def _project(storygen, sheet_kind):
    storygen.write("configuration.yaml", """
        sheet_generation:
          sheets:
            alice:
              %s: sheet.rst
        document_generation:
          clues:
            document_source: clues.odt
            document_splitting:
              - [clue_one, 1]
        summary_generation:
          game_items_template: items.rst
          game_items_destination: items
        """ % sheet_kind)
    storygen.write("sheet.rst", '{% xfact "the fact" %}Hello')
    storygen.write("items.rst", "Items")
    storygen.write("clues.odt", "not really an odt")


def _fake_odt(storygen):
    calls = []
    storygen.monkeypatch.setattr(cli_module, "extract_text_from_odt_file",
                                 lambda source: '{% xitem "odt item" is provided %}text')
    storygen.monkeypatch.setattr(cli_module, "split_odt_file_into_separate_documents",
                                 lambda *args, **kwargs: calls.append((args, kwargs)))
    return calls


def test_serious_coherence_errors_give_nonzero_exit_code_after_generation(storygen):
    _project(storygen, "cheat_sheet")  # fact only in a cheat sheet is a serious error
    _fake_odt(storygen)
    result = storygen.run(expect_ok=False)
    assert result.exit_code == 1
    assert storygen.build_file("items.txt").exists()  # everything was generated before exiting


def test_coherent_project_exits_with_zero(storygen):
    _project(storygen, "full_sheet")
    _fake_odt(storygen)
    assert storygen.run().exit_code == 0


def test_errors_are_detected_even_without_summary_templates(storygen):
    _project(storygen, "cheat_sheet")
    storygen.write("configuration.yaml", """
        sheet_generation:
          sheets:
            alice:
              cheat_sheet: sheet.rst
        """)
    assert storygen.run(expect_ok=False).exit_code == 1


def test_skip_document_splitting_still_registers_tags(storygen):
    _project(storygen, "full_sheet")
    split_calls = _fake_odt(storygen)
    storygen.run()
    assert len(split_calls) == 1

    split_calls.clear()
    storygen.write("configuration.yaml", """
        document_generation:
          clues:
            document_source: clues.odt
            document_splitting: [[clue_one, 1]]
        summary_generation:
          game_items_template: items.rst
          game_items_destination: items
        """)
    storygen.write("items.rst", "{{ items_registry }}")
    storygen.run("--skip-document-splitting")
    assert split_calls == []
    assert "odt item" in storygen.build_text("items.txt")
