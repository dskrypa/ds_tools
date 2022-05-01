#!/usr/local/bin/bash

for ver in "" 3 3.11 3.10 3.9 3.8 3.7; do
    tmp_cmd="python$ver"
    if [[ $(which $tmp_cmd) ]]; then
        # echo "found $tmp_cmd"
        python_cmd=$tmp_cmd
        break
    fi
done

# echo "using $python_cmd"

if [[ -z "$python_cmd" ]]; then
    echo "Unable to find python executable" >&2
    exit 1
else
    script_dir=$(dirname "$0")
    $python_cmd "$script_dir/backup_plex.py" $@
    exit $?
fi
