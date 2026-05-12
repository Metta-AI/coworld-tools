# Run The Experienced Workflow

You are running an end-to-end experienced competitor workflow. Do not stop at planning.

## Goal

Produce a real CoGames submission attempt and then run one resume pass that outputs ranked next actions for follow-up
iteration.

## Success Criteria

1. You read tutorial docs from scratch:
   - `packages/cogames/tutorials/01_MAKE_POLICY.md`
   - `packages/cogames/tutorials/02_TRAIN.md`
   - `packages/cogames/tutorials/03_SUBMIT.md`
2. You generate and train a fresh trainable policy.
3. You run startup with `--researcher-profile experienced`.
4. You run resume on the startup run dir.
5. You collect submission + leaderboard evidence.
6. You write a final report to `./artifacts/ai_researcher/experienced_workflow_report.md`.

## Required Workflow

Run these steps from repo root:

1. Read and summarize the docs listed above.
2. Set run variables:
   - `TS=$(date +%Y%m%d-%H%M%S)`
   - `TS_MODULE=$(echo \"$TS\" | tr '-' '_')`
   - `POLICY_MODULE=\"experienced_policy_${TS_MODULE}\"`
   - `POLICY_FILE=\"${POLICY_MODULE}.py\"`
   - `POLICY_NAME=\"experienced-${TS}\"`
   - `CHECKPOINT_DIR=\"./artifacts/ai_researcher/${TS}_tutorial_train\"`
3. Create trainable policy template:
   - `uv run cogames tutorial make-policy --trainable -o \"$POLICY_FILE\"`
4. Train it:
   - `uv run cogames tutorial train -m machina_1 -p \"class=${POLICY_MODULE}.MyTrainablePolicy\" --steps 3000 --checkpoints \"$CHECKPOINT_DIR\"`
5. Find latest checkpoint:
   - `CKPT_FILE=$(find \"$CHECKPOINT_DIR\" -name 'model_*.pt' | sort | tail -n 1)`
   - Fail loudly if missing.
6. Build policy spec:
   - `POLICY_SPEC=\"class=${POLICY_MODULE}.MyTrainablePolicy,data=${CKPT_FILE}\"`
7. Run experienced startup:
   - `uv run ./cogames-rl-researcher/scripts/run_ai_researcher_startup.py --policy \"$POLICY_SPEC\" --policy-name \"$POLICY_NAME\" --season beta-cvc --researcher-profile experienced`
8. Capture startup run dir from output and run resume:
   - `uv run ./cogames-rl-researcher/scripts/run_ai_researcher_resume.py --source <startup_run_dir> --researcher-profile experienced`
9. Collect submission evidence:
   - `uv run cogames submissions --season beta-cvc --policy \"$POLICY_NAME\" --json`
   - `uv run cogames leaderboard --season beta-cvc --json`
10. Write `./artifacts/ai_researcher/experienced_workflow_report.md` with:

- tutorial summary
- policy file + checkpoint
- startup status + gates
- resume status + ranked next actions path
- submission + leaderboard evidence

## Operational Rules

- Execute commands directly; do not ask for permission unless blocked by missing credentials.
- If login/auth fails, run `uv run cogames auth login` and continue.
- If a command fails, fix and retry; do not skip required steps.
