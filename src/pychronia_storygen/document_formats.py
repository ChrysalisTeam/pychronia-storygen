import copy
import functools
import logging
from pathlib import Path

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

    Macros are not searched in excluded_dirs (eg. build and output folders), which are relative to the templates root.
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
        templates = jinja_env.macros.environment.list_templates(extensions=("rst", "txt"))  # FIXME add .j2/.jinja extensions here!
        excluded_prefixes = tuple(Path(excluded_dir).as_posix().rstrip("/") + "/" for excluded_dir in excluded_dirs)
        for tpl in templates:
            if excluded_prefixes and tpl.startswith(excluded_prefixes):  # Jinja2 template names use forward slashes
                continue
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


def convert_rst_file_to_pdf(rst_file, pdf_file, conf_file="", extra_args="", language=None):
    """
    Use rst2pdf executable to convert rst file to pdf.

    IMPORTANT : you can output default styles with "rst2pdf --print-stylesheet"
    """

    conf_file = conf_file or ""
    assert not conf_file or os.path.exists(conf_file), conf_file  # must be in CWD

    extra_args = shlex.split(extra_args or "")
    if language:
        extra_args.insert(0, "--language=%s" % language)  # For smart quotes and hyphenation

    _create_missing_parent_folders(pdf_file)

    # fit-background-mode=scale doesn't work in config file, at the moment...
    # other options: --very-verbose --show-frame-boundary or just "-v"
    # FIXME replace this by lIBRARY CALL!!
    command = [sys.executable,  # The python environment of storygen, which has rst2pdf
               "-m", "rst2pdf.createpdf", str(rst_file), "-o", str(pdf_file), "--config=%s" % conf_file,
               "--fit-background-mode=scale", "--first-page-on-right", "--smart-quotes=2", "--break-side=any",
               "-e", DOTTED_TOC_EXTENSION, "--fit-literal-mode=shrink"] + extra_args

    #print("Current directory: %s" % os.getcwd())
    logging.debug("Executing command: %s" % command)  # FIXME

    res = subprocess.run(command).returncode

    assert res == 0, "Error when calling rst2pdf"


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
    convert_rst_file_to_pdf(rst_file, pdf_file,
                            conf_file=storygen_settings.dynamic_settings.get("rst2pdf_conf_file", ""),
                            extra_args=storygen_settings.dynamic_settings.get("rst2pdf_extra_args", ""),
                            language=storygen_settings.language)



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