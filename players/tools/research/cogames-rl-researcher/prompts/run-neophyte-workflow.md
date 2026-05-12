# Run The Neophyte Workflow

You are running an end-to-end neophyte competitor workflow. Do not stop at planning.

## Goal

Produce a real CoGames submission attempt for a newly generated trainable policy, then report submission + leaderboard
evidence.

## Success Criteria

1. You read the tutorial docs from scratch:
   - `packages/cogames/tutorials/01_MAKE_POLICY.md`
   - `packages/cogames/tutorials/02_TRAIN.md`
   - `packages/cogames/tutorials/03_SUBMIT.md`
2. You generate a new trainable policy file (not reusing a preexisting custom file).
3. You train it and find a produced checkpoint file.
4. You run the neophyte startup workflow from `cogames-rl-researcher`.
5. You capture evidence from `cogames submissions` and `cogames leaderboard`.
6. You write a final report to `./artifacts/ai_researcher/neophyte_workflow_report.md`.

## Required Workflow

Run these steps from repo root:

1. Read and summarize the tutorial docs listed above (short summary in final report).
2. Set run variables:
   - `TS=$(date +%Y%m%d-%H%M%S)`
   - `TS_MODULE=$(echo \"$TS\" | tr '-' '_')`
   - `POLICY_MODULE=\"neophyte_policy_${TS_MODULE}\"`
   - `POLICY_FILE=\"${POLICY_MODULE}.py\"`
   - `POLICY_NAME=\"neophyte-${TS}\"`
   - `CHECKPOINT_DIR=\"./artifacts/ai_researcher/${TS}_tutorial_train\"`
3. Create a trainable policy template:
   - `uv run cogames tutorial make-policy --trainable -o \"$POLICY_FILE\"`
4. Train it:
   - `uv run cogames tutorial train -m machina_1 -p \"class=${POLICY_MODULE}.MyTrainablePolicy\" --steps 2000 --checkpoints \"$CHECKPOINT_DIR\"`
5. Find the latest checkpoint:
   - `CKPT_FILE=$(find \"$CHECKPOINT_DIR\" -name 'model_*.pt' | sort | tail -n 1)`
   - Fail loudly if no checkpoint is found.
6. Build policy spec:
   - `POLICY_SPEC=\"class=${POLICY_MODULE}.MyTrainablePolicy,data=${CKPT_FILE}\"`
7. Run neophyte startup (this performs docs/readthrough, scrimmage, upload, submit, leaderboard):
   - `uv run ./cogames-rl-researcher/scripts/run_ai_researcher_startup.py --policy \"$POLICY_SPEC\" --policy-name \"$POLICY_NAME\" --season beta-cvc --researcher-profile neophyte`
8. Collect submission evidence:
   - `uv run cogames submissions --season beta-cvc --policy \"$POLICY_NAME\" --json`
   - `uv run cogames leaderboard --season beta-cvc --json`
9. Write `./artifacts/ai_researcher/neophyte_workflow_report.md` with:
   - tutorial summary
   - policy file path
   - checkpoint path
   - startup run dir + status + gates status
   - submission output snippet
   - whether leaderboard currently shows the policy

## Operational Rules

- Execute commands directly; do not ask for permission unless blocked by missing credentials.
- If login/auth fails, run `uv run cogames auth login` and continue.
- If a command fails, fix and retry; do not silently skip required steps.
- Keep everything explicit and reproducible in the final report.
