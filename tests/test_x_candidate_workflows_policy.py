import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]


class XCandidateWorkflowsPolicyTest(unittest.TestCase):
    def workflow(self, name):
        return (ROOT / ".github" / "workflows" / name).read_text(encoding="utf-8")

    def test_x_candidate_workflows_keep_manual_dispatch_and_never_run_on_push(self):
        for name in (
            "review_x_candidate_posts.yml",
            "discover_x_social_graph.yml",
        ):
            with self.subTest(name=name):
                workflow = self.workflow(name)
                self.assertIn("workflow_dispatch:", workflow)
                self.assertNotIn("push:", workflow)

    def test_scheduled_runs_are_budget_bounded(self):
        """2026-07-26: スケジュール実行を許可した際の必須条件。

        手動専用にしていた理由は「日次収集と違って予算上限で止まらない」ことだった
        （2026-06-26 の判断）。スケジュールで回す以上、両スクリプトが日次収集と同じ
        予算帳簿を見て止まることをテストで固定する。
        """
        for name in ("discover_x_social_graph.py", "review_x_candidate_posts.py"):
            with self.subTest(name=name):
                script = (ROOT / name).read_text(encoding="utf-8")
                self.assertIn("x_budget_guard", script)
                self.assertIn("budget_guard.check(cfg)", script)
                self.assertIn("budget_guard.record_spend(", script)

    def test_scheduled_run_does_not_sync_to_notion(self):
        """スケジュール実行でNotionメンバーリストへ書き込まないこと。

        Notionへの登録は内田さんの承認済み候補だけに限る運用（CLAUDE.md）。
        sync ステップは `inputs.sync_only` が真のときだけ動くので、inputs が無い
        schedule 実行では動かない。
        """
        workflow = self.workflow("review_x_candidate_posts.yml")
        sync_step = workflow.split("- name: Sync saved promote results to Notion", 1)[1]
        self.assertIn("if: ${{ inputs.sync_only }}", sync_step.split("run:", 1)[0])

    def test_review_workflow_separates_x_api_review_and_notion_sync(self):
        workflow = self.workflow("review_x_candidate_posts.yml")

        self.assertIn("sync_only:", workflow)
        self.assertIn("confirm:", workflow)
        self.assertIn("REVIEW X CANDIDATES", workflow)
        self.assertIn("SYNC APPROVED X MEMBERS", workflow)
        self.assertIn("TWITTERAPI_IO_KEY", workflow)
        self.assertIn("python review_x_candidate_posts.py", workflow)
        self.assertIn("python sync_x_promoted_members.py", workflow)
        self.assertIn("spends X API quota or writes approved members to Notion", workflow)

    def test_social_graph_workflow_requires_quota_confirmation(self):
        workflow = self.workflow("discover_x_social_graph.yml")

        self.assertIn("confirm:", workflow)
        self.assertIn("DISCOVER X SOCIAL GRAPH", workflow)
        self.assertIn("TWITTERAPI_IO_KEY", workflow)
        self.assertIn("python discover_x_social_graph.py", workflow)
        self.assertIn("spends X API quota to explore follow graph candidates", workflow)

    def test_runbook_and_inventory_document_boundaries(self):
        runbook = (ROOT / "docs" / "x-candidate-workflows-operations.md").read_text(
            encoding="utf-8"
        )
        inventory = (
            ROOT / "docs" / "manual-auto-operations-inventory.md"
        ).read_text(encoding="utf-8")

        self.assertIn("DISCOVER X SOCIAL GRAPH", runbook)
        self.assertIn("REVIEW X CANDIDATES", runbook)
        self.assertIn("SYNC APPROVED X MEMBERS", runbook)
        self.assertIn("Do not add `push` triggers", runbook)
        self.assertIn("X candidate / social graph workflows は手動維持に確定", inventory)
        self.assertIn(
            "X candidate / social graph workflows を週次スケジュールへ移行", inventory
        )
        self.assertIn("Notion queue migration", inventory)


if __name__ == "__main__":
    unittest.main()
