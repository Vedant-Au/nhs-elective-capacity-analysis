#!/usr/bin/env bash
#
# Initialise this project as a git repository and push it to GitHub.
#
# Run this on your Mac, from the project folder:
#
#     cd ~/Desktop/NHS_Project
#     bash setup_github_repo.sh
#
# Why this is a script rather than something already done: the sandbox that
# built this project cannot read files it did not create (they return
# "Resource deadlock avoided" through the synced mount), and it has no network
# route to github.com and no credentials. Git therefore has to run here, on the
# machine that actually holds the files and your GitHub login.
#
# The script is safe to re-run. It stops on the first error.

set -euo pipefail

REPO_NAME="nhs-elective-capacity-analysis"
DEFAULT_BRANCH="main"

cd "$(dirname "$0")"
echo "Working in: $(pwd)"
echo

# -----------------------------------------------------------------------
# 1. Clear the partial .git left behind by the sandbox.
#
# A git init was attempted from the sandbox and failed partway through: it
# wrote loose objects and an index.lock, then hit a permissions wall and could
# not clean up after itself. That stale lock would block every git command you
# run. There are no commits in it, so nothing is lost by starting fresh.
# -----------------------------------------------------------------------
if [ -d .git ]; then
  echo "Removing the partial .git directory left by the sandbox..."
  rm -rf .git
  echo "  done"
  echo
fi

# -----------------------------------------------------------------------
# 2. Initialise
# -----------------------------------------------------------------------
git init -q -b "$DEFAULT_BRANCH"
echo "Initialised an empty repository on branch '$DEFAULT_BRANCH'."

# Set identity locally only if you have no global one configured.
if ! git config --global user.email >/dev/null 2>&1; then
  git config user.email "vedanta240701@gmail.com"
  git config user.name  "Vedant Audichya"
  echo "  set a repository-local git identity (you had no global one)"
fi
echo

# -----------------------------------------------------------------------
# 3. Stage, and check nothing oversized slipped through.
#
# GitHub rejects any single file over 100MB and warns above 50MB. The
# .gitignore excludes the 154MB warehouse and the 135MB of raw downloads,
# both of which are rebuildable. This verifies that actually held.
# -----------------------------------------------------------------------
git add -A

echo "Largest files staged for commit:"
git diff --cached --name-only -z \
  | xargs -0 -I{} sh -c 'test -f "{}" && du -k "{}"' 2>/dev/null \
  | sort -rn | head -5 \
  | awk '{ printf "  %6.1f MB  %s\n", $1/1024, $2 }'
echo

OVERSIZE=$(git diff --cached --name-only -z \
  | xargs -0 -I{} sh -c 'test -f "{}" && du -k "{}"' 2>/dev/null \
  | awk '$1 > 51200 { print $2 }')

if [ -n "$OVERSIZE" ]; then
  echo "STOP: these staged files exceed GitHub's 50MB warning threshold:"
  echo "$OVERSIZE" | sed 's/^/  /'
  echo
  echo "Add them to .gitignore, run 'git reset', and try again."
  exit 1
fi

echo "No staged file exceeds 50MB. Total staged: $(git diff --cached --name-only | wc -l | tr -d ' ') files."
echo

# -----------------------------------------------------------------------
# 4. Commit
# -----------------------------------------------------------------------
git commit -q -m "NHS Cheshire and Merseyside elective capacity analysis

End-to-end analytics and strategy engagement across seven phases: data
warehousing from seven NHS England sources, an analytics layer (pressure
index, Monte Carlo forecasting, clustering, inequality of access), a linear
capacity optimiser delivered as an Excel Solver model, a Tableau story, a
scenario and strategy model, an executive board paper, and a generalised
config-driven toolkit.

Warehouse and raw downloads are excluded and rebuildable from source."

echo "Committed:"
git --no-pager log --oneline -1 | sed 's/^/  /'
echo

# -----------------------------------------------------------------------
# 5. Create the remote and push
# -----------------------------------------------------------------------
if command -v gh >/dev/null 2>&1 && gh auth status >/dev/null 2>&1; then
  echo "GitHub CLI is installed and authenticated. Creating the remote..."
  echo
  read -r -p "Make the repository public? [y/N] " VISIBILITY
  if [ "$VISIBILITY" = "y" ] || [ "$VISIBILITY" = "Y" ]; then
    VIS_FLAG="--public"
  else
    VIS_FLAG="--private"
  fi
  gh repo create "$REPO_NAME" $VIS_FLAG --source=. --remote=origin --push
  echo
  echo "Done. Repository URL:"
  gh repo view --json url -q .url | sed 's/^/  /'
else
  cat <<'INSTRUCTIONS'
The GitHub CLI is not installed or not authenticated, so the remote has to be
created by hand. Two options.

  Option A, install the CLI (easiest if you will do this again):

      brew install gh
      gh auth login
      bash setup_github_repo.sh        # re-run this script

  Option B, create the repository in the browser:

      1. Go to https://github.com/new
      2. Name it:  nhs-elective-capacity-analysis
      3. Do NOT tick "Add a README", "Add .gitignore" or "Choose a license".
         All three already exist here and pre-adding them causes a conflict
         on the first push.
      4. Create the repository, then run:

             git remote add origin https://github.com/<your-username>/nhs-elective-capacity-analysis.git
             git push -u origin main

INSTRUCTIONS
fi
