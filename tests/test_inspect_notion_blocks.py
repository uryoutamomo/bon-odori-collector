from inspect_notion_blocks import block_checked


def test_block_checked_returns_todo_state():
    block = {"type": "to_do", "to_do": {"checked": True}}

    assert block_checked(block) is True


def test_block_checked_returns_none_for_non_todo():
    block = {"type": "paragraph", "paragraph": {}}

    assert block_checked(block) is None
