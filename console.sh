#!/bin/sh
# console.sh off|on
# Αποσυνδέει (off) ή ξανασυνδέει (on) την κονσόλα κειμένου από την οθόνη, ώστε
# να μη γράφει πάνω στην εφαρμογή όσο αυτή τρέχει. Το καλεί η υπηρεσία systemd.
for v in /sys/class/vtconsole/vtcon*; do
  grep -q "frame buffer" "$v/name" 2>/dev/null || continue
  case "$1" in
    off) echo 0 > "$v/bind" ;;
    on)  echo 1 > "$v/bind" ;;
  esac
done
exit 0
