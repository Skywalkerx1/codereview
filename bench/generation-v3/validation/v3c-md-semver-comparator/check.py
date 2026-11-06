import importlib.util, pathlib
spec = importlib.util.spec_from_file_location("mod", pathlib.Path("release/semver_cmp.py"))
mod = importlib.util.module_from_spec(spec); spec.loader.exec_module(mod)

chain = ["1.0.0-alpha", "1.0.0-alpha.1", "1.0.0-alpha.beta", "1.0.0-beta",
         "1.0.0-beta.2", "1.0.0-beta.11", "1.0.0-rc.1", "1.0.0"]
for i in range(len(chain) - 1):
    assert mod.compare_versions(chain[i], chain[i + 1]) == -1, chain[i:i+2]
    assert mod.compare_versions(chain[i + 1], chain[i]) == 1
    assert mod.compare_versions(chain[i], chain[i]) == 0
# core fields dominate and compare numerically, not lexically
assert mod.compare_versions("2.0.0", "1.9.9") == 1
assert mod.compare_versions("1.10.0", "1.9.0") == 1
assert mod.compare_versions("1.0.10", "1.0.9") == 1
# numeric prerelease identifiers rank below alphanumeric ones
assert mod.compare_versions("1.0.0-1", "1.0.0-alpha") == -1
# numeric identifiers compare numerically (2 < 11, handled above too)
assert mod.compare_versions("1.0.0-beta.2", "1.0.0-beta.11") == -1
# build metadata is ignored for ordering
assert mod.compare_versions("1.0.0+build.5", "1.0.0") == 0
assert mod.compare_versions("1.0.0-rc.1+exp.1", "1.0.0-rc.1") == 0
for bad in ["1.0", "01.0.0", "1.0.0-", "1.0.0-alpha..1", "v1.0.0", "1.0.0-01", "", "1.0.0.0"]:
    try:
        mod.parse_version(bad); assert False, bad
    except ValueError: pass
print("ok")
