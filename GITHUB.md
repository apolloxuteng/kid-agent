# Pushing code to GitHub

Use this as a reference so you don’t have to remember the commands.

---

## If the repo is already set up

You’ve already run `git init` and `git remote add origin ...`. To save and push your latest changes:

```bash
cd "/Users/jozhou/Documents/local llm server/kid-agent"
git status
git add .
git commit -m "Your short description of what changed"
git push
```

- **`git status`** — See what files changed and what will be committed.
- **`git add .`** — Stage all changes (`.gitignore` keeps venv, etc. out).
- **`git commit -m "..."`** — Create a commit with that message.
- **`git push`** — Send your commits to GitHub.

---

## If you haven’t connected to GitHub yet

1. **Create the repo on GitHub**  
   Go to [github.com/new](https://github.com/new). Choose a name (e.g. `kid-chat`), create the repo, and **do not** add a README, .gitignore, or license.

2. **In Terminal, from the project folder:**

```bash
cd "/Users/jozhou/Documents/local llm server/kid-agent"
git init
git add .
git commit -m "Initial commit: Kid Chat app (backend + iOS)"
git branch -M main
git remote add origin https://github.com/YOUR_USERNAME/kid-chat.git
git push -u origin main
```

Replace **YOUR_USERNAME** and **kid-chat** with your GitHub username and repo name.

---

## Quick reference

| What you want   | Command |
|-----------------|--------|
| See what changed | `git status` |
| Stage all files  | `git add .` |
| Commit with a message | `git commit -m "message"` |
| Push to GitHub  | `git push` |
| First-time push | `git push -u origin main` |

---

## If `git push` asks for login

- GitHub no longer accepts account passwords for Git over HTTPS.
- Use a **Personal Access Token** as the password:  
  GitHub → **Settings** → **Developer settings** → **Personal access tokens** → generate a token (with `repo` scope), then paste it when Git asks for a password.
- Or set up **SSH** and use an SSH remote URL instead of `https://`.
