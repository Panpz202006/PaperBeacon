"""Research observation history is separate from email delivery history."""
import json
from .monitor import identity_tokens
from .daily import save_json


def research_changes(inventory, state_file, scope):
    old = json.loads(state_file.read_text()) if state_file.exists() else {'seen': []}
    if old.get('scope', scope) != scope:
        raise ValueError('Research scope changed: use a separate --state file')
    seen = set(old['seen'])
    from .models import Paper
    new = [pid for pid, source in inventory.items()
           if not identity_tokens(Paper.from_dict(source['paper'])) & seen]
    for source in inventory.values():
        seen.update(identity_tokens(Paper.from_dict(source['paper'])))
    return new, {'scope': scope, 'seen': sorted(seen)}
