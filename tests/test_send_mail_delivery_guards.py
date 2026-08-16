"""配信の不変条件 INV-DLV-001 / 002 / 003 を守るテスト。

`docs/spec/L1/06-delivery.md` を参照。ここで守っているのは次の3つ。

- INV-DLV-001: `pending_mail.json` が無いときは、何もせず正常終了する。
- INV-DLV-002: 送れないときは、黙って成功にせず、本文を残して失敗させる。
- INV-DLV-003: 送信に成功したときだけ本文を消し、それをもって二重送信を防ぐ。

INV-DLV-003 は削除が workflow 側で起きるため、`send_mail.yml` の構造を検査する。
「送信ステップの後に削除ステップがある」だけでなく、
**削除ステップが失敗時にも走る書き方になっていないこと**まで見る。
`if: always()` を1行足すだけで、送れなかった本文が消える壊れ方になるため。
"""

import json
import unittest
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
    """INV-DLV-001: 本文が無いときは送信を試みない。"""

    def test_missing_pending_file_returns_zero_without_sending(self):
        with TemporaryDirectory() as tmp:
            missing = Path(tmp) / "pending_mail.json"

            with patch.object(send_mail, "PENDING_PATH", missing), \
                    patch.object(send_mail, "MAIL_USERNAME", "user@example.com"), \
                    patch.object(send_mail, "MAIL_APP_PASSWORD", "pw"), \
                    patch.object(send_mail, "send_mail") as sender:
                exit_code = send_mail.main()

        self.assertEqual(exit_code, 0)
        # 設定が揃っていても、本文が無い以上 SMTP へは一切触らない。
        sender.assert_not_called()


class SendMailFailureKeepsDraftTest(unittest.TestCase):
    """INV-DLV-002: 送れないときは非ゼロ終了し、本文を残す。

    「非ゼロを返すこと」と「ファイルが残っていること」の両方を見る。
    削除は workflow 側の仕事なので、`send_mail.py` が本文を消していないことを
    ここで押さえておかないと、失敗時に本文が失われる壊れ方を検出できない。
    """

    def _write_draft(self, directory, payload):
        path = Path(directory) / "pending_mail.json"
        path.write_text(json.dumps(payload, ensure_ascii=False), encoding="utf-8")
        return path

    def test_missing_credentials_returns_nonzero_and_keeps_draft(self):
        with TemporaryDirectory() as tmp:
            draft = self._write_draft(tmp, {"subject": "件名", "plain": "本文"})

            with patch.object(send_mail, "PENDING_PATH", draft), \
                    patch.object(send_mail, "MAIL_USERNAME", None), \
                    patch.object(send_mail, "MAIL_APP_PASSWORD", None), \
                    patch.object(send_mail, "send_mail") as sender:
                exit_code = send_mail.main()

            self.assertEqual(exit_code, 1)
            self.assertTrue(draft.exists())

        sender.assert_not_called()

    def test_empty_body_returns_nonzero_and_keeps_draft(self):
        with TemporaryDirectory() as tmp:
            draft = self._write_draft(tmp, {"subject": "件名", "plain": "", "html": ""})

            with patch.object(send_mail, "PENDING_PATH", draft), \
                    patch.object(send_mail, "MAIL_USERNAME", "user@example.com"), \
                    patch.object(send_mail, "MAIL_APP_PASSWORD", "pw"), \
                    patch.object(send_mail, "send_mail") as sender:
                exit_code = send_mail.main()

            self.assertEqual(exit_code, 1)
            self.assertTrue(draft.exists())

        sender.assert_not_called()

    def test_smtp_failure_does_not_become_success_and_keeps_draft(self):
        with TemporaryDirectory() as tmp:
            draft = self._write_draft(tmp, {"subject": "件名", "plain": "本文"})

            with patch.object(send_mail, "PENDING_PATH", draft), \
                    patch.object(send_mail, "MAIL_USERNAME", "user@example.com"), \
                    patch.object(send_mail, "MAIL_APP_PASSWORD", "pw"), \
                    patch.object(send_mail, "send_mail", side_effect=OSError("smtp down")):
                with self.assertRaises(OSError):
                    send_mail.main()

            # 例外は握り潰されず、本文も残る（workflow の削除ステップまで到達しない）。
            self.assertTrue(draft.exists())

    def test_successful_send_returns_zero_and_leaves_removal_to_workflow(self):
        with TemporaryDirectory() as tmp:
            draft = self._write_draft(tmp, {"subject": "件名", "plain": "本文"})

            with patch.object(send_mail, "PENDING_PATH", draft), \
                    patch.object(send_mail, "MAIL_USERNAME", "user@example.com"), \
                    patch.object(send_mail, "MAIL_APP_PASSWORD", "pw"), \
                    patch.object(send_mail, "send_mail") as sender:
                exit_code = send_mail.main()

            self.assertEqual(exit_code, 0)
            sender.assert_called_once()
            # 成功しても send_mail.py 自身は消さない。消すのは workflow（INV-DLV-003）。
            self.assertTrue(draft.exists())


class SendMailWorkflowRemovalOrderTest(unittest.TestCase):
    """INV-DLV-003: 削除は送信成功のあとにだけ起きる。"""

    def setUp(self):
        self.workflow = _load_workflow(SEND_MAIL_WORKFLOW)
        self.steps = _steps(self.workflow, "send")
        self.send_index = self._index_of(lambda s: "send_mail.py" in (s.get("run") or ""))
        self.remove_index = self._index_of(
            lambda s: "git rm data/pending_mail.json" in (s.get("run") or "")
        )

    def _index_of(self, predicate):
        for index, step in enumerate(self.steps):
            if predicate(step):
                return index
        return None

    def test_workflow_sends_before_removing_the_draft(self):
        self.assertIsNotNone(self.send_index, "send_mail.py を実行するステップが見つからない")
        self.assertIsNotNone(self.remove_index, "pending_mail.json を削除するステップが見つからない")
        self.assertLess(self.send_index, self.remove_index)

    def test_send_step_failure_is_not_swallowed(self):
        send_step = self.steps[self.send_index]
        # continue-on-error を付けると、送信が落ちても後続の削除ステップへ進んでしまう。
        self.assertNotEqual(send_step.get("continue-on-error"), True)

    def test_removal_step_does_not_run_when_send_fails(self):
        remove_step = self.steps[self.remove_index]
        condition = str(remove_step.get("if", "")).lower()
        # 既定（if 無し）は success() 相当。always()/failure()/cancelled() が入ると、
        # 送れなかった本文まで削除されて二重送信防止どころか本文喪失になる。
        for forbidden in ("always()", "failure()", "cancelled()"):
            self.assertNotIn(forbidden, condition)

    def test_removal_step_commits_and_pushes_the_deletion(self):
        run = self.steps[self.remove_index]["run"]
        # 削除がリポジトリへ反映されないと、次回起動が同じ本文を再送する。
        self.assertIn("git commit", run)
        self.assertIn("git push", run)


class SendMailWatchdogTest(unittest.TestCase):
    """INV-DLV-003 の後半: 残っていたら送信workflowを起動し直す。"""

    def setUp(self):
        self.workflow = _load_workflow(WATCHDOG_WORKFLOW)
        self.steps = _steps(self.workflow, "check")
        self.run_scripts = "\n".join(step.get("run") or "" for step in self.steps)

    def test_watchdog_checks_for_a_remaining_draft(self):
        self.assertIn("data/pending_mail.json", self.run_scripts)

    def test_watchdog_retriggers_the_send_workflow(self):
        self.assertIn("gh workflow run send_mail.yml", self.run_scripts)


if __name__ == "__main__":
    unittest.main()
