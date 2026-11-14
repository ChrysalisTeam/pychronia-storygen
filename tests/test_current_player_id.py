CONFIG = """
    sheet_generation:
      groups:
        npcs:
          variables: {current_player_id: group_default}
          sheets:
            inherits:
              full_sheet: sheet.rst
            overrides:
              variables: {current_player_id: sheet_choice}
              full_sheet: sheet.rst
            nobody:
              variables: {current_player_id: null}
              full_sheet: sheet.rst
      sheets:
        alice:
          full_sheet: sheet.rst
    """


def test_current_player_id_defaults_and_overrides(storygen):
    storygen.write("configuration.yaml", CONFIG)
    storygen.write("sheet.rst", """
        {{ current_player_id }} {% fact "the fact" %}
        """)
    storygen.run()
    text = lambda path: storygen.build_text(path)
    assert "alice" in text("alice_full_sheet.txt")
    assert "group_default" in text("npcs/inherits_full_sheet.txt")
    assert "sheet_choice" in text("npcs/overrides_full_sheet.txt")
    assert "None" in text("npcs/nobody_full_sheet.txt")


def test_facts_registered_per_effective_player_id(storygen):
    storygen.write("configuration.yaml", CONFIG + """
    summary_generation:
      game_facts_template: facts.rst
      game_facts_destination: facts
    """)
    storygen.write("sheet.rst", '{% fact "the fact" %}')
    storygen.write("facts.rst", "{% for name, data in facts_registry.items() %}{{ name }}: {{ data }}{% endfor %}")
    storygen.run()
    registry = storygen.build_text("facts.txt")
    for player in ("alice", "group_default", "sheet_choice"):
        assert player in registry
    assert "nobody" not in registry and "inherits" not in registry
