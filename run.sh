#!/bin/zsh
# 本地运行（读取 .env 如存在）
if [ -f .env ]; then export $(grep -v '^#' .env | xargs); fi
python3 -m app.main
