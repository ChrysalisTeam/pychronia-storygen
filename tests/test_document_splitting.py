import io

import pytest
from pypdf import PdfReader, PdfWriter
from pypdf.generic import DictionaryObject, NameObject, ArrayObject

from pychronia_storygen import document_formats
from pychronia_storygen import cli as cli_module
from pychronia_storygen.document_formats import (
    split_odt_file_into_separate_documents, normalize_document_splitting, resolve_comment_sample,
    check_comment_sample, StorygenConfigError, _NO_SNIPPET_CHECK, FULL_PDF_NAME)


def _pdf_with_pages(path, page_texts, with_text_annotation=False):
    """Write a PDF whose pages contain the given texts (None meaning a blank page)."""
    from reportlab.pdfgen import canvas
    buffer = io.BytesIO()
    pdf = canvas.Canvas(buffer)
    for text in page_texts:
        if text:
            pdf.drawString(100, 700, text)
        pdf.showPage()
    pdf.save()
    reader = PdfReader(io.BytesIO(buffer.getvalue()))
    writer = PdfWriter(clone_from=reader)
    if with_text_annotation:
        annot = DictionaryObject({NameObject("/Type"): NameObject("/Annot"), NameObject("/Subtype"): NameObject("/Text")})
        writer.pages[0][NameObject("/Annots")] = ArrayObject([writer._add_object(annot)])
    writer.write(path)


@pytest.fixture
def fake_export(monkeypatch):
    """Replace the LibreOffice export by a PDF with given pages."""
    state = dict(pages=[], annotation=False, calls=0)

    def _export(soffice, input_filename, output_filename):
        state["calls"] += 1
        _pdf_with_pages(output_filename, state["pages"], with_text_annotation=state["annotation"])

    monkeypatch.setattr(document_formats, "_find_soffice", lambda: "soffice")
    monkeypatch.setattr(document_formats, "_export_odt_to_pdf", _export)
    return state


def _page_texts(pdf_path):
    return [page.extract_text().strip() for page in PdfReader(str(pdf_path)).pages]


def test_normalize_document_splitting():
    parts = normalize_document_splitting([["a", 1], [None, 2, None], ["b", 1, "Hello"],
                                          ["c", 1, {"fr": "Bonjour"}], ["d", 1, {"fr": "x", "en": None}]], language="en")
    assert parts == [("a", 1, _NO_SNIPPET_CHECK), (None, 2, None), ("b", 1, "Hello"),
                     ("c", 1, _NO_SNIPPET_CHECK), ("d", 1, None)]
    assert normalize_document_splitting([["c", 1, {"fr": "Bonjour"}]], language="fr")[0][2] == "Bonjour"
    assert normalize_document_splitting([["c", 1, {"fr": "Bonjour"}]])[0][2] is _NO_SNIPPET_CHECK  # no language
    assert normalize_document_splitting(None) == []


@pytest.mark.parametrize("entry", [["a"], ["a", 0], ["a", "2"], [3, 1], ["a", 1, 2], ["a", 1, "x", "y"], "a", ["a", True]])
def test_normalize_document_splitting_rejects_invalid_entries(entry):
    with pytest.raises(StorygenConfigError):
        normalize_document_splitting([entry])


def test_resolve_and_check_comment_sample():
    assert resolve_comment_sample("abc") == "abc"
    assert resolve_comment_sample({"fr": "abc"}, "fr") == "abc"
    assert resolve_comment_sample({"fr": "abc"}, "en") is None
    assert resolve_comment_sample(None, "en") is None
    with pytest.raises(StorygenConfigError):
        resolve_comment_sample(12)
    check_comment_sample("some {% xfact 'a' %} text", "xfact", "doc.odt")
    check_comment_sample("some text", None, "doc.odt")
    with pytest.raises(RuntimeError, match="were not extracted"):
        check_comment_sample("some text", "xfact", "doc.odt")


def test_split_with_skipped_pages_and_snippets(tmp_path, fake_export):
    fake_export["pages"] = ["Title page", "Alpha one", "Alpha two", None, "Gamma"]
    out = tmp_path / "out"
    out.mkdir()
    (out / "alpha.pdf").write_bytes(b"stale")
    (out / "other_unlisted.pdf").write_bytes(b"kept")

    split_odt_file_into_separate_documents(
        tmp_path / "doc.odt",
        [[None, 1, "title  page"], ["alpha", 2, "AlphaOne"], ["picture", 1, None],
         ["gamma", 1, {"fr": "Gamma", "en": "ignored"}]],
        out, language="fr")

    assert _page_texts(out / "alpha.pdf") == ["Alpha one", "Alpha two"]
    assert len(PdfReader(str(out / "picture.pdf")).pages) == 1
    assert _page_texts(out / "gamma.pdf") == ["Gamma"]
    assert not (out / FULL_PDF_NAME).exists()
    assert (out / "other_unlisted.pdf").read_bytes() == b"kept"
    assert sorted(p.name for p in out.glob("*.pdf")) == ["alpha.pdf", "gamma.pdf", "other_unlisted.pdf", "picture.pdf"]
    assert fake_export["calls"] == 1  # a single LibreOffice export


def test_split_wrong_page_count_fails_and_cleans(tmp_path, fake_export):
    fake_export["pages"] = ["a", "b", "c"]
    out = tmp_path / "out"
    out.mkdir()
    (out / "one.pdf").write_bytes(b"stale")
    with pytest.raises(RuntimeError, match="declare 2 pages, but .* has 3 pages"):
        split_odt_file_into_separate_documents(tmp_path / "doc.odt", [["one", 1], ["two", 1]], out)
    assert list(out.iterdir()) == []  # stale PDF and temporary full PDF are removed


def test_split_wrong_snippet_fails(tmp_path, fake_export):
    fake_export["pages"] = ["a text", "b text"]
    with pytest.raises(RuntimeError, match="Page 2 should start document two"):
        split_odt_file_into_separate_documents(tmp_path / "doc.odt", [["one", 1, "a text"], ["two", 1, "other"]], tmp_path)
    assert not (tmp_path / FULL_PDF_NAME).exists()


def test_split_unexpected_text_on_page_declared_without_text_fails(tmp_path, fake_export):
    fake_export["pages"] = ["some text"]
    with pytest.raises(RuntimeError, match="should start document one"):
        split_odt_file_into_separate_documents(tmp_path / "doc.odt", [["one", 1, None]], tmp_path)


def test_split_missing_language_in_snippet_mapping_means_no_check(tmp_path, fake_export):
    fake_export["pages"] = ["some text"]
    split_odt_file_into_separate_documents(tmp_path / "doc.odt", [["one", 1, {"fr": "other"}]], tmp_path, language="en")
    assert (tmp_path / "one.pdf").exists()


def test_split_text_annotations_are_refused(tmp_path, fake_export):
    fake_export.update(pages=["a"], annotation=True)
    with pytest.raises(RuntimeError, match="Gamemaster comments were exported"):
        split_odt_file_into_separate_documents(tmp_path / "doc.odt", [["one", 1]], tmp_path)
    assert list(tmp_path.iterdir()) == []


def test_prune_page_resources_drops_unused_images():
    from reportlab.pdfgen import canvas
    from reportlab.lib.utils import ImageReader
    from PIL import Image
    buffer = io.BytesIO()
    pdf = canvas.Canvas(buffer)
    for color in ("red", "blue"):
        image_buffer = io.BytesIO()
        Image.new("RGB", (4, 4), color).save(image_buffer, "PNG")
        image_buffer.seek(0)
        pdf.drawImage(ImageReader(image_buffer), 10, 10)
        pdf.showPage()
    pdf.save()
    reader = PdfReader(io.BytesIO(buffer.getvalue()))
    # Simulate an office suite sharing resources between pages
    shared = reader.pages[0]["/Resources"].get_object()["/XObject"].get_object()
    other = reader.pages[1]["/Resources"].get_object()["/XObject"].get_object()
    shared.update(other)
    reader.pages[1][NameObject("/Resources")] = reader.pages[0]["/Resources"]
    assert len(reader.pages[1]["/Resources"]["/XObject"]) == 2

    document_formats._prune_page_resources(reader.pages[1], reader)
    assert len(reader.pages[1]["/Resources"]["/XObject"]) == 1


def test_clues_cli_checks_comment_sample(storygen):
    storygen.write("configuration.yaml", """
        document_generation:
          clues:
            document_source: clues.odt
            comment_sample: {fr: "xfact", en: "missing text"}
            document_splitting: [[clue_one, 1]]
        """)
    storygen.write("clues.odt", "not really an odt")
    calls = []
    storygen.monkeypatch.setattr(cli_module, "extract_text_from_odt_file", lambda source: '{% xfact "a fact" %}text')
    storygen.monkeypatch.setattr(cli_module, "split_odt_file_into_separate_documents",
                                 lambda *args, **kwargs: calls.append(kwargs))
    storygen.run("--variable", "lang=fr")
    assert calls[0]["language"] == "fr"
    result = storygen.run("--variable", "lang=en", expect_ok=False)
    assert "were not extracted" in str(result.exception)
    storygen.run("--variable", "lang=de")  # no sample for this language, no check


SOFFICE_FODT = """<?xml version="1.0" encoding="UTF-8"?>
<office:document xmlns:office="urn:oasis:names:tc:opendocument:xmlns:office:1.0"
  xmlns:text="urn:oasis:names:tc:opendocument:xmlns:text:1.0"
  xmlns:style="urn:oasis:names:tc:opendocument:xmlns:style:1.0"
  xmlns:dc="http://purl.org/dc/elements/1.1/"
  office:version="1.2" office:mimetype="application/vnd.oasis.opendocument.text">
 <office:automatic-styles>
  <style:style style:name="Break" style:family="paragraph"><style:paragraph-properties fo:break-before="page"
    xmlns:fo="urn:oasis:names:tc:opendocument:xmlns:xsl-fo-compatible:1.0"/></style:style>
 </office:automatic-styles>
 <office:body><office:text>
  <text:p>Page one text<office:annotation><dc:creator>GM</dc:creator><text:p>SECRET gamemaster comment</text:p></office:annotation></text:p>
  <text:p text:style-name="Break">Page two text</text:p>
  <text:p text:style-name="Break">Page three text</text:p>
 </office:text></office:body>
</office:document>
"""


def test_split_with_real_libreoffice(tmp_path):
    try:
        document_formats._find_soffice()
    except RuntimeError:
        pytest.skip("LibreOffice is not installed")
    source = tmp_path / "doc.fodt"
    source.write_text(SOFFICE_FODT, encoding="utf8")
    out = tmp_path / "out"
    split_odt_file_into_separate_documents(
        source, [["first", 1, "Page one text"], [None, 1, "Page two"], ["third", 1, {"en": "Page three"}]], out, language="en")

    assert sorted(p.name for p in out.iterdir()) == ["first.pdf", "third.pdf"]
    assert _page_texts(out / "first.pdf") == ["Page one text"]  # the comment was not exported
    assert _page_texts(out / "third.pdf") == ["Page three text"]

    with pytest.raises(RuntimeError, match="declare 2 pages, but .* has 3 pages"):
        split_odt_file_into_separate_documents(source, [["first", 2]], out)
    assert [p.name for p in out.iterdir()] == ["third.pdf"]  # first.pdf removed, unlisted one kept
