import unittest

from review_x_candidate_posts import select_review_candidates


def candidate(handle, score=1, seed_scores=None):
    return {
        "handle": handle,
        "candidate_score": score,
        "discovered_by": [
            {"seed": f"@seed{i}", "seed_score": seed_score, "seed_status": "trusted"}
            for i, seed_score in enumerate(seed_scores or [], start=1)
        ],
    }


class XCandidateReviewSelectionTest(unittest.TestCase):
    def test_graph_bonus_includes_high_quality_seed_candidate_outside_primary_rank(self):
        cfg = {
            "candidate_post_review": {
                "max_candidates": 2,
                "graph_bonus_candidates": 2,
                "graph_bonus_min_sources": 4,
                "graph_bonus_min_seed_score_sum": 40,
                "graph_bonus_min_high_quality_seeds": 2,
                "high_quality_seed_min_score": 10,
            }
        }
        candidates = [
            candidate("@rank1"),
            candidate("@rank2"),
            candidate("@weak_graph", seed_scores=[20, 5, 5, 5]),
            candidate("@peromaru20", seed_scores=[23.325, 12.533, 11.8, 11.35]),
        ]

        selected = select_review_candidates(candidates, cfg)

        self.assertEqual(
            [row["handle"] for row in selected],
            ["@rank1", "@rank2", "@peromaru20"],
        )
        self.assertEqual(selected[-1]["review_selection_reason"], "graph_bonus")

    def test_graph_bonus_deduplicates_primary_rank_candidates(self):
        cfg = {
            "candidate_post_review": {
                "max_candidates": 1,
                "graph_bonus_candidates": 2,
                "graph_bonus_min_sources": 1,
                "graph_bonus_min_seed_score_sum": 1,
                "graph_bonus_min_high_quality_seeds": 1,
                "high_quality_seed_min_score": 1,
            }
        }
        candidates = [
            candidate("@rank1", seed_scores=[10]),
            candidate("@rank2", seed_scores=[10]),
        ]

        selected = select_review_candidates(candidates, cfg)

        self.assertEqual([row["handle"] for row in selected], ["@rank1", "@rank2"])


if __name__ == "__main__":
    unittest.main()
