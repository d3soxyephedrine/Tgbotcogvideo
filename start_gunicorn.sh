#!/bin/bash
exec gunicorn --bind 0.0.0.0:5000 --reuse-port --reload --timeout 120 main:app
