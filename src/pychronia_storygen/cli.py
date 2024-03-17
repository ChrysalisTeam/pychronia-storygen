# -*- coding: utf-8 -*-
"""A pythonic like make file """
import logging
import os
from pathlib import Path

import click
import subprocess
import glob

from pychronia_storygen.document_formats import load_yaml_file, load_jinja_environment, load_rst_file, \
    render_with_jinja_and_fact_tags, convert_rst_content_to_pdf, render_with_jinja
from pychronia_storygen.story_tags import CURRENT_PLAYER_VARNAME


def _recursively_generate_group_sheets(data_tree: dict, group_breadcrumb: tuple, variables: dict,
                                       output_root_dir: Path, jinja_env, rst2pdf_extra_args):

    group_variables = data_tree["variables"]
    group_sheets = data_tree["sheets"]
    group_name = group_breadcrumb[-1] if group_breadcrumb else None  # LAST group name of the chain

    cumulated_variables = variables.copy()  # IMPORTANT
    cumulated_variables.update(group_variables)

    output_dir = output_root_dir.joinpath(*group_breadcrumb)

    for character_name, character_sheet_files in group_sheets.items():

        player_variables = variables.copy()  # IMPORTANT
        player_variables.update(group_variables)
        player_variables[CURRENT_PLAYER_VARNAME] = character_name

        logging.info("Processing sheet for group '%s' and character '%s'"  % (group_name or "<empty>", character_name))
        ##print(">>> ", character_name, character_sheet_files)

        filepath_base = output_dir.joinpath(character_name)  # TODO improve

        full_rst_content = ""

        # Be tolerant if a single string was entered
        character_sheet_files = (character_sheet_files,) if isinstance(character_sheet_files, str) else character_sheet_files

        for sheet_file in character_sheet_files:
            logging.debug("Rendering template file %r with jinja2", sheet_file)
            rst_content_tpl = load_rst_file(sheet_file)

            jinja_context = dict(
                group_breadcrumb=group_breadcrumb,
                group_name=group_name,
                character_name=character_name,
                **player_variables
            )
            rst_content = render_with_jinja_and_fact_tags(
                content=rst_content_tpl,
                jinja_env=jinja_env,
                jinja_context=jinja_context)
            full_rst_content += "\n\n" + rst_content

        logging.debug("Writing RST and PDF files with filename base %s", filepath_base)
        convert_rst_content_to_pdf(filepath_base=filepath_base,
                                   rst_content=full_rst_content,
                                   conf_file="rst2pdf.conf",  # FIXME put a registry
                                   extra_args=rst2pdf_extra_args)

    sub_data_tree = data_tree.get("groups", None)

    if sub_data_tree:
        for group_name, group_data_tree in sub_data_tree.items():
            _recursively_generate_group_sheets(group_data_tree, group_breadcrumb=group_breadcrumb + (group_name,), variables=cumulated_variables,
                                                   output_root_dir=output_root_dir, jinja_env=jinja_env, rst2pdf_extra_args=rst2pdf_extra_args)



@click.command()
@click.argument('project_dir', type=click.Path(exists=True, file_okay=False))
@click.option('--verbose', '-v', is_flag=True, help="Print more output.")
def cli(project_dir, verbose):
    print("HELLO STARTING")
    logging.basicConfig(level=(logging.DEBUG if verbose else logging.INFO))

    logging.debug("Switching to current working directory: %s", project_dir)
    os.chdir(project_dir)

    rst2pdf_extra_args = ""  # FIXME

    output_root_dir = Path("./_output") # FIXME
    os.makedirs(output_root_dir, exist_ok=True)

    yaml_conf_file = "./configuration.yaml"

    # FIXME here add TEMPLATES_COMMON too
    jinja_env = load_jinja_environment(["."], use_macro_tags=True)

    project_data_tree = load_yaml_file(yaml_conf_file)

    project_settings = project_data_tree["settings"]

    _recursively_generate_group_sheets(project_data_tree["sheet_generation"], group_breadcrumb=(), variables={},
                                           output_root_dir=output_root_dir, jinja_env=jinja_env, rst2pdf_extra_args=rst2pdf_extra_args)

    if project_settings["game_facts_template"]:
        logging.info("Processing special sheet for game facts")
        game_facts_template_name = project_settings["game_facts_template"]
        jinja_context = dict(facts_registry=jinja_env.facts_registry)
        rst_content = render_with_jinja(filename=game_facts_template_name, jinja_env=jinja_env, jinja_context=jinja_context)
        convert_rst_content_to_pdf(filepath_base=output_root_dir.joinpath("gamemasters", "game_facts"),
                                   rst_content=rst_content,
                                   conf_file="rst2pdf.conf",  # FIXME put a registry
                                   extra_args=rst2pdf_extra_args)




if __name__ == "__main__":
    cli()