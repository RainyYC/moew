# MoE EP/PP hackathon package

This directory contains only the contestant-facing files.

## Contents

| Path | Purpose |
|---|---|
| `problem-statement.md` | English problem statement |
| `problem-statement-cn.md` | Chinese problem statement |
| `cases/*.txt` | 50 input cases |
| `grader.py` | single-case grader: `python3 grader.py <input> <output>` |
| `sample_solution.py` | greedy sample solution (9 s default budget) |
| `sample_solution.c` | C version of the same greedy construction |
| `run_all.py` | run a submission on all 50 cases with a 10 s limit; reports TIME and CPU time, or TO |
| `report_python.txt` | reference batch report for `sample_solution.py` |
| `report_c.txt` | reference batch report for the compiled C sample |

## Single case

```bash
python3 sample_solution.py cases/r16_p4_trap.txt > /tmp/out.txt
python3 grader.py cases/r16_p4_trap.txt /tmp/out.txt
```

The grader prints the integer `TIME` on success, or `INVALID: <reason>`.
The solution must print the mapping in the format of the statement to stdout;
diagnostics should go to stderr.

## All 50 cases

The default command runs the sample solution:

```bash
python3 run_all.py
```

To test a submission, replace the command:

```bash
python3 run_all.py --cmd "python3 solution.py"
python3 run_all.py --cmd "python3 solution.py --budget 9.5"
python3 run_all.py --cmd "python3 solution.py {case}"
```

`run_all.py` appends the case path unless the command contains `{case}`.  It
enforces a 10 s wall-clock limit per case (the grader's own time is excluded)
and prints `TIME`, the solver's CPU time (user + system), and wall time for
each case.  A case that exceeds the limit is reported as `TO` with no `TIME`.

The sample solution uses a 9 s internal budget so that process startup and
output stay inside the 10 s limit.  A submission may use up to 10 s; if it exceeds the limit the case is `TO`
and is not graded.

## C sample

The C source implements the same greedy construction: legal grid enumeration,
even cuts, LPT expert placement, and list scheduling with fixed tie-break keys.

```bash
cc -O2 -std=c11 -o sample_solution_c sample_solution.c
./sample_solution_c cases/r16_p4_trap.txt > /tmp/out.txt
python3 grader.py cases/r16_p4_trap.txt /tmp/out.txt
```

It can also be used as the batch command:

```bash
python3 run_all.py --cmd "./sample_solution_c"
```

## Reference reports

`report_python.txt` and `report_c.txt` are generated with:

```bash
python3 run_all.py --cmd "python3 sample_solution.py --budget 9.0" --cases cases
cc -O2 -std=c11 -o sample_solution_c sample_solution.c
python3 run_all.py --cmd "./sample_solution_c" --cases cases
```

Both reports show 50/50 valid cases.  The C report was produced from the
compiled binary; compile it first if you want to reproduce that report.

## Notes

- Do not read the case list from `expected.tsv` or other hidden files; the
  grade is computed only from the submitted mapping and the case input.
- The grader is a forward simulator; it does not search.
- Keep the output format exact: the grader rejects malformed mappings.
