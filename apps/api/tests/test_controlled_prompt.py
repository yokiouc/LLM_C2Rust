from patch.generator import _render_controlled_prompt, _required_instructions


def test_controlled_prompt_instructions_exist_and_ordered():
    rendered = _render_controlled_prompt(evidence="E", target_function="T")
    pos = 0
    for s in _required_instructions():
        idx = rendered.find(s, pos)
        assert idx >= 0
        pos = idx + len(s)

