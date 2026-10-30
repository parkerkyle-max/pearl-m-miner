"""Public, offline capabilities for people and installation assistants."""
from . import __version__
from .devfee import DEFAULT_DEV_ADDRESS, DEV_POOL, DEV_HOST, DEV_PORT


def manifest():
    return {
        'schema': 'pearl-m-miner-info-v1',
        'name': 'Pearl M-Miner', 'version': __version__,
        'repository': 'https://github.com/parkerkyle-max/pearl-m-miner',
        'documentation': 'https://parkerkyle-max.github.io/pearl-m-miner/',
        'license': 'Apache-2.0',
        'coin': 'PRL', 'algorithm': 'PearlHash', 'certificate_version': 3,
        'backend': 'Apple Silicon Metal GPU',
        'requirements': {'os': 'macOS 26+', 'architecture': 'arm64',
                         'python': '3.12+', 'toolchain': 'Metal 4 Command Line Tools, Git, Rust/Cargo'},
        'measured_hardware': ['Apple M1 Max, 32 GPU cores, 64 GiB'],
        'other_m_series': 'experimental; local self-test and pool validation required',
        'cpu_mining': False, 'ane_mining': False, 'multi_coin': False,
        'developer_contribution': {
            'default_percent': 1, 'optional': True,
            'basis': 'completed valid GPU scan wall time; excludes stale work and idle time',
            'disable_option': '--dev-fee 0', 'public_address': DEFAULT_DEV_ADDRESS,
            'pool': DEV_POOL, 'host': DEV_HOST, 'port': DEV_PORT,
            'not_a_percentage_of_income': True,
        },
        'pools': {
            'kryptex': {'identity': 'your public krx mining ID', 'proof_transport': 'negotiated gzip-v2'},
            'luckypool': {'identity': 'your public native prl1 address'},
        },
        'languages': ['en', 'zh-CN', 'ja', 'ko'],
        'safe_sequence': ['info --json', 'doctor', 'self-test', 'benchmark --seconds 60',
                          'mine --pool kryptex --address YOUR_KRX_ID --worker my-mac --time-limit 600'],
        'operation': {'starts_mining': False, 'network_access': False,
                      'requires_wallet_secret': False, 'installs_autostart': False},
        'income_guarantee': False,
    }
