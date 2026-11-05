# Where the DORA page and its cache live in the product's main checkout, and
# reading and writing them.
#
# Part of sclaude/lib/metrics/dora.py.

import json
import os


DIR = os.path.join(".sclaude", "local", "dora")
PAGE = "index.html"


def out_dir(repo):
    return os.path.join(repo, DIR)


def load(path, default):
    try:
        with open(path, encoding="utf-8") as fh:
            return json.load(fh)
    except (OSError, ValueError):
        return default


def save(path, data):
    tmp = path + ".tmp"
    with open(tmp, "w", encoding="utf-8") as fh:
        json.dump(data, fh, ensure_ascii=False, indent=1)
    os.replace(tmp, path)
