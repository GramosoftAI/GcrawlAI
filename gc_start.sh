#!/bin/bash

cd /home/GcrawlAI

source /home/gc_env/bin/activate

exec uvicorn api.api:app \
    --host 0.0.0.0 \
    --port 4545