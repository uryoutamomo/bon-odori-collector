import unittest

from discover_x_social_graph import choose_seeds


def _account(handle, status, score, manual_status=None):
    row = {"handle": handle, "status": status, "score": score, "valuable_posts": 0}
    if manual_status:
        row["manual_status"] = manual_status
    return row


class ChooseSeedsTest(unittest.TestCase):
    def test_trusted_accounts_are_ranked_by_score(self):
        scores = {
            "accounts": {
                "a": _account("@a", "trusted", 5),
                "b": _account("@b", "trusted", 9),
            }
        }

        seeds = choose_seeds(scores, {})

        self.assertEqual([s["handle"] for s in seeds], ["@b", "@a"])

    def test_important_informant_is_included_despite_probation_status(self):
        scores = {
            "accounts": {
                "trusted_one": _account("@trusted_one", "trusted", 8),
                "thin_history": _account(
                    "@thin_history", "probation", 0.5, manual_status="優先"
                ),
            }
        }

        seeds = choose_seeds(scores, {})

        handles = [s["handle"] for s in seeds]
        self.assertIn("@thin_history", handles)

    def test_important_informant_does_not_bypass_max_seed_cap(self):
        accounts = {
            f"important_{i}": _account(f"@important_{i}", "probation", 0, manual_status="優先")
            for i in range(5)
        }
        scores = {"accounts": accounts}

        seeds = choose_seeds(scores, {"social_graph_discovery": {"max_seed_accounts": 3}})

        self.assertEqual(len(seeds), 3)

    def test_important_informant_flag_does_not_duplicate_an_already_trusted_account(self):
        scores = {
            "accounts": {
                "both": _account("@both", "trusted", 9, manual_status="優先"),
            }
        }

        seeds = choose_seeds(scores, {})

        self.assertEqual(len(seeds), 1)
        self.assertEqual(seeds[0]["handle"], "@both")


if __name__ == "__main__":
    unittest.main()
