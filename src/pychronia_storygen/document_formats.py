import copy
import functools
import io
import logging
from pathlib import Path

import click
import jinja2
import os
import re
import shlex
import shutil
import subprocess
import sys
import tempfile
import textwrap
import yaml
from jinja2 import nodes, lexer, Template, pass_context
from jinja2.ext import Extension
from jinja2.runtime import Context
from markupsafe import Markup

from pychronia_storygen.story_tags import StoryChecksExtension


###################################
#      LANGUAGE MANAGEMENT        #
###################################

# Translated files are named "<name>_<language>.<ext>", with a 2-letter language code (eg. "intro_fr.rst", "intro_en.rst")
LANGUAGE_SUFFIX_REGEX = re.compile(r"_([a-z]{2})\.[^./\\]+$")


def get_filename_language(filename):
    """Return the language code of a translated file, or None if it has no language suffix."""
    match = LANGUAGE_SUFFIX_REGEX.search(str(filename))
    return match.group(1) if match else None


LANG_PLACEHOLDER = "{lang}"


class StorygenConfigError(click.ClickException):
    """Invalid project configuration, reported to the user without traceback."""


def expand_lang_placeholder(path, language):
    """
    Replace the "{lang}" placeholder of a path-valued configuration entry by the language code.

    This is the single place handling that placeholder; using it without a language (--lang) is an error.
    Falsy values and non-strings are returned as-is.
    """
    if not path or not isinstance(path, str) or LANG_PLACEHOLDER not in path:
        return path
    if not language:
        raise StorygenConfigError("Configuration entry %r uses the %s placeholder, but no language was given (use --lang)"
                                  % (path, LANG_PLACEHOLDER))
    return path.replace(LANG_PLACEHOLDER, language)


###################################
#  LOAD AND WRITE YAML/RST FILES  #
###################################


def load_yaml_file(yaml_file):
    with open(yaml_file, "r", encoding="utf8") as f:
        data = yaml.load(f, Loader=yaml.SafeLoader)
        return data


def load_rst_file(rst_file):
    with open(rst_file, "r", encoding="utf8") as f:
        data = f.read()
        return data


def _create_missing_parent_folders(path):
    # Autocreate missing folders
    folder = os.path.dirname(path)
    assert folder  # else, naked file basename, it's not good
    if not os.path.exists(folder):
        os.makedirs(folder)

def _convert_special_markups_and_punctuations(text, language=None):
    text = text.replace("[BR]",
                                textwrap.dedent("""

                                        .. raw:: pdf

                                           Spacer 0 15

                                           """))
    text = text.replace("[PAGEBREAK]",
                                textwrap.dedent("""

                                        .. raw:: pdf

                                           PageBreak   

                                        """))

    if language in (None, "fr"):  # Without language, texts are handled as French, like before languages were supported
        # Basic fixing of orphan punctuation marks for FR language...
        text = (text.replace(" !", u"\u00A0!")
                    .replace(" ?", u"\u00A0?")
                    .replace(" ;", u"\u00A0;")
                    .replace(" :\n", u"\u00A0:\n"))  # beware about RST directives here...
    return text


def write_rst_file(rst_file, data, language=None):
    """
    Creates missing folders along the way.

    Also converts [BR] and [PAGEBREAK] to pdf spacings, and fixes punctuation spaces of French texts, on the fly.
    """

    if isinstance(data, (tuple, list)):
        full_rst = "\n\n".join(data)
    else:
        assert isinstance(data, str), type(data)
        full_rst = data

    full_rst = _convert_special_markups_and_punctuations(full_rst, language=language)

    _create_missing_parent_folders(rst_file)

    with open(rst_file, "w", encoding="utf8") as f:
        f.write(full_rst)


####################################
#     PROCESS DATA WITH JINJA2     #
####################################


def load_jinja_environment(templates_root: list, use_macro_tags: bool, language=None, excluded_dirs=()):
    """
    If a language is given, macros are only searched in templates which are language-neutral, or in this language,
    so that translations of a same template don't declare the same macros twice.

    templates_root is the list of template directories, by decreasing priority: the first one is the project dir.
    Macros are not searched in excluded_dirs (eg. build and output folders), which are relative to the FIRST
    templates directory only.
    """
    # IMPORTANT - we refuse undefined template vars: exceptions get raised instead
    jinja_env = jinja2.Environment(undefined=jinja2.StrictUndefined,
                                   loader=jinja2.FileSystemLoader(templates_root),
                                   trim_blocks=False,
                                   lstrip_blocks=False,
                                   extensions=[StoryChecksExtension])

    @pass_context
    def dangerous_render(context, value):  # FIXME RENAME THIS!!!
        return render_with_jinja_and_fact_tags(content=value, jinja_env=jinja_env, jinja_context=context)

    jinja_env.filters['dangerous_render'] = dangerous_render

    if use_macro_tags:
        # Requires https://github.com/frascoweb/jinja-macro-tags or a fork
        from jinja_macro_tags import configure_environment
        configure_environment(jinja_env)

        # We do similarly to jinja_env.macros.register_from_environment(), but for RST files!
        excluded_prefixes = tuple(Path(excluded_dir).as_posix().rstrip("/") + "/" for excluded_dir in excluded_dirs)
        extra_dirs = [Path(templates_dir).resolve() for templates_dir in templates_root[1:]]
        templates = set()
        for idx, templates_dir in enumerate(templates_root):
            for tpl in jinja2.FileSystemLoader(templates_dir).list_templates():
                if tpl.rsplit(".", 1)[-1] not in ("rst", "txt"):  # FIXME add .j2/.jinja extensions here!
                    continue
                if idx == 0 and excluded_prefixes and tpl.startswith(excluded_prefixes):  # Jinja2 template names use forward slashes
                    continue  # Only the project dir (first one) contains generated files
                if idx == 0 and any(Path(templates_dir, tpl).resolve().is_relative_to(extra_dir) for extra_dir in extra_dirs):
                    continue  # Extra dir located inside the project dir, its templates are scanned from there instead
                templates.add(tpl)
        for tpl in sorted(templates):  # A template name present in several dirs is loaded from the first one
            template_language = get_filename_language(tpl)
            if language and template_language and template_language != language:
                logging.debug("Skipping template %s, which is not in language '%s'", tpl, language)
                continue
            logging.debug("Searching for jinja2 macros in template %s", tpl)
            jinja_env.macros.register_from_template(tpl)

    return jinja_env


def render_with_jinja(content=None, filename=None, *, jinja_env, jinja_context):
    """Simple rendering, without extra steps"""
    assert isinstance(jinja_context, (dict, Context)), type(jinja_context)
    assert bool(content) ^ bool(filename), (content, filename)
    assert content is None or isinstance(content, (str, bytes)), repr(content)
    #print("<<<RENDERING CONTENT>>>\n %s" % content[:1000].encode("ascii", "ignore"))
    if filename:
        template = jinja_env.get_template(filename)
    else:
        template = jinja_env.from_string(content)
    output = template.render(jinja_context)
    return output


def render_with_jinja_and_fact_tags(content=None, filename=None, *, jinja_env, jinja_context):  # FIXME rename this
    """
    Renders content and analyses/removes the {% fact %} markers from output.
    """
    output_tagged = render_with_jinja(content=content, filename=filename, jinja_env=jinja_env, jinja_context=jinja_context)
    output = jinja_env.extract_facts_from_intermediate_markup(output_tagged)  # must exist
    return output


###################################
#      LOAD DOCUMENT FILES        #
###################################


def extract_text_from_odt_file(clues_file):
    """
    Extract texts and comments from LibreOffice ODT file.
    """
    from . import odt2txt
    odt = odt2txt.OpenDocumentTextFile(clues_file)
    text = odt.toString()
    return text



def _find_soffice():
    """Return the path of the LibreOffice executable, or raise if LibreOffice is not installed."""
    candidates = [shutil.which("soffice")]
    if sys.platform == "win32":
        for env_var in ("ProgramFiles", "ProgramFiles(x86)", "ProgramW6432"):
            if os.environ.get(env_var):
                candidates.append(os.path.join(os.environ[env_var], "LibreOffice", "program", "soffice.exe"))
    else:
        candidates += ["/usr/bin/soffice", "/usr/lib/libreoffice/program/soffice", "/opt/libreoffice/program/soffice",
                       "/Applications/LibreOffice.app/Contents/MacOS/soffice"]
    for candidate in candidates:
        if candidate and os.path.exists(candidate):
            return candidate
    raise RuntimeError("LibreOffice (soffice executable) is required to split ODT documents, but was not found")


def _export_odt_pages_to_pdf(soffice, input_filename, output_filename, page_range):
    """
    Export some pages of an ODT document to PDF with LibreOffice, WITHOUT its comments (gamemaster annotations).

    Only the selected pages are exported, so their PDF doesn't embed the images of other pages.
    A private LibreOffice profile is used, so that the job is not handed over to an already running LibreOffice.
    """
    with tempfile.TemporaryDirectory(prefix="storygen_libreoffice_") as tmp_dir:
        profile_dir = os.path.join(tmp_dir, "profile")
        out_dir = os.path.join(tmp_dir, "out")
        os.makedirs(profile_dir)
        os.makedirs(out_dir)
        # JSON filter options need LibreOffice >= 7.4
        export_filter = ('pdf:writer_pdf_Export:{"PageRange":{"type":"string","value":"%s"},'
                         '"ExportNotes":{"type":"boolean","value":"false"},'
                         '"ExportNotesInMargin":{"type":"boolean","value":"false"}}' % page_range)
        cmd = [soffice, "-env:UserInstallation=%s" % Path(profile_dir).as_uri(), "--headless", "--norestore",
               "--nologo", "--convert-to", export_filter, "--outdir", out_dir, input_filename]
        logging.debug("Exporting pages %s of ODT file with command: %s", page_range, cmd)
        subprocess.run(cmd, check=True, stdout=subprocess.DEVNULL)
        exported_pdf = os.path.join(out_dir, os.path.splitext(os.path.basename(input_filename))[0] + ".pdf")
        if not os.path.exists(exported_pdf):
            raise RuntimeError("LibreOffice did not export %s to %s" % (input_filename, exported_pdf))
        shutil.move(exported_pdf, output_filename)


def split_odt_file_into_separate_documents(input_filename, splits_config, output_dir):
    input_filename = os.path.abspath(os.path.normpath(input_filename))
    output_dir = os.path.abspath(os.path.normpath(output_dir))
    os.makedirs(output_dir, exist_ok=True)

    soffice = _find_soffice()

    current_page = 1
    for idx, (basename, page_count) in enumerate(splits_config):
        prefix = ""  # or ("%02d_" % idx) if debugging needed
        output_filename = os.path.join(output_dir, prefix + basename + ".pdf")
        page_range = '%s-%s' % (current_page, current_page + page_count - 1)
        _export_odt_pages_to_pdf(soffice, input_filename, output_filename, page_range=page_range)

        # IMPORTANT - GAMEMASTER ANNOTATIONS must never be visible in game documents
        with open(output_filename, 'rb') as f:
            data = f.read()
        if re.search(br'/Subtype\s*/Text\b', data):
            raise RuntimeError("Gamemaster comments were exported to game document '%s'" % output_filename)

        current_page += page_count



####################################
#      CONVERT MARKUP TO PDF       #
####################################

DOTTED_TOC_EXTENSION = os.path.join(os.path.dirname(os.path.abspath(__file__)), "dotted_toc_compat.py")


def unlink_unknown_rst_targets(rst_file):
    """
    Turn references to missing targets (eg. sections absent from a truncated manual) into plain text,
    since recent rst2pdf versions abort on "Unknown target name" errors. The RST file is rewritten in place.
    """
    import docutils.core

    with open(rst_file, "r", encoding="utf8") as f:
        rst_content = f.read()

    warning_stream = io.StringIO()
    docutils.core.publish_doctree(rst_content, settings_overrides=dict(halt_level=5, report_level=3,
                                                                       warning_stream=warning_stream))
    unknown_targets = set(re.findall(r'Unknown target name: "(.+?)"\.', warning_stream.getvalue()))
    if not unknown_targets:
        return

    logging.info("Unlinking unknown RST targets in %s: %s", rst_file, sorted(unknown_targets))

    def _unlink(matchobj):
        name = matchobj.group(1)
        normalized_name = " ".join(name.split()).lower()  # like docutils.nodes.fully_normalize_name()
        return name if normalized_name in unknown_targets else matchobj.group(0)

    rst_content = re.sub(r'`([^`<>]+)`_(?!_)', _unlink, rst_content)
    with open(rst_file, "w", encoding="utf8") as f:
        f.write(rst_content)


RST2PDF_ERROR_MARKERS = ("[ERROR]", "[CRITICAL]", "(ERROR/", "(SEVERE/")
DEFAULT_SMART_QUOTES = 2  # English rules, kept as default for backward-compatibility


def find_rst2pdf_errors(output_lines):
    """Return the lines of rst2pdf logs which report an error, since rst2pdf often exits with code 0 despite them."""
    return [line.rstrip() for line in output_lines if any(marker in line for marker in RST2PDF_ERROR_MARKERS)]


def convert_rst_file_to_pdf(rst_file, pdf_file, conf_file="", extra_args="", language=None,
                            smart_quotes=DEFAULT_SMART_QUOTES, docutils_conf_file=None):
    """
    Use rst2pdf executable to convert rst file to pdf.

    The output of rst2pdf is scanned for errors (eg. missing images), and on any failure the PDF file is removed,
    so that no stale or broken PDF remains.

    docutils_conf_file is given to rst2pdf (ie. docutils) through the DOCUTILSCONFIG environment variable.

    IMPORTANT : you can output default styles with "rst2pdf --print-stylesheet"
    """

    conf_file = conf_file or ""
    assert not conf_file or os.path.exists(conf_file), conf_file  # must be in CWD

    extra_args = shlex.split(extra_args or "")
    if language:
        extra_args.insert(0, "--language=%s" % language)  # For smart quotes and hyphenation

    env = dict(os.environ, PYTHONUTF8="1")  # else Windows uses an ANSI codepage for piped logs
    if docutils_conf_file:
        if not os.path.exists(docutils_conf_file):
            raise StorygenConfigError("Docutils configuration file %r does not exist" % str(docutils_conf_file))
        env["DOCUTILSCONFIG"] = os.path.abspath(docutils_conf_file)

    _create_missing_parent_folders(pdf_file)
    if os.path.exists(pdf_file):
        os.remove(pdf_file)  # so that no PDF of a previous run remains if this one fails

    # fit-background-mode=scale doesn't work in config file, at the moment...
    # other options: --very-verbose --show-frame-boundary or just "-v"
    # FIXME replace this by lIBRARY CALL!!
    command = [sys.executable,  # The python environment of storygen, which has rst2pdf
               "-m", "rst2pdf.createpdf", str(rst_file), "-o", str(pdf_file), "--config=%s" % conf_file,
               "--fit-background-mode=scale", "--first-page-on-right", "--smart-quotes=%s" % smart_quotes,
               "--break-side=any",
               "-e", DOTTED_TOC_EXTENSION, "--fit-literal-mode=shrink"] + extra_args

    logging.debug("Executing command: %s" % command)

    # rst2pdf exits with code 0 even when it logs errors (eg. missing images), so we check its logs too
    output_lines = []
    with subprocess.Popen(command, stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
                          encoding="utf8", errors="replace", env=env) as process:
        for line in process.stdout:
            sys.stderr.write(line)
            output_lines.append(line)
    error_lines = find_rst2pdf_errors(output_lines)

    if process.returncode or error_lines:
        if os.path.exists(pdf_file):
            os.remove(pdf_file)  # rst2pdf writes the PDF despite errors, don't let it pass for a valid one
        if process.returncode:
            raise RuntimeError("Error %s when calling rst2pdf on %s" % (process.returncode, rst_file))
        raise RuntimeError("rst2pdf reported errors on %s:\n%s" % (rst_file, "\n".join(error_lines)))


def convert_rst_content_to_pdf(filepath_base: Path, rst_content, conf_file="", extra_args=""):  #FIXME remove this??
    """
    We use an intermediate RST file, both for simplicity and debugging.
    """
    rst_file = filepath_base.with_suffix(".txt")  # Better than .rst for non-techs
    pdf_file = filepath_base.with_suffix(".pdf")

    write_rst_file(rst_file, data=rst_content)
    convert_rst_file_to_pdf(rst_file, pdf_file, conf_file=conf_file, extra_args=extra_args)


def generate_rst_and_pdf_files(rst_content, relative_path, storygen_settings):
    """
    We use an intermediate RST file, both for simplicity and debugging.
    """
    assert not Path(relative_path).is_absolute(), relative_path
    rst_file = storygen_settings.build_root_dir.joinpath(relative_path).with_suffix(".txt")  # Better than .rst for non-techs

    pdf_file = storygen_settings.output_root_dir.joinpath(relative_path).with_suffix(".pdf")

    write_rst_file(rst_file, data=rst_content, language=storygen_settings.language)
    if storygen_settings.dynamic_settings.get("unlink_unknown_rst_targets", False):
        unlink_unknown_rst_targets(rst_file)  # On the final RST, after jinja rendering
    convert_rst_file_to_pdf(rst_file, pdf_file,
                            conf_file=expand_lang_placeholder(storygen_settings.dynamic_settings.get("rst2pdf_conf_file", ""),
                                                              storygen_settings.language),
                            extra_args=storygen_settings.dynamic_settings.get("rst2pdf_extra_args", ""),
                            language=storygen_settings.language,
                            smart_quotes=storygen_settings.dynamic_settings.get("rst2pdf_smart_quotes", DEFAULT_SMART_QUOTES),
                            docutils_conf_file=expand_lang_placeholder(
                                storygen_settings.dynamic_settings.get("docutils_conf_file"), storygen_settings.language))



####################################
#           ALL AT ONCE            #
####################################


def render_with_jinja_and_convert_to_pdf(source_filename=None, *, relative_path=None, jinja_context, storygen_settings):

    rst_content = render_with_jinja(filename=source_filename, jinja_env=storygen_settings.jinja_env,
                                    jinja_context=jinja_context)

    relative_path = relative_path or Path(source_filename).with_suffix("")
    assert not relative_path.is_absolute(), relative_path

    generate_rst_and_pdf_files(
        rst_content=rst_content, relative_path=relative_path, storygen_settings=storygen_settings)