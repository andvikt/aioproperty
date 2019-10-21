import pytest
from aioproperty import aioproperty, async_context, rule
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
    async def some_hook(self, value):
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
