import copy
import functools
import logging
from pathlib import Path

import jinja2
import os
import re
import sys
import textwrap
import yaml
from jinja2 import nodes, lexer, Template, pass_context
from jinja2.ext import Extension
from jinja2.runtime import Context
from markupsafe import Markup

from pychronia_storygen.story_tags import StoryChecksExtension


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

def _convert_special_markups_and_punctuations(text):
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

    # Basic fixing of orphan punctuation marks for FR language...
    text = (text.replace(" !", u"\u00A0!")
                .replace(" ?", u"\u00A0?")
                .replace(" ;", u"\u00A0;")
                .replace(" :\n", u"\u00A0:\n"))  # beware about RST directives here...
    return text


def write_rst_file(rst_file, data):
    """
    Creates missing folders along the way.

    Also converts [BR] and [PAGEBREAK] to pdf spacings, and fixes punctuation spaces, on the fly.
    """

    if isinstance(data, (tuple, list)):
        full_rst = "\n\n".join(data)
    else:
        assert isinstance(data, str), type(data)
        full_rst = data

    full_rst = _convert_special_markups_and_punctuations(full_rst)

    _create_missing_parent_folders(rst_file)

    with open(rst_file, "w", encoding="utf8") as f:
        f.write(full_rst)


####################################
#     PROCESS DATA WITH JINJA2     #
####################################


def load_jinja_environment(templates_root: list, use_macro_tags: bool):
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
        for tpl in templates:
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



def split_odt_file_into_separate_documents(input_filename, splits_config, output_dir):
    input_filename = os.path.abspath(os.path.normpath(input_filename))
    output_dir = os.path.abspath(os.path.normpath(output_dir))
    os.makedirs(output_dir, exist_ok=True)

    unoconv_script = os.path.join(os.path.dirname(__file__), 'unoconv.py')

    current_page = 1
    for idx, (basename, page_count) in enumerate(splits_config):
        prefix = ""  # or ("%02d_" % idx) if debugging needed
        output_filename = os.path.join(output_dir, prefix + basename + ".pdf")
        variables = dict(python_executable=sys.executable,
                         unoconv_script=unoconv_script,
                         input=input_filename,
                         output=output_filename,
                         page_range='%s-%s' % (current_page, current_page + page_count - 1))
        cmd = '%(python_executable)s "%(unoconv_script)s" -f pdf -o "%(output)s" -e PageRange=%(page_range)s "%(input)s"' % variables
        logging.debug("Splitting PDF with command: %s", cmd)
        res = os.system(cmd)
        assert res == 0, "Error during pdf-splitting command execution"

        # IMPORTANT - remove GAMEMASTER ANNOTATIONS from PDF file
        # (BEWARE, this seems to CORRUPT a bit the PDF, find a better REGEX someday?)
        with open(output_filename, 'rb') as f:
            data = f.read()
        if b'Annots' not in data :
            logging.warning("No annotations/comments found in PDF document '%s', each separate game document should have its own for the gamemasters",output_filename)
        else:
            regex = br'/Annots\s*\[[^]]+\]'
            data = re.sub(regex, b'', data, flags=re.MULTILINE)
            assert b'Annots' not in data  # no more clues VISIBLE (but they are still hidden in PDF file alas)
            with open(output_filename, 'wb') as f:
                f.write(data)

        current_page += page_count



####################################
#      CONVERT MARKUP TO PDF       #
####################################

def convert_rst_file_to_pdf(rst_file, pdf_file, conf_file="", extra_args=""):
    """
    Use rst2pdf executable to convert rst file to pdf.

    IMPORTANT : you can output default styles with "rst2pdf --print-stylesheet"
    """

    conf_file = conf_file or ""
    assert not conf_file or os.path.exists(conf_file), conf_file  # must be in CWD

    extra_args = extra_args or ""

    vars = dict(rst_file=rst_file,
                pdf_file=pdf_file,
                conf_file=conf_file,
                extra_args=extra_args)

    _create_missing_parent_folders(pdf_file)

    # fit-background-mode=scale doesn't work in config file, at the moment...
    # other options: --very-verbose --show-frame-boundary or just "-v"
    # FIXME replace this by lIBRARY CALL!!
    command = r'''python -m rst2pdf.createpdf "%(rst_file)s" -o "%(pdf_file)s" --config=%(conf_file)s --fit-background-mode=scale --first-page-on-right --smart-quotes=2 --break-side=any  -e dotted_toc --fit-literal-mode=shrink %(extra_args)s''' % vars

    #print("Current directory: %s" % os.getcwd())
    logging.debug("Executing command: %s" % command)  # FIXME

    res = os.system(command)

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

    write_rst_file(rst_file, data=rst_content)
    convert_rst_file_to_pdf(rst_file, pdf_file,
                            conf_file=storygen_settings.dynamic_settings.get("rst2pdf_conf_file", ""),
                            extra_args=storygen_settings.dynamic_settings.get("rst2pdf_extra_args", ""))



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