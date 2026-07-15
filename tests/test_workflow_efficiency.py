from __future__ import annotations

import json
import os
import subprocess
import tempfile
import time
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]


def run_script(name: str, *args: str, env: dict[str, str] | None = None) -> subprocess.CompletedProcess:
    return subprocess.run([str(ROOT / "bin" / name), *args], capture_output=True,
                          text=True, env=env, check=False)


class WorkflowEfficiencyTest(unittest.TestCase):
    def test_skill_contracts_keep_routine_goal_and_lfg_paths_bounded(self) -> None:
        goal = (ROOT / "skills/goal-flow/SKILL.md").read_text()
        review = (ROOT / "skills/review/SKILL.md").read_text()
        lfg = (ROOT / "skills/lfg/SKILL.md").read_text()
        economy = (ROOT / "skills/references/execution-economy.md").read_text()
        self.assertIn("get_ticket_contexts", goal)
        self.assertIn("mutate_ticket_workflows", goal)
        self.assertIn('fork_turns: "none"', economy)
        self.assertIn("plain review starts native-only", review)
        self.assertNotIn("/review mode:cross", lfg)

    def test_ticket_context_and_plan_fanout_inputs_are_bounded(self) -> None:
        conventions = (ROOT / "CLAUDE.md").read_text()
        auto_plan = (ROOT / "skills/auto-plan/SKILL.md").read_text()
        fanout = (ROOT / "workflows/plan-fanout.js").read_text()

        self.assertIn('detail="light", include_events=false', conventions)
        self.assertIn("sourceArtifactFile", auto_plan)
        self.assertIn("codebaseResearchFile", auto_plan)
        self.assertIn("priorKnowledgeFile", auto_plan)
        self.assertIn("sourceArtifactFile", fanout)
        self.assertIn("codebaseResearchFile", fanout)
        self.assertIn("priorKnowledgeFile", fanout)
        self.assertNotIn("${sourceArtifact}", fanout)
        self.assertNotIn("${codebaseResearch}", fanout)
        self.assertNotIn("${priorKnowledge}", fanout)

    def test_deploy_contracts_enforce_wait_preflight_redaction_and_negative_inventory(self) -> None:
        deploy = (ROOT / "skills/auto-deploy/SKILL.md").read_text()
        promote = (ROOT / "skills/ticket-promote/SKILL.md").read_text()
        create_pr = (ROOT / "skills/create-pr/SKILL.md").read_text()
        methodology = (ROOT / "skills/auto-plan/references/plan-methodology.md").read_text()

        self.assertIn("bin/wait-ci {pr_number}", deploy)
        self.assertNotIn("gh pr checks {pr_number} --watch", deploy)
        self.assertIn("Preflight every deploy command before merge", deploy)
        self.assertIn("bin/redacted-exec", deploy)
        self.assertIn("negative inventory", deploy)
        self.assertIn("Production command preflight (before landing)", promote)
        self.assertIn("bin/redacted-exec", promote)
        self.assertIn("one final-tree health gate", promote)
        self.assertIn("--context-file", create_pr)
        self.assertIn("tree SHA equals `HEAD`", create_pr)
        self.assertIn("Record a before inventory", methodology)
        self.assertIn("live inventory contains none of the retired items", methodology)

    def test_all_documented_agent_calls_use_fresh_bounded_context(self) -> None:
        for path in (ROOT / "skills").rglob("*.md"):
            lines = path.read_text().splitlines()
            for index, line in enumerate(lines):
                if "Agent(" not in line:
                    continue
                block = "\n".join(lines[index:index + 8])
                self.assertIn("fork_turns", block, f"unbounded Agent call in {path}:{index + 1}")

    def test_compact_exec_keeps_full_output_and_returns_bounded_tail(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            result = run_script("compact-exec", "--run-dir", directory, "--tail-bytes", "5",
                                "--", "/bin/sh", "-c", "printf 123456789; exit 3")
            self.assertEqual(result.returncode, 3)
            summary = json.loads(result.stdout)
            self.assertEqual(summary["exit_code"], 3)
            self.assertEqual(summary["output_bytes"], 9)
            self.assertEqual(summary["tail"], "56789")
            self.assertEqual(Path(summary["output_file"]).read_text(), "123456789")

    def test_compact_exec_timeout_kills_descendant_process_group(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            marker = Path(directory) / "survived"
            result = run_script(
                "compact-exec", "--run-dir", directory, "--timeout", "0.1", "--",
                "/bin/sh", "-c", f"(sleep 1; touch '{marker}') & wait",
            )
            self.assertEqual(result.returncode, 124)
            self.assertTrue(json.loads(result.stdout)["timed_out"])
            time.sleep(0.7)
            self.assertFalse(marker.exists())

    def test_wait_ci_polls_with_backoff_and_emits_one_result(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            fake = root / "gh"
            fake.write_text(
                "#!/bin/sh\n"
                f"n=$(cat '{root / 'count'}' 2>/dev/null || echo 0); n=$((n+1)); "
                f"echo $n > '{root / 'count'}'\n"
                "if [ $n -eq 1 ]; then b=pending; s=IN_PROGRESS; "
                "else b=pass; s=SUCCESS; fi\n"
                "printf '[{\"name\":\"test\",\"state\":\"%s\","
                "\"bucket\":\"%s\",\"link\":\"x\"}]' \"$s\" \"$b\"\n"
            )
            fake.chmod(0o755)
            result = run_script("wait-ci", "12", "--gh", str(fake), "--timeout", "1",
                                "--initial-delay", "0", "--max-delay", "0")
            self.assertEqual(result.returncode, 0, result.stderr)
            summary = json.loads(result.stdout)
            self.assertEqual(summary["status"], "success")
            self.assertEqual(summary["polls"], 2)
            self.assertEqual(result.stdout.count("\n"), 1)

    def test_wait_ci_can_wait_for_one_actions_run(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            fake = root / "gh"
            fake.write_text(
                "#!/bin/sh\n"
                f"n=$(cat '{root / 'count'}' 2>/dev/null || echo 0); n=$((n+1)); "
                f"echo $n > '{root / 'count'}'\n"
                "if [ $n -eq 1 ]; then status=in_progress; conclusion=null; "
                "else status=completed; conclusion='\"success\"'; fi\n"
                "printf '{\"name\":\"deploy\",\"status\":\"%s\","
                "\"conclusion\":%s,\"url\":\"x\",\"jobs\":[]}' "
                '"$status" "$conclusion"\n'
            )
            fake.chmod(0o755)
            result = run_script("wait-ci", "--run", "99", "--gh", str(fake),
                                "--timeout", "1", "--initial-delay", "0", "--max-delay", "0")
            self.assertEqual(result.returncode, 0, result.stderr)
            summary = json.loads(result.stdout)
            self.assertEqual(summary["kind"], "run")
            self.assertEqual(summary["status"], "success")
            self.assertEqual(summary["polls"], 2)
            self.assertEqual(summary["run"]["conclusion"], "success")

    def test_redacted_exec_never_emits_environment_or_labeled_secrets(self) -> None:
        environment = os.environ.copy()
        environment["PREFECT_API_AUTH_STRING"] = "operator:actual-production-secret"
        result = run_script(
            "redacted-exec", "--", "/bin/sh", "-c",
            "printf '%s\\n' \"$PREFECT_API_AUTH_STRING\"; "
            "printf '%s\\n' 'PREFECT_API_AUTH_STRING=profile-only-value' >&2; "
            "printf '%s\\n' 'Authorization: Basic encoded-credential'; "
            "printf '%s\\n' '\"api_key\": \"json-profile-value\"'",
            env=environment,
        )
        combined = result.stdout + result.stderr
        self.assertEqual(result.returncode, 0)
        self.assertNotIn("actual-production-secret", combined)
        self.assertNotIn("profile-only-value", combined)
        self.assertNotIn("encoded-credential", combined)
        self.assertNotIn("json-profile-value", combined)
        self.assertGreaterEqual(combined.count("[REDACTED]"), 4)

    @staticmethod
    def write_session(path: Path, meta: dict, records: list[dict]) -> None:
        values = [{"type": "session_meta", "payload": meta}, *records]
        path.write_text("\n".join(json.dumps(value) for value in values) + "\n")

    def test_report_uses_real_fork_chronology_and_recursive_descendants(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            root_log = root / "root.jsonl"
            child_log = root / "child.jsonl"
            grandchild_log = root / "grandchild.jsonl"

            def token(timestamp: str, total: dict) -> dict:
                return {"timestamp": timestamp, "type": "event_msg",
                        "payload": {"type": "token_count", "info": {
                            "total_token_usage": total, "last_token_usage": total}}}

            def started(timestamp: str) -> dict:
                return {"timestamp": timestamp, "type": "event_msg",
                        "payload": {"type": "task_started"}}

            self.write_session(root_log, {"id": "root"}, [
                started("2026-01-01T00:00:00Z"),
                token("2026-01-01T00:00:01Z",
                      {"input_tokens": 1000, "cached_input_tokens": 400,
                       "output_tokens": 100, "reasoning_output_tokens": 20,
                       "total_tokens": 1100}),
                {"type": "response_item", "payload": {"type": "custom_tool_call",
                    "name": "spawn_agent", "input": "{\"fork_turns\":\"all\"}"}},
                {"type": "response_item", "payload": {"type": "custom_tool_call_output",
                    "output": "Warning: truncated output\nabc"}},
                {"type": "compacted", "payload": {}},
            ])
            baseline = {"input_tokens": 500, "cached_input_tokens": 200,
                        "output_tokens": 100, "reasoning_output_tokens": 10,
                        "total_tokens": 600}
            final = {"input_tokens": 900, "cached_input_tokens": 500,
                     "output_tokens": 200, "reasoning_output_tokens": 20,
                     "total_tokens": 1100}
            self.write_session(child_log, {"id": "child", "parent_thread_id": "root"},
                               [token("2026-01-01T00:00:01Z", baseline),
                                started("2026-01-01T00:00:02Z"),
                                token("2026-01-01T00:00:03Z", final),
                                {"type": "response_item", "payload": {
                                    "type": "function_call", "name": "read_file"}},
                                {"type": "response_item", "payload": {
                                    "type": "function_call_output", "output": "ok"}},
                                {"type": "event_msg", "payload": {
                                    "type": "context_compacted"}}])
            grand_baseline = {"input_tokens": 100, "cached_input_tokens": 50,
                              "output_tokens": 10, "reasoning_output_tokens": 2,
                              "total_tokens": 110}
            grand_final = {"input_tokens": 300, "cached_input_tokens": 100,
                           "output_tokens": 50, "reasoning_output_tokens": 5,
                           "total_tokens": 350}
            self.write_session(grandchild_log, {"id": "grand", "parent_thread_id": "child"},
                               [token("2026-01-01T00:00:03Z", grand_baseline),
                                started("2026-01-01T00:00:04Z"),
                                token("2026-01-01T00:00:05Z", grand_final)])
            usage_dir = root / "usage"
            usage_dir.mkdir()
            (usage_dir / "external.json").write_text(json.dumps({
                "orchestrator_thread_id": "child", "usage_available": True,
                "usage": {"input_tokens": 12, "cached_input_tokens": 4,
                          "output_tokens": 3, "total_tokens": 15},
                "duration_ms": 250, "model": "fake-model", "repo": "/repo",
                "provider": "codex",
            }))
            result = run_script("workflow-efficiency-report", str(root_log),
                                "--sessions-root", str(root),
                                "--external-usage-dir", str(usage_dir))
            self.assertEqual(result.returncode, 0, result.stderr)
            report = json.loads(result.stdout)
            self.assertEqual(report["agents"], 3)
            self.assertEqual(report["direct_children"], 1)
            self.assertEqual(report["descendants_discovered"], 2)
            self.assertEqual(report["codex_tree_usage_unique"]["total_tokens"], 1840)
            self.assertEqual(report["whole_tree_usage"]["total_tokens"], 1855)
            self.assertEqual(report["codex_tree_efficiency"]["uncached_input_tokens"], 850)
            self.assertEqual(report["codex_tree_efficiency"]["effective_non_cached_tokens"], 1090)
            self.assertEqual(report["sessions"][1]["inherited_fork_baseline"], baseline)
            self.assertEqual(report["sessions"][1]["usage_unique"]["output_tokens"], 100)
            self.assertEqual(report["tool_calls"], 2)
            self.assertEqual(report["fork_turns_modes"], {"all": 1})
            self.assertEqual(report["all_forks"], 1)
            self.assertEqual(report["truncations"], 1)
            self.assertEqual(report["compactions"], 2)
            self.assertEqual(report["external_provider_usage"]["usage"]["total_tokens"], 15)
            self.assertEqual(report["external_provider_usage"]["duration_ms"], 250)
            self.assertEqual(report["coverage"]["fork_baselines"], "complete")
            capped = run_script("workflow-efficiency-report", str(root_log),
                                "--sessions-root", str(root), "--max-descendants", "1",
                                "--external-usage-dir", str(usage_dir))
            capped_report = json.loads(capped.stdout)
            self.assertEqual(capped_report["descendants_discovered"], 2)
            self.assertEqual(capped_report["descendants_reported"], 1)
            self.assertTrue(capped_report["descendants_truncated"])

    def test_report_marks_missing_fork_baseline_uncertain(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            self.write_session(root / "root.jsonl", {"id": "root"}, [])
            usage = {"input_tokens": 20, "cached_input_tokens": 10,
                     "output_tokens": 2, "reasoning_output_tokens": 1, "total_tokens": 22}
            self.write_session(root / "child.jsonl", {"id": "child",
                                                       "parent_thread_id": "root"}, [
                {"timestamp": "2026-01-01T00:00:01Z", "type": "event_msg",
                 "payload": {"type": "token_count", "info": {
                     "total_token_usage": usage, "last_token_usage": usage}}},
            ])
            result = run_script("workflow-efficiency-report", str(root / "root.jsonl"),
                                "--sessions-root", str(root),
                                "--external-usage-dir", str(root / "missing"))
            report = json.loads(result.stdout)
            self.assertEqual(report["coverage"]["fork_baselines"], "uncertain")
            self.assertFalse(report["sessions"][1]["fork_baseline_known"])
            self.assertEqual(report["sessions"][1]["usage_unique"], usage)

    def test_report_uses_zero_baseline_when_no_replayed_usage_exists(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            self.write_session(root / "root.jsonl", {"id": "root"}, [])
            first = {"input_tokens": 20, "cached_input_tokens": 10,
                     "output_tokens": 2, "reasoning_output_tokens": 1, "total_tokens": 22}
            second = {"input_tokens": 30, "cached_input_tokens": 20,
                      "output_tokens": 3, "reasoning_output_tokens": 1, "total_tokens": 33}
            total = {key: first[key] + second[key] for key in first}
            self.write_session(root / "child.jsonl", {"id": "child",
                                                       "parent_thread_id": "root"}, [
                {"timestamp": "2026-01-01T00:00:01Z", "type": "event_msg",
                 "payload": {"type": "task_started"}},
                {"timestamp": "2026-01-01T00:00:02Z", "type": "event_msg",
                 "payload": {"type": "token_count", "info": {
                     "total_token_usage": first, "last_token_usage": first}}},
                {"timestamp": "2026-01-01T00:00:03Z", "type": "event_msg",
                 "payload": {"type": "token_count", "info": {
                     "total_token_usage": total, "last_token_usage": second}}},
            ])
            result = run_script("workflow-efficiency-report", str(root / "root.jsonl"),
                                "--sessions-root", str(root),
                                "--external-usage-dir", str(root / "missing"))
            report = json.loads(result.stdout)
            child = report["sessions"][1]
            self.assertTrue(child["fork_baseline_known"])
            self.assertEqual(child["fork_baseline_method"],
                             "zero_no_usage_before_activity_boundary")
            self.assertEqual(child["usage_unique"], total)
            self.assertEqual(report["coverage"]["fork_baselines"], "complete")

    def test_report_excludes_replayed_parent_turns_before_child_trigger(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            self.write_session(root / "root.jsonl", {"id": "root"}, [])
            replay = {"input_tokens": 100, "cached_input_tokens": 40,
                      "output_tokens": 10, "reasoning_output_tokens": 2, "total_tokens": 110}
            gross = {"input_tokens": 160, "cached_input_tokens": 70,
                     "output_tokens": 25, "reasoning_output_tokens": 4, "total_tokens": 185}
            duplicate_last = {"input_tokens": 60, "cached_input_tokens": 30,
                              "output_tokens": 15, "reasoning_output_tokens": 2,
                              "total_tokens": 75}
            self.write_session(root / "child.jsonl", {
                "id": "child", "parent_thread_id": "root"
            }, [
                {"timestamp": "2026-01-01T00:00:00.000Z", "type": "event_msg",
                 "payload": {"type": "task_started"}},
                {"timestamp": "2026-01-01T00:00:00.001Z", "type": "event_msg",
                 "payload": {"type": "token_count", "info": {
                     "total_token_usage": replay, "last_token_usage": replay}}},
                {"timestamp": "2026-01-01T00:00:00.010Z", "type": "event_msg",
                 "payload": {"type": "task_started"}},
                {"timestamp": "2026-01-01T00:00:00.020Z",
                 "type": "inter_agent_communication_metadata",
                 "payload": {"trigger_turn": True}},
                {"timestamp": "2026-01-01T00:00:01.000Z", "type": "event_msg",
                 "payload": {"type": "token_count", "info": {
                     "total_token_usage": gross, "last_token_usage": duplicate_last}}},
                # Codex can duplicate the terminal token_count; attribution must not double it.
                {"timestamp": "2026-01-01T00:00:01.001Z", "type": "event_msg",
                 "payload": {"type": "token_count", "info": {
                     "total_token_usage": gross, "last_token_usage": duplicate_last}}},
            ])
            result = run_script("workflow-efficiency-report", str(root / "root.jsonl"),
                                "--sessions-root", str(root),
                                "--external-usage-dir", str(root / "missing"))
            report = json.loads(result.stdout)
            child = report["sessions"][1]
            self.assertEqual(child["activity_boundary_method"],
                             "last_task_started_before_trigger_turn")
            self.assertEqual(child["inherited_fork_baseline"], replay)
            self.assertEqual(child["usage_unique"]["total_tokens"], 75)
            self.assertLessEqual(child["usage_unique"]["total_tokens"],
                                 child["usage_gross"]["total_tokens"])

    def test_external_agent_sidecar_records_provider_usage_without_changing_envelope(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            fake_bin = root / "bin"
            fake_bin.mkdir()
            codex = fake_bin / "codex"
            codex.write_text(
                "#!/bin/sh\nout=''\nprev=''\n"
                "for arg in \"$@\"; do [ \"$prev\" = '-o' ] && out=\"$arg\"; prev=\"$arg\"; done\n"
                "cat >/dev/null\n"
                "printf '%s' '{\"key\":\"codex\",\"files_searched\":1,\"occurrences\":[],"
                "\"summary\":\"all good\",\"questions_for_synthesis\":[]}' > \"$out\"\n"
                "echo '{\"type\":\"turn.completed\",\"usage\":{\"input_tokens\":10,"
                "\"cached_input_tokens\":4,\"output_tokens\":2,\"total_tokens\":12}}'\n"
            )
            codex.chmod(0o755)
            packet = root / "packet"
            packet.write_text("<autodev-memory-task-context>\nx\n</autodev-memory-task-context>")
            usage_dir = root / "usage"
            env = os.environ.copy()
            env["PATH"] = str(fake_bin) + os.pathsep + env["PATH"]
            result = run_script("external-agent", "--task", "research", "--provider", "codex",
                                "--question", "inspect code", "--repo", str(ROOT),
                                "--memory-context-file", str(packet), "--usage-dir", str(usage_dir),
                                "--telemetry-file", str(root / "telemetry"), env=env)
            self.assertEqual(result.returncode, 0, result.stderr)
            self.assertEqual(json.loads(result.stdout)["key"], "codex")
            sidecar = json.loads(next(usage_dir.glob("*.json")).read_text())
            self.assertTrue(sidecar["usage_available"])
            self.assertEqual(sidecar["usage"]["total_tokens"], 12)
            self.assertEqual(sidecar["model"], "provider_default")
            self.assertEqual(sidecar["repo"], str(ROOT.resolve()))
            self.assertGreaterEqual(sidecar["duration_ms"], 0)
            self.assertNotIn("all good", json.dumps(sidecar))

    def test_external_agent_failure_still_writes_unavailable_sidecar(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            fake_bin = root / "bin"
            fake_bin.mkdir()
            codex = fake_bin / "codex"
            codex.write_text("#!/bin/sh\ncat >/dev/null\nexit 7\n")
            codex.chmod(0o755)
            packet = root / "packet"
            packet.write_text("<autodev-memory-task-context>\nx\n</autodev-memory-task-context>")
            env = os.environ.copy()
            env["PATH"] = str(fake_bin) + os.pathsep + env["PATH"]
            usage_dir = root / "usage"
            result = run_script("external-agent", "--task", "research", "--provider", "codex",
                                "--question", "inspect code", "--repo", str(ROOT),
                                "--memory-context-file", str(packet), "--usage-dir", str(usage_dir),
                                "--telemetry-file", str(root / "telemetry"), env=env)
            self.assertEqual(result.returncode, 2)
            sidecar = json.loads(next(usage_dir.glob("*.json")).read_text())
            self.assertFalse(sidecar["usage_available"])
            self.assertEqual(sidecar["adapter_outcome"], "invalid_provider_output")
            self.assertEqual(sidecar["attempt_statuses"], ["exit_7", "exit_7"])


if __name__ == "__main__":
    unittest.main()
