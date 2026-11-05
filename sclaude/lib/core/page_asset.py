# A page's script or style, kept as a file of its own beside the module that
# draws the page (process_*.js, dora_*.css…), so that an editor reads it as
# one and a diff shows it as code.
#
#   STYLE = page_asset.read(__file__, "dora_page.css")
import os


def read(module_file, name):
    with open(os.path.join(os.path.dirname(os.path.abspath(module_file)), name), encoding="utf-8") as fh:
        return fh.read()
