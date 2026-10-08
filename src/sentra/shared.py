"""Shared storage boundaries. All byte ceilings use decimal provider quotas."""
from dataclasses import dataclass
import hashlib
import re

from .datasets import canonical
from .errors import SentraError
from .local_store import CapacityStop,compact_record


@dataclass(frozen=True)
class Limits:
    database_bytes: int = 350_000_000
    object_bytes: int = 700_000_000
    monthly_egress_bytes: int = 3_500_000_000
    reserve_bytes: int = 20_000_000

    def __post_init__(self):
        for value, maximum in ((self.database_bytes, 500_000_000), (self.object_bytes, 1_000_000_000),
                               (self.monthly_egress_bytes, 5_000_000_000)):
            if type(value) is not int or not 0 < value < maximum:
                raise SentraError('Hosted thresholds must be positive integers below the Free allowances.')
        if type(self.reserve_bytes) is not int or not 0 <= self.reserve_bytes < min(self.database_bytes, self.object_bytes):
            raise SentraError('Invalid hosted storage reserve.')

    def check(self, usage, *, database_add=0, object_add=0, egress_add=0):
        for key, maximum, addition, reserve in (
                ('database_bytes', self.database_bytes, database_add, self.reserve_bytes),
                ('object_bytes', self.object_bytes, object_add, self.reserve_bytes),
                ('egress_bytes', self.monthly_egress_bytes, egress_add, 0)):
            value = usage.get(key)
            if type(value) is not int or value < 0 or type(addition) is not int or addition < 0:
                raise CapacityStop('Hosted usage unavailable; stop and verify project/organization usage before resuming.')
            if value + addition + reserve >= maximum:
                raise CapacityStop('Hosted ' + key + ' threshold reached; existing data retained. Review usage and limits; no upgrade/deletion performed.')


def object_key(provider, participant, digest):
    if (provider not in ('google_health', 'whoop', 'fitbit_export')
            or not isinstance(participant, str) or not re.fullmatch(r'p[0-9]{2,4}', participant)
            or not isinstance(digest, str) or not re.fullmatch(r'[a-f0-9]{64}', digest)):
        raise SentraError('Invalid private object identity.')
    return f'{provider}/{participant}/{digest}.json.gz'


def signature(record):
    return hashlib.sha256(canonical(record).encode()).hexdigest()


def database_estimate(record):
    return len(canonical(compact_record(record)).encode())*10 + len(record['measurements'])*2048
