#!/bin/bash

# Create a desktop shortcut with the following target (with the proper path to this file) to launch the server + firefox:
# "C:\Program Files\Git\bin\bash.exe" "C:\path\to\this_file"

if [[ ${#1} < 1 ]]; then
    port=12000
else
    port=$1
fi

flask_dir="`dirname $0`"
/usr/bin/env python3 "$flask_dir"/music_manager_server.py -p $port & "/c/Program Files/Mozilla Firefox/firefox.exe" localhost:$port
