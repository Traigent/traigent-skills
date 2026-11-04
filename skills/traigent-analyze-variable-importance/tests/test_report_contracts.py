"""Render and CLI contracts for bounded cards and declared metric units."""
import json
import subprocess
import sys
import xml.etree.ElementTree as ET
from pathlib import Path

import pytest

SCRIPT = Path(__file__).resolve().parents[1] / 'scripts/significant_tuned_variables.py'


def run_card(tmp_path, *, top_k=4, objective='accuracy', values=(0.1, 0.2), extra=()):
    trials = tmp_path / 'trials.jsonl'
    trials.write_text(''.join(json.dumps({objective: values[i % 2], 'config': {
        f'knob_{k}': i % 2 for k in range(7)}}) + '\n' for i in range(12)))
    output = tmp_path / 'out'
    output.mkdir(exist_ok=True)
    result = subprocess.run([sys.executable, str(SCRIPT), '--trials', str(trials),
        '--output-dir', str(output), '--top-k', str(top_k), '--objective', objective,
        '--bootstrap-draws', '5', *extra], capture_output=True, text=True)
    return result, output


@pytest.mark.parametrize('top_k', [4, 5])
def test_accepted_card_rows_clear_axis_and_footer(tmp_path, top_k):
    result, output = run_card(tmp_path, top_k=top_k)
    assert result.returncode == 0, result.stderr
    svg = ET.parse(output / 'significant_variables.svg').getroot()
    texts = svg.findall('{http://www.w3.org/2000/svg}text')
    subtitle = next(t for t in texts if (t.text or '').startswith('Objective:'))
    axis = next(t for t in texts if (t.text or '').startswith('0 '))
    assert float(axis.get('y')) - float(axis.get('font-size')) >= float(subtitle.get('y')) + 8
    footer = next(t for t in texts if (t.text or '').startswith('directional (n='))
    knob_text = [t for t in texts if (t.text or '').startswith(('knob_', 'best:'))]
    assert len(knob_text) == top_k * 2
    assert max(float(t.get('y')) for t in knob_text) + 20 < float(footer.get('y'))
    assert float(footer.get('y')) < float(svg.get('height')) - 20


@pytest.mark.parametrize('top_k', [6, 7])
def test_unsupported_card_size_preserves_previous_outputs(tmp_path, top_k):
    output = tmp_path / 'out'
    output.mkdir()
    saved = output / 'video_card.json'
    saved.write_text('previous report')
    result, _ = run_card(tmp_path, top_k=top_k)
    assert result.returncode != 0
    assert '--top-k' in result.stderr and '5' in result.stderr
    assert saved.read_text() == 'previous report'
    assert list(output.iterdir()) == [saved]
