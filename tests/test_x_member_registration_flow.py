import unittest

from sync_x_promoted_members import approved_promote_results


class XMemberRegistrationFlowTest(unittest.TestCase):
    def test_requires_user_approval_for_promote_sync(self):
        results = [
            {"handle": "@auto", "recommendation": "promote"},
            {"handle": "@approved", "recommendation": "promote", "user_approved": True},
            {"handle": "@watch", "recommendation": "watch", "user_approved": True},
            {
                "handle": "@decision",
                "recommendation": "promote",
                "registration_decision": "登録",
            },
        ]

        approved = approved_promote_results(results)

        self.assertEqual(
            [row["handle"] for row in approved],
            ["@approved", "@watch", "@decision"],
        )


if __name__ == "__main__":
    unittest.main()
