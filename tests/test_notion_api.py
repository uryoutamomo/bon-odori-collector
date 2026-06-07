import unittest

from notion_api import validate_data_source


class FakeApi:
    def __init__(self, properties):
        self.properties = properties

    def retrieve_data_source(self, data_source_id):
        return {"id": data_source_id, "properties": self.properties}


class NotionSchemaTest(unittest.TestCase):
    def test_validates_property_type_and_relation_target(self):
        api = FakeApi(
            {
                "イベント": {
                    "type": "relation",
                    "relation": {"data_source_id": "events"},
                }
            }
        )
        validate_data_source(
            api,
            "plans",
            {
                "イベント": {
                    "type": "relation",
                    "data_source_id": "events",
                }
            },
        )

    def test_rejects_wrong_relation_target(self):
        api = FakeApi(
            {
                "イベント": {
                    "type": "relation",
                    "relation": {"data_source_id": "old-events"},
                }
            }
        )
        with self.assertRaisesRegex(ValueError, "expected relation"):
            validate_data_source(
                api,
                "plans",
                {
                    "イベント": {
                        "type": "relation",
                        "data_source_id": "events",
                    }
                },
            )


if __name__ == "__main__":
    unittest.main()
