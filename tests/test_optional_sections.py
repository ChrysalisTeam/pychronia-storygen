def test_empty_configuration(storygen):
    storygen.write("configuration.yaml", "")
    storygen.run()


def test_only_sheets_section(storygen):
    storygen.write("configuration.yaml", """
        sheet_generation:
          sheets:
            alice:
              full_sheet: alice.rst
        """)
    storygen.write("alice.rst", "Hello {{ current_player_id }}")
    storygen.run()
    assert "Hello alice" in storygen.build_text("alice_full_sheet.txt")


def test_group_without_sheets_key(storygen):
    storygen.write("configuration.yaml", """
        sheet_generation:
          groups:
            npcs:
              sheets:
                bob:
                  full_sheet: bob.rst
            empty_group:
              variables: {a: 1}
        """)
    storygen.write("bob.rst", "Bob")
    storygen.run()
    assert storygen.build_file("npcs/bob_full_sheet.txt").exists()


def test_summary_templates_independently_optional(storygen):
    storygen.write("configuration.yaml", """
        summary_generation:
          game_items_template: items.rst
          game_items_destination: summaries/items
        """)
    storygen.write("items.rst", "Items: {{ items_registry | length }}")
    storygen.run()
    assert storygen.build_file("summaries/items.txt").exists()
    assert not storygen.build_file("summaries/facts.txt").exists()


def test_inventory_with_missing_keys(storygen):
    storygen.write("configuration.yaml", """
        inventory_generation:
          nothing: {}
          partial:
            inventory_data: inv.yaml
            inventory_per_section_template: sec.rst
            inventory_per_section_destination: inventories/sec
        """)
    storygen.write("inv.yaml", """
        Section A:
          - Torch
        """)
    storygen.write("sec.rst", "Sections: {{ items_per_section | length }}")
    storygen.run()
    assert storygen.build_file("inventories/sec.txt").exists()
    assert not storygen.build_file("inventories/crate.txt").exists()
