---
name: project-environment
description: Run project commands on a connected Linux host using the project's home profile and shell login environment.
---

# Project command environment

Use the RemoteOpsAI SSH and Linux command tools. Do not use ad hoc SSH scripts or print
profile-file contents; profile files may contain sensitive values.

## Workflow

1. Connect to the intended Linux host with `connect_remote_host` and confirm which project
   the user wants to operate on.
2. If the prompt gives an exact project profile filename, pass its basename as
   `profile_file` to `linux_run_command`. The runner accepts only a simple filename, resolves
   it under the remote user's `$HOME`, and never accepts a path outside that directory. If no
   filename is given, list candidate names without reading their contents:

   ```sh
   for f in "$HOME"/.*profile*; do
     [ -f "$f" ] && printf '%s\n' "${f##*/}"
   done
   ```

   Match a candidate only when the project identity is clear. If several files could match,
   ask the user which one to use; do not guess or source every matching file.
3. Use `linux_run_command` with its default `login_shell=true`. The command runner uses the
   SSH account's configured shell directly (not a PATH lookup for `bash` or `sh`) and, on
   each invocation, sources the requested project profile first, then the applicable shell
   profile: Bash uses the first readable of `.bash_profile`,
     `.bash_login`, `.profile`, or `.bashrc`; Zsh uses `.zprofile`, then `.profile`;
     other POSIX shells use `.profile`.
   After profile loading, if either `bash` or `sh` is still missing from `PATH`, the runner
   prepends `/usr/bin:/bin` for that command and warns if either shell remains unavailable.
   If the requested project profile is absent or unreadable, the tool warns and continues
   with the shell profile. The profile file is sourced as shell code.
4. If you need to verify the environment, query only relevant values after profiles have
   loaded. For example:

   ```sh
   printf 'HOME=%s\nSHELL=%s\nPATH=%s\n' "$HOME" "$SHELL" "$PATH"
   command -v StatusCHP
   ```

   Do not dump the full environment with `env` or `printenv`; it may expose passwords,
   tokens, or other secrets. Avoid reading profile file contents unless specifically needed
   and authorized.
5. Run the requested command with `linux_run_command`. Every call starts a fresh remote
   command shell and sources the selected files again; environment changes do not persist
   between calls. Use `login_shell=false` only when the command must not load shell login
   profiles; an explicitly supplied `profile_file` is still loaded.
6. The tool does not allocate a PTY or accept interactive input. For commands that prompt,
   use a documented non-interactive flag when available, or explain that the command needs
   a true interactive terminal. Do not claim an interactive command completed when it did
   not.

Review commands before execution. Ask before destructive or state-changing operations, and
do not expose secrets that a command or profile may emit.
