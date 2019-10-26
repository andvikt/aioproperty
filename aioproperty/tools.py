import typing
import functools
import logging
import abc

logger = logging.getLogger('aioproperty')


def await_if_needed(foo):

    @functools.wraps(foo)
    async def wrapper(*args, **kwargs):
        ret = foo(*args, **kwargs)
        if isinstance(ret, typing.Awaitable):
            ret = await ret
        return ret

    return wrapper


def mark(**markers):
    """
    decorator, will set any key of **markers as _{key}={value} on decorated object
    Args:
        **markers:
    """
    def deco(foo):
        for x, y in markers.items():
            setattr(foo, f'_{x}', y)
        return foo
    return deco


def _compare_reducers(x, y):
    try:
        return getattr(x, '_id', x.__hash__()) == getattr(y, '_id', x.__hash__())
    except AttributeError:
        return False


def _merge_reducers(a: list, b: list):
    hash = []
    ret = []
    for x in a+b:
        _hash = getattr(x[1], '_id', x[1].__hash__())
        if _hash not in hash:
            ret.append(x)
            hash.append(_hash)
    ret.sort(key=lambda x: x[0])
    return ret

