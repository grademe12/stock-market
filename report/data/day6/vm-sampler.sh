#!/bin/bash
# Sample Azure VM CPU and per-container CPU every INTERVAL seconds via Run Command.
# Usage: vm-sampler.sh <output-file> [interval-seconds] [duration-seconds]
set -u
out="${1:?output file}"
interval="${2:-300}"
duration="${3:-25200}"
end=$(( $(date +%s) + duration ))

# Runs on the VM under /bin/sh (dash): keep it POSIX.
remote='ts=$(date -u +%FT%TZ)
load=$(cut -d" " -f1-3 /proc/loadavg | tr " " "/")
cpu=$(vmstat 5 2 | tail -1 | awk "{print \"us=\"\$13\" sy=\"\$14\" id=\"\$15\" wa=\"\$16\" st=\"\$17}")
ovf=$(nstat -az TcpExtListenOverflows | awk "/Listen/{print \$2}")
tw=$(ss -Htan state time-wait | wc -l)
est=$(ss -Htan state established | wc -l)
ds=$(docker stats --no-stream --format "{{.Name}}={{.CPUPerc}}" | sed "s/^stock-market-//" | sort | tr "\n" " ")
ts_cpu=$(ps -C tailscaled -o %cpu= | head -1 | tr -d " ")
echo "SAMPLE $ts load=$load $cpu ovf=$ovf timewait=$tw estab=$est tailscaled_avg=$ts_cpu $ds"'

while [ "$(date +%s)" -lt "$end" ]; do
  started=$(date +%s)
  line="$(az vm run-command invoke -g stock-market-dev-rg -n stock-market-dev-backend \
    --command-id RunShellScript --scripts "$remote" \
    --query "value[0].message" -o tsv 2>&1 | grep '^SAMPLE' | sed 's/^SAMPLE //')"
  if [ -n "$line" ]; then
    printf '%s\n' "$line" >> "$out"
  else
    printf '%s sample_failed\n' "$(date -u +%FT%TZ)" >> "$out"
  fi
  [ "$(date +%s)" -ge "$end" ] && break
  sleep $(( interval - ($(date +%s) - started) > 0 ? interval - ($(date +%s) - started) : 1 ))
done
