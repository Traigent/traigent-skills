"""Fixture project: a provider call with nothing wired. Parsed, never imported."""

from openai import OpenAI


def ask(question):
    """A plain provider call: no decorator, no dataset, no scorer."""
    client = OpenAI()
    reply = client.responses.create(model="gpt-4o-mini", input=question)
    return reply.output_text
