#!/bin/bash
# 启动虚拟 X 服务器
Xvfb :99 -ac &

# 设置 DISPLAY 环境变量
export DISPLAY=:99

# 启动签到脚本
python3 signin_script.py
