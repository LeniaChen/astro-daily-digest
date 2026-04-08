#!/bin/bash
cd /Users/lenia/claude/nature_digest
set -a
source .env
set +a
/opt/anaconda3/bin/python3 digest.py >> /Users/lenia/claude/nature_digest/digest.log 2>&1
