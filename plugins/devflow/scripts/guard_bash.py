#!/usr/bin/env python3
"""PreToolUse(Bash): one guard for every shell rule, so decisions combine in one place
(deny > ask > allow) instead of racing across parallel hooks.

Rules (see README for the rationale of each):
  git   deny  force-push (--force, --force-with-lease, --mirror, +refspec), push to or
              deletion of the protected branch, commit on it, --no-verify / commit -n,
              rebase / pull --rebase, -c core.hooksPath, gh pr merge --admin
        ask   destructive local ops (reset --hard, clean, checkout -- / . / -f, restore,
              switch -f, branch -D, stash drop/clear, worktree remove -f, filter-branch),
              merges (git merge, gh pr merge), non-GET gh api calls, deleting another
              remote branch, a push that adds secret-looking files (public repos)
  deps  ask   uv add/remove, pip install, npm/pnpm/yarn/bun/poetry add|install <pkg> ...
  spec        bare / unpinned `openspec` is rewritten to the pinned CLI; a lone read-only
              call is allowed, anything else asks
  cloud ask   cdk deploy/destroy/..., aws write calls, terraform apply/destroy, sam deploy
        deny  aws --region other than the project's region
  env   ask   any command that touches a .env file

This is a guardrail against accidents, not a security boundary: GitHub rulesets and CI
are the authoritative gates.
"""
from __future__ import annotations

import os
import re
import shlex
import sys
from dataclasses import dataclass, field
from pathlib import Path
from typing import Dict, List, Optional, Set

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import devflow_common as dc  # noqa: E402

RANK = {None: 0, "allow": 1, "ask": 2, "deny": 3}


@dataclass
class Result:
    decision: Optional[str] = None
    reasons: List[str] = field(default_factory=list)
    new_command: Optional[str] = None

    def add(self, decision: str, reason: str) -> None:
        if RANK[decision] > RANK[self.decision]:
            self.decision = decision
        if reason not in self.reasons:
            self.reasons.append(reason)


# ---------------------------------------------------------------- shell parsing

class ParseError(Exception):
    pass


def _normalize(cmd: str) -> str:
    """Turn unquoted newlines and backticks into ';' so each line is its own segment."""
    out, quote, i = [], None, 0
    while i < len(cmd):
        c = cmd[i]
        if c == "\\" and quote != "'" and i + 1 < len(cmd):
            if cmd[i + 1] == "\n":  # line continuation
                i += 2
                continue
            out.append(cmd[i:i + 2])
            i += 2
            continue
        if quote:
            if c == quote:
                quote = None
            elif c == "`" and quote == '"':
                c = ";"
        elif c in "'\"":
            quote = c
        elif c in "\n`":
            c = ";"
        out.append(c)
        i += 1
    return "".join(out)


def split_segments(cmd: str) -> List[List[str]]:
    lex = shlex.shlex(_normalize(cmd), posix=True, punctuation_chars=";&|()")
    lex.whitespace_split = True
    lex.commenters = ""
    segments: List[List[str]] = [[]]
    try:
        for tok in lex:
            if tok and all(ch in ";&|()" for ch in tok):
                segments.append([])
            else:
                segments[-1].append(tok)
    except ValueError as exc:  # unbalanced quotes
        raise ParseError(str(exc)) from exc
    return [s for s in segments if s]


WRAPPERS_NO_ARG = {"sudo", "command", "builtin", "exec", "time", "nohup", "noglob"}
SHELLS = {"bash", "sh", "zsh", "dash", "ksh"}
ASSIGNMENT = re.compile(r"^[A-Za-z_][A-Za-z0-9_]*=")
RUNNER_OPTS_WITH_VALUE = {"--with", "--with-requirements", "--with-editable", "--group", "--extra",
                          "--python", "-p", "--package", "--directory", "--project", "--env-file",
                          "--index", "--from", "-e", "--env"}


def unwrap(tokens: List[str]) -> List[str]:
    """Strip env assignments and wrapper commands so tokens[0] is the real program."""
    toks = list(tokens)
    while toks:
        head = os.path.basename(toks[0])
        if ASSIGNMENT.match(toks[0]):
            toks = toks[1:]
        elif head in WRAPPERS_NO_ARG:
            toks = toks[1:]
            while toks and toks[0].startswith("-"):
                toks = toks[1:]
        elif head == "env":
            toks = toks[1:]
            while toks and (toks[0].startswith("-") or ASSIGNMENT.match(toks[0])):
                toks = toks[1:]
        elif head in ("uv", "poetry", "pipenv", "pdm", "hatch") and len(toks) > 1 and toks[1] == "run":
            # `uv run <cmd>` runs <cmd>: skip the runner and its own options.
            toks = toks[2:]
            while toks and toks[0].startswith("-"):
                flag = toks[0]
                toks = toks[1:]
                if flag in RUNNER_OPTS_WITH_VALUE and toks:
                    toks = toks[1:]
        elif head in ("timeout", "nice", "xargs"):
            toks = toks[1:]
            while toks and toks[0].startswith("-"):
                flag = toks[0]
                toks = toks[1:]
                if flag in ("-n", "-s", "-k", "-I", "-P", "-L", "-d") and toks:
                    toks = toks[1:]
            if head == "timeout" and toks:  # the duration
                toks = toks[1:]
        else:
            break
    return toks


def expand_nested(tokens: List[str], depth: int = 0) -> List[List[str]]:
    """bash -c '...' and eval '...' run another command line: parse it too."""
    toks = unwrap(tokens)
    if not toks or depth > 3:
        return [toks] if toks else []
    head = os.path.basename(toks[0])
    inner: Optional[str] = None
    if head in SHELLS:
        for i, t in enumerate(toks[1:], 1):
            if t.startswith("-") and "c" in t.lstrip("-") and not t.startswith("--"):
                inner = toks[i + 1] if i + 1 < len(toks) else ""
                break
    elif head == "eval":
        inner = " ".join(toks[1:])
    if inner is None:
        return [toks]
    result: List[List[str]] = []
    for seg in split_segments(inner):
        result.extend(expand_nested(seg, depth + 1))
    return result


def short_flags(args: List[str], takes_value: str = "") -> Set[str]:
    """Letters in short-option clusters (-fu -> {f,u}). A letter in `takes_value`
    consumes the rest of its cluster or the next token, so -mnew is not -m -n -e -w."""
    flags: Set[str] = set()
    skip_next = False
    for a in args:
        if skip_next:
            skip_next = False
            continue
        if a == "--":
            break
        if len(a) < 2 or a[0] != "-" or a[1] == "-":
            continue
        for j, ch in enumerate(a[1:]):
            flags.add(ch)
            if ch in takes_value:
                if j == len(a) - 2:
                    skip_next = True
                break
    return flags


def has_long(args: List[str], *names: str) -> bool:
    for a in args:
        if a == "--":
            return False
        for n in names:
            if a == n or a.startswith(n + "="):
                return True
    return False


def positionals(args: List[str], value_opts: Set[str] = frozenset()) -> List[str]:
    out, skip = [], False
    for a in args:
        if skip:
            skip = False
            continue
        if a in value_opts:
            skip = True
            continue
        if a.startswith("-") and a != "-":
            continue
        out.append(a)
    return out


# ---------------------------------------------------------------- context

@dataclass
class Ctx:
    cwd: Path
    root: Path
    cfg: Dict[str, str]

    @property
    def protected(self) -> str:
        return self.cfg.get("PROTECTED_BRANCH") or "main"


def _strip_heads(ref: str) -> str:
    for prefix in ("refs/heads/", "heads/"):
        if ref.startswith(prefix):
            return ref[len(prefix):]
    return ref


# ---------------------------------------------------------------- git

GIT_GLOBAL_WITH_ARG = {"-C", "-c", "--git-dir", "--work-tree", "--namespace", "--config-env",
                       "--super-prefix", "--exec-path"}
SECRET_FILE = re.compile(r"(^|/)\.env($|\.)|credential|secret|\.pem$|\.key$|\.p12$|"
                         r"service[-_]?account.*\.json$|id_(rsa|ed25519|ecdsa)$", re.I)


def check_git(args: List[str], ctx: Ctx, res: Result) -> None:
    i, cdir, configs = 0, None, []
    while i < len(args) and args[i].startswith("-"):
        a = args[i]
        if a in GIT_GLOBAL_WITH_ARG:
            val = args[i + 1] if i + 1 < len(args) else ""
            if a == "-C":
                cdir = val
            elif a in ("-c", "--config-env"):
                configs.append(val)
            i += 2
            continue
        i += 1
    if any(c.lower().startswith("core.hookspath") for c in configs):
        res.add("deny", "git -c core.hooksPath overrides the repo's git hooks.")
    if i >= len(args):
        return
    sub, rest = args[i], args[i + 1:]
    repo = ctx.cwd / cdir if cdir else ctx.cwd
    branch = dc.current_branch(repo)
    prot = ctx.protected

    if has_long(rest, "--no-verify"):
        res.add("deny", "--no-verify skips checks; fix the failure instead.")

    if sub == "commit":
        if "n" in short_flags(rest, takes_value="mFcCtS"):
            res.add("deny", "git commit -n is --no-verify; fix the failure instead.")
        if branch == prot:
            res.add("deny", f"Never commit on {prot}. Create a feature branch first (/devflow:new-branch).")
    elif sub == "push":
        check_push(rest, ctx, res, repo, branch)
    elif sub == "rebase":
        if not has_long(rest, "--abort", "--quit", "--show-current-patch"):
            res.add("deny", "No rebasing unless the user explicitly asks; if they did, they run it themselves.")
    elif sub == "pull":
        if (has_long(rest, "--rebase") and not has_long(rest, "--rebase=false")) or "r" in short_flags(rest):
            res.add("deny", "git pull --rebase rewrites history; use a plain git pull (merge).")
    elif sub == "merge":
        if not has_long(rest, "--abort", "--quit"):
            res.add("ask", f"Merge is the human gate: needs explicit user confirmation (branch: {branch or '?'}).")
    elif sub == "reset":
        if has_long(rest, "--hard", "--merge", "--keep"):
            res.add("ask", "git reset --hard discards uncommitted work.")
    elif sub == "clean":
        if "n" not in short_flags(rest) and not has_long(rest, "--dry-run"):
            res.add("ask", "git clean deletes untracked files permanently.")
    elif sub == "checkout":
        if "--" in rest or "." in rest or "f" in short_flags(rest, "bBo") or has_long(rest, "--force", "--ours", "--theirs"):
            res.add("ask", "This git checkout overwrites working-tree files and can discard uncommitted work.")
    elif sub == "restore":
        staged = has_long(rest, "--staged") or "S" in short_flags(rest, "s")
        worktree = has_long(rest, "--worktree") or "W" in short_flags(rest, "s")
        if worktree or not staged:
            res.add("ask", "git restore discards uncommitted changes in the working tree.")
    elif sub == "switch":
        if has_long(rest, "--discard-changes", "--force") or "f" in short_flags(rest, "cC"):
            res.add("ask", "git switch --discard-changes/-f throws away local changes.")
    elif sub == "branch":
        flags = short_flags(rest)
        deleting = "D" in flags or "d" in flags or has_long(rest, "--delete")
        forced = "D" in flags or "f" in flags or has_long(rest, "--force")
        if deleting and (forced or prot in positionals(rest)):
            res.add("ask", "Force-deleting a branch can lose unmerged commits.")
    elif sub == "stash":
        if rest and rest[0] in ("drop", "clear"):
            res.add("ask", f"git stash {rest[0]} deletes stashed work permanently.")
    elif sub == "worktree":
        if rest and rest[0] == "remove" and ("f" in short_flags(rest) or has_long(rest, "--force")):
            res.add("ask", "git worktree remove --force can delete uncommitted work.")
    elif sub in ("filter-branch", "filter-repo"):
        res.add("ask", f"git {sub} rewrites history.")
    elif sub == "update-ref":
        if "d" in short_flags(rest):
            res.add("ask", "git update-ref -d deletes a ref.")
    elif sub == "config":
        if any(a.lower() == "core.hookspath" for a in rest) and not has_long(rest, "--get", "--list", "--unset"):
            res.add("deny", "Changing core.hooksPath disables the repo's git hooks.")


def check_push(rest: List[str], ctx: Ctx, res: Result, repo: Path, branch: Optional[str]) -> None:
    prot = ctx.protected
    flags = short_flags(rest, takes_value="o")
    if "n" in flags or has_long(rest, "--dry-run"):
        return
    pos = positionals(rest, value_opts={"-o", "--push-option", "--repo", "--receive-pack", "--exec"})
    refspecs = pos[1:]
    force = (has_long(rest, "--force", "--force-with-lease", "--mirror") or "f" in flags
             or any(r.startswith("+") for r in refspecs))
    delete = has_long(rest, "--delete") or "d" in flags or any(r.startswith(":") for r in refspecs)
    targets: List[str] = []
    for r in refspecs:
        r = r.lstrip("+")
        dst = r.split(":", 1)[1] if ":" in r else r
        if dst in ("HEAD", "@", ""):
            dst = branch or ""
        targets.append(_strip_heads(dst))
    if not refspecs:
        targets.append(branch or "")
    if has_long(rest, "--all", "--mirror"):
        targets.append(prot)

    if force:
        res.add("deny", "Force-push is not allowed (it rewrites published history).")
    if prot in targets:
        if delete:
            res.add("deny", f"Never delete the protected branch {prot}.")
        else:
            res.add("deny", f"Never push to {prot}. Land changes through a PR (/devflow:land-branch).")
    elif delete:
        res.add("ask", "Deleting a remote branch: needs explicit user confirmation.")
    if dc.cfg_bool(ctx.cfg, "PUBLIC_REPO") and not force and prot not in targets:
        base = dc.git(repo, "merge-base", f"origin/{prot}", "HEAD")
        if base:
            added = dc.git(repo, "diff", "--name-only", "--diff-filter=A", base, "HEAD") or ""
            risky = [f for f in added.splitlines() if SECRET_FILE.search(f)]
            if risky:
                res.add("ask", "Public repo: this push adds secret-looking files: " + ", ".join(risky[:10]))


# ---------------------------------------------------------------- gh

def check_gh(args: List[str], ctx: Ctx, res: Result) -> None:
    if len(args) < 2:
        return
    group, action, rest = args[0], args[1], args[2:]
    if group == "pr" and action == "merge":
        if has_long(rest, "--admin"):
            res.add("deny", "gh pr merge --admin bypasses the required CI check.")
        else:
            res.add("ask", "Merge is the human gate: needs explicit user confirmation.")
    elif group == "api":
        a = args[1:]
        method = "GET"
        for j, tok in enumerate(a):
            if tok in ("-X", "--method") and j + 1 < len(a):
                method = a[j + 1].upper()
            elif tok.startswith("--method="):
                method = tok.split("=", 1)[1].upper()
            elif tok.startswith("-X") and len(tok) > 2:
                method = tok[2:].upper()
        writes_body = any(t in ("-f", "-F", "--field", "--raw-field", "--input") or
                          t.startswith(("--field=", "--raw-field=", "--input=")) for t in a)
        explicit = any(t in ("-X", "--method") or t.startswith(("-X", "--method=")) for t in a)
        graphql_read = "graphql" in a and not any("mutation" in t for t in a)
        if method == "GET" and writes_body and not explicit and not graphql_read:
            method = "POST"
        if method != "GET":
            res.add("ask", f"gh api {method} changes GitHub state: needs explicit user confirmation.")
    elif (group, action) in {("repo", "delete"), ("repo", "archive"), ("repo", "rename"), ("repo", "edit"),
                             ("release", "delete"), ("secret", "set"), ("secret", "delete"),
                             ("secret", "remove"), ("variable", "set"), ("variable", "delete"),
                             ("ruleset", "delete"), ("workflow", "disable")}:
        res.add("ask", f"gh {group} {action} changes repository settings or secrets.")


# ---------------------------------------------------------------- dependencies

def check_deps(prog: str, args: List[str], res: Result) -> None:
    reason = "Dependency change: needs user approval (ask before adding, removing or upgrading a dependency)."
    upgrade = has_long(args, "--upgrade", "--upgrade-package") or bool({"U", "P"} & short_flags(args, "P"))
    if prog == "uv":
        if args[:1] in (["add"], ["remove"]) or args[:2] in (["pip", "install"], ["pip", "uninstall"]):
            res.add("ask", reason)
        elif args[:1] in (["lock"], ["sync"]) and upgrade:
            res.add("ask", reason)
    elif prog in ("pip", "pip3") or re.match(r"^python[0-9.]*$", prog):
        a = args[2:] if args[:2] == ["-m", "pip"] else (args if prog.startswith("pip") else None)
        if a is not None and a[:1] in (["install"], ["uninstall"]):
            res.add("ask", reason)
    elif prog == "npm":
        if args[:1] and args[0] in ("update", "up", "upgrade"):
            res.add("ask", reason)
        elif args[:1] and args[0] in ("install", "i", "add", "uninstall", "remove", "rm", "un"):
            if positionals(args[1:]):
                res.add("ask", reason)
    elif prog in ("pnpm", "yarn", "bun"):
        if args[:1] and args[0] in ("add", "remove", "rm", "up", "update", "upgrade"):
            res.add("ask", reason)
    elif prog == "poetry":
        if args[:1] in (["add"], ["remove"], ["update"]) or (args[:1] == ["lock"] and "--regenerate" in args):
            res.add("ask", reason)


# ---------------------------------------------------------------- cloud

AWS_GLOBAL_WITH_ARG = {"--region", "--profile", "--output", "--query", "--endpoint-url",
                       "--cli-read-timeout", "--cli-connect-timeout", "--color", "--ca-bundle",
                       "--cli-binary-format"}
AWS_READ_OPS = re.compile(r"^(describe|get|list|head|batch-get|search|lookup|validate|estimate|"
                          r"simulate|filter|tail|scan|query|select|test)(-|$)")
AWS_READ_SERVICES = {"sts", "configure", "login", "sso", "sso-oidc", "help"}
CDK_WRITE = {"deploy", "destroy", "bootstrap", "import", "migrate", "rollback", "watch", "gc", "refactor"}


def check_cloud(prog: str, args: List[str], ctx: Ctx, res: Result) -> None:
    cloud = ctx.cfg.get("CLOUD", "").lower()
    if prog in ("npx", "pnpx") and args and args[0] in ("cdk", "aws-cdk"):
        prog, args = "cdk", args[1:]
    if prog == "cdk" and "aws" in cloud:
        sub = next((a for a in args if not a.startswith("-")), "")
        if sub in CDK_WRITE:
            res.add("ask", f"cdk {sub} creates, changes or deletes cloud resources: needs explicit approval.")
    elif prog == "aws" and "aws" in cloud:
        region, pos, j = None, [], 0
        while j < len(args):
            a = args[j]
            if a in AWS_GLOBAL_WITH_ARG:
                if a == "--region" and j + 1 < len(args):
                    region = args[j + 1]
                j += 2
                continue
            if a.startswith("--region="):
                region = a.split("=", 1)[1]
            elif not a.startswith("-"):
                pos.append(a)
            j += 1
        want = ctx.cfg.get("AWS_REGION", "")
        if want and region and region != want:
            res.add("deny", f"This project only uses AWS region {want} (got --region {region}).")
        service = pos[0] if pos else ""
        op = pos[1] if len(pos) > 1 else ""
        if not service or service in AWS_READ_SERVICES or AWS_READ_OPS.match(op):
            return
        if service == "s3" and op in ("ls", "presign"):
            return
        if "--dry-run" in args:
            return
        res.add("ask", f"aws {service} {op} may change cloud resources or cost money: needs explicit approval.")
    elif prog == "terraform" and args[:1] and args[0] in ("apply", "destroy", "import"):
        res.add("ask", f"terraform {args[0]} changes infrastructure: needs explicit approval.")
    elif prog == "sam" and args[:1] and args[0] in ("deploy", "delete", "sync"):
        res.add("ask", f"sam {args[0]} changes infrastructure: needs explicit approval.")


# ---------------------------------------------------------------- recursive deletes

def _temp_dirs() -> List[str]:
    import tempfile
    dirs = {"/tmp", "/var/tmp", tempfile.gettempdir(), os.environ.get("TMPDIR", "")}
    return [os.path.realpath(d) for d in dirs if d]


def check_rm(args: List[str], ctx: Ctx, res: Result) -> None:
    flags = short_flags(args)
    if not ({"r", "R"} & flags or has_long(args, "--recursive")):
        return
    root = os.path.realpath(str(ctx.root))
    home = os.path.realpath(os.path.expanduser("~"))
    temps = _temp_dirs()
    for p in positionals(args):
        if "$" in p:
            res.add("ask", f"rm -r on {p}: the path depends on a variable; please confirm it.")
            continue
        target = os.path.expanduser(p)
        if not os.path.isabs(target):
            target = os.path.join(str(ctx.cwd), target)
        t = os.path.normpath(target.rstrip("*") or "/")
        if t in ("/", home) or (home.startswith(t + os.sep)):
            res.add("deny", f"rm -r on {p} would delete the filesystem root or your home directory.")
        elif any(t == d or t.startswith(d + os.sep) for d in temps if not root.startswith(d + os.sep)):
            continue
        elif t == root or not t.startswith(root + os.sep):
            res.add("ask", f"rm -r on {p} reaches outside the project (or is the project root).")
        elif t == os.path.join(root, ".git") or t.startswith(os.path.join(root, ".git") + os.sep):
            res.add("ask", f"rm -r on {p} deletes git history.")


# ---------------------------------------------------------------- secrets on disk

ENV_FILE = re.compile(r"^\.env(\.(?!example$|sample$|template$|dist$)[^/]+)?$")


def check_env_files(tokens: List[str], res: Result) -> None:
    for t in tokens:
        for part in re.split(r"[=:]", t):
            if ENV_FILE.match(os.path.basename(part.rstrip("/"))):
                res.add("ask", f"This command touches {part}, which holds secrets.")
                return


# ---------------------------------------------------------------- openspec pin

OPENSPEC_CALL = re.compile(
    r"(?P<pre>^|[;&|(\n`]\s*|\$\(\s*)"
    r"(?P<call>npx\s+(?:(?:-y|--yes)\s+)?(?:@fission-ai/)?openspec(?:@[\w.\-]+)?|openspec)"
    r"(?=\s|$|[;&|)])"
)
OPENSPEC_READ_ONLY = {"list", "show", "validate", "status", "instructions", "view", "--version", "--help", "help"}


def is_openspec(prog: str, args: List[str]) -> Optional[List[str]]:
    """Return the openspec arguments if this segment runs the openspec CLI."""
    if prog == "openspec":
        return args
    if prog in ("npx", "pnpx"):
        a = [x for x in args if x not in ("-y", "--yes")]
        if a and re.match(r"^(@fission-ai/)?openspec(@[\w.\-]+)?$", a[0]):
            return a[1:]
    return None


def pin_openspec(command: str, version: str) -> str:
    pinned = f"npx --yes @fission-ai/openspec@{version}"
    return OPENSPEC_CALL.sub(lambda m: m.group("pre") + pinned, command)


# ---------------------------------------------------------------- main logic

def evaluate(command: str, ctx: Ctx) -> Result:
    res = Result()
    try:
        raw_segments = split_segments(command)
        segments: List[List[str]] = []
        for seg in raw_segments:
            segments.extend(expand_nested(seg))
    except ParseError:
        res.add("ask", "Couldn't parse this command safely; please confirm it.")
        return res

    openspec_segments, read_only = 0, True
    for toks in segments:
        if not toks:
            continue
        prog, args = os.path.basename(toks[0]), toks[1:]
        check_env_files(toks, res)
        if prog == "git":
            check_git(args, ctx, res)
        elif prog == "gh":
            check_gh(args, ctx, res)
        elif prog == "rm":
            check_rm(args, ctx, res)
        check_deps(prog, args, res)
        check_cloud(prog, args, ctx, res)
        os_args = is_openspec(prog, args)
        if os_args is not None:
            openspec_segments += 1
            sub = next((a for a in os_args if not a.startswith("-")), os_args[0] if os_args else "")
            read_only = read_only and sub in OPENSPEC_READ_ONLY

    version = ctx.cfg.get("OPENSPEC_VERSION", "")
    if version and openspec_segments:
        new = pin_openspec(command, version)
        if new != command:
            res.new_command = new
        if read_only and len(segments) == 1:
            res.add("allow", f"Read-only openspec call (pinned to {version}).")
        elif res.new_command:
            res.add("ask", f"Rewrote openspec to the pinned CLI {version}; confirm this non-read-only call.")
    return res


def main() -> int:
    payload = dc.read_payload()
    if payload.get("tool_name") != "Bash":
        return 0
    tool_input = payload.get("tool_input") or {}
    command = tool_input.get("command") or ""
    root = dc.project_dir(payload)
    cwd = Path(payload.get("cwd") or root)
    ctx = Ctx(cwd=cwd, root=root, cfg=dc.load_config(root))
    res = evaluate(command, ctx)
    if res.decision is None:
        return 0
    reason = " ".join(res.reasons)
    if res.decision in ("deny", "ask"):
        dc.log_event(root, "guard_bash", res.decision, reason, command)
    updated = None
    if res.new_command and res.decision != "deny":
        updated = dict(tool_input, command=res.new_command)
    dc.emit_pretool(res.decision, reason, updated)
    return 0


if __name__ == "__main__":
    try:
        sys.exit(main())
    except Exception as exc:  # never break the session because of a guard bug
        print(f"devflow guard_bash internal error (allowed through): {exc}", file=sys.stderr)
        sys.exit(1)
