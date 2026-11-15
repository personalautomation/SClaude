# What sclaude asks about other processes and the ports they listen on, on
# Linux and on macOS alike.
#
# Linux answers from /proc and `ss`; macOS has neither, and answers from `ps`
# and `lsof`. Every caller asks here rather than reading /proc itself, so the
# two answers stay one function apart. The Linux side is what the callers read
# before this module existed, line for line.
#
# One limit on macOS: a process's environment is shown to its own user only
# for binaries that are not the system's own (SIP hides /bin/sleep's, not a
# Homebrew or nvm node's). The marks sclaude puts on a dev server are read
# from the server's node, which is never a system binary. The environment is
# read by procinfo.py, from the kernel: ps shows it with spaces between the
# entries, and a value — a tree's path — may hold spaces itself.

procinfo_darwin() { [[ "${OSTYPE:-}" == darwin* ]]; }

# The Python half, which reads a process's environment exactly on macOS.
PROCINFO_PY="$(dirname "${BASH_SOURCE[0]}")/procinfo.py"

# The process's name, as Linux keeps it in /proc/<pid>/comm: the name it was
# started by, or the title a program gave itself ("npm exec …"). macOS's ps
# shows the same as `comm`, a path where the process was started by one; its
# `ucomm` is the executable file's own name instead, which for Claude Code is
# its version.
proc_name() {
  if procinfo_darwin; then
    local name
    name="$(ps -o comm= -p "$1" 2>/dev/null | sed 's/[[:space:]]*$//')"
    [[ "$name" == /* ]] && name="${name##*/}"
    [[ -n "$name" ]] && printf '%s\n' "$name"
  else
    cat "/proc/$1/comm" 2>/dev/null
  fi
}

# The command line, its words joined by spaces.
proc_cmdline() {
  if procinfo_darwin; then
    ps -ww -o command= -p "$1" 2>/dev/null
  else
    tr '\0' ' ' 2>/dev/null <"/proc/$1/cmdline"
  fi
}

# The executable's path, links resolved. On macOS the first file lsof lists
# as the process's text: ps names the title there, which a program may have
# changed ("npm exec …").
proc_exe() {
  local exe
  if procinfo_darwin; then
    exe="$(lsof -a -p "$1" -d txt -Fn 2>/dev/null | sed -n 's/^n//p' | head -1)"
    [[ "$exe" == /* ]] || return 1
    readlink -f "$exe" 2>/dev/null
  else
    readlink -f "/proc/$1/exe" 2>/dev/null
  fi
}

# A process's parent pid. On Linux the field after the title, which may hold
# spaces and parentheses itself ("npm run dev", "next-server (v16…)"): read
# from the last ")" on.
proc_parent() {
  if procinfo_darwin; then
    local ppid
    ppid="$(ps -o ppid= -p "$1" 2>/dev/null | tr -d ' ')"
    [[ -n "$ppid" ]] || return 1
    echo "$ppid"
    return 0
  fi
  local stat rest
  stat="$(cat "/proc/$1/stat" 2>/dev/null)" || return 1
  rest="${stat##*) }"
  set -- $rest
  echo "${2:-}"
}

# A process's working directory, links resolved; 1 when it cannot be read.
proc_cwd() {
  if procinfo_darwin; then
    local dir
    dir="$(lsof -a -d cwd -p "$1" -Fn 2>/dev/null | sed -n 's/^n//p' | head -1)"
    [[ -n "$dir" ]] || return 1
    readlink -f "$dir" 2>/dev/null
  else
    readlink -f "/proc/$1/cwd" 2>/dev/null
  fi
}

# "<pid> <working directory>" for every process whose directory can be read,
# one a line, in one pass. The directory as the system gives it, unresolved.
proc_cwds() {
  if procinfo_darwin; then
    lsof -a -d cwd -u "$(id -u)" -Fpn 2>/dev/null \
      | awk '/^p/ { pid = substr($0, 2) } /^n/ { print pid, substr($0, 2) }'
  else
    local p cwd
    for p in /proc/[0-9]*/cwd; do
      cwd="$(readlink "$p" 2>/dev/null)" || continue
      p="${p#/proc/}"
      echo "${p%/cwd} $cwd"
    done
  fi
}

# Whether a process's environment holds NAME=VALUE exactly.
proc_env_has() {
  local pid="$1" want="$2"
  if procinfo_darwin; then
    python3 "$PROCINFO_PY" env-has "$pid" "$want" 2>/dev/null
  else
    tr '\0' '\n' 2>/dev/null <"/proc/$pid/environ" | grep -qxF -- "$want"
  fi
}

# Whether any process of this user carries NAME=VALUE in its environment.
proc_env_anywhere() {
  local want="$1"
  if procinfo_darwin; then
    python3 "$PROCINFO_PY" env-anywhere "$want" 2>/dev/null
  else
    local proc
    for proc in /proc/[0-9]*; do
      grep -qzxF -- "$want" "$proc/environ" 2>/dev/null && return 0
    done
    return 1
  fi
}

# When a process started, as a word that changes when its pid is reused.
proc_start() {
  if procinfo_darwin; then
    ps -o lstart= -p "$1" 2>/dev/null | tr -s ' ' '-' | sed 's/-$//'
  else
    awk '{print $22}' "/proc/$1/stat" 2>/dev/null
  fi
}

# The ports something listens on over TCP, one a line.
ports_listening() {
  if procinfo_darwin; then
    lsof -nP -iTCP -sTCP:LISTEN -Fn 2>/dev/null | sed -n 's/^n.*://p' | sort -un
  else
    ss -ltnH 2>/dev/null | awk '{print $4}' | sed 's/.*://'
  fi
}

# The addresses a port is listened on, one a line ("127.0.0.1:3000",
# "*:3000", "[::1]:3000"); nothing when nobody listens on it.
port_addresses() {
  local port="$1"
  if procinfo_darwin; then
    lsof -nP -iTCP:"$port" -sTCP:LISTEN -Fn 2>/dev/null | sed -n 's/^n//p' | sort -u
  else
    ss -ltnH "sport = :$port" 2>/dev/null | awk '{print $4}' | sed 's/%[^:]*:/:/'
  fi
}

# The PID of the process listening on a port, or empty.
port_pid() {
  local port="$1"
  [[ "$port" =~ ^[0-9]+$ ]] || return 0
  if procinfo_darwin; then
    lsof -nP -iTCP:"$port" -sTCP:LISTEN -t 2>/dev/null | head -1
  else
    ss -ltnp 2>/dev/null | grep ":$port " | grep -oP 'pid=\K[0-9]+' | head -1
  fi
}

# "<port> <pid>" for every TCP port something listens on, one a line, a pid
# per line where several share a port; only the pids this user may see on
# Linux, and on macOS only this user's own processes.
ports_pids() {
  if procinfo_darwin; then
    lsof -nP -iTCP -sTCP:LISTEN -Fpn 2>/dev/null \
      | awk '/^p/ { pid = substr($0, 2) }
             /^n/ { port = $0; sub(/.*:/, "", port); print port, pid }' | sort -u
  else
    ss -ltnpH 2>/dev/null | awk '{ port = $4; sub(/.*:/, "", port)
      line = $0
      while (match(line, /pid=[0-9]+/)) {
        print port, substr(line, RSTART + 4, RLENGTH - 4)
        line = substr(line, RSTART + RLENGTH)
      } }' | sort -u
  fi
}

# How many bytes a process has put out so far, as a counter that grows when it
# answers anybody: what it wrote (wchar in /proc/<pid>/io — files, pipes,
# sockets alike). Nothing when it cannot be read, and always nothing on macOS:
# the kernel keeps no count of a process's writes there, its disk writes leave
# out a log printed to a terminal, and nettop's bytes_out counts only the
# connections open at the moment it looks — a request answered and closed
# between two looks never shows.
proc_output_bytes() {
  procinfo_darwin && return 0
  awk '/^wchar:/ {print $2; exit}' "/proc/$1/io" 2>/dev/null
}

# Seconds since the last keystroke or mouse move at the machine itself: on
# macOS the HID system's idle time. Linux gives no such answer to a process
# outside the session, nor WSL of Windows' keyboard: 1, and nothing printed.
input_idle() {
  procinfo_darwin || return 1
  local ns
  ns="$(ioreg -c IOHIDSystem -d 4 2>/dev/null | awk '/"HIDIdleTime"/ { print $NF; exit }')"
  [[ "$ns" =~ ^[0-9]+$ ]] || return 1
  echo $(( ns / 1000000000 ))
}

# The load average over the last minute; 1 when it cannot be read.
load_one() {
  local one
  if procinfo_darwin; then
    one="$(sysctl -n vm.loadavg 2>/dev/null | awk '{print $2}')"
  else
    read -r one _ < /proc/loadavg 2>/dev/null
  fi
  [[ -n "$one" ]] || return 1
  echo "$one"
}
