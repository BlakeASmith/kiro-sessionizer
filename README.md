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

### Backing up Sessions

You can dump all of your session transcripts into Markdown files using the `backup` subcommand. The command will recreate your file paths within the destination directory and populate the `.md` files with YAML frontmatter containing metadata about the session.

```sh
kiro-sessionizer backup /path/to/destination/dir
```

You can optionally dump a single specific session by passing its ID:

```sh
kiro-sessionizer backup /path/to/destination/dir --session-id "my_session_id"
```

### Navigation

You can quickly jump to any project directory stored in your history using the `jump` subcommand. This opens `fzf` with a list of unique project paths, ordered by recency.

```sh
kiro-sessionizer jump
```

### Maintenance

Keep your database clean by removing old or very short (likely accidental) sessions using the `prune` subcommand.

```sh
# Dry run: see what would be deleted
kiro-sessionizer prune --dry-run

# Actual prune (default: >30 days old OR <2 messages)
kiro-sessionizer prune --days 60 --min-messages 3
```

### Statistics

The `stats` command provides insights into your usage, including a list of the files you discuss most frequently with the AI.

```sh
kiro-sessionizer stats
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
