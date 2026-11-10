# Secrets cleanup (do this first, in this order)

## 1. Revoke — this is the only step that actually protects you
Deleting a file from git does **not** un-leak it. Anyone who cloned, forked, or
cached the repo may still have the old commits.

- **Hugging Face key** (`hf_...`): it was committed in `.env` on the branch you pushed
  to GitHub (16 commits). Revoke it at huggingface.co → Settings → Access Tokens.
- **Groq key** (`gsk_...`): it is in your *local* history (about 30 commits, mostly
  AI-agent checkpoint commits). Revoke it at console.groq.com → API Keys and create a
  new one. Even if you never pushed it, this zip itself contained it.
- **Neon / DATABASE_URL**: none was found in history, but if you ever pasted it into a
  chat, an issue, or a screenshot, rotate the password in the Neon dashboard.
- Put the new keys **only** in Vercel → Project → Settings → Environment Variables
  (and in a local, git-ignored `.env`). Never in chat, code, or a zip.

## 2. User data that was committed
`interviewsense.db` and `zora.db` were committed (an old copy held 2 accounts with
password hashes and a session). Session tokens are now stored hashed, but if anyone
used a real password there, tell them to change it.

## 3. Remove the files from history
**Simplest (recommended for a solo student project): start a fresh history.**
```bash
git checkout --orphan clean-main
git add -A            # .gitignore now excludes .env, *.db, venvs, node_modules
git commit -m "Initial clean commit"
git branch -M main
git push --force origin main
```
Then on GitHub: delete old branches/tags, and if it was ever public, assume the old
commits were scraped — which is why step 1 matters.

**Alternative (keep history):** `pip install git-filter-repo`, then
```bash
git filter-repo --invert-paths --path .env --path interviewsense.db --path zora.db \
                --path-glob 'venv/*' --path-glob '.venv/*'
git push --force origin main
```

## 4. Never zip these again
`.git/` (440 MB because a venv was once committed), `.venv/`, `node_modules/`, `.env`, `*.db`.
