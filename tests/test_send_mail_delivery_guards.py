"""配信の不変条件 INV-DLV-001 / 002 / 003 を守るテスト。

`docs/spec/L1/06-delivery.md` を参照。ここで守っているのは次の3つ。

- INV-DLV-001: claim済みの `sending_mail.json` が無いときは、SMTPへ触らない。
- INV-DLV-002: 送れないときは、黙って成功にせず、本文を残して失敗させる。
- INV-DLV-003: 送信前に本文をclaimし、成否不明の本文を自動再送しない。

INV-DLV-003 はclaimと完了記録が workflow 側で起きるため、`send_mail.yml` の構造を検査する。
送信より前にclaim commitがあり、SMTP失敗後や成否不明時にwatchdogが再送しないことまで見る。
"""

import json
import unittest
from contextlib import redirect_stdout
from io import StringIO
from pathlib import Path
from tempfile import TemporaryDirectory
from unittest.mock import patch

import yaml

import send_mail


REPO_ROOT = Path(__file__).resolve().parents[1]
SEND_MAIL_WORKFLOW = REPO_ROOT / ".github" / "workflows" / "send_mail.yml"
WATCHDOG_WORKFLOW = REPO_ROOT / ".github" / "workflows" / "send_mail_watchdog.yml"


def _load_workflow(path):
    return yaml.safe_load(path.read_text(encoding="utf-8"))


def _steps(workflow, job_name):
    return workflow["jobs"][job_name]["steps"]


class SendMailDraftPresenceTest(unittest.TestCase):
    """INV-DLV-001: claim済み本文が無いときは送信を試みない。"""

    def test_missing_in_flight_file_returns_zero_without_sending(self):
        with TemporaryDirectory() as tmp:
            missing = Path(tmp) / "sending_mail.json"

            with patch.object(send_mail, "IN_FLIGHT_PATH", missing), \
                    patch.object(send_mail, "MAIL_USERNAME", "user@example.com"), \
                    patch.object(send_mail, "MAIL_APP_PASSWORD", "pw"), \
                    patch.object(send_mail, "MAIL_TO", "recipient@example.com"), \
                    patch.object(send_mail, "send_mail") as sender:
                exit_code = send_mail.main()

        self.assertEqual(exit_code, 0)
        # 設定が揃っていても、本文が無い以上 SMTP へは一切触らない。
        sender.assert_not_called()


class SendMailFailureKeepsDraftTest(unittest.TestCase):
    """INV-DLV-002: 送れないときは非ゼロ終了し、claim済み本文を残す。

    「非ゼロを返すこと」と「ファイルが残っていること」の両方を見る。
    完了記録は workflow 側の仕事なので、`send_mail.py` が本文を消していないことを
    ここで押さえておかないと、失敗時に本文が失われる壊れ方を検出できない。
    """

    def _write_draft(self, directory, payload):
        path = Path(directory) / "sending_mail.json"
        path.write_text(json.dumps(payload, ensure_ascii=False), encoding="utf-8")
        return path

    def test_missing_credentials_returns_nonzero_and_keeps_draft(self):
        with TemporaryDirectory() as tmp:
            draft = self._write_draft(tmp, {"subject": "件名", "plain": "本文"})

            with patch.object(send_mail, "IN_FLIGHT_PATH", draft), \
                    patch.object(send_mail, "MAIL_USERNAME", None), \
                    patch.object(send_mail, "MAIL_APP_PASSWORD", None), \
                    patch.object(send_mail, "MAIL_TO", None), \
                    patch.object(send_mail, "send_mail") as sender:
                exit_code = send_mail.main()

            self.assertEqual(exit_code, 1)
            self.assertTrue(draft.exists())

        sender.assert_not_called()

    def test_empty_body_returns_nonzero_and_keeps_draft(self):
        with TemporaryDirectory() as tmp:
            draft = self._write_draft(tmp, {"subject": "件名", "plain": "", "html": ""})

            with patch.object(send_mail, "IN_FLIGHT_PATH", draft), \
                    patch.object(send_mail, "MAIL_USERNAME", "user@example.com"), \
                    patch.object(send_mail, "MAIL_APP_PASSWORD", "pw"), \
                    patch.object(send_mail, "MAIL_TO", "recipient@example.com"), \
                    patch.object(send_mail, "send_mail") as sender:
                exit_code = send_mail.main()

            self.assertEqual(exit_code, 1)
            self.assertTrue(draft.exists())

        sender.assert_not_called()

    def test_smtp_failure_does_not_become_success_and_keeps_draft(self):
        with TemporaryDirectory() as tmp:
            draft = self._write_draft(tmp, {"subject": "件名", "plain": "本文"})

            with patch.object(send_mail, "IN_FLIGHT_PATH", draft), \
                    patch.object(send_mail, "MAIL_USERNAME", "user@example.com"), \
                    patch.object(send_mail, "MAIL_APP_PASSWORD", "pw"), \
                    patch.object(send_mail, "MAIL_TO", "recipient@example.com"), \
                    patch.object(send_mail, "send_mail", side_effect=OSError("smtp down")):
                with self.assertRaises(OSError):
                    send_mail.main()

            # 例外は握り潰されず、本文も残る（workflow の削除ステップまで到達しない）。
            self.assertTrue(draft.exists())

    def test_successful_send_returns_zero_and_leaves_removal_to_workflow(self):
        with TemporaryDirectory() as tmp:
            draft = self._write_draft(tmp, {"subject": "件名", "plain": "本文"})

            with patch.object(send_mail, "IN_FLIGHT_PATH", draft), \
                    patch.object(send_mail, "MAIL_USERNAME", "user@example.com"), \
                    patch.object(send_mail, "MAIL_APP_PASSWORD", "pw"), \
                    patch.object(send_mail, "MAIL_TO", "recipient@example.com"), \
                    patch.object(send_mail, "send_mail") as sender:
                exit_code = send_mail.main()

            self.assertEqual(exit_code, 0)
            sender.assert_called_once()
            # 成功しても send_mail.py 自身は消さない。完了記録はworkflowが行う。
            self.assertTrue(draft.exists())

    def test_check_only_validates_without_sending(self):
        with TemporaryDirectory() as tmp:
            draft = self._write_draft(tmp, {"subject": "件名", "plain": "本文"})

            with patch.object(send_mail, "MAIL_USERNAME", "user@example.com"), \
                    patch.object(send_mail, "MAIL_APP_PASSWORD", "pw"), \
                    patch.object(send_mail, "MAIL_TO", "recipient@example.com"), \
                    patch.object(send_mail, "send_mail") as sender:
                exit_code = send_mail.main(draft, check_only=True)

            self.assertEqual(exit_code, 0)
            self.assertTrue(draft.exists())
            sender.assert_not_called()


class SendMailRecipientConfigurationTest(unittest.TestCase):
    """宛先はソースの既定値ではなく、MAIL_TOだけから決める。"""

    def test_mail_to_is_required_and_draft_is_kept(self):
        with TemporaryDirectory() as tmp:
            draft = Path(tmp) / "sending_mail.json"
            draft.write_text(json.dumps({"plain": "本文"}), encoding="utf-8")

            with patch.object(send_mail, "MAIL_USERNAME", "user@example.com"), \
                    patch.object(send_mail, "MAIL_APP_PASSWORD", "pw"), \
                    patch.object(send_mail, "MAIL_TO", None), \
                    patch.object(send_mail, "send_mail") as sender:
                exit_code = send_mail.main(draft)

            self.assertEqual(exit_code, 1)
            self.assertTrue(draft.exists())
            sender.assert_not_called()

    def test_recipients_come_only_from_mail_to_and_are_deduplicated(self):
        with patch.object(
            send_mail,
            "MAIL_TO",
            "first@example.com, second@example.com, first@example.com",
        ):
            recipients = send_mail.get_recipients()

        self.assertEqual(recipients, ["first@example.com", "second@example.com"])

    def test_log_does_not_print_recipient_addresses(self):
        with TemporaryDirectory() as tmp:
            draft = Path(tmp) / "sending_mail.json"
            draft.write_text(json.dumps({"subject": "件名", "plain": "本文"}), encoding="utf-8")
            output = StringIO()

            with patch.object(send_mail, "MAIL_USERNAME", "user@example.com"), \
                    patch.object(send_mail, "MAIL_APP_PASSWORD", "pw"), \
                    patch.object(send_mail, "MAIL_TO", "private-recipient@example.com"), \
                    patch.object(send_mail, "send_mail"), redirect_stdout(output):
                exit_code = send_mail.main(draft)

            self.assertEqual(exit_code, 0)
            self.assertNotIn("private-recipient@example.com", output.getvalue())


class SendMailWorkflowClaimOrderTest(unittest.TestCase):
    """INV-DLV-003: claimを記録してから1回だけ送り、成功後に完了を記録する。"""

    def setUp(self):
        self.workflow = _load_workflow(SEND_MAIL_WORKFLOW)
        self.steps = _steps(self.workflow, "send")
        self.claim_index = self._index_of(
            lambda s: "git mv data/pending_mail.json data/sending_mail.json" in (s.get("run") or "")
        )
        self.send_index = self._index_of(
            lambda s: "send_mail.py --draft data/sending_mail.json" in (s.get("run") or "")
        )
        self.complete_index = self._index_of(
            lambda s: "git rm data/sending_mail.json" in (s.get("run") or "")
        )

    def _index_of(self, predicate):
        for index, step in enumerate(self.steps):
            if predicate(step):
                return index
        return None

    def test_workflow_claims_before_sending_and_completes_afterward(self):
        self.assertIsNotNone(self.claim_index, "送信前claimステップが見つからない")
        self.assertIsNotNone(self.send_index, "claim済み本文の送信ステップが見つからない")
        self.assertIsNotNone(self.complete_index, "送信完了記録ステップが見つからない")
        self.assertLess(self.claim_index, self.send_index)
        self.assertLess(self.send_index, self.complete_index)

    def test_claim_is_committed_and_pushed_before_smtp(self):
        run = self.steps[self.claim_index]["run"]
        self.assertIn("git commit", run)
        self.assertIn("git push", run)
        self.assertIn("--check-only", run)
        self.assertLess(run.index("--check-only"), run.index("git mv"))

    def test_send_step_failure_is_not_swallowed(self):
        send_step = self.steps[self.send_index]
        # continue-on-error を付けると、送信が落ちても後続の削除ステップへ進んでしまう。
        self.assertNotEqual(send_step.get("continue-on-error"), True)

    def test_completion_step_does_not_run_when_send_fails(self):
        complete_step = self.steps[self.complete_index]
        condition = str(complete_step.get("if", "")).lower()
        # always()/failure()/cancelled() が入ると、失敗時にも曖昧状態が消えてしまう。
        for forbidden in ("always()", "failure()", "cancelled()"):
            self.assertNotIn(forbidden, condition)

    def test_completion_step_commits_and_pushes_the_deletion(self):
        run = self.steps[self.complete_index]["run"]
        self.assertIn("git commit", run)
        self.assertIn("git push", run)

    def test_existing_in_flight_mail_blocks_a_new_claim(self):
        run = self.steps[self.claim_index]["run"]
        sending_check = run.index("-f data/sending_mail.json")
        pending_move = run.index("git mv data/pending_mail.json")
        self.assertLess(sending_check, pending_move)
        self.assertIn("exit 1", run[sending_check:pending_move])

    def test_automatic_push_trigger_is_limited_to_main(self):
        workflow_text = SEND_MAIL_WORKFLOW.read_text(encoding="utf-8")
        self.assertRegex(workflow_text, r"push:\s*\n\s+branches:\s*\n\s+- main")


class SendMailWatchdogTest(unittest.TestCase):
    """未claimは再起動し、claim済みの曖昧状態は自動再送しない。"""

    def setUp(self):
        self.workflow = _load_workflow(WATCHDOG_WORKFLOW)
        self.steps = _steps(self.workflow, "check")
        self.run_scripts = "\n".join(step.get("run") or "" for step in self.steps)

    def test_watchdog_checks_for_a_remaining_draft(self):
        self.assertIn("data/pending_mail.json", self.run_scripts)

    def test_watchdog_retriggers_the_send_workflow(self):
        self.assertIn("gh workflow run send_mail.yml", self.run_scripts)

    def test_watchdog_fails_without_retrying_in_flight_mail(self):
        sending_check = self.run_scripts.index("data/sending_mail.json")
        trigger = self.run_scripts.index("gh workflow run send_mail.yml")
        self.assertLess(sending_check, trigger)
        self.assertIn("exit 1", self.run_scripts[sending_check:trigger])


if __name__ == "__main__":
    unittest.main()
