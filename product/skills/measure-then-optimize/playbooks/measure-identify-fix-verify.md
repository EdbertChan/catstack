# Measure, identify, fix, verify

Rob Pike's rule 2 in [*Notes on Programming in C* (1989)](https://users.ece.utexas.edu/~adnan/pike.html)
is the starting constraint: "Measure. Don't tune for speed until you've
measured." Brendan Gregg's [Performance Analysis Methodology](https://www.brendangregg.com/methodology.html)
provides methods for moving from the observed problem toward measured causes
instead of changing things at random.

## 1. Measure

Define the metric for the user's own symptom, not a convenient proxy. Exercise
the real path with the real workload, configuration, hardware, and other
settings that matter. Write a program that reruns that measurement and commit
it as the lever before changing the system; [Build the Lever](../../../../corpus/skills/principle-build-the-lever/SKILL.md)
explains why the program must remain reviewable and rerunnable.

Record the baseline with [perf_ledger.py](../scripts/perf_ledger.py), using at
least three runs and naming every relevant setting:

```sh
python3 product/skills/measure-then-optimize/scripts/perf_ledger.py record \
  --ledger perf-ledger.json \
  --phase baseline \
  --metric boot_seconds \
  --runs 5 \
  --setting workload=production \
  --symptom-metric boot_seconds \
  --lever-path scripts/measure_boot.py \
  -- python3 scripts/measure_boot.py
```

Use `--from-stdout` when the program prints the metric; otherwise the ledger
records wall-clock seconds. Preserve the baseline ledger with the change.

## 2. Identify

Name a cause only after a measurement attributes time or cost to it. Break the
symptom into measured components, then rank candidates by their measured share
of the total. Profiles, traces, counters, and time-division measurements can
support attribution; intuition and code proximity cannot.

Investigate the largest measured candidate first. If the measurements cannot
distinguish candidates, improve the measurement before choosing a cause.

## 3. Fix

Change one measured cause at a time so the next measurement can attribute any
difference to that change. Keep the measurement program, workload, and settings
fixed.

Raising a timeout, memory ceiling, retry budget, batch limit, or other limit is
not a performance fix unless the before and after symptom numbers justify it.
Treat a limit increase without that evidence as moving the boundary, not
removing the cost.

## 4. Verify

Rerun the same committed program with the same settings and record the result as
the after phase:

```sh
python3 product/skills/measure-then-optimize/scripts/perf_ledger.py record \
  --ledger perf-ledger.json \
  --phase after \
  --metric boot_seconds \
  --runs 5 \
  --setting workload=production \
  -- python3 scripts/measure_boot.py

python3 product/skills/measure-then-optimize/scripts/perf_ledger.py judge \
  perf-ledger.json
```

Report the `judge` output verbatim, including its verdict and reason set. Only a
`pass` verdict completes the performance fix. `unchecked` is not done: repair
the missing or unreadable measurement and rerun it rather than treating the
absence of evidence as success.
