# Combined scale v8 experiment

This directory contains the scale v8 solver source that passed the 50-case official acceptance and was copied to `algorithm_v5/`. `--scale=off` replays v7; `--scale=auto` enables scale search only with `borrow=ac` and `diff=auto`; `--scale=on` explicitly enables it. `borrow=none` and `diff=off` keep the previous behavior.

The wave stage tries nine full-window ranks, then refines only the two best with `{G, 2G, mb/2}`. It retains the v7 incumbent and validates memory peaks before accepting an improvement. Wave and subsequent scale stages share a 9 second elapsed-time guard, leaving time for output; v7 retains its existing search budget. The input is still read from stdin and the solution is written to stdout.
