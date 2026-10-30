#!/bin/bash
set -u
A=/home/rainy/hackathon/runs/val-t1-battery-20261029-2308
mkdir -p $A/current $A/iso-head-out $A/logs/wall-prod $A/logs/wall-iso
: > $A/logs/prod_times.txt; : > $A/logs/iso_times.txt
for f in /home/rainy/hackathon/bigcases/battery/b*.in; do
  n=$(basename $f .in)
  python3 $A/logs/_runner.py "$f" "$A/current/$n.out" "$A/logs/wall-prod/$n.json" \
      > $A/current/$n.stdout 2> $A/current/$n.stderr
  echo "$n rc=$? $(cat $A/logs/wall-prod/$n.json)" >> $A/logs/prod_times.txt
done
for f in $A/iso-head/bigcases/battery/b*.in; do
  n=$(basename $f .in)
  ( cd $A/iso-head && python3 ../logs/_runner.py "$f" "$A/iso-head-out/$n.out" "$A/logs/wall-iso/$n.json" \
      > $A/iso-head-out/$n.stdout 2> $A/iso-head-out/$n.stderr )
  echo "$n rc=$? $(cat $A/logs/wall-iso/$n.json)" >> $A/logs/iso_times.txt
done
echo DONE
