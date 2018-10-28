#!/bin/bash

# Create a desktop shortcut with the following target (with the proper path to this file) to launch the server + firefox:
# "C:\Program Files\Git\bin\bash.exe" "C:\path\to\this_file"

if [[ ${#1} < 1 ]]; then
    port=10000
else
    port=$1
fi

lf_dir="`dirname $0`"
/usr/bin/env python3 "$lf_dir"/lyric_fetcher_server.py -p $port & "/c/Program Files (x86)/Mozilla Firefox/firefox.exe" localhost:$port
