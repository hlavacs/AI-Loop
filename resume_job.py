from __future__ import annotations

import argparse
import errno
import os
import signal
import subprocess
import sys
import time


def safe_print(*args, **kwargs) -> None:
    """Print, but never die on a closed pipe.

    resume_job is often launched by the very watcher it is about to
    terminate, with stdout/stderr captured through a pipe. When that parent
    dies, the pipe closes and (with PYTHONUNBUFFERED=1) an ordinary print
    raises BrokenPipeError, aborting the resume between the kill and the
    relaunch. Output is best-effort; the resume itself must always proceed.
    """
    try:
        print(*args, **kwargs)
    except BrokenPipeError:
        pass
    except OSError as exc:
        if exc.errno != errno.EPIPE:
            raise


def _pid_alive(pid: int) -> bool:
    try:
        os.kill(pid, 0)
    except (ProcessLookupError, ValueError):
        return False
    except PermissionError:
        # The process exists but belongs to someone else; treat it as alive.
        return True
    except OSError:
        return False
    return True


def _group_has_live_member(pgid: int) -> bool:
    """Best-effort: True unless EVERY process in ``pgid``'s group is a zombie.

    A group whose members are all zombies is dead for polling purposes (no
    member will ever react to another signal), but os.killpg(pgid, 0) still
    succeeds on it, so without this check polling burns the whole 5 s SIGTERM
    grace period. The check must be group-wide, never leader-only: "leader is
    a zombie but a SIGTERM-trapping CLI child is still running" is exactly the
    case the group probe exists for (GUI-launched trios are never reaped, so
    their leaders zombify while children keep editing the worktree), and a
    leader-only zombie shortcut would wrongly drop such a group from the
    survivor poll and skip the SIGKILL escalation the child needs.

    Uses ``pgrep -g`` to enumerate group members (portable across Linux and
    macOS, where ``ps -g`` semantics differ), then ``ps`` for their states.
    Any tool failure, timeout, or empty output means "assume alive": staying
    conservative keeps the group in the poll and lets SIGKILL escalation
    fire; this check must never abort or block a resume.
    """
    try:
        listing = subprocess.run(
            ["pgrep", "-g", str(pgid)],
            capture_output=True,
            text=True,
            timeout=5,
        )
        pids = [line.strip() for line in (listing.stdout or "").splitlines() if line.strip()]
        if not pids:
            return True
        result = subprocess.run(
            ["ps", "-o", "state=", "-p", ",".join(pids)],
            capture_output=True,
            text=True,
            timeout=5,
        )
        states = [line.strip() for line in (result.stdout or "").splitlines() if line.strip()]
    except Exception:
        return True
    if not states:
        return True
    return any(not state.startswith("Z") for state in states)


def _group_alive(pid: int) -> bool:
    """True while any process in ``pid``'s process group is still alive.

    Survivor polling must track the whole group, not just the leader: a
    SIGTERM-trapping CLI child keeps the group alive after the leader exits,
    and keying liveness to the leader alone would skip the SIGKILL escalation
    that the child needs. A group whose members are all zombies counts as
    dead for polling. Falls back to _pid_alive where killpg is unavailable
    (Windows).
    """
    try:
        os.killpg(pid, 0)
    except ProcessLookupError:
        return False
    except PermissionError:
        # The group exists but belongs to someone else; treat it as alive.
        return True
    except (AttributeError, OSError):
        return _pid_alive(pid)
    # killpg succeeds against a group whose remaining members are all zombies;
    # treat such a group as dead so polling does not burn the full grace
    # period waiting for corpses that can never react to another signal. The
    # member check is group-wide on purpose: a leader-only zombie check would
    # misreport "zombie leader + live CLI child" as dead and skip the SIGKILL
    # escalation that the surviving child needs.
    return _group_has_live_member(pid)


def _pid_identity_ok(pid: int) -> bool:
    """Best-effort guard against PID reuse before signalling a stored PID.

    Returns False only when ``ps`` positively reports a command line that
    looks unrelated to the AI-Loop trio. Any ps failure, timeout, or empty
    output returns True: this check must never abort or block a resume.
    """
    try:
        result = subprocess.run(
            ["ps", "-p", str(pid), "-o", "command="],
            capture_output=True,
            text=True,
            timeout=5,
        )
        output = (result.stdout or "").strip()
    except Exception:
        return True
    if not output:
        return True
    return any(marker in output for marker in ("controller.py", "worker.py", "watcher.py", "python"))


def _signal_process(pid: int, sig: int) -> None:
    """Signal the whole process group, falling back to the single PID.

    The trio processes are started with start_new_session=True, so each is a
    session (and process-group) leader: killpg also reaches CLI children
    (codex/claude subprocesses) that would otherwise survive and keep editing
    the worktree. AttributeError covers Windows, where os.killpg is absent.
    """
    try:
        os.killpg(pid, sig)
        return
    except (ProcessLookupError, PermissionError, OSError, AttributeError):
        pass
    os.kill(pid, sig)


def terminate_previous_job_processes(root_dir, job_id: str) -> None:
    """Kill the job's previous controller/worker/watcher trio before relaunch.

    Without this, resuming leaves the old trio running: two consumers per
    stream fight over messages and the old processes keep mutating job state.
    Every per-PID step is exception-guarded so a stale or garbage PID file can
    never abort the resume. The resume's own process and its parent are never
    signalled: when the watcher itself launches the resume, killing the parent
    would break the output pipe and abort the resume before the relaunch.
    """
    runtime_dir = root_dir / "run" / "jobs" / job_id
    terminated: list[tuple[str, int]] = []
    for name in ("controller", "worker", "watcher"):
        pid_file = runtime_dir / f"{name}.pid"
        try:
            pid = int(pid_file.read_text(encoding="utf-8").strip())
        except (OSError, ValueError):
            continue
        if pid <= 1:
            safe_print(f"skipped stale {name} pid file (pid {pid} is not a signallable process id)")
            continue
        if pid in (os.getpid(), os.getppid()):
            safe_print(f"skipped {name} process (pid {pid}): it is the resume's own/parent process")
            continue
        try:
            if not _pid_alive(pid):
                continue
            if not _pid_identity_ok(pid):
                safe_print(f"skipped {name} process (pid {pid}): PID reused by another process")
                continue
            _signal_process(pid, signal.SIGTERM)
            terminated.append((name, pid))
        except (ProcessLookupError, PermissionError, ValueError, OSError):
            continue
    if terminated:
        deadline = time.monotonic() + 5.0
        survivors = list(terminated)
        while survivors and time.monotonic() < deadline:
            time.sleep(0.2)
            # The whole process GROUP must be gone, not just the leader: a
            # SIGTERM-trapping CLI child keeps editing the worktree after the
            # leader exits and still needs the SIGKILL escalation below.
            survivors = [(name, pid) for name, pid in survivors if _group_alive(pid)]
        # SIGKILL does not exist on Windows; fall back to a second SIGTERM there.
        force_signal = getattr(signal, "SIGKILL", signal.SIGTERM)
        for name, pid in survivors:
            try:
                _signal_process(pid, force_signal)
            except (ProcessLookupError, PermissionError, ValueError, OSError):
                pass
        forced = {pid for _name, pid in survivors}
        for name, pid in terminated:
            how = "SIGKILL" if pid in forced else "SIGTERM"
            safe_print(f"terminated previous {name} process (pid {pid}) with {how}")
    # Stale PID files are now dealt with; remove them so a later resume cannot
    # signal a recycled PID. launch_job_processes writes fresh ones.
    for name in ("controller", "worker", "watcher"):
        try:
            (runtime_dir / f"{name}.pid").unlink(missing_ok=True)
        except OSError:
            pass


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Resume an AI loop job with optional corrections.")
    parser.add_argument("job_id", help="Job id to resume.")
    parser.add_argument("--goal", help="Replacement goal for the resumed job.")
    parser.add_argument("--constraint", action="append", default=[], help="Additional constraint for future tasks.")
    parser.add_argument("--acceptance", action="append", default=[], help="Additional acceptance criterion.")
    parser.add_argument("--test-cmd", help="Replacement test command for future tasks.")
    parser.add_argument("--max-iterations", type=int, help="Replacement maximum Codex iteration count.")
    parser.add_argument("--granularity", choices=("fine", "normal", "coarse"), help="Replacement task granularity.")
    parser.add_argument("--wait", action="store_true", help="Wait for the job to reach a terminal status.")
    parser.add_argument("--poll-interval", type=float, default=5.0, help="Seconds between status checks with --wait.")
    parser.add_argument("--timeout", type=int, default=0, help="Maximum seconds to wait with --wait; 0 waits forever.")
    return parser.parse_args()


def main() -> int:
    args = parse_args()

    from redis.exceptions import ConnectionError, TimeoutError

    from ai_loop import db
    from ai_loop.config import CLAUDE_REQUEST_STREAM, load_settings
    from ai_loop.queues import redis_client, xadd_json
    from ai_loop.planning import normalize_granularity, replace_granularity_constraints
    from start_job import launch_job_processes, prepare_job_consumer_groups, wait_for_job

    settings = load_settings()
    db.init_db(settings.db_path)

    try:
        with db.transaction(settings.db_path) as conn:
            job = db.get_job(conn, args.job_id)
            goal = args.goal if args.goal is not None else job["goal"]
            test_cmd = args.test_cmd if args.test_cmd is not None else job["test_cmd"]
            max_iterations = args.max_iterations if args.max_iterations is not None else int(job["max_iterations"])
            granularity = normalize_granularity(args.granularity or str(job["granularity"]))
            constraints = [*job["constraints"], *args.constraint]
            constraints = replace_granularity_constraints(constraints, granularity)
            acceptance = [*job["acceptance"], *args.acceptance]
            conn.execute(
                """
                UPDATE jobs
                SET goal = ?, constraints_json = ?, acceptance_json = ?,
                    test_cmd = ?, max_iterations = ?, granularity = ?, status = ?, waiting_until = NULL, updated_at = ?
                WHERE id = ?
                """,
                (
                    goal,
                    db.to_json(constraints),
                    db.to_json(acceptance),
                    test_cmd,
                    max_iterations,
                    granularity,
                    "planning",
                    db.utc_now(),
                    args.job_id,
                ),
            )
            db.add_event(
                conn,
                job_id=args.job_id,
                kind="job_resumed",
                payload={
                    "job_id": args.job_id,
                    "goal": goal,
                    "test_cmd": test_cmd,
                    "max_iterations": max_iterations,
                    "granularity": granularity,
                    "added_constraints": args.constraint,
                    "added_acceptance": args.acceptance,
                    "previous_status": job["status"],
                },
            )

        client = redis_client(settings.redis_url)
        prepare_job_consumer_groups(client, args.job_id)
        terminate_previous_job_processes(settings.root_dir, args.job_id)
        job_processes = launch_job_processes(settings.root_dir, args.job_id)
        with db.transaction(settings.db_path) as conn:
            db.add_event(
                conn,
                job_id=args.job_id,
                kind="job_processes_started",
                payload={
                    "job_id": args.job_id,
                    "resumed": True,
                    "pids": job_processes,
                    "runtime_dir": str(settings.root_dir / "run" / "jobs" / args.job_id),
                    "log_dir": str(settings.root_dir / "logs" / "jobs" / args.job_id),
                },
            )
        xadd_json(client, CLAUDE_REQUEST_STREAM, "request", {"type": "PLAN", "job_id": args.job_id, "scope": "job"})
    except KeyError:
        safe_print(f"job {args.job_id} is not in the system", file=sys.stderr)
        return 1
    except (ConnectionError, TimeoutError) as exc:
        safe_print(f"job {args.job_id} updated, but Redis activation failed: {exc}", file=sys.stderr)
        return 1
    except Exception as exc:
        safe_print(f"could not resume job {args.job_id}: {exc}", file=sys.stderr)
        return 1

    safe_print(f"resumed job {args.job_id}")
    safe_print("status: planning - the controller is choosing the next implementation task.")
    safe_print(f"goal: {goal}")
    safe_print(f"test_cmd: {test_cmd}")
    safe_print(f"max_iterations: {max_iterations}")
    safe_print(f"granularity: {granularity}")
    safe_print(f"processes: {job_processes}")
    safe_print(f"queued PLAN on {CLAUDE_REQUEST_STREAM}")
    if args.wait:
        return wait_for_job(settings.db_path, args.job_id, job["worktree_path"], args.timeout, args.poll_interval)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
