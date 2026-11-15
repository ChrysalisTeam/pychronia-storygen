"""
Python hook of the example project (see "variables_hook" in configuration.yaml).

It is called once, before any generation, to compute extra variables and register jinja2 filters.
"""


def prepare_variables(variables, *, language, jinja_env):
    # The variables of data files are already available here
    variables["years_since_final_battle"] = variables["story_year"] - variables["final_battle_year"]

    # Usable in all templates, eg. {{ "hello"|shout }}
    jinja_env.filters["shout"] = lambda text: str(text).upper() + "!"
