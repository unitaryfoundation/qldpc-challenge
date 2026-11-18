#!/usr/bin/env python3
"""Reachability campaign variant: target missing k's (k-gaps)."""
import os
os.environ.setdefault('TARGET', 'k')
_here = os.path.dirname(os.path.abspath(__file__))
_ns = {'__name__': '__main__', '__file__': os.path.join(_here, 'reachability_campaign.py')}
with open(os.path.join(_here, 'reachability_campaign.py')) as _f:
    exec(compile(_f.read(), _ns['__file__'], 'exec'), _ns)
