#!/usr/bin/env bash
# Static release checks for the Easy Red 2 Claude plugin. No game required.
#
# Every check here corresponds to a defect that actually shipped: a name referenced but never
# imported (py_compile does not catch it), a tool advertised in the schema but not implemented,
# and error text that pointed at a path which did not exist.
#
# Usage:  tests/check.sh          (exit 0 = all pass)
set -uo pipefail
cd "$(dirname "$0")/.."

PASS=0; FAIL=0
ok()  { printf '  \033[32mPASS\033[0m  %s\n' "$1"; PASS=$((PASS+1)); }
bad() { printf '  \033[31mFAIL\033[0m  %s\n' "$1"; FAIL=$((FAIL+1)); }

SERVER=plugins/easy-red-2/tools/er2_mcp/server.py
PY_FILES="$SERVER tools/analyse_run.py tools/fix_steam_launch_options.py"

echo "== 1. Python syntax =="
for f in $PY_FILES; do
  [ -f "$f" ] || continue
  if python3 -m py_compile "$f" 2>/dev/null; then ok "$f compiles"; else bad "$f FAILS to compile"; fi
done

echo "== 2. No name referenced but never defined or imported =="
# py_compile cannot see this - name lookup is a RUNTIME operation, so a module full of undefined
# references compiles fine and then raises NameError in front of the user, mid-task.
python3 tests/undefined_names.py $PY_FILES
[ $? -eq 0 ] && PASS=$((PASS+1)) || FAIL=$((FAIL+1))

echo "== 3. Every advertised tool has an implementation =="
python3 - "$SERVER" <<'PY'
import re, sys
src = open(sys.argv[1]).read()
advertised = set(re.findall(r'"(er2_[a-z_]+)"\s*:', src))
implemented = {m[2:] for m in re.findall(r'def (t_[a-z_]+)\(', src)}
implemented = {"er2_" + n for n in implemented}
missing = sorted(advertised - implemented)
orphan = sorted(implemented - advertised)
if missing:
    print("  \033[31mFAIL\033[0m  advertised but not implemented: %s" % ", ".join(missing))
elif orphan:
    print("  \033[33mWARN\033[0m  implemented but not advertised: %s" % ", ".join(orphan))
    print("  \033[32mPASS\033[0m  every advertised tool is implemented")
else:
    print("  \033[32mPASS\033[0m  every advertised tool is implemented")
sys.exit(1 if missing else 0)
PY
[ $? -eq 0 ] && PASS=$((PASS+1)) || FAIL=$((FAIL+1))

echo "== 4. Paths quoted in error text actually exist =="
# An error message that names a fix script is worthless if the path is wrong. PLUGIN_ROOT is
# computed by walking up from server.py, so a directory move silently breaks every such message.
python3 - "$SERVER" <<'PY'
import importlib.util, os, sys
spec = importlib.util.spec_from_file_location("er2s", sys.argv[1])
m = importlib.util.module_from_spec(spec)
try:
    spec.loader.exec_module(m)
except SystemExit:
    pass
except Exception as e:
    print("  \033[31mFAIL\033[0m  server.py does not import cleanly: %s" % e); sys.exit(1)
root = getattr(m, "PLUGIN_ROOT", None)
if not root or not os.path.isdir(root):
    print("  \033[31mFAIL\033[0m  PLUGIN_ROOT does not resolve to a directory: %r" % root); sys.exit(1)
tool = os.path.join(root, "tools/fix_steam_launch_options.py")
if not os.path.exists(tool):
    print("  \033[31mFAIL\033[0m  error text points at a missing script: %s" % tool); sys.exit(1)
print("  \033[32mPASS\033[0m  PLUGIN_ROOT resolves and the referenced tools exist")
PY
[ $? -eq 0 ] && PASS=$((PASS+1)) || FAIL=$((FAIL+1))

echo "== 5. Plugin manifest is present and valid =="
for f in plugins/easy-red-2/.claude-plugin/plugin.json plugins/easy-red-2/.mcp.json; do
  if [ -f "$f" ] && python3 -c "import json,sys;json.load(open('$f'))" 2>/dev/null; then
    ok "$(basename $f) is valid JSON"
  else
    bad "$f missing or invalid JSON"
  fi
done

echo
echo "-------------------------------------------"
printf 'PASS %d   FAIL %d\n' "$PASS" "$FAIL"
[ "$FAIL" -eq 0 ] || exit 1
