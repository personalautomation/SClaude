# Read by every non-interactive bash (BASH_ENV) while tests/coverage runs the
# suite: each process traces the commands it runs into a file of its own, as
# `<source>|<function>|<line>`, for tests/coverage to map onto the library.
if [[ -n "${SCLAUDE_COVER:-}" && -d "$SCLAUDE_COVER" && $- != *x* ]]; then
  exec {__cover_fd}>>"$SCLAUDE_COVER/$$.$RANDOM"
  BASH_XTRACEFD=$__cover_fd
  PS4=$'\x01${BASH_SOURCE[0]:-}|${FUNCNAME[0]:-}|${LINENO}|'
  set -x
fi
