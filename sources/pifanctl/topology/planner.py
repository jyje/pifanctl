import copy
from pifanctl.topology.model import TopologyError, digest, matches, normalize


def plan(resources, nodes=None, previous=None):
    """Pure planner. Invalid relationships produce fail-safe plans, not omissions."""
    resources = normalize(resources)
    fans = {o['metadata']['name']: o for o in resources if o['kind'] == 'Fan'}
    zones = {o['metadata']['name']: o for o in resources if o['kind'] == 'CoolingZone'}
    live = nodes is not None
    nodes = nodes or []
    node_map = {n['metadata']['name']: n for n in nodes}
    if not live and any('nodeSelector' in z['spec'] for z in zones.values()):
        raise TopologyError('nodeSelector requires live Kubernetes Node resolution')
    output = {'format': 1, 'fans': {}, 'zones': {}}
    claims = {}
    families = {}
    for name, fan in fans.items():
        s = fan['spec']
        node = node_map.get(s['nodeName'], {})
        hw = s['hardware']; family = next(iter(hw)); channel = hw[family]
        claim = (s['nodeName'], family, channel['pin']) if family == 'rpigpio' else (s['nodeName'], family, channel['chip'], channel['channel'])
        claims.setdefault(claim, []).append(name)
        families.setdefault(s['nodeName'], set()).add(family)
        issues = []
        if live and not node:
            issues.append('MissingWorkerNode')
        elif live and not any(c.get('type') == 'Ready' and c.get('status') == 'True' for c in node.get('status', {}).get('conditions', [])):
            issues.append('WorkerNodeNotReady')
        if fan['metadata'].get('deletionTimestamp'):
            issues.append('DeletingFan')
        output['fans'][name] = {'name': name, **copy.deepcopy(s), 'nodeUID': node.get('metadata', {}).get('uid', ''), 'zones': [], 'issues': issues}
    for names in claims.values():
        if len(names) > 1:
            for name in names: output['fans'][name]['issues'].append('HardwareConflict')
    for name, fan in output['fans'].items():
        if len(families[fan['nodeName']]) > 1:
            fan['issues'].append('MixedHardwareDrivers')
    for name, zone in zones.items():
        s = zone['spec']
        membership_key = digest([zone['metadata'].get('uid', ''), s.get('nodeSelector'), s.get('nodeNames')])
        prior = (previous or {}).get(name, {})
        if prior.get('membershipKey') != membership_key: prior = {}
        if 'nodeSelector' in s:
            members = sorted(n for n, o in node_map.items() if matches(s['nodeSelector'], o['metadata'].get('labels', {})))
            # Deleted Nodes may still be physical cooling members. Keep them
            # missing until an explicit selector change or zone replacement.
            members = sorted(set(members) | {n for n in prior.get('members', []) if n not in node_map})
        else:
            members = sorted(s['nodeNames'])
        issues = []
        member_uids = {n: node_map.get(n, {}).get('metadata', {}).get('uid', '') for n in members}
        for n, old_uid in prior.get('memberUIDs', {}).items():
            if n in members and old_uid and member_uids[n] != old_uid:
                if member_uids[n]: issues.append('NodeReplaced')
                member_uids[n] = old_uid
        if not members: issues.append('EmptySelection')
        if live and any(n not in node_map for n in members): issues.append('MissingNode')
        if live and any(n in node_map and not any(c.get('type') == 'Ready' and c.get('status') == 'True' for c in node_map.get(n, {}).get('status', {}).get('conditions', [])) for n in members):
            issues.append('NodeNotReady')
        if any(n not in fans for n in s['fanRefs']): issues.append('MissingFan')
        if zone['metadata'].get('deletionTimestamp'): issues.append('DeletingZone')
        if s['telemetry']['source'] == 'local' and any(n in fans and fans[n]['spec']['nodeName'] != members[0] for n in s['fanRefs']):
            issues.append('InvalidLocalPlacement')
        resolved = {'name': name, 'members': members, 'memberUIDs': member_uids, 'membershipKey': membership_key,
                    'fanRefs': s['fanRefs'], 'telemetry': copy.deepcopy(s['telemetry']), 'issues': sorted(set(issues))}
        output['zones'][name] = resolved
        for fan in s['fanRefs']:
            if fan in output['fans']: output['fans'][fan]['zones'].append(copy.deepcopy(resolved))
    for fan in output['fans'].values():
        telemetry = {}
        for zone in fan['zones']:
            for member in zone['members']:
                key = digest(zone['telemetry'])
                if member in telemetry and telemetry[member] != key:
                    fan['issues'].append('TelemetryConflict')
                telemetry[member] = key
        if not fan['zones']: fan['issues'].append('NoCoolingZone')
        fan['issues'] = sorted(set(fan['issues']))
    output['hash'] = digest(output)
    return output


def worker_plan(topology, node, watchdog=120):
    fans = {name: fan for name, fan in topology['fans'].items() if fan['nodeName'] == node}
    uids = {f['nodeUID'] for f in fans.values()}
    if len(uids) > 1: raise TopologyError('worker node has inconsistent identity')
    result = {'format': 1, 'nodeName': node, 'nodeUID': next(iter(uids), ''), 'fans': fans, 'watchdogSeconds': watchdog}
    result['hash'] = digest(result)
    return result
