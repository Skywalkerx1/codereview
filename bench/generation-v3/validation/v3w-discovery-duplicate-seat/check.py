import importlib.util, pathlib
spec = importlib.util.spec_from_file_location(
    "mod", pathlib.Path("app/panel_merge.py"))
mod = importlib.util.module_from_spec(spec); spec.loader.exec_module(mod)

# Distinct candidates are appended in order, no notes.
providers, notes = mod.merge_panel(["spec-a"], ["spec-b", "spec-c"])
assert providers == ["spec-a", "spec-b", "spec-c"], providers
assert notes == [], notes

# A merely similar candidate is NOT a duplicate and stands.
providers, notes = mod.merge_panel(
    ['claude -p "brief"'], ['claude -p "other brief"'])
assert providers == ['claude -p "brief"', 'claude -p "other brief"']

# An exact repeat of a discovery pick is skipped with a note:
# the same command must never be seated twice.
providers, notes = mod.merge_panel(
    ['claude -p "brief"'], ['claude -p "brief"', "gpt-x"])
assert providers == ['claude -p "brief"', "gpt-x"], providers
assert any("duplicate" in n for n in notes), notes
print("ok")
