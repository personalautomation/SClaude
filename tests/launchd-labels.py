#!/usr/bin/env python3
# The names of macOS's launchd agents, spelled alike wherever they are named.
#
# An agent's label is its template's file name, launchd/<label>.plist: that is
# what install.sh writes and loads, and what launchd.sh lists. The same label
# is written out by hand in the places that start, stop or ask about an agent:
# LABELS and LOG_FILES in keepawake/units.py (the bot's buttons), the second
# argument of service_up/unit_state in bin/keepawake (keepawake status), the
# port table and the bot's exception in install.sh, the bot's exception in
# doctor.sh, and the `launchctl print` the bot's docs tell a person to type.
# A template renamed alone leaves each of them asking after an agent that is
# not there, which reads as "not installed", without an error.
#
# Also: each LABELS key is a systemd unit the checkout has, launchd.sh's split
# by prefix (sclaude.* the core, keepawake* the extras) takes every template,
# and the socket name the gate takes from launchd (LAUNCHD_SOCKET in
# bin/sclaude-proxy) is the one sclaude.gate.plist declares.
#
# Run it with: python3 tests/launchd-labels.py
import os
import re
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)
from keepawake import units  # noqa: E402

failures = []


def check(name, got, want):
    print(("PASS  " if got == want else "FAIL  ") + name)
    if got != want:
        failures.append(name)
        print("  want: %r\n  got:  %r" % (want, got))


def read(*path):
    with open(os.path.join(ROOT, *path), encoding="utf-8") as fh:
        return fh.read()


templates = sorted(f[:-len(".plist")] for f in os.listdir(os.path.join(ROOT, "launchd"))
                   if f.endswith(".plist"))
known = set(templates)
check("there are templates", bool(templates), True)


def unknown(names):
    return sorted(set(names) - known)


check("units.LABELS names templates", unknown(units.LABELS.values()), [])
check("units.LOG_FILES names templates", unknown(units.LOG_FILES), [])
systemd = set(os.listdir(os.path.join(ROOT, "systemd")))
check("units.LABELS keys are systemd units of the checkout",
      sorted(set(units.LABELS) - systemd), [])

keepawake = read("bin", "keepawake")
said = re.findall(r"\b(?:service_up|unit_state)\s+\S+\s+([A-Za-z][\w.-]*)", keepawake)
check("bin/keepawake asks after agents by label", bool(said), True)
check("bin/keepawake's labels name templates", unknown(said), [])

install = read("install.sh")
in_install = re.findall(r"\[((?:sclaude|keepawake)\.[\w-]+)\]=", install)
in_install += re.findall(r'"\$label" == ((?:sclaude|keepawake)\.[\w-]+)', install)
check("install.sh names agents", bool(in_install), True)
check("install.sh's labels name templates", unknown(in_install), [])

doctor = read("sclaude", "lib", "commands", "doctor.sh")
in_doctor = re.findall(r'"\$label" == ((?:sclaude|keepawake)\.[\w-]+)', doctor)
check("doctor.sh's labels name templates", unknown(in_doctor), [])

docs = read("keepawake", "docs.py")
in_docs = re.findall(r"gui/\$\(id -u\)/([\w.-]+)", docs)
check("docs.py's launchctl lines name templates", unknown(in_docs), [])

# launchd_labels in launchd.sh: core:sclaude.*, extras:keepawake*.
check("every template is the core's or the extras'",
      [t for t in templates if not (t.startswith("sclaude.") or t.startswith("keepawake"))], [])

proxy = read("bin", "sclaude-proxy")
found = re.search(r'^LAUNCHD_SOCKET = "([^"]+)"', proxy, re.M)
# The template is not plain XML for plistlib (its comments), so the key is
# read as the first one inside <key>Sockets</key><dict>.
sockets = re.search(r"<key>Sockets</key>\s*<dict>\s*<key>([^<]+)</key>",
                    read("launchd", "sclaude.gate.plist"))
check("the gate takes the socket sclaude.gate.plist declares",
      bool(found and sockets) and found.group(1) == sockets.group(1), True)

if failures:
    print("\n%d failed" % len(failures))
    sys.exit(1)
print("\nall passed")
