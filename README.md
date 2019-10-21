## Install

```bash
pip3 install aioproperty
```

## Documentation

You can find documentation [here](http://aioproperty.readthedocs.io)


## Description

aioproperty presents async properties with both async getter and setter in one place.

#### Example:
```python
from aioproperty import aioproperty
import asyncio

class SomeClass:
    
    @aioproperty
    async def hello(self, value):
        await asyncio.sleep(1)
        return value

some_obj = SomeClass()
some_obj.hello = 'hello'

async def run():
    print(await some_obj.hello)

asyncio.run(run())
```

aioproperty is not a property in a classic meaning, it keeps values inside asincio tasks. Once
you set a new value, it is scheduled in a task. If any task is running now, it will wait untill it is finished.
When you get value, you actually get a current task, and you can await it to get a value.
More of that: you can use math without awaiting like that:

```python
other = some_obj.hello + ' byby'
print(await other)
```

We also introduce chaining:

```python
class SomeClass:
    
    @aioproperty
    async def hello(self, value):
        await asyncio.sleep(1)
        return value
    
    @hello.chain
    async def some_more(self, value):
        push_value(value)
```

And with our special MetaClass you can effectively inject some new chains in inherited classes:

```python
class Parent(metaclass=AiopropMeta):
    
    @aioproperty
    async def hello(self, value):
        await asyncio.sleep(1)
        return value
    
    @hello.chain
    async def some_more(self, value):
        push_value(value)

class Child(Parent):
    
    @inject(Parent.hello, priotity=100)
    async def injected_method(self, value):
        print('hello from injection')

```

Read more in our [docs](http://aioproperty.readthedocs.io)
