#!/bin/bash

# Thresholds in Celsius
CPU_MAX=85
DRIVE_MAX=50

# Check Intel Core i7 (coretemp Package id 0)
CPU_TEMP=$(sensors | grep 'Package id 0:' | awk '{print $4}' | tr -d '+°C' | cut -d. -f1)

if [ -n "$CPU_TEMP" ] && [ "$CPU_TEMP" -ge "$CPU_MAX" ]; then
    /usr/local/bin/tg_alert.sh "High CPU Temperature: ${CPU_TEMP}°C"
fi

# Check drives (drivetemp)
# Check SATA drives
sensors | grep -A 2 'drivetemp' | grep 'temp1:' | while read -r line; do
    DRIVE_TEMP=$(echo "$line" | awk '{print $2}' | tr -d '+°C' | cut -d. -f1)
    if [ -n "$DRIVE_TEMP" ] && [ "$DRIVE_TEMP" -ge "$DRIVE_MAX" ]; then
        /usr/local/bin/tg_alert.sh "High SATA Drive Temperature: ${DRIVE_TEMP}°C"
    fi
done

# Check NVMe drives
sensors | grep -A 2 'nvme' | grep 'Composite:' | while read -r line; do
    NVME_TEMP=$(echo "$line" | awk '{print $2}' | tr -d '+°C' | cut -d. -f1)
    if [ -n "$NVME_TEMP" ] && [ "$NVME_TEMP" -ge "$DRIVE_MAX" ]; then
        /usr/local/bin/tg_alert.sh "High NVMe SSD Temperature: ${NVME_TEMP}°C"
    fi
done