import functools
import typing
import asyncio
from copy import copy
from collections import defaultdict
import warnings
import inspect
from contextlib import asynccontextmanager, contextmanager
from dataclasses import dataclass, field
from enum import Enum
from pro_lambda import pro_lambda
from pro_lambda.tools import ClsInitMeta, cls_init
from pro_lambda import consts as pl_consts
import logging
from . import consts

logger = logging.getLogger('aioproperty')
_prop_context = []
_trigger_type = typing.Union[asyncio.Condition, typing.Callable[[], typing.Awaitable]]


@dataclass
class _PropertyMeta(metaclass=ClsInitMeta):
    """
    Captures task from aioproperty. When awaited, return it's result.
    It also captures getter from aioproperty and one can call it using next()

    Note:
        when use next(), it returns awaitable, so if you need some math, you can do like that:

        >>> await next(prop + 1)

    Args:
        task: pro_lambda, must return Task
        getter: pro_lambda, must return new _PropertyMeta
    """
    prop: 'aioproperty'
    instance: object
    foo: pro_lambda = field(default=pro_lambda(lambda x: x), init=False)
    _others: typing.List['aioproperty'] = field(default_factory=list, init=False)

    @cls_init
    def _add_maths(cls):
        def set_foo(params):
            name, op = params

            def wrapper(self: '_PropertyMeta', other=None):
                ret = copy(self)
                ret._others = copy(ret._others)
                if isinstance(other, _PropertyMeta):

                    async def wrap_getter():
                        return await getattr(other.instance, other.prop._name)

                    ret.foo = op(self.foo, wrap_getter)

                    if other not in ret._others:
                        ret._others.append(other)
                else:
                    ret.foo = op(self.foo, other)
                return ret

            setattr(cls, name, wrapper)

        list(map(set_foo, pl_consts.ops))

    def __await__(self):
        try:
            return self.task()
        except Exception:
            logger.exception(f'awaiting {self.instance}.{self.prop._name}')
            raise RuntimeError()

    async def wrap_next(self, _res: asyncio.Future, others: typing.Dict['_PropertyMeta', asyncio.Task]):
        try:
            _next = await self.prop.get_next(self.instance)
            _res.set_result(await _next)
            for x, y in others.items():
                if x is not self:
                    y.cancel()
        except asyncio.CancelledError:
            pass

    def __next__(self):
        try:
            _res = asyncio.Future()
            _tasks = {}
            for x in [self, *self._others]:
                _tasks[x] = asyncio.create_task(x.wrap_next(_res, _tasks))
            return _res
        except Exception:
            logger.exception(f'getting next value of {self.instance}.{self.prop._name}')
            raise RuntimeError()


@asynccontextmanager
async def prop_context():
    """
    It is a special async context manager that helps to bring async awaiting on aioproperty setattr()

    We can await on async attr setting both two ways:

    >>> some_obj.is_on = True
    >>> another_obj.is_on = False
    >>> await some_obj.is_on
    >>> await another_obj.is_on

    Or:

    >>> async with prop_context():
    ...     some_obj.is_on = True
    ...     another_obj.is_on = False

    With this context manager we get the same result: it will not go outside context until all inner objects finishes
    their async setters, but it is fewer lines of code and more readable.

    """
    yield
    context = _prop_context.copy()
    if context:
        await asyncio.gather(*context)


class aioproperty:

    """
    Асинхронный property.

    У async_property нет getter в привычном смысле, у него есть асинхронный setter, который возвращает
    значение, а геттер - это по сути ожидающая выполнения сеттера задача. Соответвенно, значения мы присваиваем в обычном
    синхронном режиме (за кадром выполняется create_task), а получаем значения в асинхронном.

    Это очень крутая особенность, которая станет основной киллер-фичей нашего фреймворка. Все статусы наших объектов
    асинхронны - это значит, чтобы получить его значение, нужно использовать await, вот пример:
    >>> async def run():
    >>> class SomeClass:
    ...     @aioproperty(default='hello')
    ...     async def some_property(self, value):
    ...         await asyncio.sleep(1)
    ...         return value
    >>> test = SomeClass()
    >>> print(await test.some_property)
    hello
    >>> test.some_property = 'byby'
    >>> test.some_property = 'hello'
    >>> print(await test.some_property)
    byby

    Args:
        default: дефолтное значение, возвращается, когда ни разу не вызывался setter
        default_factory: если нет дефолтного значения и сеттер еще не вызывался, то возвращается ф
    """

    @property
    def reducers(self):
        """
        Returns iterator of reducers used by this property
        """
        for _, x in self._reducers:
            yield x

    def __init__(self, setter = None, *, default=None, default_factory=None, format='{0}'):

        self._default = default or default_factory
        self._owner = None
        self._name = None
        self._format = format
        self._reducers = []
        if setter is not None:
            self(setter)

    def __set_name__(self, owner, name):
        self._name = name
        self._owner = owner

    def __copy__(self):
        newone = type(self)()
        newone.__dict__.update(self.__dict__)
        newone._reducers = copy(newone._reducers)
        return newone

    def __call__(self, setter):
        self._add_reducer(setter)
        return self



    def __get__(self, instance, owner):
        if instance is None:
            return self
        else:
            try:
                ret = getattr(instance, f'_{self._name}')
            except AttributeError:
                ret = asyncio.Future()
                ret.set_result(self._default)
            ret = _PropertyMeta(
                task=pro_lambda(lambda: ret),
                getter=pro_lambda(lambda: getattr(instance, self._name)),
                prop=self,
                instance=instance,
            )
            return ret

    def _add_reducer(self, reducer, priority=None, last=True):
        if reducer in self.reducers:
            warnings.warn(f'attempt to add reducer twice to {self._owner}.{self._name}')
            return
        sig = inspect.signature(reducer)
        if len(sig.parameters) not in [1,2]:
            raise RuntimeError(f'reducer {self}.{reducer} has wrong parameters: {sig.parameters}, must '
                               f'have "self, value" or just "value"')

        @await_if_needed
        def wrap_reducer(instance=None, value=None):
            if len(sig.parameters) == 1:
                return reducer(value)
            elif len(sig.parameters) == 2:
                return reducer(instance, value)

        if priority is None:
            if last:
                priority = max([x[0] for x in self._reducers]) + 1
            else:
                priority = min([x[0] for x in self._reducers]) - 1
        wrap_reducer.__name__ = reducer.__name__
        self._reducers.append((priority, wrap_reducer))
        self._reducers.sort(key=lambda x: x[0])

    async def _reduce(self, instance, value):
        """
        Основной редьюсер
        Args:
            instance:
            value:
        """
        for reducer in self.reducers:
            value = await reducer(instance, value) or value
        return value

    def get_next(self, instance) -> asyncio.Future:
        """
        Returns Future that can be awaited for informing about property is changed

        Args:
            instance: instance of object, that property belongs to
        """
        try:
            _next = getattr(instance, f'_next_{self._name}')
        except AttributeError:
            _next = asyncio.Future()
            setattr(instance, f'_next_{self._name}', _next)
        return _next

    @contextmanager
    def _next_context(self, instance) -> asyncio.Future:
        _next = self.get_next(instance)
        try:
            yield _next
        finally:
            if not _next.done():
                _next.set_result(getattr(instance, self._name))
            _next = asyncio.Future()
            setattr(instance, f'_next_{self._name}', _next)

    def __set__(self, instance, value):
        try:
            prev_task: asyncio.Future = getattr(instance, f'_{self._name}')
        except AttributeError:
            prev_task = asyncio.Future()
            prev_task.set_result(self._default)

        _context = asyncio.Future()
        _prop_context.append(_context)

        async def wrap():
            with self._next_context(instance) as _next:
                prev_value = await prev_task
            try:
                if value != prev_value:
                    logger.debug(f'set {instance}.{self._name}={value}')
                    try:
                        return await self._reduce(instance, value)
                    except Exception as exc:
                        logger.exception(f'error during setting {instance}.{self._name} to {value}')
                        return prev_value
                else:
                    return value
            finally:
                if not _context.done():
                    _context.set_result(True)
                    _prop_context.remove(_context)

        setattr(instance, f'_{self._name}', asyncio.create_task(wrap()))

    async def _default_setter(self, instance, value):
        return value

    def _check_foo(self, foo):
        sig = inspect.signature(foo)
        if not isinstance(foo, typing.Callable):
            raise TypeError(f'setter must be a callable')
        if len(sig.parameters) != 2:
            raise AttributeError(f'setter must have exact 2 arguments: self, value, but got {list(sig.parameters.keys())}')
        if list(sig.parameters)[0] != 'self':
            warnings.warn(f'first parameter of setter is usually "self", but got {list(sig.parameters)[0]}')

        if asyncio.iscoroutinefunction(foo):
            _foo = foo
        else:
            async def wrap(self, value):
                return foo(self, value)
            _foo = wrap

        async def wrap_return(self, value):
            """Если функция возвращает None, то заменяем его на value"""
            ret = await _foo(self, value)
            if ret is not None:
                return ret
            else:
                return value

        return wrap_return

    def chain(self, _foo = None, *, is_first=True, priority=None):
        """
        Добавляет функцию в цепочку редьюсеров
        Args:
            is_first: если истина, добавляется в начало, в противном случае в конец
            priority: можно управлять последовательностью исполнения редьюсеров. Чем меньше значение, тем раньше он будет
                запущен
        Returns:

        """
        def deco(foo):
            self._add_reducer(foo, last=not is_first, priority=priority)
            return foo

        return deco(_foo) if _foo is not None else deco
