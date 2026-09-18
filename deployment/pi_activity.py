"""Current official-agent lifecycle, independent of the bounded event log.

Call under the PiProcess lock. agent_end alone does not settle retry/queue work.
"""
class Activity:
    def __init__(self):
        self.reset()

    def reset(self):
        self.agent = False
        self.compacting = False
        self.retrying = False

    def observe(self, event):
        kind = event.get('type')
        if kind == 'agent_start':
            self.agent = True
        elif kind == 'agent_settled':
            self.agent = False
            self.retrying = False
        elif kind in {'compaction_start', 'auto_compaction_start'}:
            self.compacting = True
        elif kind in {'compaction_end', 'auto_compaction_end'}:
            self.compacting = False
        elif kind == 'auto_retry_start':
            self.retrying = True
        elif kind == 'auto_retry_end':
            self.retrying = False

    def snapshot(self, live):
        if not live:
            return {'busy':False, 'phase':'stopped'}
        return {'busy':self.agent or self.compacting or self.retrying,
                'phase':'retrying' if self.retrying else 'compacting' if self.compacting else 'running' if self.agent else 'idle'}
