import typing
import asyncio
from copy import copy
import warnings
import inspect
import functools
from contextlib import AbstractAsyncContextManager, AbstractContextManager, AsyncExitStack
from dataclasses import dataclass, field
from pro_lambda import pro_lambda
from pro_lambda.tools import ClsInitMeta, cls_init
from pro_lambda import consts as pl_consts
import logging
import abc
from . import tools

logger = logging.getLogger('aioproperty')
_trigger_type = typing.Union[asyncio.Condition, typing.Callable[[], typing.Awaitable]]
pT = typing.TypeVar('pT')
_dummy = object()

class _ContextCounter(AbstractContextManager):

    def __init__(self):
        self._count = 0
        self._trigger = asyncio.Event()
        self._trigger.set()

    def acquire(self):
        self._count += 1
        if self._trigger.is_set():
            self._trigger.clear()

    def release(self):
        self._count -= 1
        if self._count == 0:
            self._trigger.set()

    def __enter__(self):
        self.acquire()
        return self

    def __exit__(self, exc_type, exc_val, exc_tb):
        self.release()

    def __await__(self):
        return (self._trigger.wait()).__await__()


class _PropContext(AbstractAsyncContextManager):
    """
    Special context-manager. Everytime someone enters
    """
    def __init__(self):
        self._contexts: typing.List[_ContextCounter] = list()
        self.lck = asyncio.Lock()

    async def __aenter__(self):
        _context = _ContextCounter()
        async with self.lck:
            self._contexts.append(_context)
        return _context

    async def __aexit__(self, exc_type, exc_val, exc_tb):
        async with self.lck:
            try:
                context = self._contexts[-1]
            except IndexError:
                return
        await context
        async with self.lck:
            try:
                self._contexts.remove(context)
            except ValueError:
                pass

    def acquire(self) -> _ContextCounter:
        """
        Get current _ContextCounter and acquires it

        Returns: _ContextCounter

        """
        try:
            context = self._contexts[-1]
        except IndexError:
            context = _ContextCounter()
        context.acquire()
        return context


async_context = _PropContext()


@dataclass
class _PropertyMeta(typing.Generic[pT], metaclass=ClsInitMeta):
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
    prop: typing.Union[pT, 'aioproperty']
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
                    if other not in ret._others:
                        ret._others.append(other)
                if name != '__invert__':
                    ret.foo = op(self.foo, other)
                else:
                    ret.foo = ~self.foo
                return ret

            setattr(cls, name, wrapper)

        list(map(set_foo, pl_consts.ops))

    @property
    def context(self) -> _ContextCounter:
        return getattr(self.instance, '_aiop_context')

    def __await__(self):
        try:
            async def wrap():
                ret = getattr(self.instance, f'_{self.prop._name}', self.prop._default)
                if isinstance(ret, typing.Awaitable):
                    ret = await ret
                if self.foo.is_async:
                    return await self.foo(ret)
                else:
                    return self.foo(ret)
            return wrap().__await__()
        except Exception:
            logger.exception(f'awaiting {self.instance}.{self.prop._name}')
            raise RuntimeError()

    def add_callback(self, foo):
        foo = tools.await_if_needed(foo)
        _wrapper = tools.await_if_needed(self.foo)

        async def wrap(prop, value):
            if prop == self.prop:
                await foo(await _wrapper(value))
            else:
                await foo(await self)

        for x in [self, *self._others]:
            x.prop.add_callback(x.instance, wrap)
        return foo


def rule(prop: _PropertyMeta):
    def deco(foo):
        prop.add_callback(foo)
        return foo
    return deco


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

    def __init__(
            self,
            setter = None,
            *,
            default=None,
            default_factory=None,
            reducers=None,
            name=None,
            priority=None,
            prop_meta_cls: typing.Type[_PropertyMeta]=_PropertyMeta,
    ):

        self._default = default if default is not None else default_factory() if default_factory is not None else None
        self._owner = None
        self._name = name or None
        self._reducers = reducers or []
        self._context_lck = asyncio.Lock()
        self._root = self
        self._prop_meta_cls = prop_meta_cls
        self._default_priority = priority
        if setter is not None:
            self(setter)

        @self.chain(priority=-1000)
        @tools.mark(id=f'{self._name}_pc')
        async def _process_callbacks(instance, value):
            callbacks = self.get_callbacks(instance)
            context: _ContextCounter = getattr(instance, '_aiop_context')
            context.acquire()

            async def trigger():
                try:
                    await asyncio.gather(*[x(self, value) for x in callbacks])
                finally:
                    context.release()

            asyncio.create_task(trigger())

    def __set_name__(self, owner, name):
        self._name = self._name or name
        self._owner = owner

    def __eq__(self, other):
        if isinstance(other, aioproperty):
            return other._root is self._root

    def __copy__(self):
        newone = type(self)()
        newone.__dict__.update(self.__dict__)
        newone._reducers = copy(newone._reducers)
        return newone

    def __call__(self, setter):
        self._add_reducer(setter, priority=self._default_priority)
        return self

    def __get__(self, instance, owner):
        if instance is None:
            return self
        else:
            try:
                getattr(instance, f'_{self._name}')
            except AttributeError:
                ret = asyncio.Future()
                ret.set_result(self._default)
                setattr(instance, f'_{self._name}', ret)
            ret = self._prop_meta_cls(
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

        @tools.await_if_needed
        @functools.wraps(reducer)
        def wrap_reducer(instance=None, value=None):
            if len(sig.parameters) == 1:
                return reducer(value)
            elif len(sig.parameters) == 2:
                return reducer(instance, value)

        if priority is None:
            if self._reducers:
                if last:
                    priority = max([x[0] for x in self._reducers]) + 1
                else:
                    priority = min([x[0] for x in self._reducers]) - 1
            else:
                priority = 0

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

    def get_callbacks(self, instance) -> typing.List[typing.Callable]:
        try:
            _trig = getattr(instance, f'_t_{self._name}')
        except AttributeError:
            _trig = []
            setattr(instance, f'_t_{self._name}', _trig)
        return _trig

    def add_callback(self, instance, callback: typing.Callable):
        callbacks = self.get_callbacks(instance)
        callbacks.append(callback)

    def __set__(self, instance, value):
        try:
            prev_task: asyncio.Future = getattr(instance, f'_{self._name}')
        except AttributeError:
            prev_task = asyncio.Future()
            prev_task.set_result(self._default)

        _context = async_context.acquire()
        setattr(instance, '_aiop_context', _context)

        async def wrap():
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
                _context.release()

        setattr(instance, f'_{self._name}', asyncio.create_task(wrap()))

    async def _default_setter(self, instance, value):
        return value

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


class inject:

    def __init__(
            self,
            parent_prop: typing.Union[aioproperty, str],
            *,
            priority=None,
            is_first=True,
    ):
        """
        Decorator, decorated foo will be chained to parent's property, but in new class

        Args:
            parent_prop: can be aioproperty or string-name of property to chain new foo
            priority: like in aioproperty.chain
            is_first: like in aioproperty.chain

        Notes:
            after decoration, prop becomes actually a copy of a previous prop. So you can not
            `prop1 is prop2 == False`, if you need subclass-comparing you can use `prop1 == prop2`
        """
        if isinstance(parent_prop, aioproperty):
            self.name = parent_prop._name
        else:
            self.name = parent_prop
        self.foo = None
        self.priority=priority
        self.is_first = is_first

    def __call__(self, foo):
        self.foo = foo
        return self

    def __set_name__(self, owner, name):
        _new = copy(getattr(owner, self.name))
        _new._owner = owner
        _new.chain(self.foo, priority=self.priority, is_first=self.is_first)
        setattr(owner, self.name, _new)


class _CombineMeta(abc.ABCMeta):

    def __new__(mcls, name, bases, namespace: dict, **kwargs):
        states: typing.Dict[str, aioproperty] = {x: y for x, y in namespace.items() if isinstance(y, aioproperty)}
        for x in bases:
            for n, y in x.__dict__.items():
                if isinstance(y, aioproperty):
                    try:
                        s = states[n].__copy__()
                        s._reducers = tools._merge_reducers(s._reducers, y._reducers)
                    except KeyError:
                        s = y.__copy__()
                    states[n] = s
        namespace.update(states)
        cls = super().__new__(mcls, name, bases, namespace, **kwargs)
        return cls


class MergeAioproperties(metaclass=_CombineMeta):
    pass
