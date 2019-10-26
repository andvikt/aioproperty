from .aioproperty import aioproperty, async_context, rule, inject, MergeAioproperties, _CombineMeta

from pkg_resources import get_distribution, DistributionNotFound
try:
    __version__ = get_distribution(__name__).version
except DistributionNotFound:
    # package is not installed
    from setuptools_scm import get_version
    __version__ = get_version(root='..', relative_to=__file__)