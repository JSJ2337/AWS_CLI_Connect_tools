"""전체 모듈 import 체인 검사"""
import importlib
import pytest


MODULES = [
    'ec2menu',
    'ec2menu.core.config',
    'ec2menu.core.colors',
    'ec2menu.core.cache',
    'ec2menu.core.keychain',
    'ec2menu.core.utils',
    'ec2menu.ui.menu',
    'ec2menu.ui.history',
    'ec2menu.ui.credentials',
    'ec2menu.aws.manager',
    'ec2menu.aws.batch',
    'ec2menu.aws.transfer',
    'ec2menu.terminal.session',
    'ec2menu.terminal.kubectl',
    'ec2menu.menus.ec2',
    'ec2menu.menus.eks',
    'ec2menu.menus.ecs',
    'ec2menu.menus.rds',
    'ec2menu.menus.elasticache',
    'ec2menu.menus.cloudwatch',
    'ec2menu.menus.lambda_menu',
    'ec2menu.menus.s3',
    'ec2menu.main',
]


@pytest.mark.parametrize("module_name", MODULES)
def test_module_imports(module_name: str) -> None:
    mod = importlib.import_module(module_name)
    assert mod is not None
