# -*- coding: utf-8 -*-
"""A pythonic like make file """
import logging
import os
from pathlib import Path

import click
import subprocess
import glob

from pychronia_storygen.document_formats import load_yaml_file, load_jinja_environment, load_rst_file, \
    render_with_jinja_and_fact_tags, convert_rst_content_to_pdf



def _recursively_generate_group_sheets(data_tree: dict, group_breadcrumb: tuple, variables: dict,
                                       output_root_dir: Path, jinja_env, extra_rst2pdf_args):

    group_variables = data_tree["variables"]
    group_sheets = data_tree["sheets"]
    group_name = group_breadcrumb[-1] if group_breadcrumb else None  # LAST group name of the chain

    cumulated_variables = variables.copy()  # IMPORTANT
    cumulated_variables.update(group_variables)

    output_dir = output_root_dir.joinpath(*group_breadcrumb)

    for character_name, character_sheet_files in group_sheets.items():

        logging.info("Processing sheet for group %s and character %s"  % (group_name, character_name))
        ##print(">>> ", character_name, character_sheet_files)

        filepath_base = output_dir.joinpath(character_name)  # TODO improve

        full_rest_content = ""

        # Be tolerant if a single string was entered
        character_sheet_files = (character_sheet_files,) if isinstance(character_sheet_files, str) else character_sheet_files

        for sheet_file in character_sheet_files:
            logging.debug("Rendering template file %r with jinja2", sheet_file)
            rst_content_tpl = load_rst_file(sheet_file)

            jinja_context = dict(
                group_breadcrumb=group_breadcrumb,
                group_name=group_name,
                character_name=character_name,
                **cumulated_variables
            )
            rst_content = render_with_jinja_and_fact_tags(
                content=rst_content_tpl,
                jinja_env=jinja_env,
                jinja_context=jinja_context)
            full_rest_content += "\n\n" + rst_content

        logging.debug("Writing RST and PDF files with filename base %s", filepath_base)
        convert_rst_content_to_pdf(filepath_base=filepath_base,
                                   rst_content=full_rest_content,
                                   conf_file="rst2pdf.conf",
                                   extra_args=extra_rst2pdf_args)

    sub_data_tree = data_tree.get("groups", None)

    if sub_data_tree:
        for group_name, group_data_tree in sub_data_tree.items():
            _recursively_generate_group_sheets(group_data_tree, group_breadcrumb=group_breadcrumb + (group_name,), variables=cumulated_variables,
                                                   output_root_dir=output_root_dir, jinja_env=jinja_env, extra_rst2pdf_args=extra_rst2pdf_args)



@click.command()
# @click.option("--test", is_flag=True, help="test if the environement is nicely set up")
# @click.option("--coverage", is_flag=True, help="Generate coverage")
# @click.option("--apk", is_flag=True, help="Build an android apk with buildozer")
# @click.option("--deploy", is_flag=True, help="Deploy the app to your android device")
# @click.option("--po", is_flag=True, help="Create i18n message files")
# @click.option("--mo", is_flag=True, help="Create i18n message locales")
def cli():  #test, coverage, apk, deploy, po, mo):
    print("HELLO STARTING")

    logging.basicConfig(level=logging.DEBUG)  # FIXME

    extra_rst2pdf_args = ""  # FIXME

    project_dir = "example_project/"  # FIXME
    os.chdir(project_dir)

    output_root_dir = Path("./_output") # FIXME
    os.makedirs(output_root_dir, exist_ok=True)

    yaml_conf_file = "./configuration.yaml"

    use_macro_tags = True  # FIXME

    # FIXME here add TEMPLATES_COMMON too
    jinja_env = load_jinja_environment(["."], use_macro_tags=use_macro_tags)

    project_data_tree = load_yaml_file(yaml_conf_file)

    _recursively_generate_group_sheets(project_data_tree["sheet_generation"], group_breadcrumb=(), variables={},
                                           output_root_dir=output_root_dir, jinja_env=jinja_env, extra_rst2pdf_args=extra_rst2pdf_args)


if __name__ == "__main__":
    cli()