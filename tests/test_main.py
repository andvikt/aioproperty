import pytest
from aioproperty import aioproperty, async_context, rule, inject, MergeAioproperties
from pytest import fixture
import asyncio


class SomeClass:

    res_test_prop = 0
    res_test_prop_2 = 0
    res_test_prop_3 = 0

    def __init__(self):

        self.res_col_1 = []
        self.res_col_2 = []
        self.res_col_3 = []

    @aioproperty(default=0)
    async def test_prop(self, value):
        await asyncio.sleep(0.1)
        self.res_col_1.append(value)

    @test_prop.chain
    def some_hook(self, value):
        print('hook1', value)
        self.res_test_prop = value

    @aioproperty(default=0)
    async def test_prop_2(self, value):
        await asyncio.sleep(1)
        self.res_test_prop_2 = value
        self.res_col_2.append(value)

    @aioproperty(default=0)
    async def test_prop_3(self, value):
        self.res_test_prop_3 = value
        self.res_col_3.append(value)


class SomeInherited(SomeClass):

    def __init__(self):
        super().__init__()
        self.recieve_injection = []
        self.recieve_another_injection = []

    @inject(SomeClass.test_prop)
    async def add_some_more(self, value):
        self.recieve_injection.append(value)

    @inject('test_prop')
    async def add_some_more_2(self, value):
        self.recieve_another_injection.append(value + 1)


@fixture(scope='session')
def event_loop():
    loop = asyncio.get_event_loop()
    yield loop
    loop.close()


@fixture()
async def some_obj():
    yield SomeClass()


@fixture()
async def waiting_task(some_obj):
    collection = []

    @rule(some_obj.test_prop)
    def some_rule(value):
        collection.append(value)

    yield collection


@fixture()
async def waiting_task_2(some_obj):
    collection = []

    @rule(some_obj.test_prop + some_obj.test_prop_2)
    def some_rule(value):
        collection.append(value)

    yield collection


@pytest.mark.asyncio
async def test_1(some_obj, waiting_task, waiting_task_2):
    assert await some_obj.test_prop == 0
    async with async_context:
        async with async_context:
            some_obj.test_prop_3 = 1
        some_obj.test_prop = 1
        some_obj.test_prop_2 = 1

    assert some_obj.res_test_prop == 1
    assert some_obj.res_test_prop_2 == 1
    assert some_obj.res_test_prop_3 == 1

    assert await some_obj.test_prop == 1
    assert await some_obj.test_prop_2 == 1
    assert await some_obj.test_prop_3 == 1

    assert await (some_obj.test_prop + 1) == 2
    assert await ((some_obj.test_prop + some_obj.test_prop_2) / 2) == 1

    some_obj.test_prop_2 = 3
    assert await ((some_obj.test_prop + some_obj.test_prop_2) / 2) == 2
    assert waiting_task == [1]
    async with async_context:
        some_obj.test_prop = 2


@pytest.mark.asyncio
async def test_multiple(some_obj):
    async with async_context:
        some_obj.test_prop_3 = 1
        some_obj.test_prop_3 = 2
        some_obj.test_prop_2 = 3
        some_obj.test_prop = 4
        some_obj.test_prop_3 = 5
    assert some_obj.res_col_3 == [1,2,5]
    assert some_obj.res_col_1 == [4]
    assert some_obj.res_col_2 == [3]


@pytest.mark.asyncio
async def test_triggers(waiting_task, waiting_task_2, some_obj):
    async with async_context:
        some_obj.test_prop = 1
        some_obj.test_prop = 3
    async with async_context:
        some_obj.test_prop_2 = 3
    async with async_context:
        some_obj.test_prop = 2
    assert waiting_task == [1, 3, 2]
    assert waiting_task_2 == [1, 3, 6, 5]


@fixture()
async def some_other_obj():
    yield SomeInherited()


@pytest.mark.asyncio
async def test_inherited(some_other_obj, some_obj):
    async with async_context:
        some_obj.test_prop = 1
        some_other_obj.test_prop = 1

    assert some_obj.res_col_1 == [1]
    assert some_other_obj.res_col_1 == [1]
    assert some_other_obj.recieve_injection == [1]
    assert some_other_obj.recieve_another_injection == [2]
    assert SomeInherited.test_prop == SomeClass.test_prop


@pytest.mark.asyncio
async def test_callback(some_other_obj):
    some_list = []
    @some_other_obj.test_prop.add_callback
    async def some_foo(value):
        some_list.append(value)

    async with async_context:
        some_other_obj.test_prop = 1

    assert some_list == [1]

    some_other_obj.test_prop = 2
    assert some_list == [1]
    await asyncio.sleep(0.1)
    assert some_list == [1, 2]


class SomeTest1(MergeAioproperties):

    @aioproperty
    def is_on(self, value):
        return value


class SomeTest2(MergeAioproperties):

    @aioproperty(priority=10)
    def is_on(self, value):
        return value * 2


class Combined(SomeTest1, SomeTest2):
    pass


class MoreCombo(Combined):

    @aioproperty
    def is_on(self, value):
        return value * 2


@fixture
async def combined_obj(event_loop):
    yield Combined()


@fixture
async def morecombo_obj(event_loop):
    yield MoreCombo()


@pytest.mark.asyncio
async def test_combined(combined_obj, morecombo_obj):
    async with async_context:
        combined_obj.is_on = 2
        morecombo_obj.is_on = 2

    assert await combined_obj.is_on == 4
    assert await morecombo_obj.is_on == 8
    assert len(Combined.is_on._reducers) == 3
    assert len(MoreCombo.is_on._reducers) == 4