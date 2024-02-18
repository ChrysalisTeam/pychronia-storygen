# -*- coding: utf-8 -*-
"""A pythonic like make file """
import logging
import os

import click
import subprocess
import glob

from pychronia_storygen.document_formats import load_yaml_file, load_jinja_environment, load_rst_file, \
    render_with_jinja_and_fact_tags, convert_rst_content_to_pdf


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

    output_dir = "_output/" # FIXME
    os.makedirs(output_dir, exist_ok=True)

    project_dir = "example_project/"  # FIXME

    yaml_conf_file = "./configuration.yaml"

    os.chdir(project_dir)

    project_data = load_yaml_file(yaml_conf_file)

    project_sheet_groups = project_data["sheets"]

    project_variables = project_data["variables"]

    use_macro_tags = True  # FIXME

    # FIXME here add TEMPLATES_COMMON too
    jinja_env = load_jinja_environment(["."], use_macro_tags=use_macro_tags)

    for group_name, sheet_group in project_sheet_groups.items():
        for character_name, character_sheet_files in sheet_group.items():

            logging.info("Processing sheet for character %s of group %s" % (character_name, group_name))
            ##print(">>> ", character_name, character_sheet_files)

            filepath_base = os.path.join(output_dir, character_name)  # TODO improve

            full_rest_content = ""

            for sheet_file in character_sheet_files:
                logging.debug("Rendering template file %r with jinja2", sheet_file)
                rst_content_tpl = load_rst_file(sheet_file)

                jinja_context = dict(
                    group_name=group_name,
                    character_name=character_name,
                    **project_variables
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




if __name__ == "__main__":
    cli()