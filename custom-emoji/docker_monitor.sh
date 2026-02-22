#!/bin/bash

# Listens for container crash/stop events
docker events --filter 'event=die' --format '{{.Actor.Attributes.name}}' | while read container; do
    /usr/local/bin/tg_alert.sh "Container stopped: ${container}"
done