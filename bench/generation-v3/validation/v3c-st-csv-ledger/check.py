import importlib.util, os, pathlib, tempfile
spec = importlib.util.spec_from_file_location("mod", pathlib.Path("billing/csv_ledger.py"))
mod = importlib.util.module_from_spec(spec); spec.loader.exec_module(mod)
with tempfile.TemporaryDirectory() as d:
    p = os.path.join(d, "ledger.csv")
    led = mod.CsvLedger(p)
    assert led.rows() == []
    led.append("e1", 100, "first")
    mod.CsvLedger(p).append("e2", -50, "memo, with comma")
    led.append("e3", 25, "unicode-备忘")
    text = pathlib.Path(p).read_text(encoding="utf-8")
    assert text.count("entry_id,amount_cents,memo") == 1
    rows = led.rows()
    assert [r["entry_id"] for r in rows] == ["e1", "e2", "e3"]
    assert rows[1]["memo"] == "memo, with comma"
    assert rows[2]["memo"] == "unicode-备忘" and rows[0]["amount_cents"] == "100"
    pathlib.Path(p).write_text("", encoding="utf-8")
    mod.CsvLedger(p).append("e9", 1, "after-emptying")
    assert pathlib.Path(p).read_text(encoding="utf-8").count("entry_id") == 1
print("ok")
