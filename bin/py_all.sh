#!/usr/bin/env bash
# Generate a list of all classes and functions in the given Python file to populate __all__

grep -Po '^(class|def) \K([^(]+)' $1 | sort | awk '{print "\""$1"\""}' | paste -sd, | sed "s/\"/\'/g;s/,/, /g"
