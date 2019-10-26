def foo():
    pass

def foo2():
    pass

setattr(foo, '__hash__', lambda : 1)
setattr(foo2, '__hash__', lambda : 1)

print(foo is foo2, foo.__hash__(), foo2.__hash__())