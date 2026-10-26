"""包版本单一来源（v1.5.2）：``bacmap.__version__`` 取自安装元数据，不再硬编码漂移。"""

from importlib.metadata import version

import bacmap


def test_version_matches_metadata():
    assert bacmap.__version__ == version("bacmap")
