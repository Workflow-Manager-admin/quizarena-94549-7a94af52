#!/bin/bash
cd /home/kavia/workspace/code-generation/quizarena-94549-7a94af52/quizrealm_backend
source venv/bin/activate
flake8 .
LINT_EXIT_CODE=$?
if [ $LINT_EXIT_CODE -ne 0 ]; then
  exit 1
fi

