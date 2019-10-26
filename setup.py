from setuptools import setup

with open('README.md', 'r') as f:
    desc = f.read()

setup(
    name='aioproperty',
    use_scm_version=True,
    setup_requires=['setuptools_scm'],
    python_requires='>=3.7',
    packages=['aioproperty'],
    url='',
    license='MIT',
    author='Viktorov A.G.',
    author_email='andvikt@gmail.com',
    description='truely async properties',
    long_description=desc,
    long_description_content_type='text/markdown',
    install_requires=['pro_lambda>=0.3.3'],
    tests_require=['pytest', 'pytest-asyncio']
)
