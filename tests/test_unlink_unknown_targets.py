from pychronia_storygen.document_formats import unlink_unknown_rst_targets

RST = """Title
=====

Known section
-------------

See `Known section`_ and `Missing  Section`_ and `the text <https://example.com>`_.
"""


def test_unlink_unknown_rst_targets(tmp_path):
    rst_file = tmp_path / "doc.txt"
    rst_file.write_text(RST, encoding="utf8")
    unlink_unknown_rst_targets(str(rst_file))
    text = rst_file.read_text(encoding="utf8")
    assert "`Known section`_" in text
    assert "`Missing  Section`_" not in text and "and Missing  Section and" in text
    assert "`the text <https://example.com>`_" in text


def test_setting_is_applied_per_sheet(storygen):
    storygen.write("configuration.yaml", """
        sheet_generation:
          sheets:
            alice:
              settings: {unlink_unknown_rst_targets: true}
              full_sheet: sheet.rst
            bob:
              full_sheet: sheet.rst
        """)
    storygen.write("sheet.rst", RST)
    storygen.run()
    assert "`Missing  Section`_" not in storygen.build_text("alice_full_sheet.txt")
    assert "`Missing  Section`_" in storygen.build_text("bob_full_sheet.txt")
