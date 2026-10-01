#!/bin/sh
script="$1"
shift
dir=$(dirname "$0")
# The Windows Store stub for python exits 9009, so probe each candidate before exec.
if [ "$OS" = "Windows_NT" ]; then
  candidates="py python3 python"
else
  candidates="python3 python py"
fi
for py in $candidates; do
  flag=""
  [ "$py" = "py" ] && flag="-3"
  command -v "$py" >/dev/null 2>&1 || continue
  "$py" $flag -c 'import sys' >/dev/null 2>&1 || continue
  exec "$py" $flag "$dir/$script" "$@"
done
echo "py.sh: no working python found (tried python3, python, py -3)" >&2
exit 1
