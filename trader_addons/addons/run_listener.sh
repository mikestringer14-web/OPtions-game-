#!/usr/bin/env bash
# Supervisor for the WATCH-ONLY graduation listener. Restarts it if it crashes.
#   ./run_listener.sh start | stop | restart | status | logs
set -u
DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
LOG_DIR="${ADDONS_LOG_DIR:-$DIR/logs}"
PID_FILE="$LOG_DIR/supervisor.pid"
SUP_LOG="$LOG_DIR/supervisor.log"
if [ -x "$DIR/.venv/bin/python" ]; then PY="$DIR/.venv/bin/python"; else PY="${PYTHON:-python3}"; fi
mkdir -p "$LOG_DIR"

ts() { TZ=America/Toronto date '+%Y-%m-%dT%H:%M:%S%z'; }
is_running() { [ -f "$PID_FILE" ] && kill -0 "$(cat "$PID_FILE")" 2>/dev/null; }

supervise() {
  child=""
  stopping=0
  trap 'stopping=1; [ -n "$child" ] && kill -TERM "$child" 2>/dev/null; wait "$child" 2>/dev/null; rm -f "$PID_FILE"; echo "$(ts) supervisor stopped"; exit 0' TERM INT
  delay=5
  while true; do
    started=$(date +%s)
    echo "$(ts) starting listener"
    "$PY" "$DIR/graduation_listener.py" >>"$LOG_DIR/listener.stdout.log" 2>&1 &
    child=$!
    wait "$child"
    code=$?
    [ "$stopping" = 1 ] && break
    # a run that lasted 5+ minutes resets the backoff
    if [ $(( $(date +%s) - started )) -ge 300 ]; then delay=5; fi
    echo "$(ts) listener exited (code $code), restarting in ${delay}s"
    sleep "$delay"
    delay=$(( delay * 2 > 60 ? 60 : delay * 2 ))
  done
}

case "${1:-status}" in
  start)
    if is_running; then echo "already running (pid $(cat "$PID_FILE"))"; exit 0; fi
    nohup "$0" _supervise >>"$SUP_LOG" 2>&1 &
    echo $! >"$PID_FILE"
    echo "started supervisor pid $(cat "$PID_FILE"); logs in $LOG_DIR"
    ;;
  _supervise)
    supervise
    ;;
  stop)
    if ! is_running; then echo "not running"; rm -f "$PID_FILE"; exit 0; fi
    kill -TERM "$(cat "$PID_FILE")"
    for _ in $(seq 1 20); do is_running || break; sleep 0.5; done
    if is_running; then echo "still running, sending KILL"; kill -KILL "$(cat "$PID_FILE")"; fi
    rm -f "$PID_FILE"
    echo "stopped"
    ;;
  restart)
    "$0" stop; "$0" start
    ;;
  status)
    if is_running; then echo "running (supervisor pid $(cat "$PID_FILE"))"; else echo "not running"; fi
    if [ -f "$LOG_DIR/listener_heartbeat.txt" ]; then
      age=$(( $(date +%s) - $(stat -c %Y "$LOG_DIR/listener_heartbeat.txt") ))
      echo "heartbeat ${age}s ago:"; cat "$LOG_DIR/listener_heartbeat.txt"
      [ "$age" -gt 150 ] && echo "WARNING: heartbeat is stale"
    fi
    ;;
  logs)
    tail -n 50 -f "$LOG_DIR/listener.log"
    ;;
  *)
    echo "usage: $0 start|stop|restart|status|logs"; exit 2
    ;;
esac
