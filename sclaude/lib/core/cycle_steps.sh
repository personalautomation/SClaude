# Written by cycle_steps.py (`python3 cycle_steps.py sh > cycle_steps.sh`):
# change that file, not this one. tests/session_names.py checks the two agree.
# Sourced by steps.sh.

STEPS=(plan code pr review)
AFTER_STEPS=(sync epilogue retro)
# model effort mode|title (step_field)
declare -gA STEP_SPEC=(
  [plan]='opus high plan|planning'
  [code]='opus medium auto|development'
  [pr]='sonnet medium auto|pull request'
  [review]='opus medium auto|review'
)
declare -gA PHASE_ICON=(
  [step-plan]='📝'
  [step-code]='💻'
  [step-pr]='📤'
  [step-review]='🛠'
  [step]='▶️'
  [done]='✅'
  [friction]='🧱'
  [deferred]='🧱'
  [fix]='🔧'
  [local-review]='🔍'
  [regression]='🧪'
  [deploy]='🚀'
  [sync]='🔀'
  [epilogue]='🏁'
  [retro]='🔁'
)
