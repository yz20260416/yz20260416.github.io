#!/bin/bash
cd /Users/yz/yz20260416.github.io
export OPENAI_API_BASE="https://api.deepseek.com/v1"
export OPENAI_API_KEY="sk-fce38056f483415fb66ee04aa6da75a1"
aider --no-pretty --model openai/deepseek-chat --auto-commits --commit-prompt "aider: "
