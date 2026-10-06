# Expense-run completion check

Every expense run must update the public team repository and its reusable notes before an
operator reports it done. The check belongs after live report verification and private-state
updates; it does not submit a report or replace financial validation.

Start before processing the run (the one-shot pipeline does this automatically):

```sh
python tools/run_completion.py start --run-dir personal/runs/<run>
```

The returned `run_id` identifies this run. Repeating start resumes the same anchor. A completed
directory requires `start --new` to begin again; that resets its proof. Work on the same Git branch
through completion. Run state must be inside the repository, ignored and untracked.

Once the saved report checks pass, update a public reusable Markdown note under `docs/`,
`README.md` or `RUNBOOK.md`. Describe the tool lesson or verified workflow result without names,
claim/report IDs, amounts, statements, receipts or secrets. Review the staged diff before committing.
Keep actual run details in ignored `personal/`.

```sh
git add docs/run-lessons.md
git commit -m "Record a reusable expense workflow result" -m "Expense-Run: <run_id>"
git push origin <current-branch>
python tools/run_completion.py finish --run-dir personal/runs/<run> --public-note docs/run-lessons.md
```

Use the actual note path and ID, rather than the example placeholders. Finish requires a commit
after the captured HEAD, an exact `Expense-Run` trailer in that commit, and a change to the
specified public note. The note must still exist in committed HEAD. It verifies the actual
`origin` branch tip equals local HEAD through `git ls-remote`; a local commit or stale tracking
ref is insufficient. Changing origin or branches cannot substitute another repository/run.

Exit zero prints `completion: verified` and writes `.expense-run-completion.json` in the ignored
run directory. A failed recheck removes the old proof and exits nonzero. Do not claim completion
until this passes; describe any remaining blocker instead. Remote verification needs network
access and configured Git authentication, with no credentials supplied to this tool.

For a PR workflow, perform this check on the pushed run branch before handover and link its PR.
It verifies publication to the team repository, not a merge into the default branch. Finish is
a workflow gate for operators using it, not enforcement over arbitrary chat messages.
