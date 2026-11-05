# sclaude/lib keeps its modules in folders by what they do — core, cycle,
# review, github, ship, tree, improve, metrics, flow, commands — and they
# import one another by their bare names, as when they all lay side by side.
# Importing this module puts every folder on sys.path, ahead of what is there,
# so that `import pr_context` finds review/pr_context.py from anywhere — also
# from tests/, where a bench may carry a module's own name. The names stay
# unique across the folders and clear of the standard library's;
# tests/paths.py checks both.
import os
import sys

_HERE = os.path.dirname(os.path.abspath(__file__))
_DIRS = [os.path.join(_HERE, n) for n in sorted(os.listdir(_HERE))
         if os.path.isdir(os.path.join(_HERE, n)) and not n.startswith(("_", "."))]
sys.path[:0] = [d for d in _DIRS if d not in sys.path]
