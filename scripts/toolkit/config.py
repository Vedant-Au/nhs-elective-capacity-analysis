"""
Healthcare Capacity Optimisation Toolkit — configuration loading and validation.

The toolkit's contract is that everything engagement-specific lives in a YAML
config and nothing in this package does. Validation here is deliberately strict:
a silently-defaulted parameter in a capacity model is worse than a crash,
because it produces a plausible number nobody questions.
"""
from pathlib import Path
import yaml

REQUIRED_TOP = ['engagement', 'warehouse', 'equity', 'costs', 'levers',
                'diagnostic_conversion', 'budget', 'driving_forces',
                'strategies', 'objectives']

GRADE_MEANING = {
    1: 'Sourced — published national dataset covering the current period.',
    2: 'Measured — derived from the warehouse with a quantified interval.',
    3: 'Anchored estimate — extrapolated from data or a stated policy target.',
    4: 'Unsourced estimate — analyst judgement; no published figure exists.',
}


class ConfigError(ValueError):
    pass


class Config(dict):
    """Thin dict wrapper so callers can write cfg.levers as well as cfg['levers']."""

    def __getattr__(self, item):
        try:
            return self[item]
        except KeyError as e:
            raise AttributeError(item) from e

    @property
    def lever_keys(self):
        return list(self['levers'].keys())

    @property
    def weak_levers(self):
        """Levers whose capacity assumption is an unsourced estimate. These
        define the delivery-risk objective, so the flag is load-bearing."""
        return [k for k, v in self['levers'].items() if v.get('evidence_weak')]

    def grade_of(self, driver_key):
        """Evidence grade for a driving force, resolved from wherever that
        parameter is actually defined rather than restated on the driver."""
        if driver_key == 'budget':
            return self['budget']['grade']
        if driver_key == 'diag_tests_per_pathway':
            return self['diagnostic_conversion']['grade']
        if driver_key == 'demand_mult':
            return 2  # measured — comes from the forecast's own interval
        if driver_key == 'tariff_mult':
            return min(c.get('grade', 4) for c in self['costs']['treatment_components'])
        for lever, spec in self['levers'].items():
            if driver_key == f'{lever}_growth' or (
                    driver_key == 'is_growth' and lever == 'x2') or (
                    driver_key == 'inhouse_growth' and lever == 'x1'):
                return spec['growth_grade']
        raise ConfigError(f'No evidence grade resolvable for driving force {driver_key!r}')

    def basis_of(self, driver_key):
        if driver_key == 'budget':
            return self['budget']['basis']
        if driver_key == 'diag_tests_per_pathway':
            return self['diagnostic_conversion']['basis']
        if driver_key == 'demand_mult':
            return ('Taken from the warehouse forecast\'s own p5 and p95 at horizon '
                    'end, relative to the central case. Measured, not assumed.')
        if driver_key == 'tariff_mult':
            return self['costs']['source']
        for lever, spec in self['levers'].items():
            if (driver_key == 'is_growth' and lever == 'x2') or (
                    driver_key == 'inhouse_growth' and lever == 'x1'):
                return spec['growth_basis']
        return ''


def load(path):
    path = Path(path)
    if not path.exists():
        raise ConfigError(f'Config not found: {path}')
    with open(path) as f:
        raw = yaml.safe_load(f)
    cfg = Config(raw)
    validate(cfg, path)
    return cfg


def validate(cfg, path='<config>'):
    missing = [k for k in REQUIRED_TOP if k not in cfg]
    if missing:
        raise ConfigError(f'{path}: missing required sections: {", ".join(missing)}')

    if not cfg['levers']:
        raise ConfigError(f'{path}: at least one lever must be defined')

    valid_prices = {'treatment', 'treatment_outsourced', 'diagnostic'}
    for key, lv in cfg['levers'].items():
        for field in ('name', 'cap_basis', 'growth_rate', 'growth_grade', 'price'):
            if field not in lv:
                raise ConfigError(f'{path}: lever {key} missing {field!r}')
        if lv['price'] not in valid_prices:
            raise ConfigError(
                f'{path}: lever {key} has price {lv["price"]!r}; '
                f'expected one of {sorted(valid_prices)}')
        if lv['growth_grade'] not in GRADE_MEANING:
            raise ConfigError(f'{path}: lever {key} growth_grade must be 1-4')

    if not cfg.weak_levers:
        raise ConfigError(
            f'{path}: no lever is flagged evidence_weak, so the delivery-risk '
            'objective would be identically zero for every strategy and would '
            'rank nothing. Either flag the levers resting on unsourced '
            'assumptions, or remove that objective.')

    known = {'budget', 'demand_mult', 'is_growth', 'inhouse_growth',
             'diag_tests_per_pathway', 'tariff_mult'}
    for d in cfg['driving_forces']:
        if d['key'] not in known:
            raise ConfigError(
                f'{path}: driving force {d["key"]!r} is not a parameter the '
                f'engine knows how to vary. Known: {sorted(known)}')
        if d.get('range_from') == 'config':
            if 'low' not in d or 'high' not in d:
                raise ConfigError(
                    f'{path}: driving force {d["key"]!r} declares range_from '
                    '"config" but does not state low and high')
            if d['low'] >= d['high']:
                raise ConfigError(f'{path}: driving force {d["key"]!r} has low >= high')
        elif d.get('range_from') != 'forecast_interval':
            raise ConfigError(
                f'{path}: driving force {d["key"]!r} range_from must be '
                '"config" or "forecast_interval"')
        cfg.grade_of(d['key'])  # raises if unresolvable

    if len(cfg['driving_forces']) < 2:
        raise ConfigError(
            f'{path}: at least two driving forces are needed — the scenario set '
            'is framed from the two most critical, and with fewer than two '
            'there is no matrix to select from')

    codes = [s['code'] for s in cfg['strategies']]
    if len(codes) != len(set(codes)):
        raise ConfigError(f'{path}: duplicate strategy codes')
    for s in cfg['strategies']:
        for lv in s.get('spec', {}).get('lock', []):
            if lv not in cfg['levers']:
                raise ConfigError(
                    f'{path}: strategy {s["code"]} locks unknown lever {lv!r}')
        for field in ('min_share', 'max_share'):
            for lv in s.get('spec', {}).get(field, {}):
                if lv not in cfg['levers']:
                    raise ConfigError(
                        f'{path}: strategy {s["code"]} sets {field} on unknown '
                        f'lever {lv!r}')

    for o in cfg['objectives']:
        if o['direction'] not in ('max', 'min'):
            raise ConfigError(f'{path}: objective {o["key"]!r} direction must be max or min')

    eq = cfg['equity']
    if 'low_rank_means_higher_need' not in eq:
        raise ConfigError(
            f'{path}: equity.low_rank_means_higher_need must be stated explicitly. '
            'Deprivation indices differ in direction and the toolkit will not '
            'guess — getting it backwards silently inverts the equity constraint.')
    return cfg
