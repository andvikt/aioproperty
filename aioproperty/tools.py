import typing
import functools
import logging

logger = logging.getLogger('aioproperty')


def await_if_needed(foo):

    @functools.wraps(foo)
    async def wrapper(*args, **kwargs):
        ret = foo(*args, **kwargs)
        if isinstance(ret, typing.Awaitable):
            ret = await ret
        return ret

    return wrapper
