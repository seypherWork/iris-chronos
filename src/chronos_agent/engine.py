"""Bindings to the same simulator engine, isolated per native source manifest.

Only the trusted native loader injects _simulation_package before execution.
Normal Python imports use the installed chronos_simulation package.
"""
from importlib import import_module

_package=globals().get('_simulation_package','chronos_simulation')
clock=import_module(_package+'.clock')
model=import_module(_package+'.model')
workflow=import_module(_package+'.workflow')
S,M=clock.MICROSECONDS,clock.NATIVE_SCALE
authority_snapshot,require_native=clock.authority_snapshot,clock.require_native
canonical,fingerprint,integer,validate=model.canonical,model.fingerprint,model.integer,model.validate
Change,preview=workflow.Change,workflow.preview
