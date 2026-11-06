import importlib.util, pathlib
spec = importlib.util.spec_from_file_location("mod", pathlib.Path("ops/log_parser.py"))
mod = importlib.util.module_from_spec(spec); spec.loader.exec_module(mod)

text = (
    "2026-11-05 09:00:01 [INFO] service started\n"
    "2026-11-05 09:01:10 [ERROR] request failed\n"
    "    Traceback (most recent call last):\n"
    "      File \"app.py\", line 9, in handle\n"
    "    ValueError: boom\n"
    "2026-11-05 09:02:00 [INFO] recovered\n"
)
recs = mod.parse_log(text)
assert len(recs) == 3, recs
assert recs[0]["level"] == "INFO" and recs[0]["continuation"] == []
assert recs[1]["message"] == "request failed"
assert len(recs[1]["continuation"]) == 3, recs[1]
assert recs[1]["continuation"][0].startswith("Traceback")
assert recs[1]["continuation"][-1] == "ValueError: boom"
assert recs[2]["timestamp"] == "2026-11-05 09:02:00"
assert mod.parse_log("") == []
# tab-indented lines also continue the previous record
recs = mod.parse_log("2026-11-05 09:00:01 [WARN] low disk\n\tdetail here\n")
assert recs[0]["continuation"] == ["detail here"]
# continuation before any record is an error, not a lost line
try:
    mod.parse_log("  orphan stack line\n"); assert False
except ValueError: pass
# a non-indented non-record line is an error
try:
    mod.parse_log("2026-11-05 09:00:01 [INFO] ok\ngarbage line\n"); assert False
except ValueError: pass
print("ok")
