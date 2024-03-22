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
    render_with_jinja_and_fact_tags, convert_rst_content_to_pdf, render_with_jinja, generate_rst_and_pdf_files, \
    render_with_jinja_and_convert_to_pdf, extract_text_from_odt_file, split_odt_file_into_separate_documents
from pychronia_storygen.inventory import analyze_and_normalize_game_items
from pychronia_storygen.story_tags import CURRENT_PLAYER_VARNAME, IS_CHEAT_SHEET_VARNAME, detect_game_item_errors, \
    detect_game_symbol_errors, detect_game_fact_errors


@dataclass
class StorygenSettings:
    """Settings for the whole processing pipeline"""
    project_root_dir: str
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

    for sheet_name, sheet_config in group_sheets.items():

        player_variables = variables.copy()  # IMPORTANT
        player_variables.update(group_variables)
        player_variables.update(sheet_config.get("variables", {}))
        player_variables[CURRENT_PLAYER_VARNAME] = sheet_name   # FIXME??

        logging.info("Processing sheet for group '%s' and sheet '%s'"  % (group_name or "<empty>", sheet_name))
        ##print(">>> ", character_name, character_sheet_files)

        for (sheet_parts, is_cheat_sheet) in [
            (sheet_config.get("full_sheet", None), False),
            (sheet_config.get("cheat_sheet", None), True),
        ]:

            if not sheet_parts:
                continue

            _sheet_name_tpl = "%s_cheat_sheet" if is_cheat_sheet else "%s_full_sheet"
            relative_filepath_base = relative_folders.joinpath(_sheet_name_tpl % sheet_name)

            jinja_context = dict(
                group_breadcrumb=group_breadcrumb,
                group_name=group_name,
                sheet_name=sheet_name,
                **{IS_CHEAT_SHEET_VARNAME: is_cheat_sheet},
                **player_variables
            )

            # Be tolerant if a single string was entered
            sheet_parts = (sheet_parts,) if isinstance(sheet_parts, str) else sheet_parts

            full_rst_content = ""
            for sheet_part in sheet_parts:
                logging.debug("Rendering template file '%s' with jinja2", sheet_part)
                rst_content = render_with_jinja_and_fact_tags(
                    filename=sheet_part,
                    jinja_env=storygen_settings.jinja_env,
                    jinja_context=jinja_context)
                full_rst_content += "\n\n" + rst_content

            logging.debug("Writing RST and PDF files with filename base '%s'", relative_filepath_base)
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



def _generate_inventory_files(inventory_name, inventory_config, storygen_settings: StorygenSettings):

    logging.info("Analysing data for game inventory '%s'" % inventory_name)
    inventory_data_path = Path(inventory_config["inventory_data"])
    inventory_data = load_yaml_file(inventory_data_path)
    game_items_per_section, game_items_per_crate = analyze_and_normalize_game_items(
        inventory_data, important_marker="IMPORTANT")

    inventory_per_section_template_name = inventory_config["inventory_per_section_template"]
    inventory_per_section_destination = inventory_config["inventory_per_section_destination"]

    inventory_per_crate_template_name = inventory_config["inventory_per_crate_template"]
    inventory_per_crate_destination = inventory_config["inventory_per_crate_destination"]

    base_context = dict(inventory_name=inventory_name)

    if inventory_per_section_template_name and inventory_per_section_destination:
        logging.info("Processing per-section sheet for game inventory '%s'" % inventory_name)
        jinja_context = dict(**base_context, items_per_section=game_items_per_section)
        render_with_jinja_and_convert_to_pdf(inventory_per_section_template_name,
                                             relative_path=Path(inventory_per_section_destination),
                                             jinja_context=jinja_context,
                                             settings=storygen_settings)

    if inventory_per_crate_template_name and inventory_per_crate_destination:
        logging.info("Processing per-crate sheet for game inventory '%s'" % inventory_name)
        jinja_context = dict(**base_context, items_per_crate=game_items_per_crate)
        render_with_jinja_and_convert_to_pdf(inventory_per_crate_template_name,
                                             relative_path=Path(inventory_per_crate_destination),
                                             jinja_context=jinja_context,
                                             settings=storygen_settings)

def _generate_document_files(document_bundle_name, document_config, storygen_settings: StorygenSettings):
    logging.info("Processing generation of game document bundle '%s'" % document_bundle_name)
    document_source = document_config["document_source"]
    document_text = extract_text_from_odt_file(document_source)

    # No need for rendered output, we just fill game-tags registries
    render_with_jinja_and_fact_tags(
        content=document_text,
        jinja_env=storygen_settings.jinja_env,
        jinja_context=dict(document_bundle_name=document_bundle_name))

    # We then split the PDF into parts
    output_relative_dir, ext = os.path.splitext(document_source)  # The basename becomes the name of the target FOLDER
    output_dir = storygen_settings.output_root_dir.joinpath(output_relative_dir)
    document_splitting = document_config["document_splitting"]
    split_odt_file_into_separate_documents(
        document_config["document_source"],
        splits_config=document_splitting,
        output_dir=output_dir)


def _generate_summary_files(summary_config, storygen_settings: StorygenSettings):

    if summary_config["game_facts_template"] and summary_config["game_facts_destination"]:
        logging.info("Processing special sheet for game facts")
        game_facts_template_name = summary_config["game_facts_template"]
        has_serious_errors1, error_messages1 = detect_game_fact_errors(storygen_settings.jinja_env.facts_registry)
        jinja_context = dict(facts_registry=storygen_settings.jinja_env.facts_registry,
                             has_serious_errors=has_serious_errors1,
                             error_messages=error_messages1)
        render_with_jinja_and_convert_to_pdf(game_facts_template_name,
                                             relative_path=Path(summary_config["game_facts_destination"]),
                                             jinja_context=jinja_context,
                                             settings=storygen_settings)

    if summary_config["game_symbols_template"] and summary_config["game_symbols_destination"]:
        logging.info("Processing special sheet for game symbols")
        game_symbols_template_name = summary_config["game_symbols_template"]
        has_serious_errors2, error_messages2 = detect_game_symbol_errors(storygen_settings.jinja_env.symbols_registry)
        jinja_context = dict(symbols_registry=storygen_settings.jinja_env.symbols_registry,
                             has_serious_errors=has_serious_errors2,
                             error_messages=error_messages2)
        render_with_jinja_and_convert_to_pdf(game_symbols_template_name,
                                             relative_path=Path(summary_config["game_symbols_destination"]),
                                             jinja_context=jinja_context,
                                             settings=storygen_settings)

    if summary_config["game_items_template"] and summary_config["game_items_destination"]:
        logging.info("Processing special sheet for game items")
        game_items_template_name = summary_config["game_items_template"]
        has_serious_errors3, error_messages3 = detect_game_item_errors(storygen_settings.jinja_env.items_registry)
        jinja_context = dict(items_registry=storygen_settings.jinja_env.items_registry,
                             has_serious_errors=has_serious_errors3,
                             error_messages=error_messages3)
        render_with_jinja_and_convert_to_pdf(game_items_template_name,
                                             relative_path=Path(summary_config["game_items_destination"]),
                                             jinja_context=jinja_context,
                                             settings=storygen_settings)

    logging.info("Processing final results of scenario coherence analysis")
    _handle_analysis_results(
            has_serious_errors=any([has_serious_errors1, has_serious_errors2, has_serious_errors3]),
            error_messages=error_messages1 + error_messages2 + error_messages3
    )


def _handle_analysis_results(has_serious_errors, error_messages):
    if has_serious_errors:
        logging.critical("*** Serious coherence errors were detected during the processing of scenario data, see details below ***")
    for criticity, message in error_messages:
        logger_func = logging.error if criticity == "ERROR" else logging.warning
        logger_func(message)


@click.command()
@click.argument('project_dir', type=click.Path(exists=True, file_okay=False))
@click.option('--verbose', '-v', is_flag=True, help="Print more output.")
@click.option("-t", "--type", "selected_asset_types", type=click.Choice(['sheets', 'documents', 'inventories'], case_sensitive=False),
                            multiple=True, help="Select the types of assets to generate")
def cli(project_dir, verbose, selected_asset_types):
    print("HELLO STARTING", selected_asset_types)
    project_dir = os.path.abspath(project_dir).rstrip("\\/") + os.path.sep

    def _is_asset_type_enabled(_type):
        assert _type.lower() == _type, _type
        if _type == "summaries":
            return (not selected_asset_types)  # We only generate summaries if ALL other assets have been generated too!
        return (not selected_asset_types) or (_type in selected_asset_types)

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

    storygen_settings = StorygenSettings(
        project_root_dir=project_dir,
        build_root_dir=build_root_dir,
        output_root_dir=output_root_dir,
        jinja_env=jinja_env,
        rst2pdf_conf_file="rst2pdf.conf",  # FIXME??
        rst2pdf_extra_args=""  # FIXME??
    )

    if _is_asset_type_enabled("sheets"):
        # GENERATE FULL SHEETS AND CHEAT SHEETS
        _recursively_generate_group_sheets(project_data_tree["sheet_generation"],
                                           group_breadcrumb=(),
                                           variables={ "project_dir": project_dir.replace("\\", "/") },
                                           storygen_settings=storygen_settings)

    if _is_asset_type_enabled("documents"):
        # GENERATE GAME DOCUMENTS
        document_generation_tree = project_data_tree["document_generation"]
        if document_generation_tree:
            for document_bundle_name, document_config in document_generation_tree.items():
                _generate_document_files(document_bundle_name, document_config=document_config, storygen_settings=storygen_settings)

    if _is_asset_type_enabled("inventories"):
        # GENERATE INVENTORIES
        inventory_generation_tree = project_data_tree["inventory_generation"]
        if inventory_generation_tree:
            for inventory_name, inventory_config in inventory_generation_tree.items():
                _generate_inventory_files(inventory_name, inventory_config=inventory_config, storygen_settings=storygen_settings)

    if _is_asset_type_enabled("summaries"):
        # GENERATE SUMMARIES
        summary_config = project_data_tree["summary_generation"]
        _generate_summary_files(summary_config, storygen_settings=storygen_settings)



if __name__ == "__main__":
    cli()