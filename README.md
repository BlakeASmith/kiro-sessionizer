# kiro-sessionizer

Global session resume support for `kiro-cli`

`kiro-cli` supports resuming sessions by `kiro-cli chat --resume` or `kiro-cli chat --resume-picker` however it only shows sessions that were 
started in the current directory. Since it is difficult to remember which directory a session was started in, having support for global session
search and resume would be nice. Thus, this repo was born. `kiro-sessionizer` reads the `sqlite` database which `kiro-cli` uses to track session
data and provides you with a fuzzy-finder selection experience to resume any session no matter where it was started.

## Usage

```sh
kiro-sessionizer
```

This opens `fzf` with a list of all available sessions. Select one to automatically navigate to its working directory and resume that specific session.

### Subcommands

- `timeline`: Show sessions grouped by date (TODAY, YESTERDAY, etc.).
- `report`: Generate a daily activity report summarizing work across all projects.
- `new`: Interactively select a project directory to start a fresh `kiro-cli chat` session.
- `continue [--project <query>]`: Resume the most recent session, optionally filtered by project name.
- `search <query>`: Search session transcripts and resume a matching session.
- `stats`: Show session statistics (total sessions, message counts, model usage).
- `backup <dest_dir>`: Dump sessions to Markdown files.

### Interactive Shortcuts (in `fzf`)

- `ctrl-f`: **Fork** the selected session (duplicate it and refresh the list).
- `ctrl-x`: **Delete** the selected session(s).
- `tab`: Select multiple sessions for deletion.

### Backing up Sessions

You can dump all of your session transcripts into Markdown files using the `backup` subcommand. The command will recreate your file paths within the destination directory and populate the `.md` files with YAML frontmatter containing metadata about the session.

```sh
kiro-sessionizer backup /path/to/destination/dir
```

You can optionally dump a single specific session by passing its ID:

```sh
kiro-sessionizer backup /path/to/destination/dir --session-id "my_session_id"
```

## Installation

```sh
git clone https://github.com/<username>/kiro-global-session-picker.git
cd kiro-global-session-picker
pip install -e .
```

### Dependencies

- `fzf` — [Install instructions](https://github.com/junegunn/fzf#installation)
- `kiro-cli` — [Install instructions](https://kiro.dev/docs/cli/installation/)

## How does it work? 

`kiro-cli` uses a SQLite database to track session state. When you run `kiro-cli chat --resume`, it resumes the most recent session from the current working directory.

`kiro-sessionizer` reads the same SQLite database directly and displays all sessions across all directories. Once you select a session via `fzf`, it automatically:
1. Updates the session timestamp in the database to make it the most recent
2. Changes to that session's working directory
3. Runs `kiro-cli chat --resume` to resume that specific session
