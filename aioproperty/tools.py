import typing
import inspect
import functools
import logging
from contextlib import contextmanager
import asyncio

logger = logging.getLogger('aioproperty')

def skip_not_needed_kwargs(foo):
    """
    Decorator, decorated foo will silently skip not needed kwargs
    """

    params: typing.Dict[str, inspect.Parameter] = inspect.signature(foo).parameters
    has_kwargs = max([x.kind is x.VAR_KEYWORD for x in params.values()])

    @functools.wraps(foo)
    def wrapper(*args, **kwargs):
        kwargs = {x: y for x, y in kwargs.items() if x in params}
        return foo(*args, **kwargs)

    if has_kwargs:
        return foo
    else:
        return wrapper



@contextmanager
def log_exception(msg: str = 'error in context', logger: logging.Logger = None, except_=None, raise_=True):
    except_ = except_ or []
    logger = logger or logging.getLogger()
    _exc = []
    try:
        yield _exc
    except Exception as exc:
        _exc.append(exc)
        if exc.__class__ not in except_:
            logger.exception(msg)
        if raise_:
            raise


def deco_log_exception(msg, logger: logging.Logger=None, except_=None, raise_=True):
    """
    Decorator, decorated foo runs with exception logger

    Args:
        logger: logger to use, by default root is used
        except_: exceptions that should be ignored (not logged)
        raise_: if False, will not raise exception, only logs it
    """
    def deco(foo):

        @functools.wraps(foo)
        def wrapper(*args, **kwargs):
            with log_exception(msg, logger, except_=except_, raise_=raise_):
                return foo(*args, **kwargs)

        @functools.wraps(foo)
        async def async_wrapper(*args, **kwargs):
            with log_exception(msg, logger, except_=except_, raise_=raise_):
                return await foo(*args, **kwargs)

        if not asyncio.iscoroutinefunction(foo):
            return wrapper
        else:
            return async_wrapper

    return deco