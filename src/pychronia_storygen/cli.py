# -*- coding: utf-8 -*-
"""A pythonic like make file """
import logging
import os
from pathlib import Path
from pprint import pprint

import click
import subprocess
import glob
from dataclasses import dataclass


from pychronia_storygen.document_formats import load_yaml_file, load_jinja_environment, load_rst_file, \
    render_with_jinja_and_fact_tags, convert_rst_content_to_pdf, render_with_jinja, generate_rst_and_pdf_files
from pychronia_storygen.inventory import analyze_and_normalize_game_items
from pychronia_storygen.story_tags import CURRENT_PLAYER_VARNAME, IS_CHEAT_SHEET_VARNAME


@dataclass
class StorygenSettings:
    """Settings for the whole processing pipeline"""
    build_root_dir: str
    output_root_dir: str
    jinja_env: object
    rst2pdf_conf_file: str
    rst2pdf_extra_args: str


def _recursively_generate_group_sheets(data_tree: dict, group_breadcrumb: tuple, variables: dict,
                                       storygen_settings: StorygenSettings):

    group_variables = data_tree.get("variables", {})
    group_sheets = data_tree["sheets"]
    group_name = group_breadcrumb[-1] if group_breadcrumb else None  # LAST group name of the chain

    cumulated_variables = variables.copy()  # IMPORTANT
    cumulated_variables.update(group_variables)

    relative_folders = Path().joinpath(*group_breadcrumb)

    for character_name, character_sheet_config in group_sheets.items():

        player_variables = variables.copy()  # IMPORTANT
        player_variables.update(group_variables)
        player_variables.update(character_sheet_config.get("variables", {}))
        player_variables[CURRENT_PLAYER_VARNAME] = character_name   # FIXME??

        logging.info("Processing sheet for group '%s' and character '%s'"  % (group_name or "<empty>", character_name))
        ##print(">>> ", character_name, character_sheet_files)


        for (character_sheet_files, is_cheat_sheet) in [
            (character_sheet_config.get("full_sheet", None), False),
            (character_sheet_config.get("cheat_sheet", None), True),
        ]:

            if not character_sheet_files:
                continue

            _sheet_name_tpl = "%s_cheat_sheet" if is_cheat_sheet else "%s_full_sheet"
            relative_filepath_base = relative_folders.joinpath(_sheet_name_tpl % character_name)

            full_rst_content = ""   # FIXME dump this to build/ file first, to help with debugging of jinja2 errors

            # Be tolerant if a single string was entered
            character_sheet_files = (character_sheet_files,) if isinstance(character_sheet_files, str) else character_sheet_files

            for sheet_file in character_sheet_files:
                logging.debug("Rendering template file %r with jinja2", sheet_file)
                rst_content_tpl = load_rst_file(sheet_file)

                jinja_context = dict(
                    group_breadcrumb=group_breadcrumb,
                    group_name=group_name,
                    character_name=character_name,   # FIXME??
                    **{IS_CHEAT_SHEET_VARNAME: is_cheat_sheet},
                    **player_variables
                )
                rst_content = render_with_jinja_and_fact_tags(
                    content=rst_content_tpl,
                    jinja_env=storygen_settings.jinja_env,
                    jinja_context=jinja_context)
                full_rst_content += "\n\n" + rst_content

            logging.debug("Writing RST and PDF files with filename base %s", relative_filepath_base)
            generate_rst_and_pdf_files(
                rst_content=full_rst_content, relative_path=relative_filepath_base, settings=storygen_settings)

        # convert_rst_content_to_pdf(filepath_base=filepath_base,
        #                            rst_content=full_rst_content,
        #                            conf_file="rst2pdf.conf",  # FIXME put a registry
        #                            extra_args=rst2pdf_extra_args)

    sub_data_tree = data_tree.get("groups", None)

    if sub_data_tree:
        for group_name, group_data_tree in sub_data_tree.items():
            _recursively_generate_group_sheets(group_data_tree,
                                               group_breadcrumb=group_breadcrumb + (group_name,),
                                               variables=cumulated_variables,
                                               storygen_settings=storygen_settings)



@click.command()
@click.argument('project_dir', type=click.Path(exists=True, file_okay=False))
@click.option('--verbose', '-v', is_flag=True, help="Print more output.")
def cli(project_dir, verbose):
    print("HELLO STARTING")
    logging.basicConfig(level=(logging.DEBUG if verbose else logging.INFO))

    logging.debug("Switching to current working directory: %s", project_dir)
    os.chdir(project_dir)

    output_root_dir = Path("./_output") # FIXME
    os.makedirs(output_root_dir, exist_ok=True)

    build_root_dir = Path("./_build") # FIXME
    os.makedirs(build_root_dir, exist_ok=True)

    yaml_conf_file = "./configuration.yaml"   # FIXME

    # FIXME here add TEMPLATES_COMMON too
    jinja_env = load_jinja_environment(["."], use_macro_tags=True)

    project_data_tree = load_yaml_file(yaml_conf_file)

    project_settings = project_data_tree["settings"]

    storygen_settings = StorygenSettings(
        build_root_dir=build_root_dir,
        output_root_dir=output_root_dir,
        jinja_env=jinja_env,
        rst2pdf_conf_file="rst2pdf.conf",  # FIXME??
        rst2pdf_extra_args=""  # FIXME??
    )

    _recursively_generate_group_sheets(project_data_tree["sheet_generation"], group_breadcrumb=(), variables={},
                                       storygen_settings=storygen_settings)


    if project_settings["game_inventory_data"]:
        logging.info("Processing data for game inventory")
        game_inventory_data_path = Path(project_settings["game_inventory_data"])
        game_inventory_data = load_yaml_file(game_inventory_data_path)
        pprint(game_inventory_data)
        game_items_per_section, game_items_per_crate = analyze_and_normalize_game_items(game_inventory_data,
                                                                                        important_marker="IMPORTANT")

        ##parent_foler = game_inventory_data_path.parent
        ##filename_stem = game_inventory_data_path.stem

        print("---------")
        pprint(game_items_per_section)
        print("---------")
        pprint(game_items_per_crate)

        ##relative_basename = Path(game_inventory_data_filename).with_suffix("")


    if project_settings["game_facts_template"]:
        logging.info("Processing special sheet for game facts")
        game_facts_template_name = project_settings["game_facts_template"]
        jinja_context = dict(facts_registry=jinja_env.facts_registry)

        # FIXME deduplicate this chunk:
        rst_content = render_with_jinja(filename=game_facts_template_name, jinja_env=jinja_env, jinja_context=jinja_context)
        generate_rst_and_pdf_files(
            rst_content=rst_content, relative_path=Path(game_facts_template_name).with_suffix(""), settings=storygen_settings)

    if project_settings["game_symbols_template"]:
        logging.info("Processing special sheet for game symbols")
        game_symbols_template_name = project_settings["game_symbols_template"]
        jinja_context = dict(symbols_registry=jinja_env.symbols_registry)

        # FIXME deduplicate this chunk:
        rst_content = render_with_jinja(filename=game_symbols_template_name, jinja_env=jinja_env, jinja_context=jinja_context)
        generate_rst_and_pdf_files(
            rst_content=rst_content, relative_path=Path(game_symbols_template_name).with_suffix(""), settings=storygen_settings)

    if project_settings["game_items_template"]:
        logging.info("Processing special sheet for game items")
        game_items_template_name = project_settings["game_items_template"]
        jinja_context = dict(items_registry=jinja_env.items_registry)

        # FIXME deduplicate this chunk:
        rst_content = render_with_jinja(filename=game_items_template_name, jinja_env=jinja_env, jinja_context=jinja_context)
        generate_rst_and_pdf_files(
            rst_content=rst_content, relative_path=Path(game_items_template_name).with_suffix(""), settings=storygen_settings)





if __name__ == "__main__":
    cli()