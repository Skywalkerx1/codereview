import importlib.util, pathlib
spec = importlib.util.spec_from_file_location(
    "mod", pathlib.Path("extract/htmltext.py"))
mod = importlib.util.module_from_spec(spec); spec.loader.exec_module(mod)
t = mod.html_to_text

# plain paragraphs separated by newlines
assert t("<p>First</p><p>Second</p>") == "First\nSecond"
# script and style contents excluded entirely
assert t("<p>Keep</p><script>var secret = 1;</script>") == "Keep"
assert t("<style>body { color: red; }</style><p>Visible</p>") == "Visible"
assert t("<script>if (a < b) { go(); }</script>After") == "After"
# entities decoded, named and numeric
assert t("<p>Fish &amp; Chips</p>") == "Fish & Chips"
assert t("<p>caf&#233; &lt;3</p>") == "café <3"
assert t("Tom &amp; Jerry &copy; 2026") == "Tom & Jerry © 2026"
# br and headings / list items break lines
assert t("one<br>two<br/>three") == "one\ntwo\nthree"
assert t("<h1>Title</h1><ul><li>a</li><li>b</li></ul>") == "Title\na\nb"
# inline markup does not break lines; whitespace collapses
assert t("<p>Hello <b>bold</b>   world</p>") == "Hello bold world"
# nested block structure still yields one line per block
assert t("<div><p>Inner</p></div><div>Outer</div>") == "Inner\nOuter"
# script nested inside a kept element is still excluded
assert t("<div>Shown<script>hidden()</script> tail</div>") == "Shown tail"
# empty and markup-only fragments
assert t("") == ""
assert t("<div>   </div>") == ""
assert t("<script>only script</script>") == ""
# unclosed script swallows the rest (never leaks script text)
assert t("<p>Before</p><script>never closed") == "Before"
print("ok")
