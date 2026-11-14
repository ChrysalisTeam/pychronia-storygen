def _project(storygen, hook_module, hook_source, hook_ref=None, template_dirs=""):
    storygen.write("configuration.yaml", """
        variables_hook: "%s"
        %s
        data_files:
          - file: data.yaml
        variables:
          from_config: C
        sheet_generation:
          sheets:
            alice:
              full_sheet: sheet.rst
        """ % (hook_ref or (hook_module + ".prepare"), template_dirs))
    storygen.write("data.yaml", "from_data: D\n")
    storygen.write(hook_module.replace(".", "/") + ".py", hook_source)


def test_hook_mutates_variables_and_registers_filter(storygen):
    _project(storygen, "hook_mutating", """
        def prepare(variables, *, language, jinja_env):
            variables["computed"] = variables["from_data"] + variables["from_config"] + str(language)
            jinja_env.filters["shout"] = lambda value: value.upper() + "!"
        """)
    storygen.write("sheet.rst", "{{ computed }} {{ 'hey' | shout }}")
    storygen.run()
    assert "DCNone HEY!" in storygen.build_text("alice_full_sheet.txt")


def test_hook_returning_new_dict_and_template_dirs_on_sys_path(storygen):
    storygen.write("shared_helpers/hook_returning_helper.py", "VALUE = 'helper'\n")
    _project(storygen, "hook_returning", """
        import hook_returning_helper
        def prepare(variables, *, language, jinja_env):
            return dict(variables, computed=hook_returning_helper.VALUE, from_config="overridden")
        """, template_dirs="template_dirs: [shared_helpers]")
    storygen.write("sheet.rst", "{{ computed }} {{ from_config }} {{ from_data }}")
    storygen.run()
    assert "helper overridden D" in storygen.build_text("alice_full_sheet.txt")


def test_hook_errors_are_reported(storygen):
    _project(storygen, "hook_broken", "x = 1\n", hook_ref="hook_broken.prepare")
    storygen.write("sheet.rst", "x")
    result = storygen.run(expect_ok=False)
    assert result.exit_code != 0 and "prepare" in result.output
    _project(storygen, "hook_broken", "x = 1\n", hook_ref="no_such_module_xyz.prepare")
    result = storygen.run(expect_ok=False)
    assert result.exit_code != 0 and "no_such_module_xyz" in result.output
