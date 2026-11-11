# A page's script or style, kept as a file of its own beside the module that
# draws the page (process_*.js, dora_*.css…), so that an editor reads it as
# one and a diff shows it as code.
#
#   STYLE = page_asset.read(__file__, "dora_page.css")
import os


def read(module_file, name):
    with open(os.path.join(os.path.dirname(os.path.abspath(module_file)), name), encoding="utf-8") as fh:
        return fh.read()


def tab_icon(emoji):
    """The page's icon in the browser's tab, an emoji drawn as SVG: each kind
    of sclaude's pages its own (🗂 the features, 🎬 a demo, 🗺 the process
    map, 📊 the metrics), so a row of tabs tells them apart."""
    from urllib.parse import quote
    svg = ("<svg xmlns='http://www.w3.org/2000/svg' viewBox='0 0 100 100'>"
           "<text y='.9em' font-size='90'>%s</text></svg>" % emoji)
    return '<link rel="icon" href="data:image/svg+xml,%s">' % quote(svg)
