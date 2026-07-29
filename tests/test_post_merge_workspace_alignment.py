from __future__ import annotations

import json
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
SCRIPT = ROOT / "bin" / "align-merged-pr-workspace"


def run(repo: Path, *command: str) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        list(command), cwd=repo, capture_output=True, text=True, check=False,
    )


def upstream(repo: Path) -> str:
    branch = run(
        repo, "git", "symbolic-ref", "--quiet", "--short", "HEAD",
    ).stdout.strip()
    return run(
        repo,
        "git",
        "for-each-ref",
        "--format=%(upstream:short)",
        f"refs/heads/{branch}",
    ).stdout.strip()


class PostMergeWorkspaceAlignmentTests(unittest.TestCase):
    def make_fixture(
        self, root: Path, *, delete_remote_head: bool,
    ) -> tuple[Path, Path, str]:
        remote = root / "remote.git"
        writer = root / "writer"
        workspace = root / "workspace"
        subprocess.run(["git", "init", "--bare", str(remote)], check=True,
                       capture_output=True)
        subprocess.run(["git", "clone", str(remote), str(writer)], check=True,
                       capture_output=True)
        run(writer, "git", "config", "user.name", "Test User")
        run(writer, "git", "config", "user.email", "test@example.com")
        run(writer, "git", "switch", "-c", "main")
        (writer / "value.txt").write_text("base\n")
        run(writer, "git", "add", "value.txt")
        run(writer, "git", "commit", "-m", "base")
        run(writer, "git", "push", "-u", "origin", "main")
        run(remote, "git", "symbolic-ref", "HEAD", "refs/heads/main")

        subprocess.run(["git", "clone", str(remote), str(workspace)], check=True,
                       capture_output=True)
        run(workspace, "git", "config", "user.name", "Test User")
        run(workspace, "git", "config", "user.email", "test@example.com")
        run(workspace, "git", "switch", "-c", "feature")
        with (workspace / "value.txt").open("a") as handle:
            handle.write("first\n")
        run(workspace, "git", "commit", "-am", "first feature commit")
        (workspace / "value.txt").write_text("base\nfinal\n")
        run(workspace, "git", "commit", "-am", "second feature commit")
        run(workspace, "git", "push", "-u", "origin", "feature")
        head_oid = run(workspace, "git", "rev-parse", "HEAD").stdout.strip()

        run(writer, "git", "fetch", "origin", "feature")
        run(writer, "git", "merge", "--squash", "origin/feature")
        run(writer, "git", "commit", "-m", "squash feature")
        run(writer, "git", "push", "origin", "main")
        if delete_remote_head:
            run(writer, "git", "push", "origin", "--delete", "feature")

        fake_gh = root / "fake-gh"
        fake_gh.write_text(
            "#!/bin/sh\n"
            "cat <<'EOF'\n"
            + json.dumps({
                "state": "MERGED",
                "baseRefName": "main",
                "headRefName": "feature",
                "headRefOid": head_oid,
                "isCrossRepository": False,
            })
            + "\nEOF\n"
        )
        fake_gh.chmod(0o755)
        return workspace, fake_gh, head_oid

    def align(
        self, workspace: Path, fake_gh: Path,
    ) -> subprocess.CompletedProcess[str]:
        return run(
            workspace,
            sys.executable,
            str(SCRIPT),
            "17",
            "--repo",
            str(workspace),
            "--gh",
            str(fake_gh),
        )

    def test_aligns_multi_commit_squash_without_replaying_commits(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            workspace, fake_gh, _ = self.make_fixture(
                Path(directory), delete_remote_head=True,
            )

            completed = self.align(workspace, fake_gh)

            self.assertEqual(completed.returncode, 0, completed.stderr)
            self.assertEqual(json.loads(completed.stdout)["status"], "aligned")
            self.assertEqual(
                run(workspace, "git", "rev-parse", "HEAD").stdout.strip(),
                run(workspace, "git", "rev-parse", "origin/main").stdout.strip(),
            )
            self.assertEqual(run(workspace, "git", "status", "--porcelain").stdout, "")
            self.assertEqual(upstream(workspace), "")
            self.assertNotIn(
                "[gone]", run(workspace, "git", "status", "--short", "--branch").stdout,
            )

    def test_refuses_to_align_while_remote_head_exists(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            workspace, fake_gh, head_oid = self.make_fixture(
                Path(directory), delete_remote_head=False,
            )

            completed = self.align(workspace, fake_gh)

            self.assertEqual(completed.returncode, 1)
            self.assertEqual(
                json.loads(completed.stdout)["reason"], "remote_head_still_exists",
            )
            self.assertEqual(
                run(workspace, "git", "rev-parse", "HEAD").stdout.strip(), head_oid,
            )

    def test_refuses_dirty_workspace(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            workspace, fake_gh, head_oid = self.make_fixture(
                Path(directory), delete_remote_head=True,
            )
            with (workspace / "value.txt").open("a") as handle:
                handle.write("uncommitted\n")

            completed = self.align(workspace, fake_gh)

            self.assertEqual(completed.returncode, 1)
            self.assertEqual(json.loads(completed.stdout)["reason"], "dirty_worktree")
            self.assertEqual(
                run(workspace, "git", "rev-parse", "HEAD").stdout.strip(), head_oid,
            )

    def test_refuses_clean_post_merge_commits(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            workspace, fake_gh, head_oid = self.make_fixture(
                Path(directory), delete_remote_head=True,
            )
            (workspace / "after.txt").write_text("new work\n")
            run(workspace, "git", "add", "after.txt")
            run(workspace, "git", "commit", "-m", "post-merge work")
            post_merge_oid = run(
                workspace, "git", "rev-parse", "HEAD",
            ).stdout.strip()

            completed = self.align(workspace, fake_gh)

            self.assertEqual(completed.returncode, 1)
            self.assertEqual(
                json.loads(completed.stdout)["reason"],
                "branch_contains_post_merge_commits",
            )
            self.assertNotEqual(
                run(workspace, "git", "rev-parse", "HEAD").stdout.strip(), head_oid,
            )
            self.assertEqual(
                run(workspace, "git", "rev-parse", "HEAD").stdout.strip(),
                post_merge_oid,
            )

    def test_removes_gone_upstream_when_branch_is_already_aligned(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            workspace, fake_gh, _ = self.make_fixture(
                Path(directory), delete_remote_head=True,
            )
            run(workspace, "git", "fetch", "--prune", "origin", "main")
            moved = run(
                workspace, "git", "rebase", "--onto", "origin/main", "HEAD",
            )
            self.assertEqual(moved.returncode, 0, moved.stderr)

            completed = self.align(workspace, fake_gh)

            self.assertEqual(completed.returncode, 0, completed.stderr)
            self.assertEqual(
                json.loads(completed.stdout)["status"], "already_aligned",
            )
            self.assertEqual(upstream(workspace), "")
            self.assertNotIn(
                "[gone]", run(workspace, "git", "status", "--short", "--branch").stdout,
            )


if __name__ == "__main__":
    unittest.main()
