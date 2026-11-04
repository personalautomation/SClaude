#!/usr/bin/env python3
"""Where two copies of sclaude's project config differ, key by key.

    config_diff.py <here> <origin>

Prints one line per differing key, `<dotted.key>\t<here>\t<origin>`, values
as JSON and `(none)` for a key one side lacks; objects are compared key by
key, anything else whole. Nothing printed means the two are equal.

Exit 0 when both are JSON (an empty file reads as {}); 1 otherwise, after
one line saying the files differ as text.

Part of sclaude: called by prod_main_unready in deploy.sh.
"""

import json
import sys

MISSING = object()


def shown(value):
    return "(none)" if value is MISSING else json.dumps(value, ensure_ascii=False)


def same(a, b):
    # Python's == calls true 1 and 1.0 1; the settings are compared as written.
    if a is MISSING or b is MISSING:
        return a is b
    return json.dumps(a, sort_keys=True) == json.dumps(b, sort_keys=True)


def walk(here, origin, path, out):
    if same(here, origin):
        return
    if isinstance(here, dict) and isinstance(origin, dict):
        for key in list(origin) + [k for k in here if k not in origin]:
            walk(here.get(key, MISSING), origin.get(key, MISSING), path + [key], out)
        return
    out.append((".".join(path) or "(the whole file)", here, origin))


def main():
    loaded = []
    for path in sys.argv[1:3]:
        try:
            with open(path, encoding="utf-8") as fh:
                text = fh.read()
            loaded.append(json.loads(text) if text.strip() else {})
        except (OSError, ValueError):
            print("(the whole file)\tnot JSON on one side\t-")
            return 1
    out = []
    walk(loaded[0], loaded[1], [], out)
    for key, here, origin in out:
        print(f"{key}\t{shown(here)}\t{shown(origin)}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
