# sclaude's table of the cycle's steps (sclaude/lib/core/cycle_steps.py), for
# the bot: the icons sclaude's lines open with (notices.PHASE_ICONS) and the
# order of the cycle's places (i18n's act.steps, from its `cycle.<name>`
# words) come from the same table as sclaude's own, rather than from a copy
# kept in step by hand.
#
# Loaded by its path, not through sclaude's import path: i18n reads it as the
# bot starts, before anything else of sclaude is needed.
import importlib.util
import os

PATH = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
                    "sclaude", "lib", "core", "cycle_steps.py")


def _load():
    spec = importlib.util.spec_from_file_location("sclaude_cycle_steps", PATH)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


steps = _load()
