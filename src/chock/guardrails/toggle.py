"""The guardrails toggle file and its lookup. Stdlib only: shipped verbatim in every merged plugin as its hook wrapper.

`.chock/guardrails.json` (repo; else `~/.chock/guardrails.json`) is all on when absent, invalid or unlike its record.
`--bundle <b> --member <id> <adapter> [args...]`: off runs the adapter with no args. `--verify <adapter>`: a Stop is
refused while a toggle file in its `cwd` or any workspace root loosened or changed during the session.
`--session-start <adapter>`: binds the session to the files it sees and lists every member that is off.

An `off` is honoured only by a session that started after its file's record last changed: a session is bound to the
files it first saw (the session log's id names it), and once one differs every member is on for the rest of it. This
is not a security boundary against an agent running as the person: that agent can write both the file and its record.
"""

from __future__ import annotations

import contextlib
import hashlib
import importlib.util
import io
import json
import os
import re
import runpy
import sys
import time
from pathlib import Path

try:  # beside this wrapper in a merged plugin; inside the chock package everywhere else
    from chock_bundle_log import log_off
except ImportError:
    from chock.guardrails.chock_bundle_log import log_off

FILENAME = ".chock/guardrails.json"
VERSION = 1
ON, OFF = "on", "off"
STATES = (ON, OFF)
NAME_RE = re.compile(r"^[a-z][a-z0-9-]{2,63}$")
REPO, USER = "repo", "user"
_TOP_KEYS = frozenset({"version", "bundles"})
_ARGC = 5
#: The record `chock bundle` keeps of the file it last wrote, beside it under the engine's own state folder.
RECORD_PARTS = ("state", "guardrails.sha256")
VERIFY = "--verify"
SESSION_START = "--session-start"
#: The built-in self-protection: never a catalog member, so an entry naming it switches nothing.
PROTECT_ID = "chock-guardrails-protect"
#: The session log's id keys (`session_id`, Copilot's `sessionId`), then the conversation id Cursor and Antigravity send instead.
SESSION_ID_KEYS = ("session_id", "sessionId", "conversation_id", "conversationId")
SESSION_ID_MAX = 128
SESSION_UNKNOWN = "unknown"
BOUND_NAME = "guardrails-session-{}.json"
BOUND_PRUNE_SECONDS = 7 * 24 * 3600
SOURCE_COMPACT = "compact"
_UNSEEN = [None, None]
MOVED = (
    "changed during this session, so an `off` in it applies from the next session; every guardrail stays on until then"
)
DELETED = "it was deleted after `chock bundle` wrote it"
DRIFTED = (
    "guardrails.json differs from the last `chock bundle` change; every guardrail stays on until the person "
    "re-applies it or runs `chock bundle status --adopt`"
)
_VERDICT_DENY = "deny"
_BLOCKING_EXIT = 2  # the launcher's refusal too: the wrapper speaks no client's dialect
_NOTICE = (
    "chock: these guardrails are switched off for this session (set before it started; `chock bundle status` shows "
    "them):\n{listed}\nA toggle is not a security boundary against an agent running as the person; a change made "
    "during a session applies from the next one."
)


class ToggleError(ValueError):
    """A toggle file that does not say, unambiguously, which members are off."""


def user_path() -> Path:
    """The user-scope toggle file."""
    return Path.home() / FILENAME


def repo_root(start: Path) -> Path | None:
    """The repository `start` is in: the nearest folder holding `.git`, or None outside one."""
    here = Path(start).absolute()
    return next((folder for folder in (here, *here.parents) if (folder / ".git").exists()), None)


def source(start: Path) -> tuple[Path | None, str | None]:
    """(the file that governs at `start`, its scope); a broken link or a folder governs too, read as all on."""
    root = repo_root(start)
    if root is not None and os.path.lexists(root / FILENAME):
        return root / FILENAME, REPO
    user = user_path()
    return (user, USER) if os.path.lexists(user) else (None, None)


def _require_object(value: object, where: str) -> dict:
    if not isinstance(value, dict):
        msg = f"{where} must be an object, got {type(value).__name__}"
        raise ToggleError(msg)
    return value


def parse(text: str) -> dict[str, dict[str, str]]:
    """{bundle: {policy id: on|off}} from the file's text, or ToggleError saying what is wrong."""
    try:
        document = json.loads(text)
    except ValueError as exc:
        msg = f"not valid JSON ({exc})"
        raise ToggleError(msg) from exc
    _require_object(document, "the file")
    if set(document) != _TOP_KEYS:
        msg = f"the file must have exactly the keys {sorted(_TOP_KEYS)}, got {sorted(document)}"
        raise ToggleError(msg)
    version = document["version"]
    if type(version) is not int or version != VERSION:
        msg = f"version must be {VERSION}, got {version!r}"
        raise ToggleError(msg)
    bundles: dict[str, dict[str, str]] = {}
    for name, members in _require_object(document["bundles"], "'bundles'").items():
        if not NAME_RE.fullmatch(name):
            msg = f"bundle name {name!r} must match {NAME_RE.pattern}"
            raise ToggleError(msg)
        for policy_id, state in _require_object(members, f"bundle {name!r}").items():
            if not NAME_RE.fullmatch(policy_id):
                msg = f"policy id {policy_id!r} in {name!r} must match {NAME_RE.pattern}"
                raise ToggleError(msg)
            if state not in STATES:
                msg = f"{name}/{policy_id} is {state!r}; a state is 'on' or 'off', never a pattern or a rule"
                raise ToggleError(msg)
        bundles[name] = dict(members)
    return bundles


def read(path: Path) -> dict[str, dict[str, str]]:
    """The parsed file at `path`; ToggleError for anything unreadable, so it reads as all on."""
    try:
        text = path.read_text(encoding="utf-8")
    except (OSError, UnicodeDecodeError) as exc:
        msg = f"cannot be read ({type(exc).__name__})"
        raise ToggleError(msg) from exc
    return parse(text)


def load(start: Path) -> tuple[Path | None, str | None, dict[str, dict[str, str]], str | None]:
    """(governing file, scope, toggles, warning). An invalid file yields no toggles: all on, plus the warning."""
    path, scope = source(start)
    if path is None:
        return None, None, {}, None
    if drift(path):
        return path, scope, {}, f"{path}: {DRIFTED}"
    try:
        return path, scope, read(path), None
    except ToggleError as exc:
        return path, scope, {}, f"{path} is ignored, every guardrail stays on: {exc}"


def state(toggles: dict[str, dict[str, str]], bundle: str, member: str) -> str:
    """A member's state: off only when its own entry says so."""
    return OFF if toggles.get(bundle, {}).get(member) == OFF else ON


def _wheres(payload: bytes) -> list[Path]:
    """Where the agent works: `cwd` (goose: `working_dir`), then each workspace root (Cursor's `/C:/x` is `C:/x`)."""
    try:
        raw = json.loads(payload.decode("utf-8-sig"))
        roots = [r for k in ("workspace_roots", "workspacePaths") if isinstance(raw.get(k), list) for r in raw[k]]
        named = [raw.get("cwd") or raw.get("working_dir"), *roots]
    except Exception:  # noqa: BLE001 -- an unreadable payload is the adapter's to refuse
        named = []
    folders = [t[1:] if t[:1] == "/" and t[2:3] == ":" and t[1:2].isalpha() else t for t in named if isinstance(t, str)]
    return [Path(folder) for folder in folders if folder] or [Path.cwd()]


def record_path(toggle_file: Path) -> Path:
    """Where `chock bundle` records the sha256 of the toggle file it wrote."""
    return Path(toggle_file).parent.joinpath(*RECORD_PARTS)


def digest(path: Path) -> str | None:
    """The sha256 of a file's bytes; None when nothing is there, `unreadable` when something is but cannot be read."""
    if not os.path.lexists(path):
        return None
    try:
        return hashlib.sha256(Path(path).read_bytes()).hexdigest()
    except OSError:
        return "unreadable"


def recorded(toggle_file: Path) -> str | None:
    """The sha256 `chock bundle` last recorded for `toggle_file`, or None when it recorded none."""
    try:
        return record_path(toggle_file).read_text(encoding="utf-8").strip() or None
    except (OSError, UnicodeDecodeError):
        return None


def drift(toggle_file: Path) -> str | None:
    """Why `toggle_file` is not what `chock bundle` last wrote, or None when it is (or neither exists)."""
    now, then = digest(toggle_file), recorded(toggle_file)
    if now == then:
        return None
    if now is None:
        return DELETED
    return "`chock bundle` has no record of it" if then is None else "it was changed outside `chock bundle`"


def scopes(start: Path) -> list[Path]:
    """Every toggle file that can govern work at `start`: the repository's, then the user's."""
    root = repo_root(start)
    return [*([root / FILENAME] if root else []), user_path()]


def _document(payload: bytes) -> dict:
    """The hook payload as an object; empty when it is not one."""
    try:
        raw = json.loads(payload.decode("utf-8-sig"))
    except ValueError:
        return {}
    return raw if isinstance(raw, dict) else {}


def session_id(payload: bytes) -> str:
    """The session's id as the session log names it: a safe file stem, never empty."""
    raw = _document(payload)
    given = next((raw[key] for key in SESSION_ID_KEYS if raw.get(key)), "")
    stem = "".join(c for c in str(given) if c.isalnum() or c in "._-").lstrip(".")
    return stem[:SESSION_ID_MAX] or SESSION_UNKNOWN


def _states(starts: list[Path]) -> dict[str, list]:
    """{toggle file: [sha256 of it, its record]} for every file in scope of any of `starts`."""
    paths = dict.fromkeys(path for start in starts for path in scopes(start))
    return {str(path): [digest(path), recorded(path)] for path in paths}


def bound_path(session: str) -> Path:
    """Where a session's binding is kept: the user's engine state folder, so a `cd` in the session cannot move it."""
    return user_path().parent / "state" / BOUND_NAME.format(session)


def _keep(path: Path, states: dict[str, list], *, replace: bool) -> None:
    """Write the binding whole or not at all; without `replace`, an existing one wins. Best effort: never raises."""
    scratch = path.with_name(f"{path.name}.{os.getpid()}.tmp")
    try:
        path.parent.mkdir(parents=True, exist_ok=True)
        scratch.write_text(json.dumps(states), encoding="utf-8")
        if replace:
            os.replace(scratch, path)
            cutoff = time.time() - BOUND_PRUNE_SECONDS
            for old in path.parent.glob(BOUND_NAME.format("*")):
                if old.stat().st_mtime < cutoff:
                    old.unlink()
        else:
            os.link(scratch, path)
    except OSError:  # no binding is kept: the session then reads every file as changed
        pass
    finally:
        with contextlib.suppress(OSError):
            scratch.unlink()


def bind(starts: list[Path], session: str, *, fresh: bool) -> dict | None:
    """The files' states this session is bound to, or None when it is bound to none.

    A session start (`fresh`) binds anew. Any other first hook binds the session to what it sees, an absent file
    included, when the client names the session; one that does not stays unbound until a session start.
    """
    path = bound_path(session)
    states = _states(starts)
    if fresh or (session != SESSION_UNKNOWN and not path.exists()):
        _keep(path, states, replace=fresh)
    try:
        bound = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return None
    return bound if isinstance(bound, dict) else None


def moved(starts: list[Path], bound: dict | None) -> list[Path]:
    """Every toggle file in scope whose state is not the one the session was bound to (an unbound file always is)."""
    held = bound or {}
    return [Path(file) for file, state in _states(starts).items() if held.get(file, _UNSEEN) != state]


def _has_off(path: Path) -> bool:
    try:
        return any(s == OFF for members in read(path).values() for s in members.values())
    except ToggleError:
        return False


def switched_off(starts: list[Path]) -> list[str]:
    """One line per toggle file in scope that switches a member off: its scope, path and members."""
    governing = source(starts[0])[0]
    lines = []
    for path in dict.fromkeys(path for start in starts for path in scopes(start)):
        if not os.path.lexists(path) or drift(path):
            continue
        try:
            off = sorted(
                f"{b}/{i}" for b, ms in read(path).items() for i, s in ms.items() if s == OFF and i != PROTECT_ID
            )
        except ToggleError:
            continue
        if off:
            scope = USER if path == user_path() else REPO
            shadowed = "" if governing in (None, path) else " (not applied here: the repository's own file governs)"
            lines.append(f"{scope} ({path}){shadowed}: {', '.join(off)}")
    return lines


def handed_to_user() -> str | None:
    """Why a deleted repo file loosens: the user file that now governs switches members off, or is unvouched for."""
    user = user_path()
    if not os.path.lexists(user):
        return None
    if drift(user):
        return f"deleting it hands control to {user}, which `chock bundle` did not write"
    try:
        off = sorted(f"{b}/{i}" for b, members in read(user).items() for i, s in members.items() if s == OFF)
    except ToggleError:
        return None
    return f"deleting it hands control to {user}, which switches {', '.join(off)} off" if off else None


def turn_end_drifted(starts: list[Path], session: str | None = None) -> list[str]:
    """One line per toggle file in scope of any of `starts` that loosened or, in `session`, changed to switch a member off.

    A tightening deletion drops its record.
    """
    lines = []
    for path in dict.fromkeys(path for start in starts for path in scopes(start)):
        why = drift(path)
        if why == DELETED:
            why = None if path == user_path() else handed_to_user()
            if why is None:
                with contextlib.suppress(OSError):
                    record_path(path).unlink()
        if why:
            lines.append(f"{path}: {why}")
    if session is not None:
        listed = {line.split(": ", 1)[0] for line in lines}
        late = [p for p in moved(starts, bind(starts, session, fresh=False)) if _has_off(p) and str(p) not in listed]
        lines += [f"{path}: {MOVED}" for path in late]
    return lines


def _adapter(path: str):
    """The client's adapter loaded as a module, its `main` not yet run."""
    spec = importlib.util.spec_from_file_location("chock_adapter", path)
    if spec is None or spec.loader is None:
        msg = f"cannot load the adapter at {path}"
        raise SystemExit(msg)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def verify(argv: list[str], payload: bytes) -> None:
    """Turn-end check: the adapter (`argv`: it, `--gate <gate> --stop`) refuses a Stop while a toggle file drifted."""
    adapter, gate = _adapter(argv[0]), Path(argv[argv.index("--gate") + 1])
    wheres, session = _wheres(payload), session_id(payload)
    ledger = next((root for root in map(repo_root, wheres) if root), wheres[0])
    refuse = adapter.handle  # an entry whose shared runtime failed to load refuses every event itself

    def handle(event):
        if getattr(adapter, "_CHOCK_RUNTIME_FAULT", None) is not None:
            return refuse(event)
        lines = turn_end_drifted(wheres, session) if getattr(event, "event", "") == "stop" else []
        refusal = (
            f"chock: a guardrails toggle file was changed outside `chock bundle` or since this session started: "
            f"{'; '.join(lines)}. Only a person changes it: they re-apply it with `chock bundle on|off <policy-id>`, "
            "or review it and run `chock bundle status --adopt`; an `off` applies from the next session. "
            "The agent does not."
        )
        decision = adapter.settle_stop(event, ledger, gate, (_VERDICT_DENY, refusal), {}) if lines else None
        return adapter._spoken(decision) if decision else None

    adapter.handle = handle
    sys.argv = list(argv)
    adapter.main()


def start(argv: list[str], payload: bytes) -> None:
    """Session start: the adapter (`argv`: it) logs its heartbeat; the session is bound and told what is off."""
    adapter, wheres, session = _adapter(argv[0]), _wheres(payload), session_id(payload)
    heartbeat = adapter.handle
    resumed = _document(payload).get("source") != SOURCE_COMPACT  # a compaction continues the session it is in

    def handle(event):
        decision = heartbeat(event)
        if decision is not None or getattr(event, "event", "") != "session_start":
            return decision
        bind(wheres, session, fresh=resumed)
        listed = switched_off(wheres)
        return adapter.Decision.allow(context=_NOTICE.format(listed="\n".join(listed))) if listed else None

    adapter.handle = handle
    sys.argv = list(argv)
    adapter.main()


def wrapped(argv: list[str], payload: bytes) -> list[str]:
    """The adapter argv this member runs with: its own when on, none when off. Any doubt is on."""
    if len(argv) < _ARGC or argv[0] != "--bundle" or argv[2] != "--member":
        msg = "usage: chock_bundle.py --bundle <name> --member <id> <adapter> [args...]"
        raise SystemExit(msg)
    bundle, member, adapter, rest = argv[1], argv[3], argv[4], argv[5:]
    try:
        starts = _wheres(payload)
        governing, _scope, toggles, warning = load(starts[0])
        held = moved(starts, bind(starts, session_id(payload), fresh=False))
        if held and any(s == OFF for members in toggles.values() for s in members.values()):
            toggles, warning = {}, "; ".join(f"{path}: {MOVED}" for path in held)
    except Exception as exc:  # noqa: BLE001 -- a lookup that fails switches nothing off
        governing, toggles, warning = None, {}, f"the guardrails toggle lookup failed, every guardrail stays on: {exc}"
    if warning:
        sys.stderr.write(f"chock: {warning}\n")
    if governing is not None and state(toggles, bundle, member) == OFF:
        log_off(governing, bundle, member)
        return [adapter]
    return [adapter, *rest]


def main() -> None:
    """Hook entry: decide on or off, then run the client's adapter in this process on the same payload."""
    try:
        payload = sys.stdin.buffer.read()
        sys.stdin = io.TextIOWrapper(io.BytesIO(payload), encoding="utf-8")
        if sys.argv[1:2] == [VERIFY]:
            verify(sys.argv[2:], payload)
            return
        if sys.argv[1:2] == [SESSION_START]:
            start(sys.argv[2:], payload)
            return
        sys.argv = wrapped(sys.argv[1:], payload)
        runpy.run_path(sys.argv[0], run_name="__main__")
    except (Exception, SystemExit) as exc:  # the adapter answers its own faults; these never answered
        if isinstance(exc, SystemExit) and isinstance(exc.code, (int, type(None))):
            raise
        sys.stderr.write(f"chock: the guardrails wrapper failed ({type(exc).__name__}: {exc}), so it refuses.\n")
        sys.exit(_BLOCKING_EXIT)


if __name__ == "__main__":
    main()
