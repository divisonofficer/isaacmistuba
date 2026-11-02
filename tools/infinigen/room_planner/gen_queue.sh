#!/bin/bash
# Memory-safe job queue for the offline plant / object generators (user 10-23: 'the machine is going to blow up').
#   gen_queue.sh JOBFILE        one job per line = the full command (python plant_gen2.py ... / obj_gen.py ...); every job runs under
#   - prlimit --as=24 GB   (a model that hits the cap fails and is skipped; FAIL line in $GQ_FAILS),
#   - timeout $GQ_TIMEOUT s (default 900),
#   - at most $GQ_PAR (default 3) at a time, and a job starts only when MemAvailable >= $GQ_MINFREE_GB (default 100; it waits and re-checks every 20 s).
# Never put PalmTreeFactory / LargePlantContainerFactory in a job file (runaway memory / segfault).
PAR=${GQ_PAR:-3}; CAP=$(( ${GQ_CAP_GB:-24} * 1073741824 )); TO=${GQ_TIMEOUT:-900}; MINF=${GQ_MINFREE_GB:-100}; FAILS=${GQ_FAILS:-/tmp/gen_queue_fails.txt}
export OMP_NUM_THREADS=2 MKL_NUM_THREADS=2 OPENBLAS_NUM_THREADS=2
n=0
while IFS= read -r job; do
  [ -z "$job" ] && continue
  case "$job" in *tropic_plants.PalmTreeFactory*|*" PalmTreeFactory"*|*LargePlantContainer*) echo "SKIP (banned): $job" >> "$FAILS"; continue;; esac
  while [ "$(pgrep -P $$ | wc -l)" -ge "$PAR" ]; do sleep 5; done
  while [ "$(awk '/MemAvailable/ {print int($2/1048576)}' /proc/meminfo)" -lt "$MINF" ]; do sleep 20; done
  ( prlimit --as=$CAP timeout $TO bash -c "$job" || echo "FAIL($?) $job" >> "$FAILS" ) &
  sleep 3
done < "$1"
wait
