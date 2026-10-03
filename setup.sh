#!/bin/bash
set -euo pipefail
cd -- "$(dirname -- "$(readlink -f -- "$0")")"
focus_source=$(pwd -P)
if [[ ${1:-} != '' && ${1:-} != '--passwordless' ]]; then
  echo 'Usage: setup.sh [--passwordless]' >&2
  exit 1
fi
# One elevation runs only /usr/bin/install on fixed destinations. Never execute plugin code as root.
if [[ $EUID == 0 ]]; then elevate=(); elif [[ -t 0 ]]; then elevate=(sudo); else elevate=(pkexec); fi
installs='/usr/bin/install -o root -g root -m 755 -D "$1" /usr/local/bin/focus-root-helper && /usr/bin/install -o root -g root -m 644 -D "$2" /usr/share/polkit-1/actions/local.focus.policy'
focus_rule=''
if [[ ${1:-} == '--passwordless' ]]; then
  focus_user=${SUDO_USER:-${USER:-}}
  [[ $focus_user =~ ^[a-z_][a-z0-9_-]*\$?$ ]] || { echo 'Cannot identify login user.' >&2; exit 1; }
  focus_rule=$(mktemp)
  trap 'rm -f -- "$focus_rule"' EXIT
  cat > "$focus_rule" <<RULE
polkit.addRule(function(action, subject) {
  if (action.id === "local.focus.modify" && subject.user === "$focus_user" && subject.local && subject.active && action.lookup("program") === "/usr/local/bin/focus-root-helper") {
    return polkit.Result.YES;
  }
});
RULE
  installs+=' && /usr/bin/install -o root -g root -m 644 -D "$3" /etc/polkit-1/rules.d/49-local.focus.rules'
fi
"${elevate[@]}" /usr/bin/bash -c "$installs" focus-setup "$focus_source/setup/focus-root-helper" "$focus_source/setup/local.focus.policy" "$focus_rule"
printf '%s\n' 'Focus helper installed. Run focusctl recover to remove all Focus blocking.'
