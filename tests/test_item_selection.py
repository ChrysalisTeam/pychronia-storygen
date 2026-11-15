from pychronia_storygen import cli as cli_module


ALL_ITEM_IDS = [  # in processing order: sheets of a group before those of its subgroups
    "sheets/gamemaster_manual/full",
    "sheets/players/alice/full",
    "sheets/players/alice/cheat",
    "sheets/players/bob/full",
    "documents/clues",
    "inventories/main/per_section",
    "summaries/facts",
    "summaries/items",
]


def _project(storygen):
    storygen.write("configuration.yaml", """
        sheet_generation:
          groups:
            players:
              sheets:
                alice:
                  full_sheet: alice.rst
                  cheat_sheet: alice_cheat.rst
                bob:
                  full_sheet: bob.rst
          sheets:
            gamemaster_manual:
              full_sheet: manual.rst
        document_generation:
          clues:
            document_source: clues.odt
            document_splitting: [[clue_one, 1]]
        inventory_generation:
          main:
            inventory_data: inventory.yaml
            inventory_per_section_template: per_section.rst
            inventory_per_section_destination: inventory_per_section
        summary_generation:
          game_facts_template: facts.rst
          game_facts_destination: facts
          game_items_template: items.rst
          game_items_destination: items
        """)
    storygen.write("alice.rst", '{% xfact "alice fact" %}Alice')
    storygen.write("alice_cheat.rst", '{% xfact "alice fact" %}Alice cheat')
    storygen.write("bob.rst", '{% xfact "bob fact" %}Bob')
    storygen.write("manual.rst", "Manual")
    storygen.write("inventory.yaml", "{}")
    storygen.write("per_section.rst", "Inventory")
    storygen.write("facts.rst", "{{ facts_registry }}")
    storygen.write("items.rst", "{{ items_registry }}")
    storygen.write("clues.odt", "not really an odt")

    split_calls = []
    storygen.monkeypatch.setattr(cli_module, "extract_text_from_odt_file",
                                 lambda source: '{% xitem "odt item" is provided %}text')
    storygen.monkeypatch.setattr(cli_module, "split_odt_file_into_separate_documents",
                                 lambda *args, **kwargs: split_calls.append(args[0]))
    storygen.monkeypatch.setattr(cli_module, "analyze_and_normalize_game_items", lambda *args, **kwargs: ({}, {}))
    return split_calls


def _generated_pdfs(storygen):
    return sorted(call["pdf_file"].relative_to("_output").as_posix() for call in storygen.pdf_calls)


ALL_PDFS = sorted([
    "players/alice_full_sheet.pdf",
    "players/alice_cheat_sheet.pdf",
    "players/bob_full_sheet.pdf",
    "gamemaster_manual_full_sheet.pdf",
    "inventory_per_section.pdf",
    "facts.pdf",
    "items.pdf",
])


def test_everything_is_generated_without_selection(storygen):
    split_calls = _project(storygen)
    storygen.run()
    assert _generated_pdfs(storygen) == ALL_PDFS
    assert split_calls == ["clues.odt"]


def test_only_selects_items_by_glob_pattern(storygen):
    split_calls = _project(storygen)
    storygen.run("--only", "*alice*")
    assert _generated_pdfs(storygen) == ["players/alice_cheat_sheet.pdf", "players/alice_full_sheet.pdf"]
    assert split_calls == []
    assert not storygen.build_file("players/bob_full_sheet.txt").exists()

    storygen.run("--only", "*/cheat", "--only", "documents/*")
    assert _generated_pdfs(storygen) == ["players/alice_cheat_sheet.pdf"]
    assert split_calls == ["clues.odt"]


def test_skip_unselects_items_even_if_matched_by_only(storygen):
    split_calls = _project(storygen)
    storygen.run("--only", "sheets/players/*", "--skip", "*/cheat")
    assert _generated_pdfs(storygen) == ["players/alice_full_sheet.pdf", "players/bob_full_sheet.pdf"]

    storygen.run("--skip", "sheets/*", "--skip", "documents/clues")
    assert _generated_pdfs(storygen) == ["facts.pdf", "inventory_per_section.pdf", "items.pdf"]
    assert split_calls == []


def test_unselected_items_still_feed_the_coherence_analysis(storygen):
    _project(storygen)
    storygen.run("--only", "summaries/*")
    assert _generated_pdfs(storygen) == ["facts.pdf", "items.pdf"]
    assert "bob fact" in storygen.build_text("facts.txt")  # from an unselected sheet
    assert "odt item" in storygen.build_text("items.txt")  # from an unselected document bundle

    storygen.write("bob.rst", '{% xfact "bob fact" %}{% xitem "ghost item" is needed %}Bob')  # item never provided
    result = storygen.run("--only", "*alice*", expect_ok=False)
    assert result.exit_code == 1  # coherence errors of unselected items are still detected
    assert _generated_pdfs(storygen) == ["players/alice_cheat_sheet.pdf", "players/alice_full_sheet.pdf"]


def test_patterns_matching_no_item_are_errors(storygen):
    _project(storygen)
    result = storygen.run("--only", "*alice*", "--skip", "*alise*", expect_ok=False)
    assert result.exit_code == 2
    assert "'*alise*' match no item ID" in result.output
    assert "'*alice*'" not in result.output


def test_list_prints_item_ids_without_generating_anything(storygen):
    split_calls = _project(storygen)
    storygen.write("bob.rst", "{{ undefined_macro() }}")  # templates are not even rendered
    result = storygen.run("--list", "--only", "sheets/*", "--skip", "*/cheat")
    assert result.output.splitlines() == [
        ("[x] " if item_id in ("sheets/players/alice/full", "sheets/players/bob/full",
                               "sheets/gamemaster_manual/full") else "[ ] ") + item_id
        for item_id in ALL_ITEM_IDS
    ]
    assert storygen.pdf_calls == [] and split_calls == []
    assert not (storygen.project_dir / "_output").exists()
    assert not (storygen.project_dir / "_build").exists()


def test_type_option_was_removed(storygen):
    _project(storygen)
    result = storygen.run("-t", "sheets", expect_ok=False)
    assert result.exit_code == 2
    assert "No such option" in result.output


def test_no_pdf_only_writes_rst_files(storygen):
    split_calls = _project(storygen)
    storygen.write("bob.rst", '{% xfact "bob fact" %}{% xitem "ghost item" is needed %}Bob')  # item never provided
    result = storygen.run("--no-pdf", expect_ok=False)
    assert result.exit_code == 1  # coherence is still analysed
    assert storygen.pdf_calls == [] and split_calls == []
    assert not (storygen.project_dir / "_output").joinpath("players").exists()
    for rst_file in ["players/alice_full_sheet.txt", "players/alice_cheat_sheet.txt", "players/bob_full_sheet.txt",
                     "gamemaster_manual_full_sheet.txt", "inventory_per_section.txt", "facts.txt", "items.txt"]:
        assert storygen.build_file(rst_file).exists(), rst_file
    assert "odt item" in storygen.build_text("items.txt")  # documents are still parsed


def test_no_pdf_combines_with_item_selection(storygen):
    _project(storygen)
    storygen.run("--no-pdf", "--only", "*bob*")
    assert storygen.pdf_calls == []
    assert storygen.build_file("players/bob_full_sheet.txt").exists()
    assert not storygen.build_file("players/alice_full_sheet.txt").exists()
