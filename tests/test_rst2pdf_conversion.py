import pytest
from pypdf import PdfReader

from pychronia_storygen import document_formats
from pychronia_storygen.document_formats import convert_rst_file_to_pdf, find_rst2pdf_errors


def test_find_rst2pdf_errors():
    lines = ["[INFO] fine\n", "[ERROR] createpdf.py:123 Missing image file: x.png\n",
             "foo.txt:3: (ERROR/3) Unknown target name: \"bar\".\n", "[WARNING] meh\n"]
    assert len(find_rst2pdf_errors(lines)) == 2
    assert find_rst2pdf_errors(["[WARNING] only a warning"]) == []


def test_settings_reach_rst2pdf(storygen):
    storygen.write("docutils.conf", "[general]\n")
    storygen.write("configuration.yaml", """
        settings:
          rst2pdf_smart_quotes: 0
          docutils_conf_file: docutils.conf
        sheet_generation:
          sheets:
            alice:
              full_sheet: sheet.rst
            bob:
              settings: {rst2pdf_smart_quotes: 1}
              full_sheet: sheet.rst
        """)
    storygen.write("sheet.rst", "Hello")
    storygen.run()
    calls = {call["rst_file"].name: call for call in storygen.pdf_calls}
    assert calls["alice_full_sheet.txt"]["smart_quotes"] == 0
    assert calls["bob_full_sheet.txt"]["smart_quotes"] == 1
    assert calls["alice_full_sheet.txt"]["docutils_conf_file"] == "docutils.conf"


def test_default_smart_quotes_unchanged(storygen):
    storygen.write("configuration.yaml", "sheet_generation:\n  sheets:\n    alice:\n      full_sheet: sheet.rst\n")
    storygen.write("sheet.rst", "Hello")
    storygen.run()
    assert storygen.pdf_calls[0]["smart_quotes"] == 2
    assert not storygen.pdf_calls[0]["docutils_conf_file"]


def test_real_rst2pdf_conversion_and_missing_image(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    good = tmp_path / "good.txt"
    good.write_text("Title\n=====\n\nHello \"world\"\n", encoding="utf8")
    pdf = tmp_path / "out" / "good.pdf"
    conf = tmp_path / "rst2pdf.conf"
    conf.write_text("[general]\ncompressed=false\n", encoding="utf8")
    convert_rst_file_to_pdf(str(good), str(pdf), conf_file=str(conf))
    assert pdf.read_bytes().startswith(b"%PDF")
    contents = PdfReader(str(pdf)).pages[0]["/Contents"].get_object()
    assert "/FlateDecode" in contents.get("/Filter", [])  # always compressed, despite the conf file

    bad = tmp_path / "bad.txt"
    bad.write_text("Title\n=====\n\n.. image:: missing_image.png\n", encoding="utf8")
    bad_pdf = tmp_path / "out" / "bad.pdf"
    bad_pdf.write_bytes(b"stale")
    with pytest.raises(RuntimeError, match="reported errors"):
        convert_rst_file_to_pdf(str(bad), str(bad_pdf))
    assert not bad_pdf.exists()
