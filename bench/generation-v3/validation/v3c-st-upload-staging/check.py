import importlib.util, os, pathlib, tempfile
spec = importlib.util.spec_from_file_location("mod", pathlib.Path("app/upload_staging.py"))
mod = importlib.util.module_from_spec(spec); spec.loader.exec_module(mod)
with tempfile.TemporaryDirectory() as d:
    st = mod.UploadStaging(d, max_bytes=8, allowed_extensions={".png", ".jpg"})
    st.stage("ok.PNG", b"12345678")
    assert st.in_quarantine("ok.PNG")
    assert not st.in_final("ok.PNG")
    st.promote("ok.PNG")
    assert st.in_final("ok.PNG")
    assert not st.in_quarantine("ok.PNG")
    st.stage("big.png", b"123456789")
    st.stage("evil.exe", b"tiny")
    for bad in ("big.png", "evil.exe"):
        try:
            st.promote(bad); raise AssertionError(f"{bad} must not promote")
        except ValueError:
            pass
        assert not st.in_final(bad)
        assert st.in_quarantine(bad)
    try:
        st.promote("ghost.png"); raise AssertionError("missing must raise")
    except FileNotFoundError:
        pass
    try:
        st.stage("../x.png", b"x"); raise AssertionError("traversal must raise")
    except ValueError:
        pass
print("ok")
