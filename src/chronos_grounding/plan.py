"""Versioned entry point; old renderers remain available for ledger replay."""
from . import renderer_v1
from .renderer_v1 import (Catalog, Prepared, PLAN_SCHEMA, REPLY_SCHEMA, TOPICS,
                         PREFERENCES, PROMPT, RENDERER_VERSION, build, prepare, finish, minute)

def renderer(version):
    if type(version) is not str or version!=renderer_v1.RENDERER_VERSION:
        raise renderer_v1.c.Invalid('UNSUPPORTED_RENDERER_VERSION')
    return renderer_v1
