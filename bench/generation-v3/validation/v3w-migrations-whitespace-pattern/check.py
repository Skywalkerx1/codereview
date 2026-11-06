import importlib.util, pathlib
spec = importlib.util.spec_from_file_location(
    "mod", pathlib.Path("app/risk_patterns.py"))
mod = importlib.util.module_from_spec(spec); spec.loader.exec_module(mod)

# Ordinary single-space SQL is classified.
assert mod.is_migration_risk("DROP TABLE users")
assert mod.is_migration_risk("alter table t add column c int")
# Unrelated text is not.
assert not mod.is_migration_risk("drop the kids off at school")
# The same statement split across lines / tabs / repeated spaces
# is still the same statement and must be classified.
assert mod.is_migration_risk("DROP\nTABLE users"), "newline-split SQL missed"
assert mod.is_migration_risk("drop\t\ttable users"), "tab-split SQL missed"
assert mod.is_migration_risk("create   index idx on t (c)"), "padded SQL missed"
print("ok")
